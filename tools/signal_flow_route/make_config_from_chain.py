#!/usr/bin/env python3
"""tools/signal_flow_route/make_config_from_chain.py - 链序→路由 config 自动桥接

purpose: 从 chain_order_*.json (原理图链序) + components_index.json (PCB 位置)
        自动生成 signal_flow_route 的路由 config (rx_flow_config.json),
        实现 schematic_flow_walk → PCB 标注的完整自动化
format: Python 3
version: 0.1 (2026-09-16)

用法:
  python3 make_config_from_chain.py --chain chain_order_rx.json \
      --index components_index.json --out rx_flow_config.json \
      [--mirror-x 2530]
"""

import argparse
import json
import sys
from pathlib import Path


def pcb_position(refdes, index, mirror_x=None):
    """从 components_index 取 PCB 位置. 返回 (x, y, view) 或 None.
    index 里的 bot 视图坐标用 mirror_x 镜像到 top (渲染空间)."""
    info = index.get(refdes)
    if not info or not isinstance(info, dict):
        return None
    center = info.get("center")
    if not center:
        return None
    view = info.get("view", "top")
    x, y = center[0], center[1]
    if view == "bot" and mirror_x:
        x = 2 * mirror_x - x
    return (x, y, view)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chain", required=True, help="chain_order_rx.json (schematic_flow_walk 输出)")
    ap.add_argument("--index", required=True, help="components_index.json (pcb_px 缺失时回查)")
    ap.add_argument("--out", required=True, help="输出路由 config (rx_flow_config.json)")
    ap.add_argument("--mirror-x", type=float, default=None,
                    help="bot→top 镜像中心 x; 不指定则用板中心推算")
    args = ap.parse_args()

    chain = json.load(open(args.chain))
    index = json.load(open(args.index))

    if args.mirror_x is None:
        bb = None
        for v in index.values():
            if isinstance(v, dict) and v.get("tgt_board_bbox"):
                bb = v["tgt_board_bbox"]
                break
        if bb:
            args.mirror_x = (bb[0] + bb[2]) / 2
        else:
            args.mirror_x = 2550  # 5000 宽板近似中心

    components = {}
    connections = []
    missing = []
    order = []
    for c in chain["chain"]:
        rd = c["refdes"]
        if not rd:
            missing.append(rd)
            continue
        # 优先用 chain 内已回填的 pcb_px (固定格式 §3.1)
        pos = c.get("pcb_px")
        view = c.get("pcb_view", "top")
        if not pos:
            p2 = pcb_position(rd, index, args.mirror_x)
            if p2 is None:
                missing.append(rd)
                continue
            pos = (p2[0], p2[1])
            view = p2[2]
        components[rd] = {
            "x": round(pos[0]), "y": round(pos[1]), "view": view,
            "lpos": "ur", "fs": 36,
        }
        order.append(rd)
    for i in range(len(order) - 1):
        connections.append([order[i], order[i + 1]])

    cfg = {
        "meta": {
            "purpose": f"Auto-generated from {Path(args.chain).name}",
            "version": "auto",
            "consumers": ["tools/signal_flow_route/signal_flow_route.py"],
            "view": "pcb_top_600dpi",
        },
        "components": components,
        "connections": connections,
    }
    with open(args.out, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"[make_config] saved: {args.out}")
    print(f"[make_config] components: {len(components)}, connections: {len(connections)}")
    for rd in order:
        c = components[rd]
        print(f"  {rd:6s} @({c['x']},{c['y']}) {c['view']}")
    if missing:
        print(f"[make_config] missing: {missing}")


if __name__ == "__main__":
    main()