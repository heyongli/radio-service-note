#!/usr/bin/env python3
"""tools/sch_symbol/sch_ind.py — 电感符号识别 (线本体)

识别电感 (L) 的线本体: 黑线断口 = 端点, 中心 = 断口中点 (2 端器件).
与电阻同策略, 用纯黑图层. 消费 sch_components.json, 只处理 flow_through + ind 类型.

用法:
  python3 sch_ind.py --img sch.png --db sch_components.json
"""
import argparse, sys
import cv2
from common import pure_black_mask, load_db, save_db, boundary_from_body
from sch_res import detect  # 电感/电阻同用线断口定位


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
        if c["refdes"].upper().startswith("L"):
            b = detect(pb, c["symbol_pos"][0], c["symbol_pos"][1], args.radius)
            c["symbol_type"] = "ind"
            c["symbol_body"] = b
            c["sym_boundary"] = boundary_from_body(b)
            if b:
                n += 1
    save_db(db, args.db)
    print(f"[sch_ind] inductor lines: {n}")


if __name__ == "__main__":
    main()