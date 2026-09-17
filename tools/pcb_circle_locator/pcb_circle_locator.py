#!/usr/bin/env python3
"""tools/pcb_circle_locator/circle_locator.py - PCB 全板圆形裁切定位器

purpose: 在 PCB 600dpi 母图上检测所有圆形轮廓 (电感/晶振/电解电容/测试点等),
         裁切保存 + 写 schema 合规 circle_crops_index.json
format: Python 3 + OpenCV + numpy
version: 0.1 (2026-09-15, 初版)
consumers: OCR 验证、组件发现、圆形元件定位
parent_doc: ../../schema.md

设计:
  1. PCB 600dpi top/bot 母图
  2. OpenCV HoughCircles + 轮廓圆度检测
     - 多阈值合并 (30-150, 50-200, 100-250)
     - 直径 10-200 px (@600dpi ≈ 0.4-8mm)
     - 圆度 > 0.6 (4π*area/perimeter²)
  3. 按直径/面积自动分类:
     - crystal: 直径 30-80px (晶振/振荡器)
     - inductor_round: 直径 40-120px (圆形电感)
     - capacitor_elec: 直径 50-150px (电解电容)
     - test_point: 直径 10-30px (测试点)
     - via: 直径 5-15px (过孔)
     - unknown: 其他
  4. 每个圆形裁切保存 (bbox + pad) + 写 metadata
  5. 输出 circle_crops_index.json
"""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage


def find_all_circles(img_gray, diameter_range=(10, 200), circularity_min=0.6):
    """检测 PCB 上所有圆形轮廓 (HoughCircles + 轮廓验证)"""
    found = []

    # 方法1: HoughCircles (优化参数空间, 减少组合)
    for dp in [1, 1.5]:
        for p2 in [20, 30]:
            circles = cv2.HoughCircles(
                img_gray, cv2.HOUGH_GRADIENT,
                dp=dp, minDist=30,
                param1=80, param2=p2,
                minRadius=diameter_range[0] // 2,
                maxRadius=diameter_range[1] // 2
            )
            if circles is not None:
                for c in circles[0]:
                    x, y, r = int(c[0]), int(c[1]), int(c[2])
                    diameter = r * 2
                    area = np.pi * r * r
                    perimeter = 2 * np.pi * r
                    circ = 4 * np.pi * area / (perimeter * perimeter) if perimeter > 0 else 0
                    found.append({
                        'bbox': [x - r, y - r, x + r, y + r],
                        'center': [x, y],
                        'radius': r,
                        'diameter': diameter,
                        'area': float(area),
                        'circularity': round(circ, 3),
                        'method': f'hough_dp{dp}',
                    })

    # 方法2: 轮廓圆度检测
    for lo, hi in [(30, 150), (50, 200), (100, 250)]:
        binary = ((img_gray > lo) & (img_gray < hi)).astype(np.uint8) * 255
        # 轻微膨胀填充小间隙
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        binary = cv2.dilate(binary, kernel, iterations=1)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0:
                continue
            # 圆度: 4π*area / perimeter²
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            if circularity < circularity_min:
                continue
            # 最小外接圆
            (x, y), radius = cv2.minEnclosingCircle(cnt)
            x, y, radius = int(x), int(y), int(radius)
            diameter = radius * 2
            if not (diameter_range[0] <= diameter <= diameter_range[1]):
                continue
            # 面积比: 轮廓面积 / 圆面积
            circle_area = np.pi * radius * radius
            area_ratio = area / circle_area if circle_area > 0 else 0
            if area_ratio < 0.5:  # 太不像圆
                continue
            found.append({
                'bbox': [x - radius, y - radius, x + radius, y + radius],
                'center': [x, y],
                'radius': radius,
                'diameter': diameter,
                'area': float(area),
                'circularity': round(circularity, 3),
                'area_ratio': round(area_ratio, 3),
                'method': f'contour_{lo}_{hi}',
            })

    # 去重 (合并重叠圆)
    unique = []
    for f in found:
        dup = False
        for u in unique:
            dist = ((f['center'][0] - u['center'][0])**2 +
                    (f['center'][1] - u['center'][1])**2)**0.5
            if dist < max(f['radius'], u['radius']) * 0.6:
                dup = True
                break
        if not dup:
            unique.append(f)
    return unique


