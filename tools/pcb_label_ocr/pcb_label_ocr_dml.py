#!/usr/bin/env python3
"""tools/ic_ocr_scan/ic_ocr_scan_dml.py - PCB 矩形裁切多角度 OCR (Windows DirectML GPU)

purpose: 在 Windows 原生 Python + DirectML GPU 上对 crops_index.json 中的矩形裁切
         做 0/90/270° 旋转 OCR, 识别出的所有 refdes 写入 components_index.json
format: Python 3 + RapidOCR + DirectML
version: 0.4 (2026-09-15, 全类别 OCR + 坐标转换 → components_index + DML)
consumers: Windows 端 GPU 加速 OCR
parent_doc: ../../schema.md

用法 (Windows 原生 Python):
    C:\\Users\\radio\\py311\\python.exe tools\\ic_ocr_scan\\ic_ocr_scan_dml.py ^
        --crops-index projects\\icom2200h\\crops\\rectangle\\crops_index.json ^
        --pcb projects\\icom2200h\\render\\pcb-top-600-1.png ^
        --view top ^
        --rots 0,90,270

坐标转换: crop 本地 box → 母图坐标 (详见 architecture.md §13)
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# DirectML 补丁 (遵循 best_practices.md §12)
sys.path.insert(0, str(Path(__file__).parent.parent / 'ai_ocr_eval'))
from dml_helper import enable_dml
enable_dml()
from rapidocr import RapidOCR

# 常见 refdes 正则
REF_RE = re.compile(
    r'(?i)\b(IC|R|C|L|Q|D|FI|EP|BPF|F|J|TR|SW|X|Y|CR|RB|RV|U|VR|Z)\s*(\d{1,4})\b'
)


def ocr_crop(engine, img_crop, rots=[0, 90, 270]):
    Wc, Hc = img_crop.size
    results = []
    for rot in rots:
        if rot == 0:
            cropped = img_crop
        else:
            cropped = img_crop.rotate(-rot, expand=True)
        arr = np.array(cropped)
        ocr_result = engine(arr)
        if hasattr(ocr_result, 'boxes') and ocr_result.boxes is not None:
            for i, box in enumerate(ocr_result.boxes):
                text = ocr_result.txts[i] if ocr_result.txts and i < len(ocr_result.txts) else ''
                score = ocr_result.scores[i] if ocr_result.scores and i < len(ocr_result.scores) else None
                b = box.tolist() if hasattr(box, 'tolist') else box
                # 逆旋转: OCR box 在旋转后坐标系, 需转回原始 crop 坐标再 +crop 原点
                if rot == 90:
                    b = [[p[1], Hc - 1 - p[0]] for p in b]
                elif rot == 270:
                    b = [[Wc - 1 - p[1], p[0]] for p in b]
                results.append({
                    'text': text.strip(),
                    'rot': rot,
                    'box': b,
                    'score': float(score) if score is not None else None,
                })
    return results


def extract_refs(ocr_results):
    refs = {}
    for ocr in ocr_results:
        text = ocr['text']
        for m in REF_RE.finditer(text):
            prefix = m.group(1).upper()
            num = m.group(2)
            key = f"{prefix}{num}"
            if key not in refs or (ocr['score'] or 0) > refs[key]['score']:
                refs[key] = {'refdes': key, 'text': text, 'rot': ocr['rot'], 'score': ocr['score'], 'box': ocr['box']}
    return list(refs.values())


def box_to_pcb_coords(box, cx0, cy0):
    """crop 本地 box → 母图坐标 (architecture.md §13.2)"""
    if box is None or not isinstance(box, list) or len(box) < 4:
        return None
    return [[p[0] + cx0, p[1] + cy0] for p in box]


def box_center(pcb_box):
    if pcb_box is None:
        return None
    cx = sum(p[0] for p in pcb_box) / 4
    cy = sum(p[1] for p in pcb_box) / 4
    return [int(round(cx)), int(round(cy))]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crops-index", required=True)
    ap.add_argument("--pcb", required=True)
    ap.add_argument("--view", default="top", choices=["top", "bot"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--rots", default="0,90,270")
    ap.add_argument("--categories", default="all")
    args = ap.parse_args()

    if args.out is None:
        args.out = str(Path(args.pcb).parent.parent / 'nettable' / 'components_index.json')

    rots = [int(x) for x in args.rots.split(',')]
    with open(args.crops_index) as f:
        idx = json.load(f)
    board_bbox = idx['board_bbox']

    pcb = Image.open(args.pcb).convert('RGB')
    W, H = pcb.size
    pcb_dpi = 600

    components = {}
    if Path(args.out).exists():
        with open(args.out) as f:
            components = json.load(f)
    backtrace = components.get('_backtrace', {})
    anchor = components.get('_anchor_method', {})
    transform_legend = components.get('_transform_legend', {})

    if args.categories == 'all':
        candidates = idx['rectangles']
    else:
        cats = args.categories.split(',')
        candidates = [r for r in idx['rectangles'] if r['category'] in cats]
    print(f"[ocr_scan_dml] candidates: {len(candidates)} (categories={args.categories})")

    engine = RapidOCR()
    updated_rects = list(idx['rectangles'])
    all_found = []

    for i, r in enumerate(candidates):
        x0, y0, x1, y1 = r['bbox']
        pad = 100
        cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
        cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad)
        crop = pcb.crop((cx0, cy0, cx1, cy1))

        rect_idx = r['idx']
        print(f"  [{i+1}/{len(candidates)}] idx={rect_idx} center={r['center']} ...", end=' ', flush=True)

        ocr_results = ocr_crop(engine, crop, rots)
        refs = extract_refs(ocr_results)

        if refs:
            best = max(refs, key=lambda x: x['score'] or 0)
            updated_rects[rect_idx]['refdes'] = best['refdes']
            updated_rects[rect_idx]['status'] = 'ocr_found'
            updated_rects[rect_idx]['refdes_source'] = f"ocr_scan_dml_rot{best['rot']}_s{best['score']:.3f}"
            print(f"→ {best['refdes']} (rot={best['rot']}, score={best['score']:.3f})")
        else:
            updated_rects[rect_idx]['status'] = 'unverified'
            texts = [o['text'] for o in ocr_results[:3]]
            print(f"→ no ref (got: {texts})")

        for ref in refs:
            pcb_box = box_to_pcb_coords(ref['box'], cx0, cy0)
            pcb_center = box_center(pcb_box)
            if pcb_center is None:
                continue
            if not (board_bbox[0] <= pcb_center[0] <= board_bbox[2] and board_bbox[1] <= pcb_center[1] <= board_bbox[3]):
                continue

            key = ref['refdes']
            if key in components and isinstance(components[key], dict):
                old_score = components[key].get('_ocr_score', 0) or 0
                if (ref['score'] or 0) <= old_score:
                    continue

            components[key] = {
                'center': pcb_center,
                'box': pcb_box,
                'view': args.view,
                'role': '',
                'flow_note': '',
                'agree': False,
                'candidates': 1,
                'src': f"ocr_scan_dml_rot{ref['rot']}_{Path(args.pcb).stem}",
                'src_dpi': pcb_dpi,
                'tgt_image': Path(args.pcb).name,
                'tgt_image_dpi': pcb_dpi,
                'tgt_image_size': [W, H],
                'tgt_board_bbox': board_bbox,
                'transform': {
                    'src_image': Path(args.pcb).name,
                    'src_dpi': pcb_dpi,
                    'tgt_dpi': pcb_dpi,
                    'scale': 1.0,
                    'method': f"ocr_scan_dml: crop_idx={rect_idx}, rot={ref['rot']}, local_box→pcb_coords",
                    'validated': False,
                },
                'scale': 1.0,
                'validated': False,
                '_ocr_score': ref['score'],
                '_ocr_rot': ref['rot'],
                '_ocr_text': ref['text'],
                '_crop_idx': rect_idx,
                '_crop_bbox': r['bbox'],
                '_local_box': ref['box'],
            }

        all_found.append({'idx': rect_idx, 'bbox': r['bbox'], 'center': r['center'], 'category': r['category'], 'ocr_refs': refs})

    idx['rectangles'] = updated_rects
    idx['_meta']['ocr_scan_version'] = '0.4'
    with open(args.crops_index, 'w') as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    print(f"[ocr_scan_dml] crops_index.json updated: {args.crops_index}")

    found = [r for r in all_found if r['ocr_refs']]
    print(f"\n[ocr_scan_dml] 写入 components_index: {len(found)} 个 refdes")

    ref_keys = [k for k in components if not k.startswith('_')]
    components['_meta'] = {
        'purpose': '元器件索引 (枢纽, 跨图映射), 每条含完整溯源',
        'format': 'json dict refdes -> {...}',
        'version': '0.11 (ocr_scan_dml 写入)',
        'consumers': ['tools/ic_ocr_scan/ic_ocr_scan_dml.py', 'tools/svg-render/svg_render.py'],
        'indexed_refdes': len(ref_keys),
        'by_view': {'top': len([k for k in ref_keys if components[k].get('view') == 'top']),
                     'bot': len([k for k in ref_keys if components[k].get('view') == 'bot']),
                     'sch': len([k for k in ref_keys if components[k].get('view') == 'sch'])},
        'by_role': len([k for k in ref_keys if components[k].get('role')]),
        'anchor_count': len([k for k in ref_keys if components[k].get('validated')]),
        'scale_distribution': {},
    }
    components['_backtrace'] = backtrace
    components['_anchor_method'] = anchor
    components['_transform_legend'] = transform_legend

    with open(args.out, 'w') as f:
        json.dump(components, f, ensure_ascii=False, indent=2)
    print(f"[ocr_scan_dml] components_index.json saved: {args.out}")

    print(f"\n[ocr_scan_dml] 汇总:")
    for r in found:
        best = max(r['ocr_refs'], key=lambda x: x['score'] or 0)
        print(f"  {best['refdes']} @ {r['center']} (rot={best['rot']}, score={best['score']:.3f})")


if __name__ == "__main__":
    main()
