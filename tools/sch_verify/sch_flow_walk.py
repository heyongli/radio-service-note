#!/usr/bin/env python3
"""tools/sch_flow_walk/sch_flow_walk.py — 层2 鉴别: 绿线流走线 (flow walk)

purpose: 读 sch_components.json, 判定每个组件是否属于绿线流经:
         flow_through (主路: 绿线两侧共线通过) / branch (支路: 单侧) / none
         更新 sch_components.json 的 membership 字段 (schema §3.5)
format: Python 3 + OpenCV
version: 0.1 (2026-09-16)

用法:
  python3 sch_flow_walk.py --img render/rxtx-sch-600-1.png \
      --color green --db sch_components.json

与 sch_recognize / sch_render 通过 sch_components.json 交互:
  识别(sch_recognize) → 鉴别(本程序) → 渲染(sch_render)
"""

import argparse
import json
import sys

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


def verify(components, green, band=14, touch_r=25, side=(30, 70)):
    """给每个组件加 membership (绿线鉴别)."""
    H, W = green.shape
    sd0, sd1 = side
    out = []
    for c in components:
        sx, sy = c["symbol_pos"]
        touch = green[max(0, sy - touch_r):sy + touch_r, max(0, sx - touch_r):sx + touch_r].sum() > 0
        sides = []
        if not touch:
            c["membership"] = "none"
            c["green_sides"] = []
            c["green_touch"] = False
            out.append(c)
            continue
        e = green[max(0, sy - band):sy + band, min(sx + sd0, W - 1):min(sx + sd1, W - 1)].sum() > 0
        w = green[max(0, sy - band):sy + band, max(0, sx - sd1):max(0, sx - sd0)].sum() > 0
        n = green[max(0, sy - sd1):max(0, sy - sd0), max(0, sx - band):sx + band].sum() > 0
        s = green[min(sy + sd0, H - 1):min(sy + sd1, H - 1), max(0, sx - band):sx + band].sum() > 0
        if e: sides.append("E")
        if w: sides.append("W")
        if n: sides.append("N")
        if s: sides.append("S")
        c["green_touch"] = True
        c["green_sides"] = sides
        if (e and w) or (n and s):
            c["membership"] = "flow_through"
            c["flow_dir"] = "H" if (e and w) else "V"
        elif len(sides) >= 1:
            c["membership"] = "branch"
        else:
            c["membership"] = "none"
        out.append(c)
    return out


