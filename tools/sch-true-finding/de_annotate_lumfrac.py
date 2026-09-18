#!/usr/bin/env python3
"""tools/sch-true-finding/de_annotate_lumfrac.py — 信号流标注去除 (段内暗芯法, 固化版)

purpose: 从原理图中去除信号流标注线 (绿=RX/红=TX/黄=控制/青=common).
        **用户裁定 (2026-09-17): 段内暗芯法 (lumfrac) 为最终解法** ——
        不断线、不变细. chandiff 会断线/变细 (把绿标注下的走线一起删);
        段内暗芯法保留每个彩色段内"相对最暗的 25%" (即被标注覆盖的走线),
        染回走线色 → 走线连续且全宽, 彩色残留=0.
        **方法简称 = lumfrac (segment luminance frac)** → 命名 de_annotate_lumfrac.
format: Python 3 + OpenCV
version: 1.0 (2026-09-17)

算法:
  1. 彩色掩膜 (BGR 通道差 > --diff-th) = 标注候选
  2. 每个彩色段 (连通域): 段内亮度阈值 = 分位数(--frac) → 保留亮度最低的芯
  3. 保留芯染回走线色 (median 走线灰); 其余标注置白
  4. 按段内相对暗度, 不用全局亮度 (全局会把整条绿带当走线)

用法:
  python3 de_annotate_lumfrac.py --img sch.png --out deannot.png
    [--diff-th 40] [--frac 0.25] [--fill 255]

消费方: sch_wirenet (走线 net 识别前去除标注干扰), 原理图纯净底图.
"""

import argparse
import sys

import cv2
import numpy as np


def annotation_mask(img, diff_th=40):
    """BGR 通道差掩膜: maxdiff > diff_th = 标注 (彩色). 返回 0/255."""
    b, g, r = cv2.split(img.astype(int))
    maxdiff = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    return (maxdiff > diff_th).astype(np.uint8)


def wire_color(img, diff_th=40, dark_th=150):
    """估计走线色 (非彩色暗像素中位)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b, g, r = cv2.split(img.astype(int))
    md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    surv = (gray < dark_th) & (md <= diff_th)
    px = img[surv]
    if len(px):
        return np.median(px, axis=0).astype(np.uint8)
    return np.array([30, 30, 30], np.uint8)


def core_mask(gray, annot, frac=0.25):
    """段内暗芯: 每个标注段保留亮度最低 frac 的像素."""
    keep = np.zeros_like(annot, bool)
    n, u_lab, u_stats, _ = cv2.connectedComponentsWithStats(annot, 8)
    H, W = annot.shape
    m = 5
    for uc in range(1, n):
        x0, y0, w0, h0 = u_stats[uc, 0], u_stats[uc, 1], u_stats[uc, 2], u_stats[uc, 3]
        xa, xb = max(0, x0 - m), min(W, x0 + w0 + m)
        ya, yb = max(0, y0 - m), min(H, y0 + h0 + m)
        seg = u_lab[ya:yb, xa:xb] == uc
        if seg.sum() == 0:
            continue
        gv = gray[ya:yb, xa:xb]
        th = np.percentile(gv[seg], frac * 100)
        keep[ya:yb, xa:xb] |= seg & (gv < th)
    return keep


def de_annotate(img, annot, keep, wcolor, fill=255):
    """输出: 保留芯染走线色, 其余标注置白."""
    out = img.copy()
    out[annot > 0] = fill
    out[keep] = wcolor
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True, help="原理图渲染图 (600dpi)")
    ap.add_argument("--out", required=True, help="输出去标注底图")
    ap.add_argument("--diff-th", type=int, default=40,
                    help="BGR 通道差阈值 (标注=彩色; 实测40)")
    ap.add_argument("--frac", type=float, default=0.25,
                    help="每段保留亮度最低比例 (暗芯=走线; 实测0.25平衡)")
    ap.add_argument("--fill", type=int, default=255, help="填充色 (255=白)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    annot = annotation_mask(img, args.diff_th)
    keep = core_mask(gray, annot, args.frac)
    out = de_annotate(img, annot, keep, wire_color(img, args.diff_th), args.fill)
    cv2.imwrite(args.out, out)

    # 校验 (自监督): 彩色残留 / 线宽
    b, g, r = cv2.split(out.astype(int))
    md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    resid = int((md > args.diff_th).sum())
    print(f"[de-annotate:lumfrac] kept_core={int(keep.sum())} px, "
          f"colored_resid={resid}, saved {args.out}")


if __name__ == "__main__":
    main()