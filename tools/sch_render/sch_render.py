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
    ap.add_argument("--show-aux", action="store_true",
                    help="渲染非 flow_through 组件 (灰点辅助标记)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    mask = color_mask(img, args.color)
    db = json.load(open(args.db))

    overlay = img.copy()
    overlay[mask > 0] = [0, 255, 0]
    color_map = {"flow_through": (0, 255, 255), "branch": (255, 0, 0), "none": (128, 128, 128)}
    # 只渲染 flow_through (主路) + branch, 按符号位置去重 (一个符号一个红点)
    # 非 flow_through 由 --show-aux 控制 (灰点辅助)
    seen_pos = set()
    shown = []
    aux = []
    for c in db["components"]:
        m = c.get("membership", "none")
        sp = tuple(c["symbol_pos"])
        if sp in seen_pos:
            continue
        seen_pos.add(sp)
        if m == "flow_through":
            shown.append(c)
        elif args.show_aux:
            aux.append(c)
    for c in shown:
        sx, sy = c["symbol_pos"]
        tp = c.get("text_pos")
        color = (0, 255, 255)
        if tp:
            cv2.line(overlay, tuple(tp), (sx, sy), (0, 0, 255), 1)
            cv2.circle(overlay, tuple(tp), 12, color, 2)
            cv2.putText(overlay, str(c.get("refdes", "")), (tp[0] - 20, tp[1] - 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        # 符号边界 (sch_symbol_verify 检测): 圆/方块
        bd = c.get("sym_boundary")
        if bd:
            if bd.get("kind") == "circle":
                cv2.circle(overlay, (bd["cx"], bd["cy"]), bd["r"], (0, 255, 255), 2)
            elif bd.get("kind") == "rect":
                cv2.rectangle(overlay, (bd["cx"], bd["cy"]),
                              (bd["cx"] + bd["w"], bd["cy"] + bd["h"]), (0, 255, 255), 2)
        # label 文字框
        tbox = c.get("text_box")
        if tbox and len(tbox) == 4:
            xs = [p[0] for p in tbox]; ys = [p[1] for p in tbox]
            cv2.rectangle(overlay, (min(xs), min(ys)), (max(xs), max(ys)), (0, 165, 255), 2)
        cv2.circle(overlay, (sx, sy), 6, (0, 0, 255), -1)
    # 辅助灰点 (非 flow_through)
    for c in aux:
        sx, sy = c["symbol_pos"]
        cv2.circle(overlay, (sx, sy), 5, (128, 128, 128), -1)

    # 图例: 按图比例缩放, 放在空白区 (低墨量象限)
    H, W = img.shape[:2]
    gray_g = cv2.cvtColor(overlay, cv2.COLOR_BGR2GRAY)
    ink = gray_g < 200
    # 找空白象限: 四象限中暗像素最少者
    quad = [(0, 0, W//2, H//2), (W//2, 0, W, H//2), (0, H//2, W//2, H), (W//2, H//2, W, H)]
    best_q = min(quad, key=lambda q: ink[q[1]:q[3], q[0]:q[2]].sum())
    lx0, ly0, lx1, ly1 = best_q
    lw_px = int(W / 5100.0)      # 比例系数 (5100 宽基准)
    lw_px = max(1, lw_px)
    box_w = int(560 * lw_px)
    item_h = int(48 * lw_px)
    fs_title = 1.1 * lw_px
    fs_item = 0.85 * lw_px
    ly = ly0 + 30 * lw_px
    cv2.rectangle(overlay, (lx0 + 20, ly0 + 20), (lx0 + 20 + box_w, ly0 + 30 + 6 * item_h + 10),
                  (255, 255, 255), -1)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(overlay, "Legend", (lx0 + 30, ly), font, fs_title, (0, 0, 0), 3 * lw_px)
    items = [("RX flow line", (0, 255, 0), "line"),
             ("flow_through (main path)", (0, 255, 255), "circle"),
             ("branch (side path)", (255, 0, 0), "circle"),
             ("none (not on flow)", (128, 128, 128), "circle"),
             ("symbol center", (0, 0, 255), "dot"),
             ("label->symbol link", (0, 0, 255), "line")]
    cx0 = lx0 + 50 * lw_px
    for label, color, kind in items:
        ly += item_h
        if kind == "circle":
            cv2.circle(overlay, (cx0, ly), int(16 * lw_px), color, int(4 * lw_px))
        elif kind == "dot":
            cv2.circle(overlay, (cx0, ly), int(8 * lw_px), color, -1)
        else:
            cv2.line(overlay, (lx0 + 40 * lw_px, ly), (lx0 + 100 * lw_px, ly), color, int(5 * lw_px))
        cv2.putText(overlay, label, (lx0 + 115 * lw_px, ly + 8 * lw_px), font, fs_item,
                    (0, 0, 0), 3 * lw_px)
    cv2.imwrite(args.out, overlay)
    print(f"[sch_render] saved: {args.out} (legend at quadrant {best_q[0]},{best_q[1]})")


if __name__ == "__main__":
    main()