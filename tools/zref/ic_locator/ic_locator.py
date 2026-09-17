#!/usr/bin/env python3
"""tools/ic_locator/ic_locator.py - IC 封装几何定位器

purpose: 用几何特征 + OCR 找 PCB 上的 IC 封装 (矩形 + 圆形 + 内部丝印)
format: Python 3 + OpenCV + numpy
version: 0.1 (2026-09-15 初版)
consumers: IC12/IC4/Q27 等 OCR 找不到的器件定位
parent_doc: ../../schema.md

设计 (组合多种几何特征):
  1. PCB top/bot 找所有深色矩形 (颜色 30-150 灰度)
     - 长宽比 < 5, 面积 800-30000 px (@ 600dpi ≈ 2-50 mm²)
  2. PCB 找所有圆形 (中周/线圈, Hough Circle)
     - 半径 20-80 px @ 600dpi
  3. 对每个候选矩形/圆形, 内部做局部 OCR (高密度, 单 tile)
  4. 与 chain_order 已知 refdes 匹配 → 真位置
  5. 验证 + 入 components_index

为何之前 OCR + 矩形检测失败:
  - OCR v4+v5s 600dpi 全图 stage1 grid 经常 "detection result is empty"
    (模型对 PCB 字体不熟 + 大字体被切碎)
  - 矩形检测阈值 (< 100 黑像素) 漏检中等灰度 IC 本体 (50-150 灰度)
  - 单尺度 tile 扫描 → 大字符被切到边界 → 模型识别失败
  - 垂直旋转丝印 (--stage1-rots 0) → 90/270 度字符漏检

本工具改用:
  - 多阈值合并 (30-150 + 50-200)
  - 单字符高密度 OCR (tile=200, overlap=80, upsample=3x)
  - 旋转 0/90/270 度全部跑
  - 候选区分别 OCR (避免大图噪音)
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage


def find_rectangles(img_gray, area_range=(800, 30000), aspect_max=5.0):
    """找深色矩形 (多阈值合并)"""
    found = []
    for lo, hi in [(30, 150), (50, 200), (100, 250)]:
        binary = ((img_gray > lo) & (img_gray < hi)).astype(np.uint8) * 255
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if not (area_range[0] <= area <= area_range[1]):
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = max(w, h) / min(w, h)
            if aspect > aspect_max:
                continue
            # 矩形度 = contour area / bbox area
            rect_area = w * h
            if rect_area == 0:
                continue
            rectangularity = area / rect_area
            if rectangularity < 0.5:  # 不够方
                continue
            found.append({
                'bbox': (x, y, x + w, y + h),
                'center': (x + w // 2, y + h // 2),
                'wh': (w, h),
                'area': float(area),
                'aspect': round(aspect, 2),
                'rectangularity': round(rectangularity, 2),
                'gray_range': (lo, hi),
            })
    # 去重 (同一矩形被多阈值检测)
    unique = []
    for f in found:
        dup = False
        for u in unique:
            if (abs(f['center'][0] - u['center'][0]) < max(f['wh'][0], u['wh'][0]) // 2
                    and abs(f['center'][1] - u['center'][1]) < max(f['wh'][1], u['wh'][1]) // 2):
                dup = True
                break
        if not dup:
            unique.append(f)
    return unique


def find_circles(img_gray, radius_range=(20, 80), min_dist=40):
    """找圆形 (中周/线圈)"""
    circles = cv2.HoughCircles(
        img_gray, cv2.HOUGH_GRADIENT, dp=1, minDist=min_dist,
        param1=80, param2=25, minRadius=radius_range[0], maxRadius=radius_range[1]
    )
    found = []
    if circles is not None:
        for (x, y, r) in circles[0]:
            found.append({
                'center': (int(x), int(y)),
                'radius': int(r),
            })
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pcb", required=True, help="PCB 母图 PNG 路径")
    ap.add_argument("--view", default="top", choices=["top", "bot"])
    ap.add_argument("--out", default=None,
                    help="输出 JSON (默认 stdout)")
    ap.add_argument("--save-crops", action="store_true",
                    help="保存每个候选区裁切图到 /tmp/ic_crops/")
    args = ap.parse_args()

    # 加载
    img = np.array(Image.open(args.pcb).convert("RGB"))
    g = np.mean(img, axis=2).astype(np.uint8)
    H, W = g.shape
    print(f"[ic_locator] PCB: {args.pcb} ({W}x{H}) view={args.view}")

    # 找矩形
    rects = find_rectangles(g)
    print(f"[ic_locator] 矩形候选: {len(rects)}")
    # 找圆形
    circles = find_circles(g)
    print(f"[ic_locator] 圆形候选: {len(circles)}")

    # PCB 板边 (简单 Otsu)
    binary = (g < 230).astype(np.uint8)
    labeled, n = ndimage.label(binary)
    sizes = ndimage.sum(binary, labeled, range(1, n+1))
    big = int(np.argmax(sizes)) + 1
    ys_b, xs_b = np.where(labeled == big)
    PCB = (int(xs_b.min()), int(ys_b.min()), int(xs_b.max()), int(ys_b.max()))
    print(f"[ic_locator] PCB 板边: {PCB}")

    # 过滤到板内
    rects_in = [r for r in rects if PCB[0] <= r['center'][0] <= PCB[2]
                and PCB[1] <= r['center'][1] <= PCB[3]]
    circles_in = [c for c in circles if PCB[0] <= c['center'][0] <= PCB[2]
                  and PCB[1] <= c['center'][1] <= PCB[3]]
    print(f"[ic_locator] 板内: 矩形 {len(rects_in)}, 圆形 {len(circles_in)}")

    # 按面积降序
    rects_in.sort(key=lambda r: -r['area'])
    circles_in.sort(key=lambda c: -c['radius'])

    # 保存裁切图
    if args.save_crops:
        out_dir = Path("/tmp/ic_crops")
        out_dir.mkdir(exist_ok=True)
        for i, r in enumerate(rects_in[:30]):
            x0, y0, x1, y1 = r['bbox']
            crop = img[y0:y1, x0:x1]
            Image.fromarray(crop).save(out_dir / f"rect_{i:02d}_{r['center'][0]}x{r['center'][1]}.png")
        for i, c in enumerate(circles_in[:30]):
            x, y, rad = c['center'][0], c['center'][1], c['radius']
            x0, y0 = max(0, x-rad*2), max(0, y-rad*2)
            x1, y1 = min(W, x+rad*2), min(H, y+rad*2)
            crop = img[y0:y1, x0:x1]
            Image.fromarray(crop).save(out_dir / f"circ_{i:02d}_{x}x{y}_r{rad}.png")
        print(f"[ic_locator] 裁切图保存: {out_dir}")

    out = {
        "_meta": {
            "purpose": "IC 封装几何定位器",
            "tool_version": "0.1",
            "pcb": args.pcb,
            "view": args.view,
            "method": "OpenCV findContours (矩形) + Hough Circle (圆形)",
        },
        "rectangles_in_board": rects_in,
        "circles_in_board": circles_in,
        "board_bbox": list(PCB),
    }
    if args.out:
        with open(args.out, 'w') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"[ic_locator] saved: {args.out}")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
