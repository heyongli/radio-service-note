#!/usr/bin/env python3
"""tools/sch_render/sch_render.py — 层3 渲染 (识别+鉴别结果到原理图)

purpose: 读 sch_components.json, 把识别+鉴别结果渲染到原理图:
         绿线高亮, 组件按 membership 着色 (flow_through/branch/none),
         标号→符号红连线
format: Python 3 + OpenCV
version: 0.1 (2026-09-16)

用法:
  python3 sch_render.py --img render/rxtx-sch-600-1.png \
      --color green --db sch_components.json --out sch_flow_roundXXX.png

与 sch_recognize / sch_verify 通过 sch_components.json 交互 (独立渲染层).
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True, help="原理图渲染图")
    ap.add_argument("--color", default="green", choices=["green", "red", "cyan", "yellow"])
    ap.add_argument("--db", required=True, help="sch_components.json")
    ap.add_argument("--out", required=True, help="输出 PNG")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    mask = color_mask(img, args.color)
    db = json.load(open(args.db))

    overlay = img.copy()
    overlay[mask > 0] = [0, 255, 0]
    color_map = {"flow_through": (0, 255, 255), "branch": (255, 0, 0), "none": (128, 128, 128)}
    for c in db["components"]:
        sx, sy = c["symbol_pos"]
        tp = c.get("text_pos")
        m = c.get("membership", "none")
        color = color_map.get(m, (128, 128, 128))
        if tp:
            cv2.line(overlay, tuple(tp), (sx, sy), (0, 0, 255), 1)
            cv2.circle(overlay, tuple(tp), 12, color, 2)
            cv2.putText(overlay, str(c.get("refdes", "")), (tp[0] - 20, tp[1] - 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.circle(overlay, (sx, sy), 6, (0, 0, 255), -1)
    cv2.imwrite(args.out, overlay)
    print(f"[sch_render] saved: {args.out}")


if __name__ == "__main__":
    main()