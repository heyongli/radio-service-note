#!/usr/bin/env python3
"""tools/sch_symbol/sch_diode.py — 二极管/变容二极管符号识别

识别二极管 (D) 本体:
  - 普通二极管: 三角形 + 短竖杠 (阴极)
  - 变容二极管: 三角形 + 两条平行线 (类电容阴极, varicap)
  中心 = 三角质心. 消费 sch_components.json, 只处理 flow_through + D 类型.

用法:
  python3 sch_diode.py --img sch.png --db sch_components.json
"""
import argparse, sys
import cv2
import numpy as np
from common import dark_contours, load_db, save_db


def _triangle(gray, x, y, radius=60):
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return None
    dark = (sub < 150).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(dark, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        a = cv2.contourArea(c)
        per = cv2.arcLength(c, True)
        if a < 150 or a > 60000 or per <= 0:
            continue
        approx = cv2.approxPolyDP(c, 0.05 * per, True)
        if len(approx) not in (3, 4, 5):
            continue
        xx, yy, w, h = cv2.boundingRect(c)
        if min(w, h) / max(1, max(w, h)) < 0.3:
            continue
        if a / max(1, w * h) < 0.25:
            continue  # 排除空心箭头
        cx, cy = xx + w / 2, yy + h / 2
        d = abs(cx + x - radius - x) + abs(cy + y - radius - y)
        if best is None or d < best[0]:
            best = (d, {"kind": "diode", "cx": int(cx + x - radius),
                        "cy": int(cy + y - radius), "w": int(w), "h": int(h)})
    return best[1] if best else None


def _unused_varactor(gray, cx, cy, radius=40):
    """变容判断: 三角旁有两条平行短线 (类电容阴极)."""
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
    return _triangle(gray, x, y, radius)


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
            c["symbol_type"] = "diode"
            c["symbol_body"] = b
            if b:
                n += 1
    save_db(db, args.db)
    print(f"[sch_diode] diode bodies: {n}")


if __name__ == "__main__":
    main()