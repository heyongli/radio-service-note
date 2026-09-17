#!/usr/bin/env python3
"""tools/sch_flow_walk/sch_flow_walk.py — 层2 鉴别: 绿线流走线 (flow walk)

purpose: 读 sch_components.json, 判定每个组件是否属于绿线流经:
         flow_through (主路: 绿线两侧共线通过) / branch (支路: 单侧) / none
         更新 sch_components.json 的 membership 字段 (schema §3.5)
format: Python 3 + OpenCV
version: 0.1 (2026-09-16)

用法:
  python3 sch_flow_walk.py --img render/rxtx-sch-600-1.png \
      --color green --db sch_components.json

与 sch_recognize / sch_render 通过 sch_components.json 交互:
  识别(sch_recognize) → 鉴别(本程序) → 渲染(sch_render)
"""

import argparse
import json
import sys

import cv2
import numpy as np


def color_mask(img, color, g_th=120, r_th=110, b_th=110):
    b, g, r = cv2.split(img.astype(int))
    if color == "green":
        return ((g > g_th) & (r < r_th) & (b < b_th)).astype(np.uint8)
    if color == "red":
        return ((r > g_th) & (g < r_th) & (b < b_th)).astype(np.uint8)
    if color == "cyan":
        return ((g > g_th) & (b > g_th) & (r < r_th)).astype(np.uint8)
    if color == "yellow":
        return ((r > g_th) & (g > g_th) & (b < r_th)).astype(np.uint8)
    raise ValueError(color)


def verify(components, green, band=14):
    """给每个组件加 membership (绿线鉴别)."""
    H, W = green.shape
    out = []
    for c in components:
        sx, sy = c["symbol_pos"]
        touch = green[max(0, sy - 25):sy + 25, max(0, sx - 25):sx + 25].sum() > 0
        sides = []
        if not touch:
            c["membership"] = "none"
            c["green_sides"] = []
            c["green_touch"] = False
            out.append(c)
            continue
        e = green[max(0, sy - band):sy + band, min(sx + 30, W - 1):min(sx + 70, W - 1)].sum() > 0
        w = green[max(0, sy - band):sy + band, max(0, sx - 70):max(0, sx - 30)].sum() > 0
        n = green[max(0, sy - 70):max(0, sy - 30), max(0, sx - band):sx + band].sum() > 0
        s = green[min(sy + 30, H - 1):min(sy + 70, H - 1), max(0, sx - band):sx + band].sum() > 0
        if e: sides.append("E")
        if w: sides.append("W")
        if n: sides.append("N")
        if s: sides.append("S")
        c["green_touch"] = True
        c["green_sides"] = sides
        if (e and w) or (n and s):
            c["membership"] = "flow_through"
            c["flow_dir"] = "H" if (e and w) else "V"
        elif len(sides) >= 1:
            c["membership"] = "branch"
        else:
            c["membership"] = "none"
        out.append(c)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True, help="原理图渲染图")
    ap.add_argument("--color", default="green", choices=["green", "red", "cyan", "yellow"])
    ap.add_argument("--db", required=True, help="sch_components.json (读+写 membership)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    mask = color_mask(img, args.color)
    print(f"[sch_flow_walk] {args.color} mask: {(mask > 0).sum()} px")

    db = json.load(open(args.db))
    db["components"] = verify(db["components"], mask)
    db["_meta"]["verify"] = f"{args.color} flow membership"
    with open(args.db, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    ft = [c for c in db["components"] if c["membership"] == "flow_through"]
    br = [c for c in db["components"] if c["membership"] == "branch"]
    print(f"[sch_flow_walk] flow_through={len(ft)} branch={len(br)} none={len(db['components'])-len(ft)-len(br)}")
    for c in ft:
        rd = c["refdes"] if c["refdes"] else "-"
        print(f"  {rd:6s} sides={c['green_sides']} {c['flow_dir']}")


if __name__ == "__main__":
    main()