def _ocr_reads_ref(gray, ocr, x, y, refdes, radius=50, rots=(0,)):
    """在 (x,y) 反向 OCR (旋转集, 默认 0 快速), 返回是否读出 refdes (含 1↔I 修正)."""
    def norm(s):
        return s.replace("I", "1").replace("L", "1")
    tgt = norm(refdes)
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return False, None
    base = cv2.resize(sub, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    for rot, code in [(0, None), (90, cv2.ROTATE_90_CLOCKWISE),
                      (180, cv2.ROTATE_180), (270, cv2.ROTATE_90_COUNTERCLOCKWISE)]:
        if rot not in rots:
            continue
        im = cv2.rotate(base, code) if code is not None else base
        res, _ = ocr(im)
        if not res:
            continue
        for t in res:
            nr = norm(t[1].strip().upper().replace(" ", ""))
            if nr and (tgt == nr or tgt in nr or nr in tgt):
                return True, rot
        if any("FL-363" in t[1] for t in res):
            return True, rot
    return False, None


def reverse_ocr_verify(gray, ocr, components, sym_list=None, radius=50, correct=True, rots=(0,)):
    """反向 OCR 验证符号中心 (只验 flow_through), 报告准确率.

    correct=True 时纠正: 符号中心读不出 refdes 的, 在文字附近找
    真正读出该 refdes 的符号 → 更新 symbol_pos.
    """
    n_ok = n_total = n_corrected = 0
    for c in components:
        if c.get("membership") != "flow_through" or not c.get("refdes"):
            continue
        sx, sy = c["symbol_pos"]
        ok, rot = _ocr_reads_ref(gray, ocr, sx, sy, c["refdes"], radius, rots)
        n_total += 1
        c["sym_verify"] = "ok" if ok else "wrong"
        if ok:
            n_ok += 1
            continue
        # 纠正: 文字附近找真正读出 refdes 的符号 (最近 8 个, 命中即停)
        if not correct or not sym_list:
            continue
        tx, ty = c.get("text_pos") or (sx, sy)
        near = sorted(sym_list, key=lambda s: abs(s["x"] - tx) + abs(s["y"] - ty))[:8]
        for s in near:
            ok2, _ = _ocr_reads_ref(gray, ocr, s["x"], s["y"], c["refdes"], radius, rots)
            if ok2:
                c["symbol_pos"] = [s["x"], s["y"]]
                c["sym_verify"] = "corrected"
                c["sym_d"] = abs(s["x"] - tx) + abs(s["y"] - ty)
                n_corrected += 1
                break
    # 去重: 同 refdes 保留 sym_verify=ok/corrected 的第一个
    seen = {}
    for c in components:
        rd = c.get("refdes")
        if not rd or c.get("membership") != "flow_through":
            continue
        keep = c["sym_verify"] in ("ok", "corrected")
        if rd in seen:
            if keep and not seen[rd]:
                seen[rd] = True
                continue
            if not keep and seen[rd]:
                c["membership"] = "dup_drop"
            else:
                c["membership"] = "dup_drop"
        else:
            seen[rd] = keep
    print(f"[sch_flow_walk] symbol-center reverse-OCR: {n_ok}/{n_total} OK "
          f"(corrected {n_corrected})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True, help="原理图渲染图")
    ap.add_argument("--color", default="green", choices=["green", "red", "cyan", "yellow"])
    ap.add_argument("--db", required=True, help="sch_components.json (读+写 membership)")
    ap.add_argument("--chain", help="输出 chain_order JSON (flow_through 有序链, 供结合管线)")
    ap.add_argument("--seed", help="起点 x,y (可选, 用于 walk_d 排序)")
    ap.add_argument("--band", type=int, default=22, help="绿线侧边探测带宽 (px; 实测 22 最优)")
    ap.add_argument("--touch-r", type=int, default=25, help="符号触点绿线判定半径")
    ap.add_argument("--side-dist", type=str, default="20,50", help="侧边绿线探测距离范围 (px; 实测 20,50 最优)")
    ap.add_argument("--no-verify", action="store_true", help="跳过反向 OCR 验证 (加速)")
    ap.add_argument("--verify-radius", type=int, default=50, help="反向 OCR 验证裁剪半径")
    ap.add_argument("--verify-rots", type=str, default="0", help="验证旋转集 (逗号分隔, 如 0,90,180,270)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    mask = color_mask(img, args.color)
    print(f"[sch_flow_walk] {args.color} mask: {(mask > 0).sum()} px")

    db = json.load(open(args.db))
    db["components"] = verify(db["components"], mask, args.band, args.touch_r,
                                  tuple(int(v) for v in args.side_dist.split(",")))
    db["_meta"]["verify"] = f"{args.color} flow membership"
    if not args.no_verify:
        from rapidocr_onnxruntime import RapidOCR
        gray = cv2.cvtColor(cv2.imread(args.img), cv2.COLOR_BGR2GRAY)
        ocr = RapidOCR()
        syms = db.get("symbols", [])
        # 1) 验证+纠正符号中心
        reverse_ocr_verify(gray, ocr, db["components"], syms, correct=True, radius=args.verify_radius, rots=tuple(int(v) for v in args.verify_rots.split(",")))
        # 2) 纠正后重新跑 membership (纠正的位置可能触点绿线)
        db["components"] = verify(db["components"], mask, args.band, args.touch_r,
                                  tuple(int(v) for v in args.side_dist.split(",")))
        # 3) 重新验证
        reverse_ocr_verify(gray, ocr, db["components"], syms, correct=False, radius=args.verify_radius, rots=tuple(int(v) for v in args.verify_rots.split(",")))
    with open(args.db, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    ft = [c for c in db["components"] if c["membership"] == "flow_through"]
    br = [c for c in db["components"] if c["membership"] == "branch"]
    print(f"[sch_flow_walk] flow_through={len(ft)} branch={len(br)} none={len(db['components'])-len(ft)-len(br)}")

    # chain_order 输出 (去重 + 排序)
    if args.chain:
        import numpy as np
        # 去重 (同 refdes 保留第一个)
        seen = set()
        ftu = []
        for c in ft:
            rd = c.get("refdes")
            if not rd or rd in seen:
                continue
            seen.add(rd)
            ftu.append(c)
        # 排序: 按绿线走线距离 (BFS from seed)
        if args.seed:
            from collections import deque
            sx, sy = (int(v) for v in args.seed.split(","))
            mask = color_mask(cv2.imread(args.img), args.color)
            H, W = mask.shape
            dist = np.full((H, W), -1, dtype=np.int32)
            if mask[sy, sx]:
                q = deque([(sx, sy)])
                dist[sy, sx] = 0
                while q:
                    x, y = q.popleft()
                    d = dist[y, x]
                    for dx, dy in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]:
                        nx, ny = x+dx, y+dy
                        if 0 <= nx < W and 0 <= ny < H and mask[ny, nx] and dist[ny, nx] < 0:
                            dist[ny, nx] = d + 1
                            q.append((nx, ny))
            for c in ftu:
                sx2, sy2 = c["symbol_pos"]
                sub = dist[max(0, sy2-60):sy2+60, max(0, sx2-60):sx2+60]
                pos = np.where(sub >= 0)
                c["walk_d"] = int(sub[pos[0], pos[1]].min()) if len(pos[0]) else None
            ftu.sort(key=lambda c: (c.get("walk_d") is None,
                                    c.get("walk_d") if c.get("walk_d") is not None else 1e9))
        chain = []
        for i, c in enumerate(ftu):
            chain.append({"idx": i + 1, "refdes": c["refdes"],
                          "sch_px": c["symbol_pos"], "symbol_type": c["symbol_type"],
                          "walk_d": c.get("walk_d"),
                          "status": "confirmed"})
        out = {"version": "1.0",
               "description": f"schematic {args.color} flow chain (sch_flow_walk)",
               "source": "sch_trace+sch_label_ocr+sch_flow_walk",
               "chain": chain}
        with open(args.chain, "w") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"[chain] saved: {args.chain} ({len(chain)} flow_through)")
    for c in ft:
        rd = c["refdes"] if c["refdes"] else "-"
        print(f"  {rd:6s} sides={c['green_sides']} {c['flow_dir']}")


if __name__ == "__main__":
    main()