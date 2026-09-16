"""
route_flow.py -- Signal flow auto-router with label avoidance

功能: 根据组件坐标和连接关系, 自动规划横平竖直的信号流路径
      路由时避开元器件标号文字区域, 避免走线覆盖文字
格式: 输入 JSON (connections + components), 输出 wpts JSON
版本: 0.3
用途: 替代手写 waypoints, 算法探索最少交叉+避文字路径

用法:
  python3 route_flow.py --config config.json --out wpts.json
  python3 route_flow.py --config config.json --out wpts.json --out-png preview.png --pcb pcb-top-600-1.png
"""

import json
import argparse
import sys

BOARD_CX = 3375
LABEL_MARGIN = 60  # px padding around label keep-out zone

def load_config(path):
    with open(path) as f:
        return json.load(f)

def to_top_view(c):
    if c.get("view", "top") == "bot":
        tx = BOARD_CX + (BOARD_CX - c["x"])
        return (tx, c["y"])
    return (c["x"], c["y"])

# ---------- label keep-out zones ----------

def label_keepout(name, c, fs=36):
    """Return keep-out rectangle (x1,y1,x2,y2) for the label of a component.
    Based on lpos convention: label is placed relative to the component center.
    """
    x, y = c["x"], c["y"]
    lpos = c.get("lpos", "ur")
    # Estimate label size: width ~ len(name)*fs*0.6, height ~ fs
    lw = len(name) * fs * 0.6 + LABEL_MARGIN
    lh = fs + LABEL_MARGIN

    if lpos == "u":
        return (x - lw/2, y - lh - 10, x + lw/2, y - 10)
    elif lpos == "d":
        return (x - lw/2, y + 10, x + lw/2, y + lh + 10)
    elif lpos == "l":
        return (x - lw - 10, y - lh/2, x - 10, y + lh/2)
    elif lpos == "r":
        return (x + 10, y - lh/2, x + lw + 10, y + lh/2)
    elif lpos == "ul":
        return (x - lw - 10, y - lh - 10, x - 10, y - 10)
    elif lpos == "ur":
        return (x + 10, y - lh - 10, x + lw + 10, y - 10)
    elif lpos == "dl":
        return (x - lw - 10, y + 10, x - 10, y + lh + 10)
    elif lpos == "dr":
        return (x + 10, y + 10, x + lw + 10, y + lh + 10)
    # Default: above-right
    return (x + 10, y - lh - 10, x + lw + 10, y - 10)

# ---------- geometry ----------

def manhattan_routes(p1, p2, n=8):
    x1, y1 = p1
    x2, y2 = p2
    routes = []
    if x1 == x2 or y1 == y2:
        routes.append([p1, p2])
        return routes
    routes.append([p1, (x1, y2), p2])
    routes.append([p1, (x2, y1), p2])
    for dy in [-400, -200, -100, 100, 200, 400]:
        mid_y = y1 + dy
        routes.append([p1, (x1, mid_y), (x2, mid_y), p2])
    return routes[:n]

def segments(route):
    return [(route[i], route[i+1]) for i in range(len(route) - 1)]

def seg_cross(s1, s2):
    (ax, ay), (bx, by) = s1
    (cx, cy), (dx, dy) = s2
    if ay == by and cx == dx:
        xmin, xmax = min(ax, bx), max(ax, bx)
        ymin, ymax = min(cy, dy), max(cy, dy)
        if xmin < cx < xmax and ymin < ay < ymax:
            return (cx, ay)
    elif ax == bx and cy == dy:
        xmin, xmax = min(ax, bx), max(ax, bx)
        ymin, ymax = min(cy, dy), max(cy, dy)
        if ymin < cy < ymax and xmin < ax < xmax:
            return (ax, cy)
    return None

def seg_in_rect(seg, rect):
    """Check if any part of an axis-aligned segment lies inside a rectangle."""
    (ax, ay), (bx, by) = seg
    x1, y1, x2, y2 = rect
    if ay == by:  # horizontal segment
        sy = ay
        if y1 < sy < y2:
            sx_min, sx_max = min(ax, bx), max(ax, bx)
            if sx_max > x1 and sx_min < x2:
                return True
    elif ax == bx:  # vertical segment
        sx = ax
        if x1 < sx < x2:
            sy_min, sy_max = min(ay, by), max(ay, by)
            if sy_max > y1 and sy_min < y2:
                return True
    return False

