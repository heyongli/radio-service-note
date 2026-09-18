#!/usr/bin/env python3
"""tools/sch-true-finding/de_annotate_chmask.py — 信号流标注去除 (通道掩膜法, 固化版)

purpose: 从原理图中去除信号流标注线 (绿=RX/红=TX/黄=控制/青=common), 得
        "标注从未存在"的纯净底图. **方法 = 通道掩膜 (chmask)**: 每色显式
        通道关系掩膜 (COLOR_SPEC ops) + 色相描边扩展, 置白去除.
        用户评估 (2026-09-18): 通道掩膜效果也还行 → 提取为独立固化程序.
        **方法简称 = chmask (channel mask)** → 命名 de_annotate_chmask.
format: Python 3 + OpenCV
version: 1.0 (2026-09-18)

算法:
  1. 每色核心掩膜: 显式通道关系 (COLOR_SPEC ops, 非"绿式"硬编码)
     green g>120/r<110/b<110; red r>150/g<110/b<200+色相; cyan g>120/r<110/b>120;
     yellow g>120/r>120/b<100
  2. 色相描边扩展 (抗锯齿边), 饱和度下限 s_min 防灰噪声 (red 曾 344k sat==0 误入)
  3. 掩膜置白 (丢弃)

用法:
  python3 de_annotate_chmask.py --img sch.png --out deannot.png
    [--color all] [--s-min 30] [--dark-th 150]

消费方: sch_wirenet (走线 net 识别前去除标注干扰), 原理图纯净底图.
"""

import argparse
import sys

import cv2
import numpy as np

# 标注色通道关系 (通道, 算子, 阈值). 核心掩膜按 ops 计算 (架构: 每色显式声明).
COLOR_SPEC = {
    "green":  {"h_center": 70, "h_tol": 12,
               "ops": [("g", ">", 120), ("r", "<", 110), ("b", "<", 110)]},
    "red":    {"h_center": 160, "h_tol": 12,
               "ops": [("r", ">", 150), ("g", "<", 110), ("b", "<", 200)],
               "h_ranges": [(0, 25), (150, 170)]},
    "cyan":   {"h_center": 90, "h_tol": 10,
               "ops": [("g", ">", 120), ("r", "<", 110), ("b", ">", 120)]},
    "yellow": {"h_center": 30, "h_tol": 12,
               "ops": [("g", ">", 120), ("r", ">", 120), ("b", "<", 100)]},
}


def core_mask(img, spec, hsv=None):
    """核心掩膜 (按 spec['ops'] 显式通道关系). spec 带 h_ranges 强制色相."""
    b, g, r = cv2.split(img.astype(int))
    cond = np.ones(img.shape[:2], bool)
    for ch, op, thr in spec["ops"]:
        v = {"g": g, "r": r, "b": b}[ch]
        cond &= (v > thr) if op == ">" else (v < thr)
    if spec.get("h_ranges"):
        if hsv is None:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h = hsv[:, :, 0]
        hm = np.zeros(img.shape[:2], bool)
        for lo, hi in spec["h_ranges"]:
            hm |= (h >= lo) & (h <= hi)
        cond &= hm
    return cond.astype(np.uint8)


def edge_mask(img, spec, hsv, s_min=30, gray_lo=40, gray_hi=200):
    """色相描边扩展 (抗锯齿). s_min 必须 (灰像素色相是噪声, 曾 red 344k sat==0 误入)."""
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    gv = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if spec.get("h_ranges"):
        hm = np.zeros(img.shape[:2], bool)
        for lo, hi in spec["h_ranges"]:
            hm |= (h >= lo) & (h <= hi)
    else:
        hc, tol = spec["h_center"], spec["h_tol"]
        if hc - tol < 0:
            hm = (h >= hc - tol + 180) | (h <= hc + tol)
        elif hc + tol > 180:
            hm = (h >= hc - tol) | (h <= hc + tol - 180)
        else:
            hm = (h >= hc - tol) & (h <= hc + tol)
    return ((hm > 0) & (gv >= gray_lo) & (gv < gray_hi) & (s > s_min)).astype(np.uint8)


def annotation_mask(img, color="all", s_min=30, gray_lo=40, gray_hi=200):
    """通道掩膜: 每色 core ∪ 描边扩展, 并集."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    colors = list(COLOR_SPEC) if color == "all" else [color]
    total = None
    for c in colors:
        spec = COLOR_SPEC[c]
        m = ((core_mask(img, spec, hsv) > 0) | (edge_mask(img, spec, hsv, s_min,
                                                         gray_lo, gray_hi) > 0))
        total = m if total is None else (total | m)
    return total.astype(np.uint8)


def de_annotate(img, mask, fill=255):
    out = img.copy()
    out[mask > 0] = fill
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True, help="原理图渲染图 (600dpi)")
    ap.add_argument("--out", required=True, help="输出去标注底图")
    ap.add_argument("--color", default="all",
                    choices=["green", "red", "cyan", "yellow", "all"],
                    help="去除哪种标注 (all=全部)")
    ap.add_argument("--s-min", type=int, default=30,
                    help="描边扩展饱和度下限 (灰像素色相噪声; 实测30)")
    ap.add_argument("--gray-lo", type=int, default=40, help="排除纯黑走线下限")
    ap.add_argument("--gray-hi", type=int, default=200, help="排除亮背景上限")
    ap.add_argument("--fill", type=int, default=255, help="填充色 (255=白)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    mask = annotation_mask(img, args.color, args.s_min, args.gray_lo, args.gray_hi)
    out = de_annotate(img, mask, args.fill)
    cv2.imwrite(args.out, out)

    b, g, r = cv2.split(out.astype(int))
    md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    resid = int((md > 40).sum())
    print(f"[de-annotate:chmask] removed {int(mask.sum())} px, "
          f"colored_resid={resid}, saved {args.out}")


if __name__ == "__main__":
    main()