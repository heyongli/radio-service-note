#!/usr/bin/env python3
"""tools/annotate_svg_flow/route_on_traces.py — 沿铜箔布线路径
purpose: 沿 bot view 铜箔自动连线, 找电气连通
format: Python 3 + OpenCV
version: 0.2.2 (2026-09-15)
consumers: 网络连通性分析"""

"""沿 PCB bot 视图铜箔线稿路由信号流 polyline.

bot 视图(9-4)是线稿: 白底255 / 板区灰204 / 铜箔线深色(~32).
本工具提取深色线为可通行网络, 用 Dijkstra 在两锚点间找"顺铜箔"路径,
Douglas-Peucker 简化后输出 through 点(300dpi), 供 annotate_svg_flow 的
waypoints JSON 使用(不臆造: 找不到低代价铜箔路径时回退正交折线并标记).

用法:
  python3 route_on_traces.py --img /tmp/opencode/bot600-1.png \
      --chain nettable/wpts_bot.json --out nettable/wpts_bot_routed.json
  # 或单段测试:
  python3 route_on_traces.py --img bot600.png --from 1034,1589 --to 1034,1686
"""
import argparse
import heapq
import json
import os

import cv2
import numpy as np


def load_trace_net(img_path, dark_thr=120, board_val=204, dilate=3):
    """提取铜箔线 mask(600dpi). 返回 (mask, scale_to_300)."""
    g = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    assert g is not None, f"cannot read {img_path}"
    h, w = g.shape
    mask = (g < dark_thr).astype(np.uint8)
    # 仅板内: 灰底或深色区域(排除白背景) — 用大邻域判断非白
    nonwhite = cv2.blur((g < 245).astype(np.uint8), (101, 101)) > 0.25
    mask = (mask & nonwhite).astype(np.uint8)
    if dilate:
        k = np.ones((dilate, dilate), np.uint8)
        mask = cv2.dilate(mask, k)
    return mask, w / 2.0  # 假定600dpi输入, px300 = px600/2


def dijkstra(mask, src, dst, off_cost=40.0, max_expand=None):
    """8邻域 Dijkstra. mask[y,x]=1 可行(代价1), 0 代价 off_cost.
    src/dst: (y,x) in mask 坐标. 返回点列 [(y,x),...] 或 None."""
    h, w = mask.shape
    if not (0 <= src[0] < h and 0 <= src[1] < w and 0 <= dst[0] < h and 0 <= dst[1] < w):
        return None
    INF = float("inf")
    dist = np.full((h, w), INF, np.float32)
    prev = np.full((h, w, 2), -1, np.int32)
    sy, sx = src
    dy, dx = dst
    dist[sy, sx] = 0.0
    pq = [(0.0, sy, sx)]
    D8 = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
          (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]
    n = 0
    while pq:
        d, y, x = heapq.heappop(pq)
        if d > dist[y, x]:
            continue
        if (y, x) == (dy, dx):
            break
        n += 1
        if max_expand and n > max_expand:
            return None
        for oy, ox, c in D8:
            ny, nx = y + oy, x + ox
            if 0 <= ny < h and 0 <= nx < w:
                step = c if mask[ny, nx] else c * off_cost
                nd = d + step
                if nd < dist[ny, nx]:
                    dist[ny, nx] = nd
                    prev[ny, nx] = (y, x)
                    heapq.heappush(pq, (nd, ny, nx))
    if dist[dy, dx] == INF:
        return None
    pts = []
    y, x = dy, dx
    while (y, x) != (sy, sx):
        pts.append((y, x))
        py, px = prev[y, x]
        if py < 0:
            return None
        y, x = py, px
    pts.append((sy, sx))
    pts.reverse()
    return pts


def simplify(pts, eps=6.0):
    """Douglas-Peucker."""
    if len(pts) < 3:
        return pts
    x0, y0 = pts[0]
    x1, y1 = pts[-1]
    best, bi = -1.0, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        if x1 == x0 and y1 == y0:
            d = ((x - x0) ** 2 + (y - y0) ** 2) ** 0.5
        else:
            t = max(0.0, min(1.0, ((x - x0) * (x1 - x0) + (y - y0) * (y1 - y0))
                             / ((x1 - x0) ** 2 + (y1 - y0) ** 2)))
            px, py = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
            d = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
        if d > best:
            best, bi = d, i
    if best > eps:
        left = simplify(pts[:bi + 1], eps)
        right = simplify(pts[bi:], eps)
        return left[:-1] + right
    return [pts[0], pts[-1]]


