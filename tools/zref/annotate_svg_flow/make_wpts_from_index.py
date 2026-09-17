#!/usr/bin/env python3
"""tools/annotate_svg_flow/make_wpts_from_index.py — waypoints 生成器
purpose: 从 components_index + chain_order 自动派生 waypoints
format: Python 3 + JSON
version: 0.2.2 (2026-09-15)
consumers: wpts 派生"""

"""从 components_index + chain_order 生成 SVG 标注用的 waypoints JSON.

产出分层 waypoints(单一 JSON, 每条目带 layer 字段):
  rx    信号链连线(引脚级前的组件级连线, 箭头)
  marks 链上元件位号标签
  blocks 功能块标签(来自 rx_blocks 的相对坐标)
  tx    底图红色区域的 TX zone(色块掩膜提取, 虚线框=区域级推断)
  ctrl  底图黄/绿区域(电源/控制 zone)
  notes 链上缺位置的"not located"项(诚实标注, 不臆造坐标)

用法:
  python3 make_wpts_from_index.py --project projects/IC-2200H \
      --base-render projects/IC-2200H/render/rxtx300-1.png \
      --out projects/IC-2200H/nettable/wpts_rxtx_sch.json
"""
import argparse
import json
import os

import numpy as np
from PIL import Image


def chain_refs(chain, universe):
    import re

    out = []
    for i, elem in enumerate(chain):
        refs = [t for t in re.findall(r"[A-Z]{1,3}[0-9]{1,4}[A-Z]?", elem) if t in universe]
        out.append((i, elem, refs))
    return out


def color_zones(img, rmin, rmax, gmin, gmax, bmin, bmax, min_area, close, max_zones):
    """6 值 RGB 区间掩膜 → 闭运算 → 连通域 → 面积过滤 → 前 N 大 zone."""
    import cv2

    a = np.asarray(img).astype(int)
    m = ((a[:, :, 0] >= rmin) & (a[:, :, 0] <= rmax) & (a[:, :, 1] >= gmin)
         & (a[:, :, 1] <= gmax) & (a[:, :, 2] >= bmin) & (a[:, :, 2] <= bmax)).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (close, close))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    zones = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if area >= min_area:
            zones.append((area, [int(x), int(y), int(w), int(h)]))
    zones.sort(reverse=True)
    return [z for _, z in zones[:max_zones]]


