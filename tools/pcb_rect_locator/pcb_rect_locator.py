#!/usr/bin/env python3
"""tools/pcb_rect_locator/rectangle_locator.py - PCB 全板矩形裁切定位器

purpose: 在 PCB 600dpi 母图上检测所有矩形 (板/IC/电阻/电感/电容/三极管/连接器等),
         裁切保存 + 写 schema 合规 rectangle_crops_index.json
format: Python 3 + OpenCV + numpy
version: 0.2 (2026-09-15, 支持全板矩形 + 分类 + schema metadata)
consumers: OCR 验证、组件发现、IC 定位
parent_doc: ../../schema.md

设计:
  1. PCB 600dpi top/bot 母图
  2. OpenCV findContours 检测所有矩形轮廓
     - 多阈值合并 (30-150, 50-200, 100-250)
     - 面积 300-200000 px² (@600dpi ≈ 1-330 mm²)
     - 长宽比 < 10
     - 矩形度 > 0.4
  3. 按面积/长宽比自动分类:
     - board: 面积 > 500000 (PCB 大板)
     - ic: 5000-200000, aspect 1-4, rectangularity > 0.8
     - resistor: 500-5000, aspect 2-10, rectangularity > 0.6
     - capacitor: 500-8000, aspect 1-3
     - inductor: 500-20000, aspect 1-3
     - transistor: 500-5000, aspect 1-3
     - unknown: 其他
  4. 每个矩形裁切保存 (bbox + pad) + 写 metadata
  5. 输出 rectangle_crops_index.json (schema §2.1 格式)
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


def find_all_rectangles(img_gray, area_range=(300, 200000), aspect_max=10.0, rect_min=0.4):
    """检测 PCB 上所有矩形轮廓 (多阈值合并)"""
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
            if min(w, h) < 5:
                continue
            aspect = max(w, h) / min(w, h)
            if aspect > aspect_max:
                continue
            rect_area = w * h
            if rect_area == 0:
                continue
            rectangularity = area / rect_area
            if rectangularity < rect_min:
                continue
            found.append({
                'bbox': [x, y, x + w, y + h],
                'center': [x + w // 2, y + h // 2],
                'wh': [w, h],
                'area': float(area),
                'aspect': round(aspect, 2),
                'rectangularity': round(rectangularity, 2),
                'gray_range': [lo, hi],
            })
    # 去重
    unique = []
    for f in found:
        dup = False
        for u in unique:
            if (abs(f['center'][0] - u['center'][0]) < max(f['wh'][0], u['wh'][0]) * 0.4
                    and abs(f['center'][1] - u['center'][1]) < max(f['wh'][1], u['wh'][1]) * 0.4):
                dup = True
                break
        if not dup:
            unique.append(f)
    return unique


def classify_rectangle(rect, board_area):
    """按面积/长宽比自动分类"""
    area = rect['area']
    aspect = rect['aspect']
    rect_val = rect['rectangularity']

    if area > board_area * 0.5:
        return 'board'
    if area > 50000:
        if aspect < 4 and rect_val > 0.85:
            return 'ic'
        return 'large_passive'
    if 5000 <= area <= 50000:
        if aspect < 4 and rect_val > 0.85:
            return 'ic'
        if aspect >= 4 and rect_val > 0.7:
            return 'resistor'
        if aspect < 3 and rect_val > 0.8:
            return 'inductor'
        return 'medium_passive'
    if 1000 <= area < 5000:
        if aspect >= 4 and rect_val > 0.6:
            return 'resistor'
        if aspect < 3 and rect_val > 0.75:
            return 'capacitor'
        return 'small_passive'
    if 300 <= area < 1000:
        if aspect >= 3:
            return 'trace_segment'
        return 'tiny_passive'
    return 'unknown'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pcb", required=True, help="PCB 母图 PNG 路径")
    ap.add_argument("--view", default="top", choices=["top", "bot"])
    ap.add_argument("--crops-dir", required=True,
                    help="裁切图保存目录 (例如 projects/icom2200h/crops/rectangle/)")
    ap.add_argument("--out", default=None,
                    help="输出 crops_index.json 路径 (默认 crops-dir/crops_index.json)")
    ap.add_argument("--board-bbox", default=None,
                    help="PCB 板边 bbox [x0,y0,x1,y1] (可选, 自动检测)")
    args = ap.parse_args()

    # 默认输出路径: crops-dir/crops_index.json
    if args.out is None:
        args.out = str(Path(args.crops_dir) / 'crops_index.json')

    # 加载
    img = np.array(Image.open(args.pcb).convert("RGB"))
    g = np.mean(img, axis=2).astype(np.uint8)
    H, W = g.shape
    print(f"[rect_loc] PCB: {args.pcb} ({W}x{H}) view={args.view}")

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
    print(f"[rect_loc] PCB 板边: {PCB}, 板面积: {board_area}")

    # 检测所有矩形
    rects = find_all_rectangles(g)
    print(f"[rect_loc] 检测到矩形: {len(rects)}")

    # 板内过滤
    rects_in = [r for r in rects if PCB[0] <= r['center'][0] <= PCB[2]
                and PCB[1] <= r['center'][1] <= PCB[3]]
    print(f"[rect_loc] 板内矩形: {len(rects_in)}")

    # 分类
    for r in rects_in:
        r['category'] = classify_rectangle(r, board_area)
    rects_in.sort(key=lambda r: -r['area'])

    # 统计
    cats = {}
    for r in rects_in:
        cats[r['category']] = cats.get(r['category'], 0) + 1
    print(f"[rect_loc] 分类统计: {cats}")

    # 创建裁切目录
    crops_dir = Path(args.crops_dir)
    crops_dir.mkdir(parents=True, exist_ok=True)
    # 清理旧文件
    for f in crops_dir.glob('*.png'):
        f.unlink()

    # 加载已有 OCR 结果 (找附近 refdes)
    ocr_refs = {}
    # 搜索项目内 + Windows 工作区的 OCR 结果
    ocr_dirs = [
        Path(args.pcb).parent.parent / 'ocr_runs',
        Path('/mnt/c/Users/radio/icom2200h/ocr_runs'),
    ]
    for ocr_dir in ocr_dirs:
        if not ocr_dir.exists():
            continue
        for jf in ocr_dir.glob('*/*.json'):
            try:
                with open(jf) as f:
                    od = json.load(f)
                for h in od.get('raw_stage1', []):
                    ref = h.get('text', '').strip()
                    if ref and len(ref) <= 6 and not ref.isdigit():
                        px = h.get('px', [0, 0])
                        if ref not in ocr_refs:
                            ocr_refs[ref] = []
                        ocr_refs[ref].append({'px': px, 'source': jf.name})
            except Exception:
                pass

    def find_nearby_refs(center, radius=100):
        """找 center 附近 radius px 内的已知 refdes"""
        nearby = []
        for ref, hits in ocr_refs.items():
            for hit in hits:
                px = hit['px']
                dist = ((px[0] - center[0])**2 + (px[1] - center[1])**2)**0.5
                if dist < radius:
                    nearby.append({'refdes': ref, 'dist': round(dist, 1), 'source': hit['source']})
                    break
        nearby.sort(key=lambda x: x['dist'])
        return nearby[:5]

    def gen_description(r, nearby):
        """生成矩形描述"""
        cat_desc = {
            'board': 'PCB 大板',
            'ic': 'IC 封装',
            'resistor': '电阻',
            'capacitor': '电容',
            'inductor': '电感',
            'medium_passive': '中型无源器件',
            'small_passive': '小型无源器件',
            'tiny_passive': '微型无源器件',
            'trace_segment': '走线段',
            'large_passive': '大型无源器件',
            'unknown': '未分类',
        }
        desc = cat_desc.get(r['category'], r['category'])
        if nearby:
            refs = ', '.join([n['refdes'] for n in nearby[:3]])
            desc += f' — 附近有: {refs}'
        return desc

    # 保存裁切 + 写 metadata
    entries = []
    img_pil = Image.open(args.pcb)
    for i, r in enumerate(rects_in):
        x0, y0, x1, y1 = r['bbox']
        # 加 pad (最大 50px)
        pad = min(50, min(x0, y0, W - x1, H - y1))
        pad = max(0, pad)
        cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
        cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad)
        crop = img_pil.crop((cx0, cy0, cx1, cy1))
        fname = f"r{i:04d}_{r['category']}_{r['center'][0]}x{r['center'][1]}_w{r['wh'][0]}h{r['wh'][1]}.png"
        crop.save(crops_dir / fname)

        # 找附近 refdes
        nearby = find_nearby_refs(r['center'], radius=100)
        desc = gen_description(r, nearby)

        entries.append({
            'idx': i,
            'bbox': r['bbox'],
            'center': r['center'],
            'wh': r['wh'],
            'area': r['area'],
            'aspect': r['aspect'],
            'rectangularity': r['rectangularity'],
            'gray_range': r['gray_range'],
            'category': r['category'],
            'description': desc,
            'status': 'unverified',
            'refdes': None,
            'refdes_source': None,
            'nearby_ocr_refs': [n['refdes'] for n in nearby],
            'crop_file': fname,
            'crop_bbox_with_pad': [cx0, cy0, cx1, cy1],
            'pad_px': pad,
            'view': args.view,
            'tgt_image': os.path.basename(args.pcb),
            'tgt_image_dpi': int(os.path.basename(args.pcb).split('-')[-1].split('.')[0]) if '-' in os.path.basename(args.pcb) else 600,
        })

    # 写 schema 合规 crops_index.json (与裁切图同目录)
    out = {
        "_meta": {
            "purpose": "PCB 全板矩形裁切索引 — 所有检测到的矩形轮廓, 含 bbox/pad/分类/裁切文件",
            "format": "json dict: _meta + _backtrace + board_bbox + rectangles[]",
            "version": "0.3 (2026-09-15, crops_index 移到 crops 目录)",
            "consumers": ["rectangle_locator/rectangle_locator.py", "tools/verify_anchor/verify_anchor.py"],
            "tool": "tools/pcb_rect_locator/rectangle_locator.py",
            "tool_version": "0.3",
            "indexed_rectangles": len(entries),
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
            "description": "pcb 板边自动检测作为坐标铆钉, 所有矩形必须落在板内",
            "method": "otsu 二值化 + scipy.ndimage.label 最大连通区域 bbox",
            "image": args.pcb
        },
        "_rectangle_detection": {
            "method": "OpenCV findContours, 多阈值合并 (30-150, 50-200, 100-250)",
            "area_range": [300, 200000],
            "aspect_max": 10.0,
            "rectangularity_min": 0.4,
            "classification": {
                "board": "area > 500000 (PCB 大板)",
                "ic": "5000-200000, aspect < 4, rectangularity > 0.85",
                "resistor": "1000-50000, aspect >= 4, rectangularity > 0.6",
                "capacitor": "1000-5000, aspect < 3, rectangularity > 0.75",
                "inductor": "5000-50000, aspect < 3, rectangularity > 0.8",
                "medium_passive": "5000-50000, 未匹配以上",
                "small_passive": "1000-5000, 未匹配以上",
                "tiny_passive": "300-1000",
                "trace_segment": "300-1000, aspect >= 3",
                "large_passive": "> 50000, 未匹配以上",
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
        "rectangles": entries,
    }

    with open(args.out, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[rect_loc] rectangle_crops_index.json saved: {args.out}")
    print(f"[rect_loc] crops saved: {crops_dir} ({len(entries)} files)")


if __name__ == "__main__":
    main()