def route_pair(mask, p0, p1, off_cost=40.0, snap_r=25):
    """p0,p1: (x,y)@300dpi. 先吸附到最近铜箔, Dijkstra, 返回 (through@300, on_trace_ratio)."""
    f = 2.0  # 300→600
    def snap(px, py):
        x, y = int(px * f), int(py * f)
        if mask[y, x]:
            return y, x
        r = snap_r * 2
        ys = np.arange(max(0, y - r), min(mask.shape[0], y + r))
        xs = np.arange(max(0, x - r), min(mask.shape[1], x + r))
        if not len(ys) or not len(xs):
            return y, x
        sub = mask[np.ix_(ys, xs)]
        if not sub.any():
            return y, x
        ys_i, xs_i = np.where(sub)
        d2 = (ys_i + ys[0] - y) ** 2 + (xs_i + xs[0] - x) ** 2
        i = int(np.argmin(d2))
        return int(ys_i[i] + ys[0]), int(xs_i[i] + xs[0])
    s = snap(*p0)
    t = snap(*p1)
    pts = dijkstra(mask, s, t, off_cost=off_cost)
    if not pts:
        return None, 0.0
    on = sum(1 for y, x in pts if mask[y, x]) / len(pts)
    thr = simplify(pts, eps=12.0)
    return [(round(x / f, 1), round(y / f, 1)) for y, x in thr], on


def ortho_fallback(p0, p1):
    """正交回退: L形(先长边). (x,y)@300dpi."""
    x0, y0 = p0
    x1, y1 = p1
    if abs(x1 - x0) >= abs(y1 - y0):
        return [(x1, y0)], 0.0
    return [(x0, y1)], 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True, help="bot 600dpi 渲染 PNG")
    ap.add_argument("--chain", help="waypoints JSON (列表, 依序连线的条目)")
    ap.add_argument("--out", help="输出 routed JSON")
    ap.add_argument("--from", dest="frm", help="单段: x,y (300dpi)")
    ap.add_argument("--to", dest="to", help="单段: x,y (300dpi)")
    ap.add_argument("--off-cost", type=float, default=40.0)
    ap.add_argument("--min-on-trace", type=float, default=0.5,
                    help="铜箔占比低于此值回退正交折线")
    args = ap.parse_args()

    mask, _ = load_trace_net(args.img)
    print(f"trace mask: {mask.shape}, trace px {mask.sum()}")

    if args.frm and args.to:
        p0 = tuple(float(v) for v in args.frm.split(","))
        p1 = tuple(float(v) for v in args.to.split(","))
        thr, on = route_pair(mask, p0, p1, args.off_cost)
        print(f"on-trace ratio: {on:.2f}")
        print(f"through: {thr}")
        return

    if not args.chain:
        ap.error("need --chain or --from/--to")
    data = json.load(open(args.chain))
    entries = data if isinstance(data, list) else data.get("entries", [])
    out = []
    for i, e in enumerate(entries):
        e = dict(e)
        if i + 1 < len(entries):
            p0 = tuple(e["px"])
            p1 = tuple(entries[i + 1]["px"])
            thr, on = route_pair(mask, p0, p1, args.off_cost)
            if thr and on >= args.min_on_trace:
                e["through"] = thr
                e["note"] = (e.get("note", "") + f" trace{on:.0%}").strip()
            else:
                fb, _ = ortho_fallback(p0, p1)
                e["through"] = e.get("through") or fb
                e["note"] = (e.get("note", "") + " ortho-fallback").strip()
        out.append(e)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    json.dump(out, open(args.out, "w"), indent=1, ensure_ascii=False)
    print(f"-> {args.out} ({len(out)} entries)")


if __name__ == "__main__":
    main()
