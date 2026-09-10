#!/usr/bin/env python3
"""Decode vector-outlined text (part designators) from pdftocairo SVG exports.

Icom service-manual PCB pages draw part designators as vector outlines instead
of real text: pdftotext returns almost nothing and plain OCR fails on the thin
stroked glyphs. `pdftocairo -svg` however exports every letter as precise path
data. This tool parses those paths, groups them back into strings and
classifies each letter against font-rendered templates.

Pipeline:
  1. svgelements parses the SVG; keep stroked <path> elements
  2. split each path into subpaths (letters + their holes/counters)
  3. merge hole subpaths into their containing letter
  4. group letters left-to-right into strings (page coords)
  5. dedupe letters by path-data hash; classify unique shapes by rendering
     them (cairosvg, filled, evenodd) and matching against matplotlib
     TextPath templates (Liberation Sans / Helvetica metrics) via IoU
  6. dump designator strings with pixel positions as JSON

Coordinate notes:
  svgelements reports page coords in CSS px (pt * 96/72); a PNG rendered at
  `dpi` from the same PDF maps svg_px * dpi/96 -> image_px.

Usage:
  python3 svg_glyph_decode.py <page.svg> [--dpi 300] [--out out.json]
                              [--min-iou 0.55] [--max-gap 1.0] [--debug-img]
"""
import argparse
import hashlib
import io
import json
import re

import cairosvg
import numpy as np
import svgelements as se
from PIL import Image


def svg_path_bbox_local(d):
    p = se.Path(d)
    try:
        bb = p.bbox()
    except Exception:
        return None
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    if not all(np.isfinite(v) for v in bb):
        return None
    return x0, y0, x1, y1


def contains(a, b, margin=0.5):
    """bbox a contains bbox b"""
    return (a[0] - margin <= b[0] and a[1] - margin <= b[1] and
            b[2] <= a[2] + margin and b[3] <= a[3] + margin)


def group_letters(subs):
    """subs: list of (d_local, bbox_page). merge holes into containers.
    returns list of letters: {'parts': [d...], 'bbox': (x0,y0,x1,y1)}"""
    boxes = sorted(subs, key=lambda s: (s[1][2] - s[1][0]) * (s[1][3] - s[1][1]),
                   reverse=True)
    letters = []
    for d, bb in boxes:
        placed = False
        for L in letters:
            if contains(L["bbox"], bb):
                L["parts"].append(d)
                placed = True
                break
        if not placed:
            letters.append({"parts": [d], "bbox": bb})
    return letters


def letter_d(letter):
    return " ".join(letter["parts"])


def rasterize(d, size=96):
    bb = svg_path_bbox_local(d)
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    w, h = max(1e-3, x1 - x0), max(1e-3, y1 - y0)
    W = size
    H = min(512, max(4, int(round(h / w * size))))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" '
           f'height="{H}" viewBox="{x0} {y0} {w} {h}">'
           f'<path d="{d}" fill="black" fill-rule="evenodd"/></svg>')
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


def make_templates(chars):
    from matplotlib.font_manager import FontProperties, findfont
    from matplotlib.textpath import TextPath
    fp = findfont(FontProperties(family=["Liberation Sans", "Arial",
                                         "DejaVu Sans"]))
    tpl_bits = {}
    for ch in chars:
        tp = TextPath((0, 0), ch, prop=FontProperties(fname=fp))
        d = path_from_textpath(tp)
        bits = rasterize(d)
        if bits is not None:
            tpl_bits[ch] = bits
    return tpl_bits


