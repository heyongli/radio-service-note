#!/usr/bin/env python3
"""tools/sch-true-finding/de_annotate_chandiff.py — 信号流标注去除 (chandiff 固化版)

purpose: 从原理图中去除信号流标注线 (绿=RX/红=TX/黄=控制/青=common), 得
        "标注从未存在"的纯净底图. **用户裁定本模式为最终答案** (2026-09-17):
        BGR 通道差 (chandiff) 去除彩色, 彩色残留=0, 线宽保留 (p90=2.0).
        走线断开是可接受代价 (标注本来就该断连). 不要试图"恢复被覆盖的走线"
        (桥恢复/线续接均已证伪, 见 parameter_space.md round F).
        **方法简称 = chandiff** → 命名 de_annotate_chandiff.
format: Python 3 + OpenCV
version: 1.0 (2026-09-17)

算法:
  - 走线=灰 (BGR 三通道接近, 通道差小); 标注=彩色 (通道差大)
  - maxdiff = max(|G-R|,|G-B|,|R-B|), 阈值 --diff-th (实测 40)
  - 通道差 > 阈值 = 标注 -> 置白 (fill=255)
  - 比 HSV 饱和/色相可靠: 暗走线 HSV 噪声大, BGR 通道差稳定

用法:
  python3 de_annotate_chandiff.py --img sch.png --out sch_no_annot.png
    [--diff-th 40] [--fill 255]

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


def de_annotate(img, mask, fill=255):
    """去除标注: 掩膜像素用 fill 填充 (默认置白)."""
    out = img.copy()
    out[mask > 0] = fill
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True, help="原理图渲染图 (600dpi)")
    ap.add_argument("--out", required=True, help="输出去标注底图")
    ap.add_argument("--diff-th", type=int, default=40,
                    help="BGR 通道差阈值 (>此值=彩色标注; 走线灰→通道差≈0, 实测40)")
    ap.add_argument("--fill", type=int, default=255, help="填充色 (255=白)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")

    mask = annotation_mask(img, args.diff_th)
    out = de_annotate(img, mask, args.fill)
    cv2.imwrite(args.out, out)

    # 校验: 输出不应有彩色残留 (自监督指标 readme §7)
    b, g, r = cv2.split(out.astype(int))
    md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    resid = int((md > args.diff_th).sum())
    print(f"[de-annotate:chandiff] removed {int(mask.sum())} px, "
          f"colored_resid={resid}, saved {args.out}")


if __name__ == "__main__":
    main()