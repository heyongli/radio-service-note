#!/usr/bin/env python3
"""tools/sch_symbol_selfcheck/check_overlap.py — 符号重叠反查

purpose: 电路图符号不能重叠。检测两个 flow_through 符号边界是否重叠,
        重叠即识别错误 (误关联到同一符号/邻近符号).
        消费 sch_components.json 的 sym_boundary.

用法:
  python3 check_overlap.py --db sch_components.json [--pad 6] [--out 重叠报告]

与 sch_symbol_selfcheck.py (主边界验证) / check_reverse_ocr.py (反向OCR) 同目录,
各自独立, 都是符号反查手段.
"""

import argparse
import json
import sys


def bounds_overlap(b1, b2, pad=6):
    if b1 is None or b2 is None:
        return False
    if b1["kind"] == "circle" and b2["kind"] == "circle":
        return (b1["cx"] - b2["cx"]) ** 2 + (b1["cy"] - b2["cy"]) ** 2 <= \
               (b1["r"] + b2["r"] + pad) ** 2
    if b1["kind"] == "rect" and b2["kind"] == "rect":
        return not (b1["x"] + b1["w"] + pad < b2["x"] or b2["x"] + b2["w"] + pad < b1["x"] or
                    b1["y"] + b1["h"] + pad < b2["y"] or b2["y"] + b2["h"] + pad < b1["y"])
    c = b1 if b1["kind"] == "circle" else b2
    r = b2 if b1["kind"] == "circle" else b1
    cx, cy, rr = c["cx"], c["cy"], c["r"]
    nx = max(r["x"] - pad, min(cx, r["x"] + r["w"] + pad))
    ny = max(r["y"] - pad, min(cy, r["y"] + r["h"] + pad))
    return (cx - nx) ** 2 + (cy - ny) ** 2 <= (rr + pad) ** 2


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True, help="sch_components.json")
    ap.add_argument("--pad", type=int, default=6, help="重叠容差 (px)")
    args = ap.parse_args()

    db = json.load(open(args.db))
    ft = [c for c in db["components"]
          if c.get("membership") == "flow_through" and c.get("refdes") and c.get("sym_boundary")]
    pairs = []
    for i in range(len(ft)):
        for j in range(i + 1, len(ft)):
            if bounds_overlap(ft[i]["sym_boundary"], ft[j]["sym_boundary"], args.pad):
                pairs.append((ft[i]["refdes"], ft[j]["refdes"]))
    print(f"[check_overlap] flow_through with boundary: {len(ft)}, overlaps: {len(pairs)}")
    for a, b in pairs[:30]:
        print(f"  OVERLAP {a} <-> {b}")


if __name__ == "__main__":
    main()