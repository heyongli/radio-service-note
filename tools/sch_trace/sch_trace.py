#!/usr/bin/env python3
"""tools/sch_trace/sch_trace.py — 层1a 沿绿线走线 + 局部符号探测

purpose: 沿绿线 flow 走线 (跟随拐弯), 在绿线路径上局部探测符号 (电容/三极管/IC),
        只识别**绿线上的元器件** (无需全板识别). 写 sch_components.json 的符号候选.
format: Python 3 + OpenCV
version: 0.1 (2026-09-16)

用法:
  python3 sch_trace.py --img render/rxtx-sch-600-1.png \
      --color green --seed 626,1480 --db sch_components.json

与 sch_label_ocr / sch_verify / sch_render 经 sch_components.json 交互:
  trace(走线) → label_ocr(读标号) → verify(鉴别) → render(渲染)
"""

import argparse
import json
import sys
from collections import deque

import cv2
import numpy as np


def color_mask(img, color, g_th=120, r_th=110, b_th=110):
    b, g, r = cv2.split(img.astype(int))
    if color == "green":
        return ((g > g_th) & (r < r_th) & (b < b_th)).astype(np.uint8)
    if color == "red":
        return ((r > g_th) & (g < r_th) & (b < b_th)).astype(np.uint8)
    if color == "cyan":
        return ((g > g_th) & (b > g_th) & (r < r_th)).astype(np.uint8)
    if color == "yellow":
        return ((r > g_th) & (g > g_th) & (b < r_th)).astype(np.uint8)
    raise ValueError(color)


def trace_green_path(green, seed):
    """沿绿线 BFS 走线 (跟随拐弯), 返回 flow 上的绿像素路径."""
    H, W = green.shape
    dist = np.full((H, W), -1, dtype=np.int32)
    sx, sy = seed
    if green[sy, sx] == 0:
        ys, xs = np.where(green > 0)
        if len(xs) == 0:
            return dist
        d = (ys - sy) ** 2 + (xs - sx) ** 2
        i = int(np.argmin(d))
        sx, sy = int(xs[i]), int(ys[i])
    q = deque([(sx, sy)])
    dist[sy, sx] = 0
    while q:
        x, y = q.popleft()
        d = dist[y, x]
        for dx, dy in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and green[ny, nx] and dist[ny, nx] < 0:
                dist[ny, nx] = d + 1
                q.append((nx, ny))
    return dist


