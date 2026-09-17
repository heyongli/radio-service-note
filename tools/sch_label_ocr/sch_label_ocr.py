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
    if args.refdes:
        data = json.load(open(args.refdes))
        if isinstance(data, dict):
            for k, v in data.items():
                refs.setdefault(k, (round(v[0]), round(v[1])))
        else:
            for r in data:
                refs.setdefault(r["refdes"], (r["x"], r["y"]))
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
                               "symbol_type": s["sym"], "text_symbol_dist": d0})
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