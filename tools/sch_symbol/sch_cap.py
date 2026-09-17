#!/usr/bin/env python3
"""tools/sch_symbol/sch_cap.py — 电容符号识别 (双板本体)

识别电容 (C) 的两条平行板线本体, 中心 = 双板质心 (本体, 非引出线).
消费 sch_components.json, 只处理 flow_through + cap 类型.

用法:
  python3 sch_cap.py --img sch.png --db sch_components.json
"""
import argparse, sys
import cv2
import numpy as np
from common import find_cap_pairs, load_db, save_db


def detect(gray, x, y, radius=80):
    pairs = find_cap_pairs(gray, x, y, radius)
    if pairs:
        p = min(pairs, key=lambda p: abs(p["cx"] - x) + abs(p["cy"] - y))
        return {"kind": "cap", "cx": p["cx"], "cy": p["cy"],
                "gap": p["gap"], "len": p["len"], "dir": p.get("dir")}
    return None


def synthesize_cap_mask(plate_len=45, gap=20, wire=25, line_w=3):
    """根据知识合成电容掩膜 (-| |-): 两条平行板线 + 两侧接线.

    板长 plate_len, 板间 gap, 两侧接线长 wire.
    返回二值掩膜 (uint8 0/255).
    """
    H = gap + 2 * line_w + 4
    W = plate_len + 2 * wire + 2 * line_w
    mask = np.zeros((H, W), np.uint8)
    # 两条板线 (垂直短线, 在板区两端)
    y1 = line_w + 1
    y2 = y1 + gap
    x_left = wire + line_w // 2
    x_right = wire + plate_len + line_w // 2
    cv2.line(mask, (x_left, y1), (x_left, y2), 255, line_w)
    cv2.line(mask, (x_right, y1), (x_right, y2), 255, line_w)
    # 两侧接线
    mid = H // 2
    cv2.line(mask, (0, mid), (x_left, mid), 255, line_w)
    cv2.line(mask, (x_right, mid), (W - 1, mid), 255, line_w)
    return mask


def match_mask(gray, mask, x, y, radius=80):
    """合成电容掩膜与图中元素匹配 (TM_CCOEFF_NORMED). 返回最佳匹配分."""
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0 or mask is None:
        return None
    if mask.shape[0] >= sub.shape[0] or mask.shape[1] >= sub.shape[1]:
        return None
    res = cv2.matchTemplate(sub, mask, cv2.TM_CCOEFF_NORMED)
    _, mx, _, mloc = cv2.minMaxLoc(res)
    return float(mx), mloc


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--radius", type=int, default=80)
    ap.add_argument("--sizes-db", default=None,
                    help="符号尺寸知识库 (取电容典型尺寸合成掩膜)")
    ap.add_argument("--match-th", type=float, default=0.4, help="掩膜匹配阈值")
    args = ap.parse_args()
    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 根据知识合成电容掩膜 (典型板长/间距)
    mask = None
    if args.sizes_db:
        import os, json
        if os.path.exists(args.sizes_db):
            sdb = json.load(open(args.sizes_db))
            caps = sdb.get("cap", [])
            if caps:
                lens = [s["size"][0] for s in caps if s["size"]]
                gaps = [s["size"][1] for s in caps if s["size"]]
                if lens and gaps:
                    import statistics
                    mask = synthesize_cap_mask(
                        plate_len=int(statistics.median(lens)),
                        gap=int(statistics.median(gaps)))
                    print(f"[sch_cap] synthesized mask: "
                          f"plate={int(statistics.median(lens))} gap={int(statistics.median(gaps))}")

    db = load_db(args.db)
    n = n_match = 0
    for c in db["components"]:
        if c.get("membership") != "flow_through" or not c.get("refdes"):
            continue
        if c["refdes"].upper().startswith("C"):
            sx, sy = c["symbol_pos"][0], c["symbol_pos"][1]
            b = detect(gray, sx, sy, args.radius)
            c["symbol_type"] = "cap"
            c["symbol_body"] = b
            if mask is not None:
                m = match_mask(gray, mask, sx, sy, args.radius)
                if m:
                    score, mloc = m
                    c["mask_match"] = round(score, 3)
                    # 掩膜矫正: 匹配最高处即电容位置
                    c["mask_loc"] = [mloc[0] + sx - args.radius, mloc[1] + sy - args.radius]
                    if score >= args.match_th:
                        n_match += 1
            if b:
                n += 1
    save_db(db, args.db)
    print(f"[sch_cap] capacitor bodies: {n}")
    if mask is not None:
        print(f"[sch_cap] mask-match confirmed: {n_match}")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()