def path_from_textpath(tp):
    parts, i = [], 0
    verts, codes = tp.vertices, tp.codes
    n = len(codes)
    while i < n:
        c = codes[i]
        if c == 1:  # MOVETO
            parts.append(f"M{verts[i][0]:.3f} {verts[i][1]:.3f}")
            i += 1
        elif c == 2:  # LINETO
            parts.append(f"L{verts[i][0]:.3f} {verts[i][1]:.3f}")
            i += 1
        elif c == 3:  # CURVE3: control here, end next
            cx, cy = verts[i]
            ex, ey = verts[i + 1]
            parts.append(f"Q{cx:.3f} {cy:.3f} {ex:.3f} {ey:.3f}")
            i += 2
        elif c == 4:  # CURVE4: c1, c2, end
            c1, c2, e = verts[i], verts[i + 1], verts[i + 2]
            parts.append(f"C{c1[0]:.3f} {c1[1]:.3f} {c2[0]:.3f} {c2[1]:.3f} "
                         f"{e[0]:.3f} {e[1]:.3f}")
            i += 3
        else:  # CLOSEPOLY etc
            i += 1
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("--dpi", type=int, default=300,
                    help="dpi of the rendered PNG these coords must match")
    ap.add_argument("--out", default=None)
    ap.add_argument("--min-iou", type=float, default=0.55)
    ap.add_argument("--max-gap", type=float, default=1.0,
                    help="max letter gap to merge, in letter heights")
    args = ap.parse_args()

    svg = se.SVG.parse(args.svg)
    els = list(svg.elements())
    CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
    tpls = make_templates(CHARS)

    scale = args.dpi / 96.0  # svgelements px (css) -> rendered png px

    results, cache = [], {}

    def classify(letter):
        d = letter_d(letter)
        h = hashlib.md5(d.encode()).hexdigest()
        if h in cache:
            return cache[h]
        res = (None, 0.0)
        bits = rasterize(d)
        if bits is not None and bits.sum() > 4:
            # letters are solid-ish shapes; reject thin line fragments
            ys, xs = np.where(bits)
            area = bits.size
            if bits.sum() / area < 0.02:
                cache[h] = res
                return res
            best, bestch = 0.0, None
            for ch, tb in tpls.items():
                s = iou_score(bits, tb)
                if s > best:
                    best, bestch = s, ch
            res = (bestch, best)
        cache[h] = res
        return res

    for el in els:
        if not isinstance(el, se.Path) or el.stroke is None:
            continue
        try:
            subs = list(el.as_subpaths())
            if len(subs) < 2:
                continue
            items = []
            for sp in subs:
                d_local = sp.d()
                bb = sp.bbox()  # page css px
                if bb is None:
                    continue
                bb = tuple(float(v) for v in bb)
                # reject degenerate subpaths (bare lines / zero area)
                if bb[2] - bb[0] < 0.5 or bb[3] - bb[1] < 0.5:
                    continue
                items.append((d_local, bb))
        except Exception:
            continue
        if not items:
            continue
        letters = group_letters(items)
        if len(letters) < 2:
            continue
        letters.sort(key=lambda L: L["bbox"][0])
        words, cur = [], [letters[0]]
        for L in letters[1:]:
            prev = cur[-1]
            ph = prev["bbox"][3] - prev["bbox"][1]
            gap = L["bbox"][0] - prev["bbox"][2]
            if gap > args.max_gap * max(ph, 1e-6):
                words.append(cur)
                cur = [L]
            else:
                cur.append(L)
        words.append(cur)
        for w in words:
            text, confs, ok = "", [], True
            for L in w:
                ch, s = classify(L)
                if ch is None or s < args.min_iou:
                    ok = False
                    break
                text += ch
                confs.append(round(s, 2))
            if not ok or len(w) < 2:
                continue
            xs0 = min(L["bbox"][0] for L in w)
            ys0 = min(L["bbox"][1] for L in w)
            xs1 = max(L["bbox"][2] for L in w)
            ys1 = max(L["bbox"][3] for L in w)
            results.append({
                "text": text, "conf": confs,
                "cx_px": ((xs0 + xs1) / 2) * scale,
                "cy_px": ((ys0 + ys1) / 2) * scale,
                "bbox_px": [xs0 * scale, ys0 * scale, xs1 * scale, ys1 * scale],
            })

    out = args.out or "extract/glyphs.json"
    json.dump({"svg": args.svg, "dpi": args.dpi, "strings": results},
              open(out, "w"), indent=1)
    print(f"{len(results)} strings -> {out}")


if __name__ == "__main__":
    main()