def classify_circle(circle):
    """按直径/面积自动分类"""
    d = circle['diameter']
    area = circle['area']

    if d < 15:
        return 'via'
    if 15 <= d < 30:
        return 'test_point'
    if 30 <= d < 80:
        if area > 3000:
            return 'crystal'
        return 'inductor_round'
    if 80 <= d < 150:
        return 'capacitor_elec'
    if d >= 150:
        return 'large_circle'
    return 'unknown'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pcb", required=True, help="PCB 母图 PNG 路径")
    ap.add_argument("--view", default="top", choices=["top", "bot"])
    ap.add_argument("--crops-dir", required=True,
                    help="裁切图保存目录 (例如 projects/icom2200h/crops/circle/)")
    ap.add_argument("--out", default=None,
                    help="输出 crops_index.json 路径 (默认 crops-dir/crops_index.json)")
    ap.add_argument("--board-bbox", default=None,
                    help="PCB 板边 bbox [x0,y0,x1,y1] (可选, 自动检测)")
    ap.add_argument("--min-diameter", type=int, default=30, help="最小直径 (px, 过滤小 pad)")
    ap.add_argument("--max-diameter", type=int, default=150, help="最大直径 (px, 过滤板框)")
    ap.add_argument("--circularity-min", type=float, default=0.7, help="最小圆度")
    args = ap.parse_args()

    if args.out is None:
        args.out = str(Path(args.crops_dir) / 'crops_index.json')

    # 加载
    img = np.array(Image.open(args.pcb).convert("RGB"))
    g = np.mean(img, axis=2).astype(np.uint8)
    H, W = g.shape
    print(f"[circle_loc] PCB: {args.pcb} ({W}x{H}) view={args.view}")

    # PCB 板边
    if args.board_bbox:
        PCB = [int(x) for x in args.board_bbox.strip('[]').split(',')]
    else:
        binary = (g < 230).astype(np.uint8)
        labeled, n = ndimage.label(binary)
        sizes = ndimage.sum(binary, labeled, range(1, n + 1))
        big = int(np.argmax(sizes)) + 1
        ys_b, xs_b = np.where(labeled == big)
        PCB = [int(xs_b.min()), int(ys_b.min()), int(xs_b.max()), int(ys_b.max())]
    board_area = (PCB[2] - PCB[0]) * (PCB[3] - PCB[1])
    print(f"[circle_loc] PCB 板边: {PCB}, 板面积: {board_area}")

    # 检测所有圆形
    circles = find_all_circles(g,
                                diameter_range=(args.min_diameter, args.max_diameter),
                                circularity_min=args.circularity_min)
    print(f"[circle_loc] 检测到圆形: {len(circles)}")

    # 板内过滤
    circles_in = [c for c in circles if PCB[0] <= c['center'][0] <= PCB[2]
                  and PCB[1] <= c['center'][1] <= PCB[3]]
    print(f"[circle_loc] 板内圆形: {len(circles_in)}")

    # 分类
    for c in circles_in:
        c['category'] = classify_circle(c)
    circles_in.sort(key=lambda c: -c['area'])

    # 统计
    cats = {}
    for c in circles_in:
        cats[c['category']] = cats.get(c['category'], 0) + 1
    print(f"[circle_loc] 分类统计: {cats}")

    # 创建裁切目录
    crops_dir = Path(args.crops_dir)
    crops_dir.mkdir(parents=True, exist_ok=True)
    for f in crops_dir.glob('*.png'):
        f.unlink()

    # 保存裁切 + 写 metadata
    entries = []
    img_pil = Image.open(args.pcb)
    for i, c in enumerate(circles_in):
        x0, y0, x1, y1 = c['bbox']
        pad = min(30, min(x0, y0, W - x1, H - y1))
        pad = max(0, pad)
        cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
        cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad)
        crop = img_pil.crop((cx0, cy0, cx1, cy1))
        fname = f"c{i:04d}_{c['category']}_{c['center'][0]}x{c['center'][1]}_d{c['diameter']}.png"
        crop.save(crops_dir / fname)

        entries.append({
            'idx': i,
            'bbox': c['bbox'],
            'center': c['center'],
            'radius': c['radius'],
            'diameter': c['diameter'],
            'area': c['area'],
            'circularity': c['circularity'],
            'category': c['category'],
            'description': f"圆形元件 d={c['diameter']}px",
            'status': 'unverified',
            'refdes': None,
            'refdes_source': None,
            'crop_file': fname,
            'crop_bbox_with_pad': [cx0, cy0, cx1, cy1],
            'pad_px': pad,
            'view': args.view,
            'tgt_image': os.path.basename(args.pcb),
            'tgt_image_dpi': int(os.path.basename(args.pcb).split('-')[-1].split('.')[0]) if '-' in os.path.basename(args.pcb) else 600,
        })

    # 写 schema 合规 crops_index.json
    out = {
        "_meta": {
            "purpose": "PCB 全板圆形裁切索引 — 所有检测到的圆形轮廓, 含 bbox/pad/分类/裁切文件",
            "format": "json dict: _meta + _backtrace + board_bbox + circles[]",
            "version": "0.1",
            "consumers": ["circle_locator/circle_locator.py", "pcb_label_ocr/pcb_label_ocr.py"],
            "tool": "tools/pcb_circle_locator/circle_locator.py",
            "tool_version": "0.1",
            "indexed_circles": len(entries),
            "by_category": cats,
            "image": args.pcb,
            "image_dpi": entries[0]['tgt_image_dpi'] if entries else 600,
            "view": args.view,
        },
        "_backtrace": {
            "pdf_root": "projects/icom2200h/pdf/",
            "layers": [
                {"l0_pdf": "projects/icom2200h/pdf/IC-2200HX.pdf", "page": 1, "size_pt": [612, 792]},
                {"l1_image": args.pcb, "dpi": entries[0]['tgt_image_dpi'] if entries else 600, "size_px": [W, H], "cmd": "pdftoppm -r 600 -png"},
                {"l2_anchors": {args.pcb: {"bbox_px": PCB, "bbox_inch": [c / (entries[0]['tgt_image_dpi'] if entries else 600) for c in PCB]}}}
            ]
        },
        "_anchor_method": {
            "description": "pcb 板边自动检测作为坐标铆钉, 所有圆形必须落在板内",
            "method": "otsu 二值化 + scipy.ndimage.label 最大连通区域 bbox",
            "image": args.pcb
        },
        "_circle_detection": {
            "method": "HoughCircles + 轮廓圆度检测 (多参数合并)",
            "diameter_range": [args.min_diameter, args.max_diameter],
            "circularity_min": args.circularity_min,
            "classification": {
                "via": "d < 15px (过孔)",
                "test_point": "15-30px (测试点)",
                "crystal": "30-80px, area > 3000 (晶振)",
                "inductor_round": "30-80px (圆形电感)",
                "capacitor_elec": "80-150px (电解电容)",
                "large_circle": "> 150px",
                "unknown": "其他"
            }
        },
        "_transform_legend": {
            "src_dpi": "原始检测坐标所在 dpi 空间",
            "tgt_dpi": "存储坐标的目标 dpi 空间 (同母图)",
            "scale": "1.0 (坐标同母图, 无需转换)",
            "method": "直接从母图轮廓检测, 无 tile/缩放"
        },
        "board_bbox": PCB,
        "circles": entries,
    }

    with open(args.out, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[circle_loc] circle_crops_index.json saved: {args.out}")
    print(f"[circle_loc] crops saved: {crops_dir} ({len(entries)} files)")


if __name__ == "__main__":
    main()
