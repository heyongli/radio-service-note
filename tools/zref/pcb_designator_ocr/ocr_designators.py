#!/usr/bin/env python3
"""tools/pcb_designator_ocr/ocr_designators.py — 旧版位号 OCR
purpose: 用 OpenCV 找 ROI 后跑 Tesseract OCR (旧方案)
format: Python 3 + OpenCV + pytesseract
version: 0.2.0 (2026-09-15, 已备留, 用 ai_ocr_eval/ai_refdes_ocr.py 替代)
consumers: 旧流程基线"""

"""Designator OCR for service-manual PCB view rasters (top/bot view PNG/PDF).

Proven pipeline (2026-09, IC-2200H):
  1. source: PNG (or PDF rendered via pdftoppm at 600 dpi)
  2. gray -> autocontrast
  3. multi-threshold binarize sweep (T=100..250), 2-3x LANCZOS upscale
  4. tesseract --psm 11 TSV, designator regex filter, confidence floor
  5. cross-threshold merge: same label within ~40px = same hit (max conf kept)
  6. glyph-cluster fallback for full-image OCR misses:
     connected components (h 5-28, w 2-20, aspect<6) -> cKDTree(20px)
     union-find groups -> per-group 4x crop -> tesseract psm 7+8
  7. JSON out: label -> [{"x","y","conf","src"}]  (x,y at source-image scale)

Caveats: dense-background zones (AF section) can defeat both passes —
use visual tile reading there (see best_practices.md §5).

Usage:
  python3 ocr_designators.py <png|pdf> [--dpi 600] [--thresh 100,140,170,200,230]
      [--conf 25] [--out out.json] [--scale 0.5]  # scale: halve 600dpi -> 300dpi coords
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageOps

DESIG_RE = re.compile(r"^(IC|Q|D|L|X|FI|CDB|J|SP|B|H|RL|HR|W|FL|F)[0-9OoIl]{1,3}[A-Z]?$")
FIXMAP = {"O": "0", "o": "0", "I": "1", "i": "1"}


def norm_label(t):
    t = t.strip().replace(" ", "")
    t = "".join(FIXMAP.get(c, c) for c in t)
    t = t.upper()
    m = re.match(r"^F1([0-9])$", t)  # FI1/FI2/FI3... 的 I 被读成 1
    if m:
        t = f"FI{m.group(1)}"
    if t == "D1Z":  # D12 的 2 被读成 Z
        t = "D12"
    return t


def render_if_pdf(src, dpi):
    if src.lower().endswith(".pdf"):
        tmp = tempfile.mkdtemp(prefix="ocr_")
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", src, f"{tmp}/p"], check=True)
        pages = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
        return os.path.join(tmp, pages[0])
    return src


def tsv_tokens(img_l, x0, y0, thresh, up, psm="11"):
    b = img_l.point(lambda p: 255 if p > thresh else 0)
    b = b.resize((int(b.width * up), int(b.height * up)), Image.LANCZOS)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        b.save(f.name)
        path = f.name
    out = subprocess.run(["tesseract", path, "stdout", "--psm", psm, "tsv"],
                         capture_output=True, text=True).stdout
    os.unlink(path)
    toks = []
    for line in out.splitlines()[1:]:
        fl = line.split("\t")
        if len(fl) != 12 or not fl[11].strip():
            continue
        try:
            conf = float(fl[10])
        except ValueError:
            continue
        if conf < 5:
            continue
        gx = x0 + int(int(fl[6]) / up)
        gy = y0 + int(int(fl[7]) / up)
        toks.append((gx, gy, conf, fl[11]))
    return toks


def union_find_cluster(pts, radius):
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if math.dist(pts[i], pts[j]) <= radius:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    groups = {}
    for i in range(len(pts)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def glyph_fallback(img_l, conf_floor):
    from scipy import ndimage
    from scipy.spatial import cKDTree
    a = np.array(img_l)
    mask = a < 165
    lbl, n = ndimage.label(mask)
    objs = ndimage.find_objects(lbl)
    cands = []
    for sl in objs:
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        if 5 <= h <= 28 and 2 <= w <= 20 and w / h < 6:
            cands.append((sl[1].start, sl[0].start, w, h))
    if not cands:
        return []
    pts = [(x + w / 2, y + h / 2) for x, y, w, h in cands]
    groups = union_find_cluster(pts, 20)
    hits = []
    for g in groups:
        if not (1 <= len(g) <= 14):
            continue
        xs0 = min(cands[i][0] for i in g)
        ys0 = min(cands[i][1] for i in g)
        x1 = max(cands[i][0] + cands[i][2] for i in g)
        y1 = max(cands[i][1] + cands[i][3] for i in g)
        w, h = x1 - xs0, y1 - ys0
        if not (6 <= w <= 110 and 6 <= h <= 28):
            continue
        crop = img_l.crop((max(0, xs0 - 3), max(0, ys0 - 3), x1 + 6, y1 + 6))
        crop = crop.point(lambda p: 255 if p > 155 else 0)
        crop = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            crop.save(f.name)
            path = f.name
        txt = subprocess.run(["tesseract", path, "stdout", "--psm", "7"],
                             capture_output=True, text=True).stdout.strip()
        os.unlink(path)
        txt = norm_label(txt)
        if txt and conf_floor <= 0:
            hits.append((xs0, ys0, 40.0, txt, "glyph"))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--thresh", default="140,170,200,230")
    ap.add_argument("--conf", type=float, default=25.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--scale", type=float, default=1.0,
                    help="coords scaling (use 0.5 when --dpi 600 to get 300dpi space)")
    ap.add_argument("--no-glyph", action="store_true")
    a = ap.parse_args()

    png = render_if_pdf(a.source, a.dpi)
    img = ImageOps.autocontrast(Image.open(png).convert("L"))
    sc = a.scale

    merged = {}

    def add(lbl, x, y, conf, src):
        if not lbl:
            return
        key = (lbl, round(x * sc / 40) * 40, round(y * sc / 40) * 40)
        cur = merged.get(key)
        if not cur or conf > cur["conf"]:
            merged[key] = {"label": lbl, "x": int(x * sc), "y": int(y * sc),
                           "conf": round(conf), "src": src}

    for T in (a.thresh.split(",")):
        for gx, gy, conf, txt in tsv_tokens(img, 0, 0, int(T), 3.0):
            lbl = norm_label(txt)
            if not lbl:
                continue
            m = re.match(r"^F([0-9])$", lbl)
            cands = [lbl] + ([f"FI{m.group(1)}"] if m else [])
            for c in cands:
                if DESIG_RE.match(c) and conf >= a.conf:
                    add(c, gx, gy, conf, f"psm11 T{int(T)}")

    if not a.no_glyph:
        for gx, gy, conf, txt, src in glyph_fallback(img, a.conf):
            if txt and DESIG_RE.match(txt):
                add(txt, gx, gy, conf, src)

    result = {}
    for rec in merged.values():
        result.setdefault(rec["label"], []).append(rec)
    for v in result.values():
        v.sort(key=lambda r: -r["conf"])
    # 同位置不同 label 去重（J1/J4 同坐标取 conf 高者）
    seen = {}
    drop = set()
    for lbl, v in result.items():
        for i, r in enumerate(v):
            key = (round(r["x"] / 40), round(r["y"] / 40))
            if key in seen:
                plbl, pi, pconf = seen[key]
                if pconf >= r["conf"]:
                    drop.add((lbl, i))
                else:
                    drop.add((plbl, pi))
                    seen[key] = (lbl, i, r["conf"])
            else:
                seen[key] = (lbl, i, r["conf"])
    for lbl, i in drop:
        if lbl in result and i < len(result[lbl]):
            del result[lbl][i]
    result = {k: v for k, v in result.items() if v}

    out = a.out or os.path.join(os.path.dirname(a.source) or ".", "designators.json")
    json.dump({"source": png, "scale": sc, "designators": result},
              open(out, "w"), indent=1, ensure_ascii=False)
    n_multi = sum(1 for v in result.values() if len(v) > 1)
    print(f"{out}: {len(result)} labels, {n_multi} multi-hit, "
          f"{sum(len(v) for v in result.values())} hits total")


if __name__ == "__main__":
    main()
