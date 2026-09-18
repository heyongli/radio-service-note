#!/usr/bin/env python3
"""tools/sch-true-finding/annotation_detect.py — 标注区域识别 (annotation detect)

purpose: 从原理图中识别**信号流标注区域** (绿=RX/红=TX/黄=控制/青=common 的
        彩色线条区域), 供 de-annotation 的 ROI 局部化使用 (用户设计: 先识别标记
        区域, 再在其 bbox×scale 范围内应用去标注算法, 避免全局参数顾此失彼).
format: Python 3 + OpenCV
version: 0.1 (2026-09-17)

算法:
  1. 彩色掩膜 = BGR 通道差 > --diff-th (标注=彩色, 走线=灰)
  2. (可选) --light-th 补捉浅色带边缘
  3. 连通域 → 标注区域 (滤 --min-area 噪声)
  4. 每区域 bbox 输出 + 区域掩膜 (可选 --dilate 膨胀合并)

用法:
  python3 annotation_detect.py --img sch.png \
    --out-mask annot_regions.png --out-json annot_regions.json
    [--diff-th 40] [--light-th 0] [--min-area 20] [--dilate 0]

输出:
  - out-mask: 标注区域掩膜 PNG (0/255)
  - out-json: {regions:[{id,bbox:[x,y,w,h],area,color?}], count}
"""

import argparse
import json
import sys

import cv2
import numpy as np


def annotation_mask(img, diff_th=40, light_th=0):
    """标注彩色掩膜. light_th>0 时并上浅色 (带边缘)."""
    b, g, r = cv2.split(img.astype(int))
    md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    m = md > diff_th
    if light_th > 0:
        m = m | (md > light_th)
    return m.astype(np.uint8)


def detect_regions(img, diff_th=40, light_th=0, min_area=20, dilate=0):
    """标注区域: 彩色连通域 → bbox 列表 + 区域掩膜. 每条含 主色 (BGR中位)."""
    m = annotation_mask(img, diff_th, light_th)
    if dilate > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate, dilate))
        m = cv2.dilate(m, k)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    regions = []
    for i in range(1, n):
        area = int(stats[i, 4])
        if area < min_area:
            continue
        px = img[lab == i]
        color = np.median(px, axis=0).astype(int).tolist() if len(px) else None
        regions.append({"id": i, "bbox": [int(stats[i, 0]), int(stats[i, 1]),
                                          int(stats[i, 2]), int(stats[i, 3])],
                        "area": area, "color_bgr": color})
    return regions, m, lab, stats


def fill_stroke(img, mask, min_thick=4, aspect_min=2.0, pad=0):
    """统一线宽描边填充 (用户域知识: RX/TX 标注粗细一致, 分支同宽).

    只处理**细长+粗**区域 (aspect>=aspect_min 且 min(w,h)>=min_thick):
    排除元器件 (compact) 与细线. 每区域: 骨架膨胀到该区域统一线宽, 填纯色.
    """
    from scipy import ndimage as ndi
    from sch_wirenet import _thin
    out = img.copy()
    H, W = mask.shape
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for i in range(1, n):
        x, y, w, h = int(stats[i, 0]), int(stats[i, 1]), int(stats[i, 2]), int(stats[i, 3])
        if min(w, h) < min_thick:
            continue
        if max(w, h) / max(min(w, h), 1) < aspect_min:
            continue
        seg = lab == i
        px = img[seg]
        color = np.median(px, axis=0).astype(np.uint8)
        m = 8
        xa, xb = max(0, x - m), min(W, x + w + m)
        ya, yb = max(0, y - m), min(H, y + h + m)
        seg_w = seg[ya:yb, xa:xb]
        dt = ndi.distance_transform_edt(seg_w.astype(np.uint8))
        thick = float(np.median(dt[seg_w > 0])) if seg_w.any() else min_thick / 2
        width = max(int(2 * thick + 1), min_thick)
        sk = _thin(seg_w.astype(np.uint8) * 255) > 0
        stroke = ndi.maximum_filter(sk, size=width) & seg_w
        out[ya + np.nonzero(stroke)[0], xa + np.nonzero(stroke)[1]] = color
    return out