def detect_caps(gray, cap_gap=(8, 40), plate_len=(15, 90)):
    """检测所有电容符号 (-| |-)."""
    H, W = gray.shape
    edges = cv2.Canny(gray, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 30, minLineLength=int(plate_len[0]), maxLineGap=3)
    horiz, vert = [], []
    if lines is not None:
        for l in np.asarray(lines).reshape(-1, 4):
            a1, b1, a2, b2 = l
            L = abs(a2 - a1) if abs(a2 - a1) >= abs(b2 - b1) else abs(b2 - b1)
            if L < plate_len[0] or L > plate_len[1]:
                continue
            if abs(a2 - a1) >= abs(b2 - b1):
                horiz.append((a1, b1, a2, b2, L))
            else:
                vert.append((a1, b1, a2, b2, L))
    caps = []
    for grp, axis in [(horiz, "h"), (vert, "v")]:
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                a, b = grp[i], grp[j]
                if abs(a[4] - b[4]) > max(6, a[4] * 0.5):
                    continue
                if axis == "h":
                    gap = abs(a[1] - b[1])
                    xg0, xg1 = max(a[0], b[0]), min(a[2], b[2])
                    yg = int((a[1] + b[1]) / 2)
                    if xg1 <= xg0:
                        continue
                    gap_sub = gray[yg - 2:yg + 3, xg0:xg1]
                    wl = min(max(0, xg0 - 10), W - 1)
                    wr = min(xg1 + 10, W - 1)
                    left = (gray[max(0, a[1] - 8):a[1] + 9, wl:min(xg0, W)] < 150).sum() > 3 or \
                           (gray[max(0, b[1] - 8):b[1] + 9, wl:min(xg0, W)] < 150).sum() > 3
                    right = (gray[max(0, a[1] - 8):a[1] + 9, xg1:wr] < 150).sum() > 3 or \
                            (gray[max(0, b[1] - 8):b[1] + 9, xg1:wr] < 150).sum() > 3
                    cx = (a[0] + a[2] + b[0] + b[2]) / 4
                    cy = (a[1] + b[1]) / 2
                else:
                    gap = abs(a[0] - b[0])
                    yg0, yg1 = max(a[1], b[1]), min(a[3], b[3])
                    xg = int((a[0] + b[0]) / 2)
                    if yg1 <= yg0:
                        continue
                    gap_sub = gray[yg0:yg1, xg - 2:xg + 3]
                    wt = max(0, yg0 - 10)
                    wb = min(yg1 + 10, H - 1)
                    left = (gray[wt:min(yg0, H), max(0, a[0] - 8):a[0] + 9] < 150).sum() > 3 or \
                           (gray[wt:min(yg0, H), max(0, b[0] - 8):b[0] + 9] < 150).sum() > 3
                    right = (gray[yg1:wb, max(0, a[0] - 8):a[0] + 9] < 150).sum() > 3 or \
                            (gray[yg1:wb, max(0, b[0] - 8):b[0] + 9] < 150).sum() > 3
                    cx = (a[0] + b[0]) / 2
                    cy = (a[1] + a[3] + b[1] + b[3]) / 4
                if not (cap_gap[0] <= gap <= cap_gap[1]):
                    continue
                if (gap_sub < 140).sum() > gap_sub.size * 0.15:
                    continue
                if not (left and right):
                    continue
                caps.append({"x": round(cx), "y": round(cy), "w": a[4], "h": gap + 6})
    uniq = []
    for c in caps:
        if not any(abs(u["x"] - c["x"]) < 15 and abs(u["y"] - c["y"]) < 15 for u in uniq):
            uniq.append(c)
    return uniq


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--color", default="green", choices=["green", "red", "cyan", "yellow"])
    ap.add_argument("--seed", required=True, help="起点 x,y")
    ap.add_argument("--db", required=True, help="sch_components.json 输出 (symbols 候选)")
    # 可调参数 (有效值沉淀为知识, best_practices)
    ap.add_argument("--cap-gap", type=str, default="8,40", help="电容极间距范围 (px)")
    ap.add_argument("--plate-len", type=str, default="15,90", help="电容板长范围 (px)")
    ap.add_argument("--circle-area", type=str, default="600,60000", help="三极管圆面积范围")
    ap.add_argument("--ic-area", type=str, default="4000,250000", help="IC 矩形面积范围")
    ap.add_argument("--touch-r", type=int, default=30, help="符号触点绿线判定半径")
    args = ap.parse_args()

    cap_gap = tuple(int(v) for v in args.cap_gap.split(","))
    plate_len = tuple(int(v) for v in args.plate_len.split(","))
    circle_area = tuple(int(v) for v in args.circle_area.split(","))
    ic_area = tuple(int(v) for v in args.ic_area.split(","))

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = color_mask(img, args.color)
    sx, sy = (int(v) for v in args.seed.split(","))
    # 绿线被器件断开成多段; 沿整条绿线网络走 (全绿 = 可达), 器件在断口处
    reach = mask > 0
    print(f"[sch_trace] green flow: {reach.sum()} px (seed {sx},{sy})")

    # 只沿绿线路径 (BFS 距离场) 局部探测符号
    caps = detect_caps(gray, cap_gap, plate_len)
    symbols = []
    for c in caps:
        if reach[max(0, c["y"] - args.touch_r):c["y"] + args.touch_r, max(0, c["x"] - args.touch_r):c["x"] + args.touch_r].sum() > 0:
            symbols.append({"x": int(c["x"]), "y": int(c["y"]), "w": int(c["w"]),
                            "h": int(c["h"]), "sym": "cap"})
    # 圆 (三极管) + IC, 触点绿线路径者
    _, th = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY_INV)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        a = cv2.contourArea(c)
        if a < circle_area[0] or a > circle_area[1]:
            continue
        per = cv2.arcLength(c, True)
        if per <= 0 or 4 * np.pi * a / (per * per) < 0.8:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if min(w, h) / max(1, max(w, h)) < 0.6:
            continue
        cx, cy = x + w // 2, y + h // 2
        if reach[max(0, cy - args.touch_r):cy + args.touch_r, max(0, cx - args.touch_r):cx + args.touch_r].sum() > 0:
            symbols.append({"x": int(cx), "y": int(cy), "sym": "circle"})
    _, th2 = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY_INV)
    th2 = cv2.morphologyEx(th2, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts2, _ = cv2.findContours(th2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts2:
        a = cv2.contourArea(c)
        if a < ic_area[0] or a > ic_area[1]:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if not (60 <= max(w, h) <= 500):
            continue
        per = cv2.arcLength(c, True)
        if per and len(cv2.approxPolyDP(c, 0.04 * per, True)) == 4 and a / (w * h) > 0.55:
            cx, cy = x + w // 2, y + h // 2
            if reach[max(0, cy - args.touch_r):cy + args.touch_r, max(0, cx - args.touch_r):cx + args.touch_r].sum() > 0:
                symbols.append({"x": int(cx), "y": int(cy), "sym": "ic"})

    db = {"_meta": {"purpose": "sch components (trace: green-flow symbols)",
                    "source": "sch_trace (green line walk + symbol detect)"},
          "symbols": symbols}
    with open(args.db, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    print(f"[sch_trace] saved: {args.db} ({len(symbols)} symbols on green flow)")


if __name__ == "__main__":
    main()