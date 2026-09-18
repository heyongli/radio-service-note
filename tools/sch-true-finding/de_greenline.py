#!/usr/bin/env python3
"""tools/sch-true-finding/de_greenline.py — 去除信号流标注线 (de-annotation)

purpose: 从原理图中去除信号流标注线 (绿=RX/红=TX/黄=控制/青=common),
        得到"标注从未存在"的纯净底图. 标注线叠在深色走线上 (best_practices §4),
        直接丢弃即可; 但边界有深色描边 (抗锯齿), 需扩展掩膜覆盖.
format: Python 3 + OpenCV
version: 0.2 (2026-09-17) — 扩展为 de-annotation (保留 --color green 独立能力)

算法:
  1. 核心掩膜: 颜色阈值 (对应色)
  2. 描边扩展: 色相范围 + 灰度 40-200 (深色非纯黑) + 非核心
  3. 掩膜像素置白 (丢弃)

用法:
  python3 de_greenline.py --img sch.png --out sch_no_green.png          # 去绿线 (兼容)
  python3 de_greenline.py --img sch.png --out sch_no_annot.png --color all   # 去全部标注

消费方: sch_wire (走线识别前去除标注干扰) 等.
"""

import argparse
import sys

import cv2
import numpy as np

# 标注色中心 (OpenCV 色相 0-180): green=70, red=160, cyan=90, yellow=30
COLOR_SPEC = {
    "green":  {"h_center": 70, "h_tol": 12, "g_th": 120, "r_th": 110, "b_th": 110},
    "red":    {"h_center": 160, "h_tol": 12, "g_th": None, "r_th": 130, "b_th": 110,
               "h_ranges": [(0, 25), (150, 170)]},  # 红橙(TX) + 品红
    "cyan":   {"h_center": 90, "h_tol": 10, "g_th": 120, "r_th": 110, "b_th": 120},
    "yellow": {"h_center": 30, "h_tol": 12, "g_th": 120, "r_th": 120, "b_th": 100},
}


def core_mask(img, spec, g_th=None, r_th=None, b_th=None):
    """核心掩膜 (颜色阈值). g_th/r_th/b_th 覆写 spec."""
    b, g, r = cv2.split(img.astype(int))
    g_th = g_th if g_th is not None else spec.get("g_th", 120)
    r_th = r_th if r_th is not None else spec.get("r_th", 110)
    b_th = b_th if b_th is not None else spec.get("b_th", 110)
    cond = np.ones(img.shape[:2], bool)
    if g_th is not None:
        cond &= (g > g_th)
    cond &= (r < r_th) & (b < b_th)
    return cond.astype(np.uint8)