def count_crossings(route, existing_routes):
    segs = segments(route)
    count = 0
    for er in existing_routes:
        for es in segments(er):
            for s in segs:
                if seg_cross(s, es):
                    count += 1
    return count

def count_label_hits(route, keepouts):
    """Count how many segments pass through label keep-out zones."""
    segs = segments(route)
    count = 0
    for s in segs:
        for rect in keepouts:
            if seg_in_rect(s, rect):
                count += 1
    return count

# ---------- routing ----------

def route_all(components, connections):
    coords = {name: to_top_view(c) for name, c in components.items()}

    # Build keep-out zones (in top-view coords)
    keepouts = []
    for name, c in components.items():
        tc = dict(c)
        if c.get("view") == "bot":
            tc["x"] = BOARD_CX + (BOARD_CX - c["x"])
        fs = c.get("fs", 36)
        keepouts.append(label_keepout(name, tc, fs))

    # Separate top-only vs cross-side
    top_only = []
    cross_side = []
    for fr, to in connections:
        fr_bot = components[fr].get("view", "top") == "bot"
        to_bot = components[to].get("view", "top") == "bot"
        if fr_bot or to_bot:
            cross_side.append((fr, to))
        else:
            top_only.append((fr, to))

    results = []
    routed = []

    for fr, to in top_only + cross_side:
        p1, p2 = coords[fr], coords[to]
        cands = manhattan_routes(p1, p2)
        is_cross = components[fr].get("view") == "bot" or components[to].get("view") == "bot"

        # Score: crossings * 10 + label_hits * 5 (avoid labels strongly)
        def score(r):
            return count_crossings(r, routed) * 10 + count_label_hits(r, keepouts) * 5

        best = min(cands, key=score)
        results.append((fr, to, best, is_cross))
        routed.append(best)

    return results, coords

def build_wpts(results, coords, components):
    items = []
    items.append({
        "_meta": {
            "purpose": "Auto-routed RX flow waypoints v17 (label-aware)",
            "version": "17",
            "consumers": ["tools/render_rx_flow.py"],
            "view": "pcb_top_600dpi",
            "note": "Algorithm: minimize crossings + avoid label zones"
        }
    })

    for fr, to, route, is_cross in results:
        px = list(route[0])
        through = [list(p) for p in route[1:]]
        items.append({
            "layer": "rx",
            "kind": "line",
            "px": px,
            "through": through,
            "dash": is_cross,
            "label": "",
            "lpos": "d",
            "fs": 28,
            "dot": False
        })

    added = set()
    for fr, to, route, is_cross in results:
        for name in [fr, to]:
            if name in added:
                continue
            added.add(name)
            px = list(coords[name])
            mark = {
                "layer": "marks",
                "px": px,
                "label": name,
                "dot": False,
                "fs": 36,
                "lpos": "ur"
            }
            if is_cross and name == to:
                mark["mark_type"] = "via"
            items.append(mark)

    return items

def main():
    parser = argparse.ArgumentParser(description="Signal flow auto-router")
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--out-png")
    parser.add_argument("--pcb")
    args = parser.parse_args()

    cfg = load_config(args.config)
    results, coords = route_all(cfg["components"], cfg["connections"])

    wpts = build_wpts(results, coords, cfg["components"])

    with open(args.out, "w") as f:
        json.dump(wpts, f, indent=2, ensure_ascii=False)
    print(f"Wpts saved: {args.out} ({len(wpts)} items)")

    for fr, to, route, is_cross in results:
        tag = "DASH" if is_cross else "SOLID"
        cr = count_crossings(route, [])
        print(f"  {fr} -> {to} [{tag}] cross={cr}  {' -> '.join(str(p) for p in route)}")

    if args.out_png and args.pcb:
        import subprocess
        cmd = [
            sys.executable, "tools/render_rx_flow.py",
            "--pcb", args.pcb,
            "--wpts", args.out,
            "--skip-confirm-boxes",
            "--out-png", args.out_png
        ]
        subprocess.run(cmd, check=True)

if __name__ == "__main__":
    main()
