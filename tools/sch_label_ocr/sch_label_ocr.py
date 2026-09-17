#!/usr/bin/env python3
"""tools/sch_label_ocr/sch_label_ocr.py — 层1b 读绿线符号的标号

purpose: 读 sch_trace 的 sch_components.json (symbols), 对每个绿线符号局部 OCR,
        关联 refdes → 生成带标号的 sch_components.json (schema §3.5)
format: Python 3 + rapidocr
version: 0.1 (2026-09-16)

用法:
  python3 sch_label_ocr.py --img render/rxtx-sch-600-1.png \
      [--refdes refdes.json] --db sch_components.json
"""

import argparse
import json
import re
import sys

import cv2


def norm_ref(s):
    return s.replace("I", "1").replace("L", "1")


def reverse_ocr_check(gray, ocr, sx, sy, refdes, radius=50, correction=True):
    """反向 OCR 验证: 在符号中心读 refdes, 确认关联正确."""
    sub = gray[max(0, sy - radius):sy + radius, max(0, sx - radius):sx + radius]
    sub2 = cv2.resize(sub, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    res, _ = ocr(sub2)
    if not res:
        return "empty"
    reads = [t[1].strip().upper().replace(" ", "") for t in res]
    target = norm_ref(refdes)
    for r in reads:
        nr = norm_ref(r)
        if nr and (target == nr or target in nr or nr in target):
            return "ok"
    # FL-363 陶瓷滤波 (F13/F14 = FI3/FI4)
    if any("FL-363" in r for r in reads):
        return "ok"
    return "wrong"


def locate_text_box(gray, ocr, x, y, refdes, radius=70):
    """定位 refdes 文字的方框 (4 角). 用局部 OCR 找 refdes 的 box."""
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return None
    sub2 = cv2.resize(sub, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    res, _ = ocr(sub2)
    if not res:
        return None
    tgt = refdes.replace("I", "1").replace("L", "1")
    for t in res:
        nr = t[1].strip().upper().replace(" ", "").replace("I", "1").replace("L", "1")
        if nr and (tgt == nr or tgt in nr or nr in tgt):
            bx = t[0]
            # 缩放回原图坐标
            box = [[round(p[0] / 2.5 + x - radius), round(p[1] / 2.5 + y - radius)] for p in bx]
            return box
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--refdes", help="OCR refdes 位置 JSON (可选; 无则局部 OCR)")
    ap.add_argument("--db", required=True, help="sch_components.json (读写)")
    ap.add_argument("--assoc-dist", type=int, default=120, help="标号→符号关联最大距离")
    ap.add_argument("--type-bonus", type=int, default=40, help="类型匹配加分")
    args = ap.parse_args()

    from rapidocr_onnxruntime import RapidOCR
    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ocr = RapidOCR()
    db = json.load(open(args.db))
    symbols = db.get("symbols", db.get("components", []))

    # 用全量 refdes 位置集 (优先) 做关联
    refs = {}
    boxes = {}
    if args.refdes:
        data = json.load(open(args.refdes))
        if isinstance(data, dict):
            for k, v in data.items():
                refs.setdefault(k, (round(v[0]), round(v[1])))
                if len(v) >= 5:
                    boxes[k] = v[4]
        else:
            for r in data:
                refs.setdefault(r["refdes"], (r["x"], r["y"]))
                if "box" in r:
                    boxes[r["refdes"]] = r["box"]
    PREFIX = {"Q": "circle", "TR": "circle", "C": "cap", "IC": "ic",
              "U": "ic", "FI": "ic", "F": "ic", "L": "circle", "R": "cap"}

    components = []
    for s in symbols:
        sx, sy = s["x"], s["y"]
        # 关联最近 refdes (类型匹配)
        best = None
        for rd, (rx, ry) in refs.items():
            prefix = "".join(ch for ch in rd if ch.isalpha()).upper()
            d = abs(sx - rx) + abs(sy - ry)
            if d > args.assoc_dist:
                continue
            score = d - (args.type_bonus if PREFIX.get(prefix) == s["sym"] else 0)
            if best is None or score < best[0]:
                best = (score, d, rd)
        if best is not None:
            _, d0, rd = best
            components.append({"refdes": rd, "symbol_pos": [sx, sy],
                               "symbol_type": s["sym"], "text_symbol_dist": d0,
                               "text_box": boxes.get(rd)})
            continue
        # 局部 OCR 兜底
        sub = gray[max(0, sy - 50):sy + 50, max(0, sx - 50):sx + 50]
        sub2 = cv2.resize(sub, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        res, _ = ocr(sub2)
        rd = None
        if res:
            for t in res:
                txt = t[1].strip()
                if re.match(r"^(IC|Q|F|FI|D|J|C|R|L|X|U|TR|Z)\s*\d+", txt, re.I):
                    rd = txt.upper().replace(" ", "")
                    break
        components.append({"refdes": rd, "symbol_pos": [sx, sy],
                           "symbol_type": s["sym"], "text_symbol_dist": None})

    db["components"] = components
    db["_meta"]["source"] = "sch_trace + sch_label_ocr"

    with open(args.db, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    print(f"[sch_label_ocr] saved: {args.db} ({len(components)} labeled)")


if __name__ == "__main__":
    main()