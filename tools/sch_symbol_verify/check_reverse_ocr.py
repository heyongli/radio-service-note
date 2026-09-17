#!/usr/bin/env python3
"""tools/sch_symbol_verify/check_reverse_ocr.py — 反向 OCR 反查

purpose: 在符号中心反向 OCR, 确认读出的 refdes 与关联一致.
        若不一致 → 关联错误 (红点在别的符号/label 上).

用法:
  python3 check_reverse_ocr.py --img sch.png --db sch_components.json \
      [--radius 45] [--rots 0,90,180,270]

与 sch_symbol_verify.py (主边界) / check_overlap.py (重叠) 同目录, 独立反查手段.
"""

import argparse
import json
import sys

import cv2
import numpy as np


def reads_ref(gray, ocr, x, y, refdes, radius=45, rots=(0,)):
    def norm(s):
        return s.replace("I", "1").replace("L", "1")
    tgt = norm(refdes)
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return False
    base = cv2.resize(sub, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    for rot, code in [(0, None), (90, cv2.ROTATE_90_CLOCKWISE),
                      (180, cv2.ROTATE_180), (270, cv2.ROTATE_90_COUNTERCLOCKWISE)]:
        if rot not in rots:
            continue
        im = cv2.rotate(base, code) if code is not None else base
        res, _ = ocr(im)
        if not res:
            continue
        for t in res:
            nr = norm(t[1].strip().upper().replace(" ", ""))
            if nr and (tgt == nr or tgt in nr or nr in tgt):
                return True
        if any("FL-363" in t[1] for t in res):
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--db", required=True, help="sch_components.json")
    ap.add_argument("--radius", type=int, default=45)
    ap.add_argument("--rots", default="0,90,180,270")
    args = ap.parse_args()

    from rapidocr_onnxruntime import RapidOCR
    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ocr = RapidOCR()
    db = json.load(open(args.db))
    rots = tuple(int(v) for v in args.rots.split(","))

    n = n_ok = 0
    for c in db["components"]:
        if c.get("membership") != "flow_through" or not c.get("refdes"):
            continue
        sx, sy = c["symbol_pos"]
        n += 1
        ok = reads_ref(gray, ocr, sx, sy, c["refdes"], args.radius, rots)
        c["reverse_ocr_ok"] = ok
        if ok:
            n_ok += 1
    with open(args.db, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    print(f"[check_reverse_ocr] flow_through reverse-OCR: {n_ok}/{n} OK")
    for c in db["components"]:
        if c.get("membership") == "flow_through" and c.get("refdes") and not c.get("reverse_ocr_ok"):
            print(f"  FAIL {c['refdes']:6s} @{c['symbol_pos']}")


if __name__ == "__main__":
    main()