#!/usr/bin/env python3
"""tools/sch_symbol/sch_ic.py — IC 符号识别 (方块本体 + 型号)

识别 IC (IC/U/FI/F/X) 的黑边空心方块, 输出 symbol_body (rect).
**不同型号 IC 尺寸不同** → 识别具体型号 (如 TA31136FN / FL-363),
尺寸知识库按型号键 (ic:<model>).
消费 sch_components.json, 只处理 flow_through + ic 类型.

用法:
  python3 sch_ic.py --img sch.png --db sch_components.json
"""
import argparse, re, sys
import cv2
from rapidocr_onnxruntime import RapidOCR
from common import find_rects, load_db, save_db, boundary_from_body


def detect(gray, x, y, radius=100):
    for cc in find_rects(gray, x, y, radius):
        if cc["x"] - 4 <= x <= cc["x"] + cc["w"] + 4 and \
           cc["y"] - 4 <= y <= cc["y"] + cc["h"] + 4:
            return {"kind": "rect", "x": cc["x"], "y": cc["y"],
                    "w": cc["w"], "h": cc["h"]}
    return None


def detect_model(gray, ocr, x, y, radius=100):
    """识别 IC 具体型号 (如 TA31136FN / FL-363). 反向 OCR 符号附近文字."""
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return None
    sub2 = cv2.resize(sub, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    res, _ = ocr(sub2)
    if not res:
        return None
    # 型号模式: 字母开头数字结尾的混合串 (如 TA31136FN, FL-363, NJM3404AV)
    for t in sorted(res, key=lambda t: -t[2]):
        txt = t[1].strip().upper()
        if re.match(r"^[A-Z]{1,4}\d[\w\-\d]{2,}$", txt) or \
           re.match(r"^[A-Z]{1,4}\-\d{2,}$", txt):
            return txt
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--radius", type=int, default=100)
    ap.add_argument("--model", action="store_true",
                    help="反向 OCR 识别 IC 具体型号 (慢)")
    args = ap.parse_args()
    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ocr = RapidOCR() if args.model else None
    db = load_db(args.db)
    n = 0
    for c in db["components"]:
        if c.get("membership") != "flow_through" or not c.get("refdes"):
            continue
        pre = "".join(ch for ch in c["refdes"] if ch.isalpha()).upper()
        if pre in ("IC", "U", "FI", "F", "X"):
            sx, sy = c["symbol_pos"][0], c["symbol_pos"][1]
            b = detect(gray, sx, sy, args.radius)
            c["symbol_type"] = "ic"
            c["symbol_body"] = b
            c["sym_boundary"] = boundary_from_body(b)
            if ocr:
                c["ic_model"] = detect_model(gray, ocr, sx, sy, args.radius)
            if b:
                n += 1
    save_db(db, args.db)
    print(f"[sch_ic] IC rects: {n}")
    if ocr:
        for c in db["components"]:
            if c.get("symbol_type") == "ic" and c.get("refdes") and c.get("symbol_body"):
                print(f"  {c['refdes']:6s} model={c.get('ic_model')} "
                      f"size={c['symbol_body'].get('w')}x{c['symbol_body'].get('h')}")


if __name__ == "__main__":
    main()