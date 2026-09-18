#!/usr/bin/env python3
"""tools/sch-true-finding/legend_region_detect.py — 用 legend 准确色识别标注区域

purpose: 用**图例数据库的准确 RGB** (explanatory_notes.json) 识别原理图上所有
        被标注的区域 (RX/TX/common/POWER): 每色掩膜 (RGB 容差) → 连通域 →
        红色细线边框圈出. 目的: 准确识别 legend 标注的所有区域.
format: Python 3 + OpenCV
version: 0.1 (2026-09-18)

用法:
  python3 legend_region_detect.py --img sch-600.png \
    --legend explanatory_notes.json --out regions_bordered.png
    [--tol 60] [--min-area 100] [--expand 3]
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
    """RGB 容差掩膜: |channel - sample| <= tol 全部通道满足."""
    b, g, r = cv2.split(img.astype(int))
    sb, sg, sr = sample_bgr
    m = (np.abs(b - sb) <= tol) & (np.abs(g - sg) <= tol) & (np.abs(r - sr) <= tol)
    return m.astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--legend", required=True, help="explanatory_notes.json")
    ap.add_argument("--out", required=True, help="输出: 红色边框圈注区域图")
    ap.add_argument("--tol", type=int, default=60, help="RGB 容差 (每通道)")
    ap.add_argument("--min-area", type=int, default=100, help="最小区域面积")
    ap.add_argument("--expand", type=int, default=3, help="边框外扩 px")
    ap.add_argument("--fill", action="store_true", help="区域填充其颜色 (wirelum 全局120 式着色)")
    ap.add_argument("--fill-gray", action="store_true",
                    help="区域叠加半透明灰 (原图可见, 便于目测)")
    ap.add_argument("--alpha", type=float, default=0.5, help="透明灰透明度 (0-1)")
    ap.add_argument("--labels", default=None,
                    help="只处理哪些 label (逗号分隔, 如 RX,TX,COMMON; 默认全部)")
    ap.add_argument("--thick-ratio", type=float, default=2.5,
                    help="粗细过滤: 区域窄边 > 线宽×此值 = 宽于线宽, 剔除 (用户: "
                         "标注线粗细一致)")
    ap.add_argument("--line-width", type=float, default=0.0,
                    help="强制线宽 (px). >0 时覆盖学习值 (不同机型/渲染可强制)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    colors = legend_colors(args.legend)
    if not colors:
        sys.exit("legend 无色彩样本")
    if args.labels:
        want = [l.strip().upper() for l in args.labels.split(",")]
        colors = {k: v for k, v in colors.items() if any(w in k for w in want)}

    # 先收集全部区域, 再按线宽过滤 (bbox 窄边 vs 线宽; 线宽学习剔除突然最大值)
    collected = {}   # label -> [(bgr, rects[])]
    for label, bgr in colors.items():
        m = rgb_mask(img, bgr, args.tol)
        if m.sum() == 0:
            print(f"  {label} {bgr}: 无匹配")
            continue
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        rects = []
        for i in range(1, n):
            if stats[i, 4] < args.min_area:
                continue
            x, y, w, h = map(int, (stats[i, 0], stats[i, 1], stats[i, 2], stats[i, 3]))
            x0, y0 = max(0, x - args.expand), max(0, y - args.expand)
            x1, y1 = min(img.shape[1], x + w + args.expand), min(img.shape[0], y + h + args.expand)
            rects.append([x0, y0, x1 - x0, y1 - y0])
        collected[label] = (bgr, rects)

    # 线宽: 学习 (稳健: 剔除"突然最大值"胖体后取中位) 或 --line-width 强制覆盖
    all_min = np.array([min(r[2], r[3]) for b, rs in collected.values() for r in rs])
    if args.line_width > 0:
        thickness = args.line_width
        mode = f"强制 {args.line_width}px"
    else:
        arr = all_min[all_min > 0]
        med = float(np.median(arr)) if len(arr) else 0.0
        clean = arr[arr <= 1.5 * med] if len(arr) else arr   # 剔除突然最大值(胖体)
        thickness = float(np.median(clean)) if len(clean) else med
        mode = f"学习 {thickness:.0f}px (bbox窄边, 剔除突然最大值)"
    cap = thickness * args.thick_ratio
    print(f"线宽={mode}, 剔除 bbox窄边>{cap:.0f}px 的区域")

    vis = img.copy()
    gray_layer = np.full_like(img, 128)
    report = {}
    for label, (bgr, rects) in collected.items():
        valid = [r for r in rects if min(r[2], r[3]) <= cap]
        n_rej = len(rects) - len(valid)
        for r in valid:
            x0, y0, w, h = r
            cv2.rectangle(vis, (x0, y0), (x0 + w, y0 + h), (0, 0, 255), 1)
            if args.fill:
                vis[y0:y0 + h, x0:x0 + w] = bgr
            if args.fill_gray:
                vis[y0:y0 + h, x0:x0 + w] = (vis[y0:y0 + h, x0:x0 + w].astype(float) * (1 - args.alpha)
                                             + gray_layer[y0:y0 + h, x0:x0 + w] * args.alpha).astype(np.uint8)
        report[label] = {"sample_bgr": bgr,
                         "regions": len(valid), "rejected_thick": n_rej}
        print(f"  {label}: 区域{len(valid)} 剔除{int(n_rej)} (宽于线宽)")

    cv2.imwrite(args.out, vis)
    data = {"_meta": {"purpose": "legend region detect (accurate RGB)",
                      "format": "json", "version": "0.1",
                      "source": args.img, "legend": args.legend,
                      "params": vars(args)},
            "colors": report}
    with open(args.out.replace(".png", ".json"), "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()