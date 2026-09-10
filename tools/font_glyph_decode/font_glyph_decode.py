#!/usr/bin/env python3
"""Decode font-glyph <use> text from pdftocairo SVG exports.

pdftocairo -svg exports subset font glyphs as <symbol>/<use> pairs without
unicode mapping (fonts with uni=no), so pdftotext cannot read them. This tool:
  1. extracts every <symbol> (glyph outline path) and every <use> instance
  2. rasterizes each symbol and classifies it against matplotlib-rendered
     sans-serif templates (IoU on normalized bitmaps)
  3. groups instances into strings (same baseline, x-adjacent)
  4. writes decoded strings with page-pixel coordinates as JSON

Usage:
  python3 font_glyph_decode.py <page.svg> [--dpi 300] [--out out.json]
                               [--min-iou 0.45] [--sheet out.png]
"""
import argparse
import io
import json
import re
import xml.etree.ElementTree as ET

import cairosvg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SVGNS = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"


def rasterize_path(d, size=96):
    """render a symbol path (fill) -> binarized bitmap, tightly cropped"""
    import svgelements as se
    try:
        p = se.Path(d)
        bb = p.bbox()
    except Exception:
        return None
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0 or not all(np.isfinite(v) for v in bb):
        return None
    W = size
    H = max(4, min(512, int(round(h / w * size))))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"'
           f' viewBox="{x0} {y0} {w} {h}">'
           f'<path d="{d}" fill="black" fill-rule="nonzero"/></svg>')
    png = cairosvg.svg2png(bytestring=svg.encode())
    return np.array(Image.open(io.BytesIO(png)).convert("L")) < 128


