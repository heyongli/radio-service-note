#!/usr/bin/env python3
"""tools/sch_symbol/sch_varactor.py — 变容二极管符号识别 (独立程序)

识别变容二极管 (变容管, varicap): 三角 + 两条平行线阴极 (类电容).
与普通二极管 (sch_diode.py) 分开, 独立识别.

用法:
  python3 sch_varactor.py --img sch.png --db sch_components.json
"""
import argparse, sys
import cv2
import numpy as np
from common import load_db, save_db, boundary_from_body
from sch_diode import _triangle


def _has_varactor_cathode(gray, cx, cy, radius=40):
    """变容阴极: 两条平行短线 (类电容)."""
    sub = gray[max(0, cy - radius):cy + radius, max(0, cx - radius):cx + radius]
    edges = cv2.Canny(sub, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 20, minLineLength=10, maxLineGap=3)
    if lines is None:
        return False
    hh, vv = [], []
    for l in np.asarray(lines).reshape(-1, 4):
        a1, b1, a2, b2 = l
        L = abs(a2 - a1) if abs(a2 - a1) >= abs(b2 - b1) else abs(b2 - b1)
        if L < 10:
            continue
        if abs(a2 - a1) >= abs(b2 - b1):
            hh.append((b1, min(a1, a2), max(a1, a2), L))
        else:
            vv.append((a1, min(b1, b2), max(b1, b2), L))
    for grp, axis in [(hh, "h"), (vv, "v")]:
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                a, b = grp[i], grp[j]
                if abs(a[3] - b[3]) > a[3] * 0.5:
                    continue
                gap = abs(a[0] - b[0]) if axis == "h" else abs(a[1] - b[1])
                if 6 <= gap <= 30:
                    return True
    return False


def detect(gray, x, y, radius=60):
    b = _triangle(gray, x, y, radius)
    if b and _has_varactor_cathode(gray, b["cx"], b["cy"]):
        return b
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--radius", type=int, default=60)
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
        if c["refdes"].upper().startswith("D"):
            b = detect(gray, c["symbol_pos"][0], c["symbol_pos"][1], args.radius)
            c["symbol_type"] = "varactor"
            c["symbol_body"] = b
            c["sym_boundary"] = boundary_from_body(b)
            if b:
                n += 1
    save_db(db, args.db)
    print(f"[sch_varactor] varactor bodies: {n}")


if __name__ == "__main__":
    main()