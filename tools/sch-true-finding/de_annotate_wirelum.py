#!/usr/bin/env python3
"""tools/sch-true-finding/de_annotate_wirelum.py — 信号流标注去除 (亮度保走线法)

purpose: 从原理图中去除信号流标注线, **按亮度保走线** (用户洞察: 绿标注与
        走线色调融合, 按亮度更暗判走线). 处理三色: 绿=RX / 青=common /
        土黄=TX. **方法简称 = wirelum (wire luminance)**.
format: Python 3 + OpenCV
version: 1.0 (2026-09-18)

算法:
  1. 每色掩膜: 色相带 + 通道关系 (实测校准, 见 COLOR_SPEC)
  2. 亮度保走线: 标注内 亮度<--wire-lum 的暗像素 = 走线 (保留, 染回走线色
     或 --keep-color 保留原色); 亮度>=阈值的亮像素 = 标注 (置白)
  3. 其余置白

实测 (IC-2200H rxtx 600dpi 色相带):
  green RX    h45-90  223k px  BGR(82,158,13)
  cyan common h90-120  8.8k px BGR(220,163,16)
  土黄 TX     h0-25   58.5k px BGR(34,135,232) (橙红/琥珀)
  品红 (可选) h150-180 164k px BGR(128,52,181)

用法:
  python3 de_annotate_wirelum.py --img sch.png --out deannot.png
    [--wire-lum 120] [--keep-color]

消费方: sch_wirenet (去标注后 net 网表), 原理图纯净底图.
"""

import argparse
import sys

import cv2
import numpy as np

# 三色标注 (色相带 + 通道关系, 2026-09-18 实测)
COLOR_SPEC = {
    "green": {"h": (45, 90), "ops": [("g", ">", 120), ("r", "<", 110), ("b", "<", 110)]},
    "cyan":  {"h": (90, 120), "ops": [("b", ">", 150), ("g", ">", 120), ("r", "<", 60)]},
    "tuHuang": {"h": (0, 25), "ops": [("r", ">", 180), ("g", ">", 40), ("b", "<", 80)]},
    "magenta": {"h": (150, 180), "ops": [("r", ">", 150), ("b", ">", 60), ("g", "<", 110)]},
}


def color_mask(img, spec):
    """色相带 + 通道关系掩膜."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0]
    b, g, r = cv2.split(img.astype(int))
    cond = (h >= spec["h"][0]) & (h <= spec["h"][1])
    for ch, op, thr in spec["ops"]:
        v = {"g": g, "r": r, "b": b}[ch]
        cond &= (v > thr) if op == ">" else (v < thr)
    return cond.astype(np.uint8)


def annotation_mask(img, colors=("green", "cyan", "tuHuang", "magenta")):
    total = None
    for c in colors:
        m = color_mask(img, COLOR_SPEC[c])
        total = m if total is None else (total | m)
    return total.astype(np.uint8)


def wire_fill_color(img, dark_th=150):
    """估计走线色 (非彩色暗像素中位)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b, g, r = cv2.split(img.astype(int))
    md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    surv = (gray < dark_th) & (md <= 40)
    px = img[surv]
    if len(px):
        return np.median(px, axis=0).astype(np.uint8)
    return np.array([30, 30, 30], np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True, help="原理图渲染图")
    ap.add_argument("--out", required=True, help="输出去标注底图")
    ap.add_argument("--wire-lum", type=int, default=120,
                    help="亮度阈值: 标注内 亮度<此值=走线(保留), >=此值=标注(置白); "
                         "==0 时每色自适应 (按该色亮度中位, 四色都显示)")
    ap.add_argument("--keep-color", action="store_true",
                    help="保留的暗芯用原彩色, 不染走线灰")
    ap.add_argument("--colors", default="green,cyan,tuHuang,magenta",
                    help="处理哪些色 (逗号分隔; 可选 green/cyan/tuHuang/magenta)")
    ap.add_argument("--fill", type=int, default=255, help="填充色 (255=白)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    colors = tuple(c.strip() for c in args.colors.split(",") if c.strip())
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    annot = annotation_mask(img, colors)
    if args.wire_lum > 0:
        keep = (annot > 0) & (gray < args.wire_lum)
    else:
        # 每色自适应: 按该色亮度中位 (保留暗芯), 四色都显示
        keep = np.zeros_like(annot, bool)
        for c in colors:
            m = color_mask(img, COLOR_SPEC[c]) > 0
            if m.sum() == 0:
                continue
            th = np.median(gray[m])
            keep |= m & (gray < th)
    remask = (annot > 0) & (~keep)

    out = img.copy()
    out[remask > 0] = args.fill
    if args.keep_color:
        out[keep] = img[keep]
    else:
        out[keep] = wire_fill_color(img)
    cv2.imwrite(args.out, out)

    b, g, r = cv2.split(out.astype(int))
    md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    resid = int((md > 40).sum())
    print(f"[de-annotate:wirelum] colors={args.colors} wire_lum={args.wire_lum} "
          f"keep={int(keep.sum())} px, colored_resid={resid}, saved {args.out}")


if __name__ == "__main__":
    main()