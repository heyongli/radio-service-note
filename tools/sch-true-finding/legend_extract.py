#!/usr/bin/env python3
"""tools/sch-true-finding/legend_extract.py — 从说明框提取图例数据库 (色→信号 权威真值)

purpose: 从原理图说明框 (虚线方块, note_box_locate 定位) 提取**图例数据库**:
        每条 = OCR 文字标签 + 对应色彩样本 (准确线条颜色). 这是 "颜色→信号"
        的**权威校准源** (绿=RX/橙土黄=TX/青=common/品红=电压), 供 COLOR_SPEC
        探测校准 (readme §8) 直接读取.
format: Python 3 + OpenCV
version: 0.1 (2026-09-18)

工作流 (与 OCR 配合):
  1. note_box_locate: OCR找锚点文字→定位虚线框→box bbox (JSON)
  2. 本程序: 框内反查 OCR (box 内文字) + 按行提取色彩样本
  3. 对齐: 色带按 y 匹配最近 OCR 文字行 → legend 条目
  4. 存数据库: projects/<机型>/nettable/explanatory_notes.json

用法:
  python3 legend_extract.py --img sch.png --ocr-json ocr.json \
    --box-json note_box.json --out-json explanatory_notes.json
    [--ocr-dpi 300] [--img-dpi 600]
"""

import argparse
import json
import sys

import cv2
import numpy as np


def ocr_in_box(ocr_json, box, ocr_dpi, img_dpi):
    """反查 OCR: 取 box 内文字 (img_dpi 空间), 返回 [(px, text, conf)]."""
    with open(ocr_json) as f:
        d = json.load(f)
    bx0, by0, bw, bh = box
    s = img_dpi / ocr_dpi
    found = []

    def walk(o):
        if isinstance(o, dict):
            if "text" in o and "px" in o:
                px = o["px"]
                gx, gy = px[0] * s, px[1] * s
                if bx0 <= gx <= bx0 + bw and by0 <= gy <= by0 + bh:
                    found.append(([int(gx), int(gy)], str(o["text"]), float(o.get("conf", 0))))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    return found


def color_bands(img, box, min_px=3, gap=8):
    """框内色彩样本, 按行聚成色带. 返回 [(y0,y1,color_bgr,n)] (局部坐标)."""
    x, y, w, h = box
    sub = img[y:y + h, x:x + w]
    b, g, r = cv2.split(sub.astype(int))
    md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    colored = md > 40
    rows = {}
    for yy in range(h):
        if colored[yy].sum() > min_px:
            rows[yy] = colored[yy].sum()
    bands = []
    cur = []
    prev = None
    for yy in sorted(rows):
        if prev is None or yy - prev <= gap:
            cur.append(yy)
        else:
            bands.append(cur)
            cur = [yy]
        prev = yy
    if cur:
        bands.append(cur)
    out = []
    for bd in bands:
        y0, y1 = bd[0], bd[-1]
        seg = colored[y0:y1 + 1]
        px = sub[y0:y1 + 1][seg]
        out.append((y0, y1, np.median(px, axis=0).astype(int).tolist(), int(len(px))))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--ocr-json", required=True, help="OCR 数据库 JSON")
    ap.add_argument("--box-json", required=True, help="note_box_locate 输出 JSON (含 box)")
    ap.add_argument("--out-json", required=True, help="图例数据库输出")
    ap.add_argument("--ocr-dpi", type=int, default=300)
    ap.add_argument("--img-dpi", type=int, default=600)
    ap.add_argument("--match-dist", type=int, default=25,
                    help="文字与色带最大匹配距离 (标题行远→无色)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    box = json.load(open(args.box_json))["box"]
    if not box:
        sys.exit("box 为空, 先跑 note_box_locate")
    texts = ocr_in_box(args.ocr_json, box, args.ocr_dpi, args.img_dpi)
    bands = color_bands(img, box)

    # 对齐: 每条 OCR 文字 y 找最近的色带 (距离<=--match-dist, 标题行远→无色)
    entries = []
    for px, text, conf in texts:
        gy = px[1]
        dist = lambda b: abs((b[0] + b[1]) / 2 + box[1] - gy)
        best = min(bands, key=dist) if bands else None
        color = best[2] if best and dist(best) <= args.match_dist else None
        entries.append({"label": text, "px": px, "conf": conf,
                        "color_bgr": color})
    data = {"_meta": {"purpose": "explanatory notes legend (color->signal truth)",
                      "format": "json", "version": "0.1",
                      "source": args.img, "box": box},
            "entries": entries}
    with open(args.out_json, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    for e in entries:
        print(f"  {e['label']:15s} BGR={e['color_bgr']}")
    print(f"saved {args.out_json}")


if __name__ == "__main__":
    main()