def fill_segmented_rects(img, mask, cell=30, min_thick=4, pad=1):
    """沿标注线分段, 每小段取紧致矩形填主色 (用户设计: 识别粗 annot ->
    围边的分段矩形 -> 填充; 不填整条大 bbox, 避免覆盖大片图片).

    网格 cell×cell, 每格内若有标注 (且厚度 >= min_thick, 跳过细线),
    取该格内标注的紧致 bbox (pad 外扩), 填该格标注主色.
    """
    out = img.copy()
    H, W = mask.shape
    for gy in range(0, H, cell):
        for gx in range(0, W, cell):
            sub = mask[gy:gy + cell, gx:gx + cell]
            if not sub.any():
                continue
            ys, xs = np.nonzero(sub)
            h = ys.max() - ys.min() + 1
            w = xs.max() - xs.min() + 1
            if min(w, h) < min_thick:      # 细线不做
                continue
            px = img[gy:gy + cell, gx:gx + cell][sub > 0]
            color = np.median(px, axis=0).astype(np.uint8)
            y0, y1 = max(0, gy + ys.min() - pad), min(H, gy + ys.max() + 1 + pad)
            x0, x1 = max(0, gx + xs.min() - pad), min(W, gx + xs.max() + 1 + pad)
            out[y0:y1, x0:x1] = color
    return out


def fill_pure_color(img, regions, lab, stats, fill_rect=True, expand=0.0):
    """每标注区域染成其主色 (区域像素中位 BGR).

    fill_rect=True: 填整个外接矩形 (bbox 内整体填纯色, 把里面包围的杂色/走线
      一起盖掉, 得干净矩形区域). expand: bbox 额外放大比例 (如 0.1).
    """
    out = img.copy()
    H, W = out.shape[:2]
    for reg in regions:
        i = reg["id"]
        x, y, w, h = reg["bbox"]
        px = img[lab == i]
        if len(px) == 0:
            continue
        color = np.median(px, axis=0).astype(np.uint8)
        if fill_rect:
            ex, ey = int(w * expand), int(h * expand)
            xa, xb = max(0, x - ex), min(W, x + w + ex)
            ya, yb = max(0, y - ey), min(H, y + h + ey)
            out[ya:yb, xa:xb] = color
        else:
            out[lab == i] = color
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--out-mask", required=True, help="标注区域掩膜 PNG")
    ap.add_argument("--out-json", default=None, help="区域列表 JSON")
    ap.add_argument("--out-color", default=None,
                    help="区域染纯色图 PNG (每区域填主色; --no-rect 只填区域像素, 默认填外接矩形)")
    ap.add_argument("--fill-segment", action="store_true",
                    help="沿标注线分段填矩形 (识别粗annot->围边分段矩形->填充; 推荐)")
    ap.add_argument("--cell", type=int, default=30, help="分段网格尺寸 (px)")
    ap.add_argument("--min-thick", type=int, default=4, help="细线过滤: 段厚度<此值不填")
    ap.add_argument("--no-rect", action="store_true", help="只填区域像素, 不填外接矩形")
    ap.add_argument("--expand", type=float, default=0.0, help="矩形额外放大比例 (如0.1)")
    ap.add_argument("--diff-th", type=int, default=40, help="彩色阈值 (标注)")
    ap.add_argument("--light-th", type=int, default=0, help="浅色边缘补捉 (>0 开启)")
    ap.add_argument("--min-area", type=int, default=20, help="最小区域面积 (滤噪声)")
    ap.add_argument("--dilate", type=int, default=0, help="区域膨胀核 (合并邻近)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    regions, m, lab, stats = detect_regions(img, args.diff_th, args.light_th,
                                            args.min_area, args.dilate)
    cv2.imwrite(args.out_mask, m * 255)
    data = {"_meta": {"purpose": "annotation region detect", "format": "json",
                      "version": "0.1", "source": args.img, "params": vars(args)},
            "count": len(regions), "regions": regions}
    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
    if args.out_color:
        if args.fill_segment:
            cv2.imwrite(args.out_color, fill_segmented_rects(img, m, args.cell,
                                                             args.min_thick))
            print(f"[annotation_detect] segmented-rect fill saved {args.out_color}")
        else:
            cv2.imwrite(args.out_color, fill_pure_color(img, regions, lab, stats,
                                                        not args.no_rect, args.expand))
            print(f"[annotation_detect] pure-color {'rect' if not args.no_rect else 'region'} "
                  f"saved {args.out_color}")
    print(f"[annotation_detect] regions={len(regions)} "
          f"mask_px={int(m.sum())} -> {args.out_mask}")


if __name__ == "__main__":
    main()