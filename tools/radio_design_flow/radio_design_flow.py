#!/usr/bin/env python3
"""tools/radio_design_flow/radio_design_flow.py - radio design 流经元器件图

purpose: 从 chain_order_*.json 生成信号流经元器件框图 (方块+箭头+角色),
        用于 radio-design.md 的可视化流经元器件图
format: Python 3 + svgwrite
version: 0.1 (2026-09-16)

用法:
  python3 radio_design_flow.py --chain chain_order_rx.json --out radio_rx_flow.svg
"""

import argparse
import json
import sys

import svgwrite


ROLE_COLOR = {
    "connector": "#888888",
    "filter": "#2E86AB",
    "amplifier": "#C0392B",
    "mixer": "#8E44AD",
    "detector": "#D35400",
    "oscillator": "#16A085",
    "": "#555555",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chain", required=True, help="chain_order_rx.json")
    ap.add_argument("--out", required=True, help="输出 SVG 框图")
    ap.add_argument("--title", default="RX Signal Flow", help="框图标题")
    args = ap.parse_args()

    co = json.load(open(args.chain))
    chain = co["chain"]

    BW, BH = 260, 84       # 方块尺寸
    GX, GY = 90, 60        # 间距
    cols = 2               # 分 2 列排布 (蛇形折返)
    rows = (len(chain) + cols - 1) // cols
    W = cols * (BW + GX) + GX
    H = rows * (BH + GY) + GY + 80

    dwg = svgwrite.Drawing(args.out, size=(W, H), profile="full")
    dwg.add(dwg.text(args.title, insert=(GX, 40),
                     font_size=26, font_weight="bold", fill="#222"))
    mkr = dwg.marker(id="arrow", insert=(10, 10), size=(20, 20), orient="auto")
    mkr.add(dwg.path("M0,0 L20,10 L0,20 z", fill="#666"))
    dwg.defs.add(mkr)

    for i, c in enumerate(chain):
        col = i % cols
        row = i // cols
        x = GX + col * (BW + GX)
        y = GY + 80 + row * (BH + GY)
        ref = c.get("refdes") or "-"
        name = c.get("name") or ref
        role = c.get("role") or ""
        color = ROLE_COLOR.get(c.get("type", ""), "#555555")
        st = c.get("status", "")

        g = dwg.g(id=f"flow-{i}")
        g.add(dwg.rect(insert=(x, y), size=(BW, BH), rx=8,
                       fill="#FFFFFF", stroke=color, stroke_width=3))
        g.add(dwg.text(f"[{i+1}] {ref}", insert=(x + 14, y + 30),
                       font_size=20, font_weight="bold", fill=color))
        g.add(dwg.text(name, insert=(x + 14, y + 56),
                       font_size=15, fill="#333"))
        if role:
            g.add(dwg.text(role, insert=(x + 14, y + BH - 10),
                           font_size=13, fill="#666"))
        if st == "unverified":
            g.add(dwg.text("(未验证)", insert=(x + BW - 60, y + BH - 10),
                           font_size=12, fill="#C00"))
        dwg.add(g)

        # 箭头
        if i < len(chain) - 1:
            ncol = (i + 1) % cols
            nrow = (i + 1) // cols
            nx = GX + ncol * (BW + GX)
            ny = GY + 80 + nrow * (BH + GY)
            if ncol == col:  # 同列向下
                x1, y1 = x + BW / 2, y + BH
                x2, y2 = nx + BW / 2, ny
            elif nrow == row:  # 向右
                x1, y1 = x + BW, y + BH / 2
                x2, y2 = nx, ny + BH / 2
            else:  # 折返: 先下再左
                x1, y1 = x + BW / 2, y + BH
                x2, y2 = nx + BW / 2, ny
            dwg.add(dwg.line(start=(x1, y1), end=(x2, y2),
                             stroke="#666", stroke_width=3,
                             marker_end="url(#arrow)"))
    dwg.save()
    print(f"[flow] saved: {args.out} ({W}x{H})")


if __name__ == "__main__":
    main()