#!/usr/bin/env python3
"""tools/sch-true-finding/color_layer.py — 信号颜色图层 (rx/tx color layer)

purpose: 用**图例准确色** (explanatory_notes.json) 输出**颜色图层**: 灰度原理图
        + 指定信号色高亮 (如 rx_color_layer = 全图灰, RX绿线彩色). 重要视觉
        结果: 一眼看出该信号的标注位置. 通用工具 (信号可组合, 如 RX+COMMON).
format: Python 3 + OpenCV
version: 0.2 (2026-09-18)

用法:
  python3 color_layer.py --img sch-600.png --legend explanatory_notes.json \
    --signals RX,COMMON --out rx_color_layer.png
  python3 color_layer.py --img sch-600.png --legend explanatory_notes.json \
    --signals TX,COMMON --out tx_color_layer.png
  [--tol 60] [--dark 150] [--gray-bg]   # --gray-bg 只留灰度底, 无彩色其它
"""

import argparse
import json
import sys

import cv2
import numpy as np


def legend_colors(legend_json):
    with open(legend_json) as f:
        d = json.load(f)
    out = {}
    for e in d.get("entries", []):
        if e.get("color_bgr") and e.get("label"):
            out[e["label"].upper()] = e["color_bgr"]
    return out


def rgb_mask(img, sample_bgr, tol):
    b, g, r = cv2.split(img.astype(int))
    sb, sg, sr = sample_bgr
    return ((np.abs(b - sb) <= tol) & (np.abs(g - sg) <= tol)
            & (np.abs(r - sr) <= tol)).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--legend", required=True, help="explanatory_notes.json")
    ap.add_argument("--signals", required=True,
                    help="高亮哪些信号 (逗号分隔, 如 RX,COMMON / TX,COMMON)")
    ap.add_argument("--out", required=True, help="输出图 (如 rx_color_layer.png)")
    ap.add_argument("--tol", type=int, default=60, help="RGB 容差")
    ap.add_argument("--fade", type=float, default=0.45,
                    help="非目标内容褪色度: 向白混合比例 (0=全白, 1=原样; 目标信号突出)")
    ap.add_argument("--gray-bg", action="store_true",
                    help="背景只留灰度 (其它彩色像素也变灰)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    colors = legend_colors(args.legend)
    if not colors:
        sys.exit("legend 无色彩样本")

    want = [s.strip().upper() for s in args.signals.split(",")]
    targets = {k: v for k, v in colors.items() if any(w in k for w in want)}
    if not targets:
        sys.exit(f"legend 无 {args.signals} 色")

    # 图层效果 (用户定稿): 白底 + 非目标内容**调淡** (向白混合, 变浅不黑) + 目标信号彩色
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    content = gray < 245                                   # 非背景 (白底排除)
    faded = np.clip(gray * args.fade + 255 * (1 - args.fade), 0, 255).astype(np.uint8)
    out = np.full_like(img, 255)
    out[content, 0] = faded[content]
    out[content, 1] = faded[content]
    out[content, 2] = faded[content]
    # 目标信号像素恢复彩色
    for label, bgr in targets.items():
        m = rgb_mask(img, bgr, args.tol) > 0
        out[m] = img[m]
    cv2.imwrite(args.out, out)
    print(f"[color_layer] signals={args.signals} targets={list(targets)} "
          f"-> {args.out}")


if __name__ == "__main__":
    main()