def parse6(spec):
    v = [int(x) for x in spec.split(",")]
    if len(v) != 6:
        raise SystemExit(f"颜色区间须6值 rmin,rmax,gmin,gmax,bmin,bmax: {spec}")
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--base-render", help="原理图渲染图(提tx/ctrl色块用)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--view", default="schematic", help="使用的坐标视图(默认 schematic)")
    ap.add_argument("--tx-color", default="150,255,0,110,0,200",
                    help="TX 掩膜 6值区间 rmin,rmax,gmin,gmax,bmin,bmax "
                         "(本页红系深红 RGB~[236,4,142])")
    ap.add_argument("--ctrl-color", default="200,255,180,255,0,140",
                    help="ctrl 黄掩膜 6值区间(本页黄像素几乎为零, 通常空结果)")
    ap.add_argument("--zone-min-area", type=int, default=6000)
    ap.add_argument("--zone-close", type=int, default=15)
    ap.add_argument("--max-zones", type=int, default=10)
    ap.add_argument("--zone-max-frac", type=float, default=0.3,
                    help="zone bbox 面积超过页面此比例则丢弃(整页连通的大blob无区域意义)")
    ap.add_argument("--notes-x", type=int, default=40, help="not-located 罗列起始 x")
    args = ap.parse_args()

    nt_dir = os.path.join(args.project, "nettable")
    idx = json.load(open(os.path.join(nt_dir, "components_index.json")))
    nt = json.load(open(os.path.join(nt_dir, "top_pcb.json")))
    chain = nt["chain_order_schematic"]

    wpts = []

    def schpx(ref):
        v = idx["components"].get(ref, {}).get("views", {}).get(args.view)
        return v["px"] if v else None

    # rx 链: 连续有坐标的组件之间画箭头连线
    # 多位置元件(alts)按链序路径启发式选点: 使 prev→pick→next 总长最短
    raw = []
    for i, elem, refs in chain_refs(chain, set(idx["components"])):
        for r in refs:
            v = idx["components"].get(r, {}).get("views", {}).get(args.view)
            if v:
                raw.append((i, r, v["px"], v.get("alts") or [v["px"]], elem))
    seq = []
    for j, (i, r, px, alts, elem) in enumerate(raw):
        if len(alts) == 1:
            seq.append((i, r, px, elem))
            continue
        prev = seq[-1][2] if seq else None
        nxt = None
        for k in range(j + 1, len(raw)):
            if raw[k][0] != i or raw[k][1] != r:
                nxt = raw[k][2]
                break
        def cost(p):
            c = 0
            if prev:
                c += abs(p[0] - prev[0]) + abs(p[1] - prev[1])
            if nxt:
                c += abs(p[0] - nxt[0]) + abs(p[1] - nxt[1])
            return c
        pick = min(alts, key=cost)
        seq.append((i, r, list(pick), elem))
    for j in range(1, len(seq)):
        (i0, r0, p0, e0), (i1, r1, p1, e1) = seq[j - 1], seq[j]
        wpts.append({"layer": "rx", "kind": "line", "px": p0, "to": p1,
                     "dash": i1 - i0 > 1, "label": ""})
    # marks: 链上元件位号标签
    for i, r, px, elem in seq:
        wpts.append({"layer": "marks", "px": px, "label": r, "dot": True})
    # not located: 所有链元素中无可用坐标的, 左边缘竖排罗列(诚实标注)
    W_img, H_img = (Image.open(args.base_render).size if args.base_render else (3509, 2480))
    located_elems = {i for i, r, px, elem in seq}
    ny = 80
    for i, elem, refs in chain_refs(chain, set(idx["components"])):
        if i not in located_elems:
            wpts.append({"layer": "notes", "px": [args.notes_x, ny],
                         "label": f"not located: {elem}", "dot": False})
            ny += 46

    # blocks: rx_blocks [fx, fy, label] → px
    blocks_p = os.path.join(nt_dir, "rx_blocks_top.json")
    if os.path.exists(blocks_p):
        blocks = json.load(open(blocks_p))
        for b in blocks:
            fx, fy, lab = b[0], b[1], b[2]
            wpts.append({"layer": "blocks", "px": [fx * W_img, fy * H_img], "label": lab,
                         "dot": False})

    # tx / ctrl 色块 zone (6值区间掩膜; 超覆盖率的整页大blob丢弃)
    n_tx = 0
    if args.base_render:
        img = Image.open(args.base_render).convert("RGB")
        W_img, H_img = img.size
        page = W_img * H_img
        for spec, layer, lab in ((args.tx_color, "tx", "TX"), (args.ctrl_color, "ctrl", "CTRL")):
            kept = 0
            for x, y, w, h in color_zones(img, *parse6(spec), args.zone_min_area,
                                         args.zone_close, args.max_zones * 3):
                if w * h > page * args.zone_max_frac:
                    continue
                if kept >= args.max_zones:
                    break
                wpts.append({"layer": layer, "kind": "rect", "px": [x, y], "w": w, "h": h,
                             "dash": True, "label": f"{lab} z{kept}", "dot": False})
                kept += 1
            if layer == "tx":
                n_tx = kept
    if n_tx == 0:
        wpts.append({"layer": "notes", "px": [args.notes_x, 80 + 46 * 7],
                     "label": "TX chain: not yet read (红色路径遍布图面, 见 todo)", "dot": False})

    with open(args.out, "w") as f:
        json.dump(wpts, f, indent=1, ensure_ascii=False)
    from collections import Counter

    print(Counter(w["layer"] for w in wpts), f"-> {args.out}")


if __name__ == "__main__":
    main()
