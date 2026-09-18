#!/usr/bin/env python3
"""tools/sch-true-finding/de_greenline.py — 去除绿线 (de-greenline)

purpose: 从原理图中去除信号流绿线 (RX 主路标注), 得到"绿线从未存在"的底图.
        绿线在最下层 (被走线/文字盖住, 不遮挡上层内容), 直接丢弃即可.
        但边界有深色绿描边 (抗锯齿), 需扩展掩膜覆盖, 否则残留淡绿.
format: Python 3 + OpenCV
version: 0.1 (2026-09-17)

算法:
  1. 核心绿线掩膜: 颜色阈值 (g>120 & r<110 & b<110)
  2. 描边扩展: 色相 55-90° (绿) + 灰度 40-200 (深色非纯黑) + 非核心
     (深色绿描边, 排除走线纯黑/亮文字)
  3. 掩膜像素置白 (丢弃)

用法:
  python3 de_greenline.py --img sch.png --out sch_no_green.png

消费方: sch_wire (走线识别前去除绿线干扰) 等.
原理: 绿线在最下层 (best_practices §5b-3), 去除不遮挡内容.
"""

import argparse
import sys

import cv2
import numpy as np


def core_green_mask(img, g_th=120, r_th=110, b_th=110):
    """核心绿线掩膜 (颜色阈值)."""
    b, g, r = cv2.split(img.astype(int))
    return ((g > g_th) & (r < r_th) & (b < b_th)).astype(np.uint8)


def edge_green_mask(img, core, h_lo=55, h_hi=90, gray_lo=40, gray_hi=200):
    """深色绿描边掩膜 (抗锯齿边界). 色相绿 + 灰度 40-200 + 非核心."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0]
    gv = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return ((h >= h_lo) & (h <= h_hi) & (gv >= gray_lo) & (gv < gray_hi)
            & (core == 0)).astype(np.uint8)


def greenline_mask(img, g_th=120, r_th=110, b_th=110, h_lo=55, h_hi=90,
                   gray_lo=40, gray_hi=200):
    """完整绿线掩膜 = 核心 + 描边."""
    core = core_green_mask(img, g_th, r_th, b_th)
    edge = edge_green_mask(img, core, h_lo, h_hi, gray_lo, gray_hi)
    return ((core > 0) | (edge > 0)).astype(np.uint8)


def de_greenline(img, mask, fill=255):
    """去除绿线: 掩膜像素用 fill 填充."""
    out = img.copy()
    out[mask > 0] = fill
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fill", type=int, default=255, help="填充色 (255=白)")
    ap.add_argument("--g-th", type=int, default=120)
    ap.add_argument("--r-th", type=int, default=110)
    ap.add_argument("--b-th", type=int, default=110)
    ap.add_argument("--h-lo", type=int, default=55, help="绿描边色相下限")
    ap.add_argument("--h-hi", type=int, default=90, help="绿描边色相上限")
    ap.add_argument("--gray-lo", type=int, default=40, help="排除纯黑走线下限")
    ap.add_argument("--gray-hi", type=int, default=200, help="排除亮背景上限")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    mask = greenline_mask(img, args.g_th, args.r_th, args.b_th,
                          args.h_lo, args.h_hi, args.gray_lo, args.gray_hi)
    out = de_greenline(img, mask, args.fill)
    cv2.imwrite(args.out, out)
    core = int(core_green_mask(img, args.g_th, args.r_th, args.b_th).sum())
    print(f"[de-greenline] removed {int(mask.sum())} px "
          f"(core {core} + edge {int(mask.sum())-core}), fill={args.fill}, "
          f"saved {args.out}")


if __name__ == "__main__":
    main()