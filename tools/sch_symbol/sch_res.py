#!/usr/bin/env python3
"""tools/sch_symbol/sch_res.py — 电阻符号识别 (线本体)

识别电阻 (R) 的线本体: 黑线断口 = 端点, 中心 = 断口中点 (2 端器件).
用纯黑图层去绿线干扰. 消费 sch_components.json, 只处理 flow_through + res 类型.

用法:
  python3 sch_res.py --img sch.png --db sch_components.json
"""
import argparse, sys
import cv2
import numpy as np
from common import pure_black_mask, find_lines, load_db, save_db, boundary_from_body


def detect(pb, x, y, radius=100):
    gaps = find_lines(pb, x, y, radius)
    if gaps:
        g = min(gaps, key=lambda g: abs(g["cx"] - x) + abs(g["cy"] - y))
        return {"kind": "line", "cx": g["cx"], "cy": g["cy"]}
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--radius", type=int, default=100)
    args = ap.parse_args()
    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    pb = pure_black_mask(img, gray)
    db = load_db(args.db)
    n = 0
    for c in db["components"]:
        if c.get("membership") != "flow_through" or not c.get("refdes"):
            continue
        if c["refdes"].upper().startswith("R"):
            b = detect(pb, c["symbol_pos"][0], c["symbol_pos"][1], args.radius)
            c["symbol_type"] = "res"
            c["symbol_body"] = b
            c["sym_boundary"] = boundary_from_body(b)
            if b:
                n += 1
    save_db(db, args.db)
    print(f"[sch_res] resistor lines: {n}")


if __name__ == "__main__":
    main()