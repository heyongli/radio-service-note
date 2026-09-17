#!/usr/bin/env python3
"""tools/sch_wire/sch_wire.py — 原理图走线识别 (独立模块)

purpose: 识别原理图黑色走线 (traces) 与连接点 (junction 圆点):
          - 纯黑图层提取走线 (去绿线干扰)
          - 连接圆点检测 (小黑圆 = 交叉/连接点)
          - 骨架化走线 → 走线网络
        元件引出线应**对齐走线** (黑线), 连接点决定交叉.
        与 sch_symbol 独立发展, 用无监督方法逐步提高准确度.

用法:
  python3 sch_wire.py --img sch.png [--region x,y,r] [--out wires.json]
"""

import argparse
import sys

import cv2
import numpy as np


def pure_black(img, gray=None, dark_th=150):
    """纯黑图层: 暗像素去掉绿线."""
    if gray is None:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b, g, r = cv2.split(img.astype(int))
    green = ((g > 120) & (r < 110) & (b < 110)).astype(np.uint8)
    return ((gray < dark_th) & (1 - green)).astype(np.uint8) * 255


def detect_junction_dots(gray, x, y, radius=100, rmin=2, rmax=8):
    """检测连接圆点 (小黑圆 = 走线交叉/连接点)."""
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return []
    cs = cv2.HoughCircles(sub, cv2.HOUGH_GRADIENT, dp=1.2, minDist=8,
                          param1=50, param2=20, minRadius=rmin, maxRadius=rmax)
    dots = []
    if cs is not None:
        for cx, cy, r in np.rint(cs[0]).astype(int):
            dots.append({"x": int(cx) + x - radius, "y": int(cy) + y - radius, "r": int(r)})
    return dots


def zhang_suen_thin(bin_img):
    """Zhang-Suen 细化 → 走线骨架."""
    img = bin_img.copy() // 255
    prev = np.zeros_like(img)
    while True:
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


def skeletonize_wires(pb, x, y, radius=200):
    """走线骨架化: 返回区域内的骨架 (0/255)."""
    sub = pb[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return None
    return zhang_suen_thin(sub)


def wire_graph(sk):
    """从骨架提取走线端点/交叉点 (度 1 = 端点, 度 3+ = 交叉/连接)."""
    H, W = sk.shape
    nbr = [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]
    nodes = []
    for y in range(H):
        for x in range(W):
            if not sk[y, x]:
                continue
            deg = sum(1 for dx, dy in nbr
                      if 0 <= x+dx < W and 0 <= y+dy < H and sk[y+dy, x+dx])
            if deg == 1 or deg >= 3:
                nodes.append({"x": x, "y": y, "deg": int(deg)})
    return nodes


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--x", type=int, default=2500, help="关注区域中心 x")
    ap.add_argument("--y", type=int, default=2500, help="关注区域中心 y")
    ap.add_argument("--radius", type=int, default=300, help="区域半径")
    ap.add_argument("--out", help="输出 wires.json")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    pb = pure_black(img, gray)
    dots = detect_junction_dots(gray, args.x, args.y, args.radius)
    sk = skeletonize_wires(pb, args.x, args.y, args.radius)
    nodes = wire_graph(sk) if sk is not None else []

    print(f"[sch_wire] junction dots: {len(dots)}")
    for d in dots[:15]:
        print(f"  dot @({d['x']},{d['y']}) r={d['r']}")
    print(f"[sch_wire] wire nodes: {len(nodes)} "
          f"(endpoints+juncts in {2*args.radius}x{2*args.radius})")
    ends = [n for n in nodes if n["deg"] == 1]
    juncts = [n for n in nodes if n["deg"] >= 3]
    print(f"  endpoints={len(ends)} junctions={len(juncts)}")

    if args.out:
        import json, os
        data = {"junction_dots": dots,
                "wire_nodes": nodes,
                "region": [args.x - args.radius, args.y - args.radius,
                           args.x + args.radius, args.y + args.radius]}
        json.dump(data, open(args.out, "w"), indent=1)
        print(f"[sch_wire] saved: {args.out}")


if __name__ == "__main__":
    main()