def norm_bits(bits, H=48):
    ys, xs = np.where(bits)
    if not len(ys):
        return None
    b = bits[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = b.shape
    W = max(2, int(round(w * H / h)))
    im = Image.fromarray((b * 255).astype(np.uint8)).resize((W, H),
                                                            Image.LANCZOS)
    return np.array(im) > 127


def iou_score(a, b, H=48):
    a2 = norm_bits(a, H)
    b2 = norm_bits(b, H)
    if a2 is None or b2 is None:
        return 0.0
    W = max(a2.shape[1], b2.shape[1])
    ca = np.zeros((H, W), bool)
    cb = np.zeros((H, W), bool)
    ca[:, (W - a2.shape[1]) // 2:(W - a2.shape[1]) // 2 + a2.shape[1]] = a2
    cb[:, (W - b2.shape[1]) // 2:(W - b2.shape[1]) // 2 + b2.shape[1]] = b2
    u = (ca | cb).sum()
    return (ca & cb).sum() / u if u else 0.0


def path_from_textpath(tp):
    parts, i = [], 0
    verts, codes = tp.vertices, tp.codes
    n = len(codes)
    while i < n:
        c = codes[i]
        if c == 1:
            parts.append(f"M{verts[i][0]:.3f} {verts[i][1]:.3f}")
            i += 1
        elif c == 2:
            parts.append(f"L{verts[i][0]:.3f} {verts[i][1]:.3f}")
            i += 1
        elif c == 3:
            cx, cy = verts[i]
            ex, ey = verts[i + 1]
            parts.append(f"Q{cx:.3f} {cy:.3f} {ex:.3f} {ey:.3f}")
            i += 2
        elif c == 4:
            c1, c2, e = verts[i], verts[i + 1], verts[i + 2]
            parts.append(f"C{c1[0]:.3f} {c1[1]:.3f} {c2[0]:.3f} {c2[1]:.3f} "
                         f"{e[0]:.3f} {e[1]:.3f}")
            i += 3
        else:
            i += 1
    return " ".join(parts)


def make_templates():
    from matplotlib.font_manager import FontProperties, findfont
    from matplotlib.textpath import TextPath
    fp = findfont(FontProperties(family=["Liberation Sans", "Arial",
                                         "DejaVu Sans"]))
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.•"
    tpl_bits = {}
    for ch in chars:
        tp = TextPath((0, 0), ch, prop=FontProperties(fname=fp))
        bits = rasterize_path(path_from_textpath(tp))
        if bits is not None and bits.sum() > 4:
            tpl_bits[ch] = bits
    return tpl_bits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-iou", type=float, default=0.45)
    ap.add_argument("--sheet", default=None,
                    help="write a verification contact sheet of glyphs")
    args = ap.parse_args()

    root = ET.parse(args.svg).getroot()
    tpls = make_templates()

    symbols = {}
    for sym in root.iter(f"{SVGNS}symbol"):
        gid = sym.get("id")
        paths = [p.get("d") for p in sym.iter(f"{SVGNS}path")]
        if paths and paths[0]:
            symbols[gid] = " ".join(paths)

    uses = []  # (gid, x, y) in svg user units (css px)
    seen = set()
    for g in root.iter(f"{SVGNS}g"):
        for use in g.iter(f"{SVGNS}use"):
            href = use.get(f"{{{XLINK.replace('href', 'href')}}}") or \
                use.get("href")
            if href is None:
                m = use.get(f"{XLINK}")
                href = m
            href = (href or "").replace("#", "")
            if href not in symbols:
                continue
            x, y = use.get("x"), use.get("y")
            if x is None or y is None:
                continue
            key = (href, round(float(x), 3), round(float(y), 3))
            if key in seen:
                continue
            seen.add(key)
            uses.append((href, float(x), float(y)))

    # classify unique symbols
    cache = {}
    sheet = None
    if args.sheet:
        tiles = []
    for gid, d in symbols.items():
        bits = rasterize_path(d)
        best, bestch = 0.0, None
        if bits is not None and bits.sum() > 2:
            for ch, tb in tpls.items():
                s = iou_score(bits, tb)
                if s > best:
                    best, bestch = s, ch
        cache[gid] = (bestch, best)
        if args.sheet:
            tiles.append((gid, bestch, best, bits))

    if args.sheet:
        cols = 12
        CW, CH = 70, 110
        rows = (len(tiles) + cols - 1) // cols
        sheet = Image.new("L", (cols * CW, rows * CH), 255)
        dr = ImageDraw.Draw(sheet)
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        for i, (gid, ch, s, bits) in enumerate(tiles):
            x0, y0 = (i % cols) * CW, (i // cols) * CH
            dr.text((x0 + 4, y0 + 2),
                    f"{gid.replace('glyph','g')}={ch} {s:.2f}",
                    fill=0, font=font)
            if bits is not None:
                ys, xs = np.where(bits)
                if len(ys):
                    crop = bits[ys.min():ys.max() + 1,
                                xs.min():xs.max() + 1]
                    sim = Image.fromarray(((~crop) * 255).astype("uint8"))
                    sim = sim.resize((min(50, sim.width),
                                      min(70, sim.height)))
                    sheet.paste(sim, (x0 + 8, y0 + 18))
        sheet.save(args.sheet)

    scale = args.dpi / 96.0
    # group into strings: same baseline (y within 1.5), x-adjacent
    uses.sort(key=lambda u: (round(u[2] / 3), u[1]))
    used = [False] * len(uses)
    strings = []
    for i, (gid, x, y) in enumerate(uses):
        if used[i]:
            continue
        grp = [(gid, x, y)]
        used[i] = True
        ch, s = cache[gid]
        base_y, done = y, False
        while not done:
            done = True
            # repeatedly append nearest right neighbor
            last = grp[-1]
            best = None
            for j, (g2, x2, y2) in enumerate(uses):
                if used[j] or abs(y2 - base_y) >= 1.5:
                    continue
                dx = x2 - last[1]
                if 0.1 < dx < 4.0 and (best is None or dx < best[0]):
                    best = (dx, j)
            if best:
                used[best[1]] = True
                grp.append(uses[best[1]])
                done = False
        if len(grp) >= 1:
            text = "".join(cache[g][0] or "?" for g, _, _ in grp)
            conf = [round(cache[g][1], 2) for g, _, _ in grp]
            xs0 = min(x for _, x, _ in grp) * scale
            xs1 = max(x for _, x, _ in grp) * scale
            ys0 = min(y for _, _, y in grp) * scale
            ys1 = max(y for _, _, y in grp) * scale
            strings.append({
                "text": text, "conf": conf,
                "cx_px": (xs0 + xs1) / 2, "cy_px": (ys0 + ys1) / 2,
                "bbox_px": [xs0, ys0, xs1, ys1],
            })

    out = args.out or "strings.json"
    json.dump({"svg": args.svg, "dpi": args.dpi, "strings": strings},
              open(out, "w"), indent=1)
    print(f"{len(strings)} strings -> {out}")


if __name__ == "__main__":
    main()