def hue_mask(img, spec, gray_lo=40, gray_hi=200, h_tol=None):
    """色相掩膜 (标注色 + 灰度范围). 用于核心掩膜补充 (抗锯齿边缘).

    支持 h_ranges (多色相范围, 如红=橙红0-25 + 品红150-170).
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0]
    gv = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if spec.get("h_ranges"):
        hm = np.zeros(img.shape[:2], np.uint8)
        for lo, hi in spec["h_ranges"]:
            hm |= ((h >= lo) & (h <= hi)).astype(np.uint8)
    else:
        hc = spec["h_center"]
        tol = h_tol if h_tol is not None else spec["h_tol"]
        # 色相环上取范围 (含 0/180 环绕)
        if hc - tol < 0:
            hm = ((h >= hc - tol + 180) | (h <= hc + tol)).astype(np.uint8)
        elif hc + tol > 180:
            hm = ((h >= hc - tol) | (h <= hc + tol - 180)).astype(np.uint8)
        else:
            hm = ((h >= hc - tol) & (h <= hc + tol)).astype(np.uint8)
    return ((hm > 0) & (gv >= gray_lo) & (gv < gray_hi)).astype(np.uint8)


def annotation_mask(img, color="green", g_th=None, r_th=None, b_th=None,
                    gray_lo=40, gray_hi=200, h_tol=None, wire_net=None,
                    s_min=0, diff_th=0):
    """标注线掩膜. color: green/red/cyan/yellow/all.

    diff_th (BGR 通道差法, 推荐): >0 时用 maxdiff = max(|G-R|,|G-B|,|R-B|),
      通道差 > diff_th = 标注 (彩色), 保留低通道差 (灰走线).
      **比 HSV 可靠**: 走线灰 → 通道差≈0, 标注彩色 → 通道差大;
      暗走线在 HSV 下饱和/色相噪声大会误删.
    s_min: 饱和度下限 (原 HSV 方法, 默认0全收).
    wire_net: 若给, 只保留 wire 导体结构上的标注 (高置信约束, 防误删)."""
    if diff_th > 0:
        b, g, r = cv2.split(img.astype(int))
        maxdiff = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
        total = (maxdiff > diff_th).astype(np.uint8)
        if wire_net is not None:
            total = (total & wire_net).astype(np.uint8)
        return total
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    colors = list(COLOR_SPEC) if color == "all" else [color]
    total = None
    for c in colors:
        spec = COLOR_SPEC[c]
        core = core_mask(img, spec, g_th, r_th, b_th)
        edge = hue_mask(img, spec, gray_lo, gray_hi, h_tol)
        m = ((core > 0) | (edge > 0)).astype(np.uint8)
        if s_min > 0:
            m = (m & (s > s_min)).astype(np.uint8)
        total = m if total is None else ((total > 0) | (m > 0)).astype(np.uint8)
    if wire_net is not None and total is not None:
        total = (total & wire_net).astype(np.uint8)
    return total


def de_annotation(img, mask, fill=255):
    """去除标注线: 掩膜像素用 fill 填充."""
    out = img.copy()
    out[mask > 0] = fill
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--color", default="green",
                    choices=["green", "red", "cyan", "yellow", "all"],
                    help="去除哪种标注 (green=RX/red=TX/yellow=控制/cyan=common/all)")
    ap.add_argument("--fill", type=int, default=255, help="填充色 (255=白)")
    ap.add_argument("--g-th", type=int, default=None)
    ap.add_argument("--r-th", type=int, default=None)
    ap.add_argument("--b-th", type=int, default=None)
    ap.add_argument("--h-tol", type=int, default=None, help="色相容差 (覆盖 spec)")
    ap.add_argument("--s-min", type=int, default=0,
                    help="饱和度下限 (标注高饱和; >80 排除低饱和走线, 防误删)")
    ap.add_argument("--diff-th", type=int, default=0,
                    help="BGR 通道差阈值 (标注识别最佳; >40=彩色标注, 保留灰走线)")
    ap.add_argument("--gray-lo", type=int, default=40, help="排除纯黑走线下限")
    ap.add_argument("--gray-hi", type=int, default=200, help="排除亮背景上限")
    ap.add_argument("--wire-net", default=None,
                    help="wire net 掩膜 PNG (只去除其上的标注, 防误删)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    wn = None
    if args.wire_net:
        wn = cv2.imread(args.wire_net, cv2.IMREAD_GRAYSCALE)
        if wn is None:
            sys.exit(f"cannot read wire net {args.wire_net}")
        wn = (wn > 0).astype(np.uint8)
    mask = annotation_mask(img, args.color, args.g_th, args.r_th, args.b_th,
                           args.gray_lo, args.gray_hi, args.h_tol, wn,
                           args.s_min, args.diff_th)
    out = de_annotation(img, mask, args.fill)
    cv2.imwrite(args.out, out)
    print(f"[de-annotation] color={args.color} removed {int(mask.sum())} px, "
          f"fill={args.fill}, wire_net={'on' if wn is not None else 'off'}, "
          f"saved {args.out}")


if __name__ == "__main__":
    main()