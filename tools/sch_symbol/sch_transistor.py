#!/usr/bin/env python3
"""tools/sch_symbol/sch_transistor.py — 三极管符号识别 (圆本体)

识别三极管 (Q/TR) 的圆本体: Hough 圆 / 黑边圆, 输出 symbol_body (circle).
消费 sch_components.json, 只处理 flow_through + circle 类型.

用法:
  python3 sch_transistor.py --img sch.png --db sch_components.json
"""
import argparse, sys
import cv2
from common import find_circles, load_db, save_db, boundary_from_body


def detect(gray, x, y, radius=80):
    for h in find_circles(gray, x, y, radius):
        if (x - h["cx"]) ** 2 + (y - h["cy"]) ** 2 <= (h["r"] + 4) ** 2:
            return {"kind": "circle", "cx": h["cx"], "cy": h["cy"], "r": h["r"]}
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--radius", type=int, default=80)
    args = ap.parse_args()
    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    db = load_db(args.db)
    n = 0
    for c in db["components"]:
        if c.get("membership") != "flow_through" or not c.get("refdes"):
            continue
        if c["refdes"].upper().startswith("Q") or c["refdes"].upper().startswith("TR"):
            b = detect(gray, c["symbol_pos"][0], c["symbol_pos"][1], args.radius)
            c["symbol_type"] = "circle"
            c["symbol_body"] = b
            c["sym_boundary"] = boundary_from_body(b)
            if b:
                n += 1
    save_db(db, args.db)
    print(f"[sch_transistor] transistor circles: {n}")


if __name__ == "__main__":
    main()