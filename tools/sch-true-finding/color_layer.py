#!/usr/bin/env python3
"""tools/sch-true-finding/color_layer.py — 信号颜色图层 (rx/tx color layer)

purpose: 用**图例准确色** (explanatory_notes.json) 输出**颜色图层**: 白底 +
        非目标内容调淡 (褪色) + 指定信号色高亮. 重要视觉结果: 一眼看出该
        信号的标注位置. 通用工具 (信号可组合, 如 RX+COMMON).
        **Stage-2 (--pure)**: 图层去灰 (饱和度阈值) → **纯区域图** (白底+
        纯目标色, 无灰色干扰).
format: Python 3 + OpenCV
version: 0.3 (2026-09-18)

用法:
  stage1 (图层): python3 color_layer.py --img sch-600.png \
    --legend explanatory_notes.json --signals RX --out rx_color_layer.png
  stage2 (纯区域图): ... --pure --sat-min 100 --out rx_line_region.png
  [--tol 60] [--fade 0.45] [--dark 150]
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


def legend_line_width(img, legend_json, tol=40):
    """从 legend 说明框量**参考线宽** (色样本条带厚度, 600dpi).

    说明框 (explanatory_notes.json _meta.box) 内有各信号色样本短条, 其厚度
    = 真实标注线宽. 取各色样本条带厚度的中位作参考.
    """
    with open(legend_json) as f:
        d = json.load(f)
    box = d.get("_meta", {}).get("box")
    if not box:
        return 0.0
    x, y, w, h = map(int, box)
    sub = img[max(0, y):y + h, max(0, x):x + w]
    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    thick = []
    for e in d.get("entries", []):
        if not e.get("color_bgr"):
            continue
        m = rgb_mask(sub, e["color_bgr"], tol) > 0
        if m.sum() == 0:
            continue
        # 色样本条带厚度 = 掩膜行方向的连续厚度 (多数行的厚度)
        rowsum = m.sum(1)
        runs = rowsum > 0
        if not runs.any():
            continue
        # 每列连续厚度
        colsum = m.sum(0)
        rr = colsum[colsum > 0]
        if len(rr):
            thick.append(float(np.median(rr)))
    return float(np.median(thick)) if thick else 0.0


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
    ap.add_argument("--pure", action="store_true",
                    help="Stage-2: 图层去灰 (饱和度阈值) → 纯区域图 (白底+纯目标色)")
    ap.add_argument("--sat-min", type=int, default=100,
                    help="Stage-2 饱和度阈值 (灰度像素低饱和, 剔除; 目标信号高饱和保留)")
    ap.add_argument("--heal", action="store_true",
                    help="Stage-3: 线身填实 + 外1px边框")
    ap.add_argument("--continu", action="store_true",
                    help="Stage-3 先方向闭接续 (填同向间隙) 再填实; 默认不接续")
    ap.add_argument("--heal-k", type=int, default=0,
                    help="Stage-3 合并核. 0=自动用 legend 参考线宽 (色样本条带厚度)")
    ap.add_argument("--border", action="store_true",
                    help="Stage-3 额外加 1px 黑边框 (默认纯填实)")
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
    if args.pure:
        # Stage-2: 去灰 (饱和度阈值) → 纯区域图 (白底+纯目标色)
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1] > args.sat_min
        pure = np.full_like(img, 255)
        pure[sat] = out[sat]
        out = pure
    if args.heal:
        # Stage-3 (用户定稿): 线身**填实** (直接 legend 准确色掩膜) + 外 1px 边框.
        #   可选方向闭接续 (--continu); 宽度约束不增宽.
        from scipy import ndimage as ndi
        ksize = args.heal_k if args.heal_k > 0 else int(legend_line_width(img, args.legend))
        if ksize <= 0:
            ksize = 13
        print(f"[stage3-heal] 参考线宽={ksize}px (直接色掩膜填实+1px框)")
        merged = np.zeros(img.shape[:2], bool)
        for label, bgr in targets.items():
            merged |= rgb_mask(img, bgr, args.tol) > 0
        if args.continu:
            kh = cv2.getStructuringElement(cv2.MORPH_RECT, (ksize, 1))
            kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, ksize))
            merged = cv2.morphologyEx(merged.astype(np.uint8), cv2.MORPH_CLOSE, kh)
            merged |= cv2.morphologyEx(merged.astype(np.uint8), cv2.MORPH_CLOSE, kv)
            merged = merged > 0
            dtm = ndi.distance_transform_edt(merged)
            merged[dtm > ksize / 2] = False
        # 填实 (用户定稿: rx_outline_band_3over2 样式 = 纯填实) + 可选 1px 边框
        healed = np.full_like(img, 255)
        fill_color = targets[list(targets)[0]] if targets else (0, 160, 0)
        healed[merged > 0] = fill_color
        if args.border:
            n, lab, st, _ = cv2.connectedComponentsWithStats((merged > 0).astype(np.uint8), 8)
            for i in range(1, n):
                if st[i, 4] < 20:
                    continue
                cs, _ = cv2.findContours((lab == i).astype(np.uint8) * 255,
                                         cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                cv2.drawContours(healed, cs, -1, (0, 0, 0), 1)
        out = healed
    cv2.imwrite(args.out, out)
    print(f"[color_layer] signals={args.signals} targets={list(targets)} "
          f"-> {args.out}")


if __name__ == "__main__":
    main()