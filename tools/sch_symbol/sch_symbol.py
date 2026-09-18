#!/usr/bin/env python3
"""tools/sch_symbol/sch_symbol.py — 原理图符号识别 (per-type)

purpose: 按符号类型识别原理图元器件本体 (区分本体 vs 引出线):
          - 三极管(circle): 黑边圆 / Hough 圆, 本体中心+半径
          - IC(rect): 黑边空心方块, 本体框
          - 电容(cap): 两条平行板线质心 (本体), 非引出线
          - 电阻/电感(res/ind): 黑线断口 = 端点, 中心 = 断口中点
        对应 PCB 侧 pcb_package (封装识别). 消费 sch_components.json 候选,
        输出每个组件的 symbol body (kind/cx/cy/r 或 x/y/w/h).
        sch_symbol_selfcheck 消费本模块结果做验证.

用法:
  python3 sch_symbol.py --img sch.png --db sch_components.json
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np


def type_from_refdes(refdes):
    pre = "".join(ch for ch in refdes if ch.isalpha()).upper()
    if pre in ("Q", "TR"):
        return "circle"
    if pre in ("IC", "U", "FI", "F", "X"):
        return "ic"
    if pre == "C":
        return "cap"
    if pre == "L":
        return "ind"
    if pre == "R":
        return "res"
    return "cap"


def pure_black_mask(img, gray=None, dark_th=150):
    """纯黑图层: 暗像素去掉绿线 (绿线叠加干扰符号/走线检测)."""
    if gray is None:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b, g, r = cv2.split(img.astype(int))
    green = ((g > 120) & (r < 110) & (b < 110)).astype(np.uint8)
    return ((gray < dark_th) & (1 - green)).astype(np.uint8) * 255


def hough_circles(gray, x, y, radius=80, rmin=10, rmax=40):
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return []
    cs = cv2.HoughCircles(sub, cv2.HOUGH_GRADIENT, dp=1.2, minDist=12,
                          param1=80, param2=28, minRadius=rmin, maxRadius=rmax)
    out = []
    if cs is not None:
        for cx, cy, r in np.rint(cs[0]).astype(int):
            out.append({"cx": int(cx) + x - radius, "cy": int(cy) + y - radius, "r": int(r)})
    return out


def dark_contours(gray, x, y, radius=80, th=150):
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return []
    dark = (sub < th).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(dark, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        per = cv2.arcLength(c, True)
        if a < 40 or per <= 0:
            continue
        xx, yy, w, h = cv2.boundingRect(c)
        out.append({"a": int(a), "x": int(xx) + x - radius, "y": int(yy) + y - radius,
                    "w": int(w), "h": int(h),
                    "circ": float(4 * np.pi * a / (per * per)) if per else 0})
    return out


def detect_body(gray, pb, x, y, sym, radius=80):
    """识别 (x,y) 附近某类型符号本体. 返回 dict {kind, cx, cy, r|w,h} 或 None."""
    if sym == "circle":
        for h in hough_circles(gray, x, y, radius):
            if (x - h["cx"]) ** 2 + (y - h["cy"]) ** 2 <= (h["r"] + 4) ** 2:
                return {"kind": "circle", "cx": h["cx"], "cy": h["cy"], "r": h["r"]}
        for cc in dark_contours(gray, x, y, radius):
            if cc["circ"] > 0.7 and cc["w"] >= 15 and cc["h"] >= 15:
                cx, cy = cc["x"] + cc["w"] / 2, cc["y"] + cc["h"] / 2
                r = max(cc["w"], cc["h"]) / 2
                if (x - cx) ** 2 + (y - cy) ** 2 <= (r + 4) ** 2:
                    return {"kind": "circle", "cx": int(cx), "cy": int(cy), "r": int(r)}
        return None
    if sym == "ic":
        for cc in dark_contours(gray, x, y, radius):
            if cc["w"] >= 30 and cc["h"] >= 25:
                if cc["x"] - 4 <= x <= cc["x"] + cc["w"] + 4 and \
                   cc["y"] - 4 <= y <= cc["y"] + cc["h"] + 4:
                    return {"kind": "rect", "x": cc["x"], "y": cc["y"],
                            "w": cc["w"], "h": cc["h"]}
        return None
    if sym == "cap":
        return detect_cap_body(gray, x, y, radius)
    if sym in ("res", "ind"):
        return detect_terminal_body(pb if pb is not None else gray, x, y)
    return None


def detect_cap_body(gray, x, y, radius=80, plate_len=(15, 90)):
    """电容本体: 两条平行板线质心 (本体, 非引出线)."""
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return None
    edges = cv2.Canny(sub, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 25, minLineLength=14, maxLineGap=3)
    if lines is None:
        return None
    hh, vv = [], []
    for l in np.asarray(lines).reshape(-1, 4):
        a1, b1, a2, b2 = l
        L = abs(a2 - a1) if abs(a2 - a1) >= abs(b2 - b1) else abs(b2 - b1)
        if L < plate_len[0] or L > plate_len[1]:
            continue
        if abs(a2 - a1) >= abs(b2 - b1):
            hh.append((a1, b1, a2, b2, L))
        else:
            vv.append((a1, b1, a2, b2, L))
    for grp, axis in [(hh, "h"), (vv, "v")]:
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                a, b = grp[i], grp[j]
                if abs(a[4] - b[4]) > a[4] * 0.5:
                    continue
                gap = abs(a[1] - b[1]) if axis == "h" else abs(a[0] - b[0])
                if 8 <= gap <= 45:
                    cx = (a[0] + a[2] + b[0] + b[2]) / 4 + x - radius
                    cy = (a[1] + b[1]) / 2 + y - radius
                    return {"kind": "cap", "cx": int(cx), "cy": int(cy),
                            "gap": int(gap), "len": int(a[4])}
    return None


def detect_terminal_body(pb, x, y, radius=100, min_wire=50):
    """电阻/电感本体: 黑线断口 = 端点, 中心 = 断口中点 (2 端器件)."""
    sub = pb[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return None
    edges = cv2.Canny(sub, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 30, minLineLength=min_wire, maxLineGap=5)
    if lines is None:
        return None
    horiz, vert = [], []
    for l in np.asarray(lines).reshape(-1, 4):
        a1, b1, a2, b2 = l
        L = abs(a2 - a1) if abs(a2 - a1) >= abs(b2 - b1) else abs(b2 - b1)
        if L < min_wire:
            continue
        if abs(a2 - a1) >= abs(b2 - b1):
            horiz.append((b1, min(a1, a2), max(a1, a2), L))
        else:
            vert.append((a1, min(b1, b2), max(b1, b2), L))
    for y1, x0, x1, _ in horiz:
        for y2, x2, x3, _ in horiz:
            if abs(y1 - y2) > 8:
                continue
            if x1 < x2 and (x2 - x1) > 15:
                return {"kind": "line", "cx": int((x1 + x2) / 2) + x - radius,
                        "cy": int(y1) + y - radius}
            if x3 < x0 and (x0 - x3) > 15:
                return {"kind": "line", "cx": int((x3 + x0) / 2) + x - radius,
                        "cy": int(y1) + y - radius}
    for x1, y0, y1, _ in vert:
        for x2, y2, y3, _ in vert:
            if abs(x1 - x2) > 8:
                continue
            if y1 < y2 and (y2 - y1) > 15:
                return {"kind": "line", "cx": int(x1) + x - radius,
                        "cy": int((y1 + y2) / 2) + y - radius}
            if y3 < y0 and (y0 - y3) > 15:
                return {"kind": "line", "cx": int(x1) + x - radius,
                        "cy": int((y3 + y0) / 2) + y - radius}
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--db", required=True, help="sch_components.json (读写, 加 symbol_body)")
    ap.add_argument("--radius", type=int, default=80)
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    pb = pure_black_mask(img, gray)
    db = json.load(open(args.db))

    n_found = 0
    for c in db["components"]:
        if c.get("membership") != "flow_through" or not c.get("refdes"):
            continue
        sym = type_from_refdes(c["refdes"])
        body = detect_body(gray, pb, c["symbol_pos"][0], c["symbol_pos"][1], sym, args.radius)
        c["symbol_type"] = sym
        c["symbol_body"] = body
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from common import boundary_from_body
        c["sym_boundary"] = boundary_from_body(body)
        if body:
            n_found += 1
    tmp = args.db + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    import os
    os.replace(tmp, args.db)
    print(f"[sch_symbol] flow_through bodies detected: {n_found}")


if __name__ == "__main__":
    main()