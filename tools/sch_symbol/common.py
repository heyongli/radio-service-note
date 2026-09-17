#!/usr/bin/env python3
"""tools/sch_symbol/common.py — sch_symbol 共享工具 (各类型识别程序共用)."""

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


# ---------- 基础设施: 圆/方块/线 提取 (供各类符号识别复用) ----------

def find_circles(gray, x, y, radius=80, rmin=10, rmax=40, circ_min=0.6):
    """提取 (x,y) 附近的圆 (Hough + 黑边轮廓圆度). 供三极管等圆符号用."""
    circles = hough_circles(gray, x, y, radius, rmin, rmax)
    for cc in dark_contours(gray, x, y, radius):
        if cc["circ"] > circ_min and cc["w"] >= 14 and cc["h"] >= 14:
            cx, cy = cc["x"] + cc["w"] / 2, cc["y"] + cc["h"] / 2
            r = max(cc["w"], cc["h"]) / 2
            if not any(abs(c["cx"] - cx) < 10 and abs(c["cy"] - cy) < 10 for c in circles):
                circles.append({"cx": int(cx), "cy": int(cy), "r": int(r)})
    return circles


def find_rects(gray, x, y, radius=100, min_w=30, min_h=25):
    """提取 (x,y) 附近的方块 (黑边空心矩形). 供 IC 等方块符号用."""
    return [cc for cc in dark_contours(gray, x, y, radius)
            if cc["w"] >= min_w and cc["h"] >= min_h]


def find_lines(pb_or_gray, x, y, radius=100, min_wire=40, pair_gap=15):
    """提取 (x,y) 附近的走线断口 (2 端器件端点定位). 返回两段线对的中断位置.

    pb_or_gray: 纯黑图层 (去绿线) 或灰度图. 断口 = 符号, 中点 = 中心.
    """
    src = pb_or_gray
    sub = src[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return []
    edges = cv2.Canny(sub, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 30, minLineLength=min_wire, maxLineGap=5)
    if lines is None:
        return []
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
    gaps = []
    for y1, x0, x1, _ in horiz:
        for y2, x2, x3, _ in horiz:
            if abs(y1 - y2) > 8:
                continue
            if x1 < x2 and (x2 - x1) > pair_gap:
                gaps.append({"cx": int((x1 + x2) / 2) + x - radius, "cy": int(y1) + y - radius})
            if x3 < x0 and (x0 - x3) > pair_gap:
                gaps.append({"cx": int((x3 + x0) / 2) + x - radius, "cy": int(y1) + y - radius})
    for x1, y0, y1, _ in vert:
        for x2, y2, y3, _ in vert:
            if abs(x1 - x2) > 8:
                continue
            if y1 < y2 and (y2 - y1) > pair_gap:
                gaps.append({"cx": int(x1) + x - radius, "cy": int((y1 + y2) / 2) + y - radius})
            if y3 < y0 and (y0 - y3) > pair_gap:
                gaps.append({"cx": int(x1) + x - radius, "cy": int((y3 + y0) / 2) + y - radius})
    return gaps


def find_cap_pairs(gray, x, y, radius=80, plate_len=(10, 40), gap_range=(8, 30)):
    """提取电容双板线对 (两平行短线 = 板线, 与走线垂直). 返回质心.

    走线水平时板线垂直 (vv), 走线垂直时板线水平 (hh).
    板线 = 短线 (10-40), 间距 = 板间距 (8-30).
    """
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return []
    edges = cv2.Canny(sub, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 25, minLineLength=8, maxLineGap=3)
    if lines is None:
        return []
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
    out = []
    # 水平走线电容: 板线垂直 (vv), 两板水平间距 = gap
    for i in range(len(vv)):
        for j in range(i + 1, len(vv)):
            a, b = vv[i], vv[j]
            if abs(a[4] - b[4]) > max(5, a[4] * 0.5):
                continue
            ov = min(a[3], b[3]) - max(a[1], b[1])  # 垂直重叠
            if ov < 5:
                continue
            gap = abs(a[0] - b[0])
            if gap_range[0] <= gap <= gap_range[1]:
                cx = (a[0] + b[0]) / 2 + x - radius
                cy = (a[1] + a[3] + b[1] + b[3]) / 4 + y - radius
                out.append({"cx": int(cx), "cy": int(cy), "gap": int(gap),
                            "len": int(a[4]), "dir": "h"})
    # 垂直走线电容: 板线水平 (hh), 两板垂直间距 = gap
    for i in range(len(hh)):
        for j in range(i + 1, len(hh)):
            a, b = hh[i], hh[j]
            if abs(a[4] - b[4]) > max(5, a[4] * 0.5):
                continue
            ov = min(a[2], b[2]) - max(a[0], b[0])  # 水平重叠
            if ov < 5:
                continue
            gap = abs(a[1] - b[1])
            if gap_range[0] <= gap <= gap_range[1]:
                cx = (a[0] + a[2] + b[0] + b[2]) / 4 + x - radius
                cy = (a[1] + b[1]) / 2 + y - radius
                out.append({"cx": int(cx), "cy": int(cy), "gap": int(gap),
                            "len": int(a[4]), "dir": "v"})
    return out


def load_db(db_path):
    import json
    return json.load(open(db_path))


def save_db(db, db_path):
    import json, os
    tmp = db_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    os.replace(tmp, db_path)


# ---------- 符号尺寸知识库 (从电路图学习的封装知识) ----------

def body_size(body):
    """从 symbol_body 提取尺寸 (w, h)."""
    if body is None:
        return None
    if body["kind"] == "circle":
        return (2 * body["r"], 2 * body["r"])
    if body["kind"] == "rect":
        return (body["w"], body["h"])
    if body["kind"] == "cap":
        return (body.get("len", 0), body.get("gap", 0))
    if body["kind"] == "line":
        return None  # 线本体尺寸意义不大, 用断口 gap
    if body["kind"] == "diode":
        return (body.get("w", 0), body.get("h", 0))
    return None


def update_sizes_db(sizes_path, sym, size, refdes=None):
    """记录一个已确认符号的尺寸到知识库. sizes_path 持久化 JSON."""
    import json, os
    db = {}
    if os.path.exists(sizes_path):
        db = json.load(open(sizes_path))
    db.setdefault(sym, []).append({
        "size": list(size), "refdes": refdes,
    })
    tmp = sizes_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    os.replace(tmp, sizes_path)
    return db


def typical_size(sizes_path, sym):
    """该类型符号的典型尺寸 (中位宽/高)."""
    import json, os, numpy as np
    if not os.path.exists(sizes_path):
        return None
    db = json.load(open(sizes_path))
    if sym not in db or not db[sym]:
        return None
    sizes = [s["size"] for s in db[sym] if s["size"]]
    if not sizes:
        return None
    arr = np.array(sizes)
    return (float(np.median(arr[:, 0])), float(np.median(arr[:, 1])))


def check_size(size, typical, tol=0.6):
    """校验尺寸是否在典型范围内 (印证封装知识). 返回 ok 或偏差比."""
    if size is None or typical is None:
        return None
    w, h = size
    tw, th = typical
    if tw == 0 or th == 0:
        return None
    rw = w / tw
    rh = h / th
    if (1 - tol) <= rw <= (1 + tol) and (1 - tol) <= rh <= (1 + tol):
        return True
    return max(abs(1 - rw), abs(1 - rh))