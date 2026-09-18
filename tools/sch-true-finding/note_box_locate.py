#!/usr/bin/env python3
"""tools/sch-true-finding/note_box_locate.py — 定位原理图说明框 (虚线方块 + 图例)

purpose: 定位原理图**说明框 (虚线方块)** 并识别图例. 管线和算法 (2026-09-18 固化):
  1. OCR 找锚点文字 (如 "Explanatory") → 大致位置 (可读 OCR 数据库 JSON 或手动给)
  2. 文字定位 → 大致区域
  3. 区域内检测**连续 dash 虚线边框** (参数化: 段长/间隔/最少段数)
  4. 识别图例 (框内裁剪, 含各颜色标注说明: 绿=RX/红=TX/青=common)
format: Python 3 + OpenCV
version: 1.0 (2026-09-18)

虚线框实测 (IC-2200H rxtx 600dpi): 边框 dash 13px 段 + 11px 间隔规律重复;
  顶 y982-983 (x4130-4414), 底 y1189-1190, 左 x4115-4117, 右 x4413-4414.

用法:
  # 从 OCR 数据库找锚点 (legacy AI-OCR JSON, 300dpi)
  python3 note_box_locate.py --img sch-600.png --ocr-json ocr.json \
    --anchor-text "Explanatory" --ocr-dpi 300 --img-dpi 600 \
    --out-box box.png --out-json box.json
  # 或手动给锚点
  python3 note_box_locate.py --img sch-600.png --anchor 4254 1002 \
    --out-box box.png --out-json box.json
"""

import argparse
import json
import sys

import cv2
import numpy as np


def anchor_from_ocr(ocr_json, text, ocr_dpi, img_dpi):
    """从 OCR 数据库找锚点文字, 返回 (x,y) (img_dpi 空间)."""
    with open(ocr_json) as f:
        d = json.load(f)
    found = []

    def walk(o):
        if isinstance(o, dict):
            if "text" in o and "px" in o and text.lower() in str(o["text"]).lower():
                found.append(o["px"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    if not found:
        return None
    px = found[0]
    return [int(px[0] * img_dpi / ocr_dpi), int(px[1] * img_dpi / ocr_dpi)]


def dashes_in_line(arr, lo, hi):
    """一行/列的暗段, 返回长度在 [lo,hi] 的段列表."""
    out = []
    on = False
    s = 0
    for i, v in enumerate(arr):
        if v and not on:
            on, s = True, i
        elif not v and on:
            out.append((s, i - 1))
            on = False
    if on:
        out.append((s, len(arr) - 1))
    return [(a, b) for a, b in out if lo <= b - a + 1 <= hi]


def dash_lines(mask, axis, lo, hi, min_dashes, win_lo, win_hi, off):
    """axis=0 扫行 / axis=1 扫列, 找 dash 线. 返回 [(pos, span_lo, span_hi)]."""
    n = mask.shape[axis]
    res = []
    for p in range(win_lo, win_hi):
        line = mask[p] if axis == 0 else mask[:, p]
        ds = dashes_in_line(line, lo, hi)
        if len(ds) >= min_dashes:
            res.append((off + p, off + ds[0][0], off + ds[-1][1]))
    return res


def group(positions, gap):
    if not positions:
        return []
    out = [[positions[0]]]
    for p in positions[1:]:
        if p[0] - out[-1][-1][0] <= gap:
            out[-1].append(p)
        else:
            out.append([p])
    return [(int(np.mean([q[0] for q in g])),
             min(q[1] for q in g), max(q[2] for q in g)) for g in out]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--out-box", default=None, help="框裁剪图 PNG (含图例)")
    ap.add_argument("--out-json", default=None, help="框 bbox JSON")
    # 锚点: OCR 或手动
    ap.add_argument("--ocr-json", default=None, help="OCR 数据库 JSON (找锚点文字)")
    ap.add_argument("--anchor-text", default="Explanatory", help="OCR 锚点文字")
    ap.add_argument("--ocr-dpi", type=int, default=300)
    ap.add_argument("--img-dpi", type=int, default=600)
    ap.add_argument("--anchor", nargs=2, type=int, default=None, help="手动锚点 x y")
    # 虚线框参数 (2026-09-18 实测: 13px 段 + 11px 间隔)
    ap.add_argument("--dash-lo", type=int, default=8, help="dash 段最小长度")
    ap.add_argument("--dash-hi", type=int, default=25, help="dash 段最大长度")
    ap.add_argument("--min-dashes", type=int, default=6, help="成边最少 dash 数")
    ap.add_argument("--gap", type=int, default=6, help="相邻行/列聚簇间隔")
    ap.add_argument("--search", type=int, default=250, help="锚点周围搜索窗 (px)")
    ap.add_argument("--dark-th", type=int, default=150)
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark = (gray < args.dark_th).astype(np.uint8)
    H, W = dark.shape

    if args.anchor:
        ax, ay = args.anchor
    elif args.ocr_json:
        a = anchor_from_ocr(args.ocr_json, args.anchor_text, args.ocr_dpi, args.img_dpi)
        if a is None:
            sys.exit(f"OCR 数据库未找到 '{args.anchor_text}'")
        ax, ay = a
    else:
        sys.exit("需要 --anchor x y 或 --ocr-json")

    # 搜索窗
    wl, wr = max(0, ax - args.search), min(W, ax + args.search)
    wt, wb = max(0, ay - args.search), min(H, ay + args.search)
    sub = dark[wt:wb, wl:wr]

    # 横/竖 dash 线
    hl = dash_lines(sub, 0, args.dash_lo, args.dash_hi, args.min_dashes,
                    0, sub.shape[0], wt)
    vl = dash_lines(sub, 1, args.dash_lo, args.dash_hi, args.min_dashes,
                    0, sub.shape[1], wl)
    hg = group(hl, args.gap)
    vg = group(vl, args.gap)
    print(f"横 dash 边: {hg}")
    print(f"竖 dash 边: {vg}")

    # 选离锚点最近的上下/左右 dash 边 → 框
    box = None
    if len(hg) >= 1 and len(vg) >= 1:
        top = min(hg, key=lambda g: abs(g[0] - ay))
        bot = max(hg, key=lambda g: g[0]) if len(hg) >= 2 else None
        lef = min(vg, key=lambda g: abs(g[0] - ax))
        rig = max(vg, key=lambda g: g[0]) if len(vg) >= 2 else None
        if bot and rig:
            box = [lef[0], top[0], rig[0] - lef[0], bot[0] - top[0]]

    data = {"_meta": {"purpose": "note box locate", "format": "json", "version": "1.0",
                      "source": args.img, "params": vars(args),
                      "anchor": [ax, ay]},
            "h_edges": hg, "v_edges": vg, "box": box}
    if box and args.out_box:
        x, y, w, h = box
        cv2.imwrite(args.out_box, img[max(0, y):y + h, max(0, x):x + w])
    if args.out_json:
        with open(args.out_json, "w") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
    print(f"[note_box_locate] anchor=({ax},{ay}) box={box} -> {args.out_box}")


if __name__ == "__main__":
    main()