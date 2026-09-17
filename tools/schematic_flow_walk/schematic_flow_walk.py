#!/usr/bin/env python3
"""tools/schematic_flow_walk/schematic_flow_walk.py - 原理图信号流走线

purpose: 从原理图渲染图识别信号流彩线 (RX=绿, TX=红, 控制=黄, common=青),
        像流水一样沿彩线 flooding 走线 (跟随拐弯), 在断口处识别元器件,
        排出流经元器件链序, 生成 chain_order_rx.json / chain_order_tx.json
format: Python 3 + OpenCV + numpy + rapidocr
version: 0.2 (2026-09-16)

方法:
  1. 颜色掩膜: 绿 g>120,r<110,b<110; 红 r>120,g<110,b<110; 黄; 青
  2. BFS 距离场从 seed 沿彩线 flooding (天然跟随拐弯)
  3. 前沿断口 = 元器件 (绿线经过元器件断开; 空心箭头排除; 几像素断层 flood 弥合)
  4. 断口 gap = 元器件尺度, 6-8x 裁切, OCR 识别 refdes
  5. 按 BFS 距离排序 → 流经元器件链序

用法:
  python3 schematic_flow_walk.py --img render/rxtx-sch-600-1.png \
      --color green --seed 626,1480 --refdes refdes.json --out chain_order_rx.json
"""

import argparse
import json
import re
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
    raise ValueError(f"color must be green|red|cyan|yellow, got {color}")


def bfs_dist_from_seed(mask, seed):
    H, W = mask.shape
    dist = np.full((H, W), -1, dtype=np.int32)
    sx, sy = seed
    if mask[sy, sx] == 0:
        ys, xs = np.where(mask > 0)
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
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < W and 0 <= ny < H and mask[ny, nx] and dist[ny, nx] < 0:
                dist[ny, nx] = d + 1
                q.append((nx, ny))
    return dist


def refdes_distance(dist, x, y, radius=60):
    H, W = dist.shape
    x0, x1 = max(0, x - radius), min(W, x + radius)
    y0, y1 = max(0, y - radius), min(H, y + radius)
    sub = dist[y0:y1, x0:x1]
    pos = np.where(sub >= 0)
    if len(pos[0]) == 0:
        return None
    return int(sub[pos[0], pos[1]].min())


def line_width(mask):
    H, W = mask.shape
    runs = []
    for x in range(W):
        col = mask[:, x]
        start = None
        for y in range(H):
            if col[y]:
                if start is None:
                    start = y
            elif start is not None:
                runs.append(y - start)
                start = None
        if start is not None:
            runs.append(H - start)
    if not runs:
        return 0
    return int(np.median(runs))


def is_hollow_arrow(gray, x, y, r=30):
    """断口处是否为空心箭头 (非元器件).

    判据 (用户): flood 处箭头是**封闭边框** (空心三角轮廓)。
    检测: 局部暗色轮廓 = 封闭空心形状 (轮廓近似少角点 + 填充率低), 即箭头。
    """
    H, W = gray.shape
    x0, x1 = max(0, x - r), min(W, x + r)
    y0, y1 = max(0, y - r), min(H, y + r)
    sub = gray[y0:y1, x0:x1]
    dark = (sub < 150).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(dark, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 80 or a > 9000:
            continue
        per = cv2.arcLength(c, True)
        if per <= 0:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if min(w, h) / max(1, max(w, h)) < 0.3:
            continue
        approx = cv2.approxPolyDP(c, 0.03 * per, True)
        # 封闭空心轮廓: 少角点 (三角/四边形) + 填充率低 (边框) + 面积不算太小
        if len(approx) <= 5 and a / (w * h) < 0.55:
            return True
    return False


def zhang_suen_thin(bin_img):
    """Zhang-Suen 细化 → 单像素骨架."""
    img = bin_img.copy() // 255
    prev = np.zeros_like(img)
    while True:
        # 步骤1
        mask = np.zeros_like(img)
        for y in range(1, img.shape[0] - 1):
            for x in range(1, img.shape[1] - 1):
                if not img[y, x]:
                    continue
                p = [img[y-1,x],img[y-1,x+1],img[y,x+1],img[y+1,x+1],
                     img[y+1,x],img[y+1,x-1],img[y,x-1],img[y-1,x-1]]
                b = sum(p)
                a = sum((not p[i]) and p[(i+1)%8] for i in range(8))
                if 2 <= b <= 6 and a == 1 and p[0]*p[2]*p[4] == 0 and p[2]*p[4]*p[6] == 0:
                    mask[y, x] = 1
        img[mask > 0] = 0
        # 步骤2
        mask = np.zeros_like(img)
        for y in range(1, img.shape[0] - 1):
            for x in range(1, img.shape[1] - 1):
                if not img[y, x]:
                    continue
                p = [img[y-1,x],img[y-1,x+1],img[y,x+1],img[y+1,x+1],
                     img[y+1,x],img[y+1,x-1],img[y,x-1],img[y-1,x-1]]
                b = sum(p)
                a = sum((not p[i]) and p[(i+1)%8] for i in range(8))
                if 2 <= b <= 6 and a == 1 and p[0]*p[2]*p[6] == 0 and p[0]*p[4]*p[6] == 0:
                    mask[y, x] = 1
        img[mask > 0] = 0
        if np.array_equal(img, prev):
            break
        prev = img.copy()
    return (img * 255).astype(np.uint8)


def flood_walk_breaks(green, seed, gray=None, max_gap=260, min_gap=8,
                      close_k=3, skip_arrow=True, max_iter=200, black=None):
    """绿线断口 = 元器件位置 (骨架端点 + 绿/黑双线追踪).

    域特征 (ICOM/Yaesu):
      - 绿线沿黑线走; 器件处绿线断但黑线连续 → 沿未断黑线前进
      - 断口 = 绿线离开黑线处
      - 小黑圆点 = 交叉点, 沿有绿覆盖的黑线走
    """
    if black is None and gray is not None:
        black = ((gray < 150) & (green == 0)).astype(np.uint8)
    if close_k > 1:
        green = cv2.morphologyEx(green, cv2.MORPH_CLOSE,
                                 np.ones((close_k, close_k), np.uint8))
    lw = line_width(green)
    H, W = green.shape
    sk = zhang_suen_thin((green > 0).astype(np.uint8) * 255)
    sk = sk // 255
    ys, xs = np.where(sk > 0)
    if len(xs) == 0:
        return []
    # 端点 = 骨架像素 8 邻域只有 1 个骨架邻居
    breaks = []
    nbr = [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]
    for y, x in zip(ys, xs):
        deg = sum(1 for dx, dy in nbr
                  if 0 <= x+dx < W and 0 <= y+dy < H and sk[y+dy, x+dx])
        if deg != 1:
            continue
        # 沿线方向: 端点 → 前一骨架像素 → 方向向量
        prev = None
        for dx, dy in nbr:
            if 0 <= x+dx < W and 0 <= y+dy < H and sk[y+dy, x+dx]:
                prev = (x - dx, y - dy)
                ddx, ddy = dx, dy
                break
        if prev is None:
            continue
        # 绿/黑双线探测: 沿方向走, 绿断但黑线连续则穿过器件, 绿复现 = 断口
        gstop = None     # 绿线停止处
        gresume = None   # 绿线复现处
        for g in range(1, max_gap + 1):
            hit_green = False
            hit_black = False
            for off in range(-4, 5):
                nx = x + ddx * g + ddy * off
                ny = y + ddy * g + ddx * off
                if not (0 <= nx < W and 0 <= ny < H):
                    continue
                if sk[ny, nx]:
                    break
                if green[ny, nx]:
                    hit_green = True
                    gresume = (nx, ny, g)
                elif black is not None and black[ny, nx]:
                    hit_black = True
            if hit_green:
                break
            if hit_black:
                if gstop is None:
                    gstop = g
                continue  # 黑线连续, 穿过器件继续
            # 白区: 若已过黑线段后仍白, 停
            if gstop is not None:
                break
        if gresume is None or gstop is None:
            continue
        gap = gresume[2] - gstop
        if gap < min_gap:
            continue
        fx, fy = gresume[0], gresume[1]
        bx, by = round(x + ddx * (gstop + gap // 2)), round(y + ddy * (gstop + gap // 2))
        if gray is not None and skip_arrow and is_hollow_arrow(gray, bx, by):
            continue
        if gray is not None and not gap_has_symbol(gray, x, y, fx, fy, lw):
            continue
        breaks.append({"x": bx, "y": by, "gap": gap,
                       "xin": x, "yin": y, "xout": fx, "yout": fy})
    # 去重
    uniq = []
    for b in breaks:
        dup = False
        for u in uniq:
            if abs(u["x"] - b["x"]) < 20 and abs(u["y"] - b["y"]) < 20:
                if b["gap"] < u["gap"]:
                    u["gap"] = b["gap"]
                dup = True
                break
        if not dup:
            uniq.append(b)
    return uniq
    # BFS 遍历图
    if seed_comp == 0:
        return []
    breaks = []
    visited = {seed_comp}
    from collections import deque
    q = deque([seed_comp])
    while q:
        c = q.popleft()
        for e in adj.get(c, []):
            if e["to"] in visited:
                continue
            visited.add(e["to"])
            breaks.append({"x": e["x"], "y": e["y"], "gap": e["gap"],
                           "from": c, "to": e["to"]})
            q.append(e["to"])
    return breaks


def detect_symbol_near(gray, cx, cy, want, radius):
    """在 OCR refdes 文字附近局部检测最相关元器件符号."""
    H, W = gray.shape
    x0, x1 = max(0, cx - radius), min(W, cx + radius)
    y0, y1 = max(0, cy - radius), min(H, cy + radius)
    sub = gray[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    if want == "circle":
        _, th = cv2.threshold(sub, 170, 255, cv2.THRESH_BINARY_INV)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        cnts, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in cnts:
            a = cv2.contourArea(c)
            if a < 400 or a > 6000:
                continue
            per = cv2.arcLength(c, True)
            if per <= 0 or 4 * np.pi * a / (per * per) < 0.85:
                continue
            bx, by, w, h = cv2.boundingRect(c)
            if min(w, h) / max(1, max(w, h)) < 0.6:
                continue
            d = abs(bx + w / 2 - radius) + abs(by + h / 2 - radius)
            if best is None or d < best[0]:
                best = (d, bx + w // 2 + x0, by + h // 2 + y0)
        return {"x": best[1], "y": best[2], "sym": "circle"} if best else None
    if want == "cap":
        edges = cv2.Canny(sub, 60, 160)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 30, minLineLength=20, maxLineGap=3)
        hh, vv = [], []
        if lines is not None:
            for l in np.asarray(lines).reshape(-1, 4):
                a1, b1, a2, b2 = l
                if abs(a2 - a1) >= abs(b2 - b1) and abs(a2 - a1) >= 20:
                    hh.append((a1, b1, a2, b2, abs(a2 - a1)))
                elif abs(b2 - b1) >= 20:
                    vv.append((a1, b1, a2, b2, abs(b2 - b1)))
        for grp, axis in [(hh, "h"), (vv, "v")]:
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    a, b = grp[i], grp[j]
                    if abs(a[4] - b[4]) > a[4] * 0.5:
                        continue
                    if axis == "h":
                        gap = abs(a[1] - b[1])
                        ov = min(a[2], b[2]) - max(a[0], b[0])
                    else:
                        gap = abs(a[0] - b[0])
                        ov = min(a[3], b[3]) - max(a[1], b[1])
                    if 10 <= gap <= 40 and ov > 10:
                        return {"x": cx, "y": cy, "sym": "cap"}
        return None
    if want == "ic":
        _, th = cv2.threshold(sub, 160, 255, cv2.THRESH_BINARY_INV)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in cnts:
            a = cv2.contourArea(c)
            if a < 800 or a > 50000:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if not (35 <= max(w, h) <= 400 and 0.2 < min(w, h) / max(1, max(w, h)) < 5):
                continue
            per = cv2.arcLength(c, True)
            if per and len(cv2.approxPolyDP(c, 0.04 * per, True)) == 4 and a / (w * h) > 0.55:
                d = abs(x + w / 2 - radius) + abs(y + h / 2 - radius)
                if best is None or d < best[0]:
                    best = (d, x + w // 2 + x0, y + h // 2 + y0)
        return {"x": best[1], "y": best[2], "sym": "ic"} if best else None
    if want == "res":
        _, th = cv2.threshold(sub, 160, 255, cv2.THRESH_BINARY_INV)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in cnts:
            a = cv2.contourArea(c)
            if a < 600 or a > 9000:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if min(w, h) / max(1, max(w, h)) < 0.2:
                continue
            d = abs(x + w / 2 - radius) + abs(y + h / 2 - radius)
            if best is None or d < best[0]:
                best = (d, x + w // 2 + x0, y + h // 2 + y0)
        return {"x": best[1], "y": best[2], "sym": "res"} if best else None
    return None


def sample_components(img, gray, green, seed, ocr=None, scale_max=8):
    """从绿线断口采样元器件: 入/出端点距离=尺度, 6-8x 裁切, OCR 识别 refdes."""
    from rapidocr_onnxruntime import RapidOCR
    if ocr is None:
        ocr = RapidOCR()
    breaks = flood_walk_breaks(green, seed, gray)
    H, W = gray.shape
    out = []
    for br in breaks:
        x, y = br["x"], br["y"]
        # 入/出端点给出器件包围框 (flow 方向尺寸 = gap, 垂直方向估 2x)
        gw = br.get("gap", 40)
        gh = gw * 2
        sz = max(100, min(gw * scale_max, 700))
        r = sz // 2
        sub = img[max(0, y - r):y + r, max(0, x - r):x + r]
        if sub.size == 0:
            continue
        sub2 = cv2.resize(sub, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        res, _ = ocr(sub2)
        refs = []
        if res:
            for t in res:
                txt = t[1].strip()
                if re.match(r"^(IC|Q|F|FI|D|J|C|R|L|X|U|TR|Z)\s*\d+", txt, re.I):
                    refs.append((txt.upper().replace(" ", ""), float(t[2])))
        if br["gap"] > 100:
            typ = "ic"
        elif br["gap"] > 60:
            typ = "mid"
        else:
            typ = "small"
        out.append({"x": x, "y": y, "gap": br["gap"], "sz": sz,
                    "xin": br.get("xin"), "yin": br.get("yin"),
                    "xout": br.get("xout"), "yout": br.get("yout"),
                    "refdes": refs[0][0] if refs else None,
                    "score": refs[0][1] if refs else 0,
                    "type": typ})
    return out


def detect_caps_in_flow(gray, green, lw, cap_gap=(8, 40), plate_len=(15, 90)):
    """检测绿线 flow 上的电容符号 (-| |- 双短线 + 两侧接线).

    绿线经过电容基本连续 (只变细), 无完整断口 → 需检测电容符号本身:
      1. Hough 线找短平行线段对 (板), 两板间空 + 两侧各有接线 (-| |-)
      2. 板的接线连到绿线 (附近有绿) → 该电容在 flow 上

    返回 list: {x, y, w, h}
    """
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
                    # 两侧接线: 窗口采样 (板行 ±8)
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
                # 板间空
                if (gap_sub < 140).sum() > gap_sub.size * 0.15:
                    continue
                # 两侧接线
                if not (left and right):
                    continue
                # 接线连到绿线: 板附近有绿
                ci, cj = round(cx), round(cy)
                if green[max(0, cj - 15):cj + 15, max(0, ci - 15):ci + 15].sum() > 0:
                    caps.append({"x": ci, "y": cj, "w": a[4], "h": gap + 6})
    # 去重
    uniq = []
    for c in caps:
        if not any(abs(u["x"] - c["x"]) < 15 and abs(u["y"] - c["y"]) < 15 for u in uniq):
            uniq.append(c)
    return uniq


def gap_has_symbol(gray, xin, yin, xout, yout, lw=7, min_thick=None):
    """断口 gap 内是否有真实器件符号 (非细走线).

    用户洞察:
      - 细黑走线横穿绿线 (宽度 < 绿线 1/5, 沿法向小范围截图到图边沿) → 忽略
      - 真实器件 (电容板/圆/IC 框) 厚度 ≥ 绿线一部分
    判定: gap 内暗色特征最大**厚度** ≥ 绿线 1/5 才算器件.
    """
    if min_thick is None:
        min_thick = max(2, lw // 5 + 1)
    H, W = gray.shape
    # 取 gap 中段区域, 看暗色特征最大厚度
    cx = (xin + xout) // 2
    cy = (yin + yout) // 2
    r = max(abs(xout - xin), abs(yout - yin)) // 2 + 8
    x0, x1 = max(0, cx - r), min(W, cx + r)
    y0, y1 = max(0, cy - r), min(H, cy + r)
    sub = gray[y0:y1, x0:x1]
    dark = (sub < 150).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    max_thick = 0
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 20:
            continue
        x, y, w, h = cv2.boundingRect(c)
        # 特征厚度 = 短边 (沿垂直方向的截面宽)
        thick = min(w, h)
        max_thick = max(max_thick, thick)
    return max_thick >= min_thick


def recognize_components(gray, refdes_json=None, ocr=None):
    """层1 识别: OCR 全量 refdes + 符号检测 → 组件集.

    独立于绿线 (任何原理图可用). 输出标号→符号关联:
    {refdes, text_pos, symbol_pos, symbol_type}
    """
    from rapidocr_onnxruntime import RapidOCR
    if ocr is None:
        ocr = RapidOCR()
    H, W = gray.shape
    # OCR 全量 refdes
    refs = {}
    if refdes_json:
        data = json.load(open(refdes_json))
        if isinstance(data, dict):
            for k, v in data.items():
                refs.setdefault(k, (round(v[0]), round(v[1])))
        else:
            for r in data:
                refs.setdefault(r["refdes"], (r["x"], r["y"]))
    else:
        tile, overlap = 900, 150
        for y0 in range(0, H, tile - overlap):
            for x0 in range(0, W, tile - overlap):
                sub = gray[y0:min(y0 + tile, H), x0:min(x0 + tile, W)]
                res, _ = ocr(sub)
                if not res:
                    continue
                for t in res:
                    txt = t[1].strip()
                    if re.match(r"^(IC|Q|F|FI|D|J|C|R|L|X|U|TR|Z)\s*\d+", txt, re.I):
                        bx = t[0]
                        cx = (bx[0][0] + bx[2][0]) / 2 + x0
                        cy = (bx[0][1] + bx[2][1]) / 2 + y0
                        refs.setdefault(txt.upper().replace(" ", ""), (round(cx), round(cy)))
    # 符号检测 (独立于绿线): 全局电容 + 圆 + IC
    syms = [dict(c, sym="cap") for c in detect_caps(gray)]
    _, th = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY_INV)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 600 or a > 60000:
            continue
        per = cv2.arcLength(c, True)
        if per <= 0 or 4 * np.pi * a / (per * per) < 0.8:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if min(w, h) / max(1, max(w, h)) < 0.6:
            continue
        syms.append({"x": x + w // 2, "y": y + h // 2, "sym": "circle"})
    _, th2 = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY_INV)
    th2 = cv2.morphologyEx(th2, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts2, _ = cv2.findContours(th2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts2:
        a = cv2.contourArea(c)
        if a < 4000 or a > 250000:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if not (60 <= max(w, h) <= 500):
            continue
        per = cv2.arcLength(c, True)
        if per and len(cv2.approxPolyDP(c, 0.04 * per, True)) == 4 and a / (w * h) > 0.55:
            syms.append({"x": x + w // 2, "y": y + h // 2, "sym": "ic"})
    # 关联: refdes → 最近符号
    PREFIX = {"Q": "circle", "TR": "circle", "C": "cap", "IC": "ic",
              "U": "ic", "FI": "ic", "F": "ic", "L": "circle", "R": "cap"}
    out = []
    for rd, (rx, ry) in refs.items():
        prefix = "".join(ch for ch in rd if ch.isalpha()).upper()
        best = None
        for s in syms:
            d = abs(s["x"] - rx) + abs(s["y"] - ry)
            if d > 150:
                continue
            score = d
            if PREFIX.get(prefix) == s["sym"]:
                score -= 60
            if best is None or score < best[0]:
                best = (score, d, s)
        if best is None:
            cand = detect_symbol_near(gray, rx, ry, PREFIX.get(prefix, "cap"), 100)
            if cand is None:
                for alt in ["ic", "circle", "cap"]:
                    cand = detect_symbol_near(gray, rx, ry, alt, 100)
                    if cand:
                        break
            if cand is None:
                continue
            sx, sy = cand["x"], cand["y"]
            out.append({"refdes": rd, "text_pos": [rx, ry],
                        "symbol_pos": [sx, sy], "symbol_type": cand["sym"],
                        "text_symbol_dist": abs(sx - rx) + abs(sy - ry)})
            continue
        score, d0, s = best
        out.append({"refdes": rd, "text_pos": [rx, ry],
                    "symbol_pos": [s["x"], s["y"]], "symbol_type": s["sym"],
                    "text_symbol_dist": d0})
    return out


def detect_caps(gray, cap_gap=(8, 40), plate_len=(15, 90)):
    """检测所有电容符号 (-| |-), 独立于绿线."""
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


def verify_green_membership(components, green, band=14):
    """层2 鉴别: 是否属于绿线 flow → 给每个组件加 membership.

    判定:
      - none: 符号不触点绿线 (不是流经)
      - branch: 触点绿线但只有单侧 (支路/死端)
      - flow_through: 绿线两侧共线通过 (主路, 绿线真正流过)

    返回 components 每个加: {green_touch, green_sides, flow_dir, membership}
    """
    H, W = green.shape
    out = []
    for c in components:
        sx, sy = c["symbol_pos"]
        touch = green[max(0, sy - 25):sy + 25, max(0, sx - 25):sx + 25].sum() > 0
        if not touch:
            c["membership"] = "none"
            c["green_sides"] = []
            out.append(c)
            continue
        sides = []
        if green[max(0, sy - band):sy + band, min(sx + 70, W - 1):min(sx + 30, W - 1)].sum() > 0 or \
           green[max(0, sy - band):sy + band, min(sx + 30, W - 1):min(sx + 40, W - 1)].sum() > 0:
            pass
        # 侧边绿 (沿流向 ±30~70px)
        e = green[max(0, sy - band):sy + band, min(sx + 30, W - 1):min(sx + 70, W - 1)].sum() > 0
        w = green[max(0, sy - band):sy + band, max(0, sx - 70):max(0, sx - 30)].sum() > 0
        n = green[max(0, sy - 70):max(0, sy - 30), max(0, sx - band):sx + band].sum() > 0
        s = green[min(sy + 30, H - 1):min(sy + 70, H - 1), max(0, sx - band):sx + band].sum() > 0
        if e: sides.append("E")
        if w: sides.append("W")
        if n: sides.append("N")
        if s: sides.append("S")
        if (e and w) or (n and s):
            c["membership"] = "flow_through"
            c["flow_dir"] = "H" if (e and w) else "V"
        elif len(sides) >= 1:
            c["membership"] = "branch"
        else:
            c["membership"] = "none"
        c["green_sides"] = sides
        out.append(c)
    return out


def render_sch_flow(img, green, components, out_png, show_membership=True):
    """层3 渲染: 识别+鉴别结果渲染到 sch (独立渲染层).

    绿线高亮; 组件: flow_through=黄, branch=蓝, none=灰; 标号→符号连线.
    """
    H, W = img.shape[:2]
    overlay = img.copy()
    overlay[green > 0] = [0, 255, 0]
    color_map = {"flow_through": (0, 255, 255), "branch": (255, 0, 0), "none": (128, 128, 128)}
    for c in components:
        tx, ty = c["text_pos"]
        sx, sy = c["symbol_pos"]
        m = c.get("membership", "none")
        color = color_map.get(m, (128, 128, 128))
        cv2.line(overlay, (tx, ty), (sx, sy), (0, 0, 255), 1)
        cv2.circle(overlay, (tx, ty), 12, color, 2)
        cv2.circle(overlay, (sx, sy), 6, (0, 0, 255), -1)
        cv2.putText(overlay, c["refdes"], (tx - 20, ty - 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.imwrite(out_png, overlay)
    return out_png


def detect_flow_components(gray, green, lw=7, ocr=None, refdes_json=None):
    """综合探测绿线流经元器件.

    组合方法:
      1. OCR 全量 refdes (label_ocr 思路, 网格 tile) → 位置集
      2. 符号检测: 电容(-| |-), 三极管(圆), IC(矩形) — 触点绿线者
      3. 关联: 每个 refdes 关联最近的绿线触点符号 (类型匹配)
      4. 符号触点绿线 = 在 flow 上 → 流经元器件
    """
    from rapidocr_onnxruntime import RapidOCR
    if ocr is None:
        ocr = RapidOCR()
    H, W = gray.shape
    # 1) OCR 全量 refdes
    refs = {}
    if refdes_json:
        data = json.load(open(refdes_json))
        if isinstance(data, dict):  # {refdes: [x,y,...]}
            for k, v in data.items():
                refs.setdefault(k, (round(v[0]), round(v[1])))
        else:  # [{refdes,x,y}]
            for r in data:
                refs.setdefault(r["refdes"], (r["x"], r["y"]))
    else:
        tile = 900
        overlap = 150
        for y0 in range(0, H, tile - overlap):
            for x0 in range(0, W, tile - overlap):
                sub = gray[y0:min(y0 + tile, H), x0:min(x0 + tile, W)]
                res, _ = ocr(sub)
                if not res:
                    continue
                for t in res:
                    txt = t[1].strip()
                    if re.match(r"^(IC|Q|F|FI|D|J|C|R|L|X|U|TR|Z)\s*\d+", txt, re.I):
                        bx = t[0]
                        cx = (bx[0][0] + bx[2][0]) / 2 + x0
                        cy = (bx[0][1] + bx[2][1]) / 2 + y0
                        key = txt.upper().replace(" ", "")
                        refs.setdefault(key, (round(cx), round(cy)))
    # 2) 符号检测 (触点绿线)
    syms = [dict(c, sym="cap") for c in detect_caps_in_flow(gray, green, lw)]
    # 三极管圆
    _, th = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY_INV)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 600 or a > 60000:
            continue
        per = cv2.arcLength(c, True)
        if per <= 0 or 4 * np.pi * a / (per * per) < 0.8:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if min(w, h) / max(1, max(w, h)) < 0.6:
            continue
        cx, cy = x + w // 2, y + h // 2
        if green[max(0, cy - 20):cy + 20, max(0, cx - 20):cx + 20].sum() > 0:
            syms.append({"x": cx, "y": cy, "sym": "circle"})
    # IC 矩形 (触点绿线)
    _, th2 = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY_INV)
    th2 = cv2.morphologyEx(th2, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts2, _ = cv2.findContours(th2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts2:
        a = cv2.contourArea(c)
        if a < 4000 or a > 250000:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if not (60 <= max(w, h) <= 500):
            continue
        per = cv2.arcLength(c, True)
        if per and len(cv2.approxPolyDP(c, 0.04 * per, True)) == 4 and a / (w * h) > 0.55:
            cx, cy = x + w // 2, y + h // 2
            if green[max(0, cy - 60):cy + 60, max(0, cx - 60):cx + 60].sum() > 0:
                syms.append({"x": cx, "y": cy, "sym": "ic"})
    # 电感弧链 (触点绿线) — detect_inductors 待恢复
    # 3) 关联: refdes → 最近符号 (全局集, 距离 150, 类型加分)
    PREFIX = {"Q": "circle", "TR": "circle", "C": "cap", "IC": "ic",
              "U": "ic", "FI": "ic", "F": "ic", "L": "circle", "R": "cap"}
    out = []
    for rd, (rx, ry) in refs.items():
        prefix = "".join(ch for ch in rd if ch.isalpha()).upper()
        best = None
        for s in syms:
            d = abs(s["x"] - rx) + abs(s["y"] - ry)
            if d > 150:
                continue
            score = d
            if PREFIX.get(prefix) == s["sym"]:
                score -= 60
            if best is None or score < best[0]:
                best = (score, d, s)
        if best is not None:
            score, d0, s = best
            out.append({"x": round(rx), "y": round(ry), "sym": s["sym"],
                        "refdes": rd, "sym_d": d0, "sym_at": (s["x"], s["y"])})
            continue
        # 回退: 逐 refdes 局部符号检测 + 绿触点
        want = PREFIX.get(prefix, "cap")
        cand = detect_symbol_near(gray, rx, ry, want, 100)
        if cand is None:
            for alt in ["ic", "circle", "cap"]:
                cand = detect_symbol_near(gray, rx, ry, alt, 100)
                if cand:
                    break
        if cand is None:
            continue
        sx, sy = cand["x"], cand["y"]
        if green[max(0, sy - 25):sy + 25, max(0, sx - 25):sx + 25].sum() == 0:
            continue
        out.append({"x": round(rx), "y": round(ry), "sym": cand["sym"],
                    "refdes": rd, "sym_d": abs(sx - rx) + abs(sy - ry),
                    "sym_at": (sx, sy)})
    # 去重 (同 refdes)
    seen = set()
    uniq = []
    for c in out:
        if c["refdes"] in seen:
            continue
        seen.add(c["refdes"])
        uniq.append(c)
    return uniq


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True, help="原理图渲染图")
    ap.add_argument("--dpi", type=int, default=600, help="原理图 dpi (默认 600)")
    ap.add_argument("--color", default="green", choices=["green", "red", "cyan", "yellow"])
    ap.add_argument("--seed", required=True, help="起点位置 x,y (如 ANT)")
    ap.add_argument("--refdes", help="refdes 位置 JSON (可选, 层1 识别输入)")
    ap.add_argument("--db", help="输出 sch_components.json (层1+层2 结果数据库)")
    ap.add_argument("--out", help="输出渲染 PNG (层3)")
    ap.add_argument("--chain", help="输出 chain_order JSON (flow_through 有序链)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    mask = color_mask(img, args.color)
    print(f"[walk] {args.color} mask: {(mask > 0).sum()} px ({np.mean(mask)*100:.2f}%)")
    lw = line_width(mask)
    print(f"[walk] line width: {lw} px")

    # 层1 识别
    comps = recognize_components(gray, args.refdes)
    print(f"[l1 recognize] components: {len(comps)}")
    # 层2 鉴别 (绿线)
    comps = verify_green_membership(comps, mask)
    ft = [c for c in comps if c["membership"] == "flow_through"]
    br = [c for c in comps if c["membership"] == "branch"]
    print(f"[l2 verify] flow_through={len(ft)} branch={len(br)} none={len(comps)-len(ft)-len(br)}")

    # 数据库输出
    if args.db:
        sx, sy = (int(v) for v in args.seed.split(","))
        dist = bfs_dist_from_seed(mask, (sx, sy))
        for c in comps:
            c["walk_d"] = refdes_distance(dist, c["symbol_pos"][0], c["symbol_pos"][1],
                                          max(60, lw * 4))
        db = {"_meta": {"purpose": f"sch components ({args.color} flow)",
                        "view": f"sch_{args.dpi}dpi",
                        "source": "schematic_flow_walk (recognize+verify)"},
              "components": comps}
        with open(args.db, "w") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        print(f"[db] saved: {args.db}")

    # 层3 渲染
    if args.out:
        render_sch_flow(img, mask, comps, args.out)
        print(f"[l3 render] saved: {args.out}")

    # chain_order (flow_through 有序)
    if args.chain:
        ft_sorted = sorted(ft, key=lambda c: (c.get("walk_d") is None,
                                       c.get("walk_d") if c.get("walk_d") is not None else 1e9))
        chain = []
        for i, c in enumerate(ft_sorted):
            chain.append({"idx": i + 1, "refdes": c["refdes"],
                          "sch_px": c["symbol_pos"], "symbol_type": c["symbol_type"],
                          "walk_d": c.get("walk_d"),
                          "status": "confirmed" if c["membership"] == "flow_through" else "unverified"})
        out = {"version": "1.0",
               "description": f"schematic {args.color} flow chain (layered)",
               "source": "schematic_flow_walk recognize+verify",
               "chain": chain}
        with open(args.chain, "w") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"[chain] saved: {args.chain} ({len(chain)} flow_through)")

    # 打印 flow_through
    for c in ft:
        print(f"  {c['refdes']:6s} sym={c['symbol_type']:6s} sides={c['green_sides']} d={c.get('walk_d')}")


if __name__ == "__main__":
    main()