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
from common import find_cap_pairs, find_lines, load_db, save_db, boundary_from_body


def detect(gray, x, y, radius=80):
    pairs = find_cap_pairs(gray, x, y, radius)
    if pairs:
        p = min(pairs, key=lambda p: abs(p["cx"] - x) + abs(p["cy"] - y))
        return {"kind": "cap", "cx": p["cx"], "cy": p["cy"],
                "gap": p["gap"], "len": p["len"], "dir": p.get("dir")}
    return None


def detect(gray, x, y, radius=100, pb=None):
    """电容检测: 优先用极板检测 (走线上的垂直粗线 = 极板, 方向已知).

    找到一块极板知方向, 沿走线搜另一块, 两板中点 = 电容中心.
    """
    if pb is not None:
        plates = detect_plates_on_wire(gray, pb, x, y, radius)
        if plates:
            p = min(plates, key=lambda p: abs(p["cx"] - x) + abs(p["cy"] - y))
            return {"kind": "cap", "cx": int(p["cx"]), "cy": int(p["cy"]),
                    "gap": int(p["gap"]), "dir": "v"}
    pairs = find_cap_pairs(gray, x, y, radius)
    if pairs:
        p = min(pairs, key=lambda p: abs(p["cx"] - x) + abs(p["cy"] - y))
        return {"kind": "cap", "cx": p["cx"], "cy": p["cy"],
                "gap": p["gap"], "len": p["len"], "dir": p.get("dir")}
    return None


def detect_with_wire(pb, gray, x, y, radius=100):
    """走线↔符号互验定位电容: 走线断口 = 电容位置, 板线对确认, 引出线对齐走线.

    1. 走线断口 (两段黑走线) 中点 = 电容中心 (走线必终结于符号)
    2. 附近板线对确认是电容
    3. 引出线 (板线外缘) 应对齐走线
    """
    # 1) 极板检测 (走线上的垂直粗线)
    plates = detect_plates_on_wire(gray, pb, x, y, radius)
    if plates:
        p = min(plates, key=lambda p: abs(p["cx"] - x) + abs(p["cy"] - y))
        return {"kind": "cap", "cx": int(p["cx"]), "cy": int(p["cy"]),
                "gap": int(p["gap"]), "dir": "v"}
    # 走线断口定位
    gaps = find_lines(pb, x, y, radius)
    if not gaps:
        return detect(gray, x, y, radius)
    g = min(gaps, key=lambda g: abs(g["cx"] - x) + abs(g["cy"] - y))
    gx, gy = g["cx"], g["cy"]
    # 2) 板线对确认 (在断口附近找)
    pairs = find_cap_pairs(gray, gx, gy, 60)
    if pairs:
        p = min(pairs, key=lambda p: abs(p["cx"] - gx) + abs(p["cy"] - gy))
        # 3) 引出线对齐走线: 板线外缘附近有走线 (纯黑)
        return {"kind": "cap", "cx": p["cx"], "cy": p["cy"],
                "gap": p["gap"], "len": p["len"], "dir": p.get("dir"),
                "wire_gap": abs(gx - x) + abs(gy - y)}
    # 无板线对, 用走线断口位置
    return {"kind": "cap", "cx": gx, "cy": gy, "gap": 0, "len": 0, "wire_only": True}


def synthesize_cap_mask(plate_len=18, gap=18, wire=12, line_w=1, vertical=False):
    """根据知识合成细电容掩膜 (极板细, 长宽比~1:1).

    极板长 plate_len, 板间距 gap (匹配时调整), 接线短 wire, 线细 line_w.
    极板区 (两板+间距) 长宽比 ~1:1.
    """
    H = gap + 2 * line_w + 4
    W = plate_len + 2 * wire + 2 * line_w
    mask = np.zeros((H, W), np.uint8)
    y1 = line_w + 1
    y2 = y1 + gap
    x_left = wire + line_w // 2
    x_right = wire + plate_len + line_w // 2
    cv2.line(mask, (x_left, y1), (x_left, y2), 255, line_w)
    cv2.line(mask, (x_right, y1), (x_right, y2), 255, line_w)
    mid = H // 2
    cv2.line(mask, (0, mid), (x_left, mid), 255, line_w)
    cv2.line(mask, (x_right, mid), (W - 1, mid), 255, line_w)
    if vertical:
        mask = cv2.rotate(mask, cv2.ROTATE_90_CLOCKWISE)
    return mask


def detect_plates_on_wire(gray, pb, x, y, radius=100, thick=3):
    """沿走线找垂直粗线 (电容极板): 走线是细水平线, 遇垂直粗线即极板.

    1. 找水平走线 (细)
    2. 走线上遇垂直粗线 (宽度>=thick) = 极板
    3. 两相邻极板 (间距 8-30) = 电容, 中心 = 两板中点
    """
    sub = pb[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return []
    edges = cv2.Canny(sub, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 30, minLineLength=30, maxLineGap=5)
    if lines is None:
        return []
    # 找水平走线 (细线)
    hlines = []
    for l in np.asarray(lines).reshape(-1, 4):
        a1, b1, a2, b2 = l
        if abs(a2 - a1) >= abs(b2 - b1) and abs(a2 - a1) >= 30:
            hlines.append((b1, min(a1, a2), max(a1, a2)))
    # 极板: 走线上的垂直粗线
    out = []
    for hy, hx0, hx1 in hlines:
        yw = hy + y - radius
        for px in range(hx0 + 10, hx1 - 10, 3):
            # 垂直粗线检测 (当前列宽 > 细线宽)
            col = pb[max(0, yw - 30):yw + 30, px + x - radius]
            runs = []
            s = None
            for i, v in enumerate(col):
                if v:
                    if s is None: s = i
                else:
                    if s is not None: runs.append(i - s); s = None
            if s is not None: runs.append(len(col) - s)
            if any(r >= thick for r in runs):
                out.append({"x": px + x - radius, "y": yw})
    # 相邻两板配对
    caps = []
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            if out[i]["y"] != out[j]["y"]:
                continue
            g = abs(out[i]["x"] - out[j]["x"])
            if 8 <= g <= 30:
                caps.append({"cx": (out[i]["x"] + out[j]["x"]) // 2,
                             "cy": out[i]["y"], "gap": g})
    return caps


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


def search_mask(gray, mask, x, y, radius=80):
    """掩膜探索: 在学习掩膜与图中元素对齐处找电容 (TM_CCOEFF_NORMED 最高处).

    若掩膜在真实黑色电容体上对齐 → 高分匹配 → 该处即电容位置.
    """
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0 or mask is None:
        return None
    if mask.shape[0] >= sub.shape[0] or mask.shape[1] >= sub.shape[1]:
        return None
    res = cv2.matchTemplate(sub, mask, cv2.TM_CCOEFF_NORMED)
    _, mx, _, mloc = cv2.minMaxLoc(res)
    # 掩膜中心在匹配框中心
    mcx = mloc[0] + mask.shape[1] // 2 + x - radius
    mcy = mloc[1] + mask.shape[0] // 2 + y - radius
    return float(mx), [int(mcx), int(mcy)]


def mask_align_score(gray, mask, x, y, radius=100, dark_th=150, frame=8):
    """掩膜互验 (1&1=1): 掩膜处应全暗 (电容体) 且掩膜外附近应全亮 (孤立).

    掩膜内暗色比例高 + 掩膜外框亮色比例高 = 真正对齐孤立电容.
    """
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return 0.0
    if mask.shape[0] > sub.shape[0] or mask.shape[1] > sub.shape[1]:
        return 0.0
    mh, mw = mask.shape
    y0 = y - radius + (sub.shape[0] - mh) // 2
    x0 = x - radius + (sub.shape[1] - mw) // 2
    if y0 < 0 or x0 < 0 or y0 + mh > gray.shape[0] or x0 + mw > gray.shape[1]:
        return 0.0
    reg = gray[y0:y0 + mh, x0:x0 + mw]
    inside = reg[mask > 0]
    inside_dark = float((inside < dark_th).mean()) if len(inside) else 0.0
    # 掩膜外框 (周围亮色)
    y1 = max(0, y0 - frame); x1 = max(0, x0 - frame)
    y2 = min(gray.shape[0], y0 + mh + frame); x2 = min(gray.shape[1], x0 + mw + frame)
    outer = gray[y1:y2, x1:x2].copy()
    outer[max(0, y0 - y1):max(0, y0 - y1) + mh, max(0, x0 - x1):max(0, x0 - x1) + mw] = 255
    outer_light = float((outer >= dark_th).mean())
    return inside_dark * outer_light


def calibrate_size(gray, x, y, base_mask, radius=100, scales=(0.7, 0.85, 1.0, 1.15, 1.3)):
    """尺寸自校准: 用不同缩放的掩膜提取图区域, 对齐分数最高的缩放 = 真实电容尺寸.

    互相印证学习: 掩膜处应与图中电容体一致 (暗色), 最佳缩放即实际尺寸.
    """
    best = None
    for s in scales:
        tw = max(8, int(base_mask.shape[1] * s))
        th = max(8, int(base_mask.shape[0] * s))
        mask = cv2.resize(base_mask, (tw, th))
        score = mask_align_score(gray, mask, x, y, radius)
        if best is None or score > best[0]:
            best = (score, s, tw, th)
    return best


def mask_probe(gray, mask, x, y, radius=120, step=10, span=40, th=0.7):
    """掩膜探测 (1&1=1): 周围扫描掩膜对齐最高处 = 电容真实位置.

    返回 (best_score, [best_x, best_y]) 或 None.
    """
    best = None
    for dy in range(-span, span + 1, step):
        for dx in range(-span, span + 1, step):
            s = mask_align_score(gray, mask, x + dx, y + dy, radius)
            if best is None or s > best[0]:
                best = (s, x + dx, y + dy)
    if best and best[0] >= th:
        return best[0], [best[1], best[2]]
    return None


def real_template_match(gray, tpl, x, y, radius=120, scales=(0.6, 0.8, 1.0, 1.2, 1.5, 2.0)):
    """真实电容模板多尺度匹配 (从 C266 等准确电容学习).

    返回最佳 (score, [x,y], scale) 或 None.
    """
    if tpl is None or tpl.size == 0:
        return None
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return None
    best = None
    for s in scales:
        tw = max(10, int(tpl.shape[1] * s))
        th = max(10, int(tpl.shape[0] * s))
        if tw >= sub.shape[1] or th >= sub.shape[0]:
            continue
        t2 = cv2.resize(tpl, (tw, th))
        res = cv2.matchTemplate(sub, t2, cv2.TM_CCOEFF_NORMED)
        _, mx, _, mloc = cv2.minMaxLoc(res)
        mcx = mloc[0] + tw // 2 + x - radius
        mcy = mloc[1] + th // 2 + y - radius
        if best is None or mx > best[0]:
            best = (float(mx), [int(mcx), int(mcy)], float(s))
    return best if best else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--radius", type=int, default=100)
    ap.add_argument("--sizes-db", default=None,
                    help="符号尺寸知识库 (取电容典型尺寸合成掩膜)")
    ap.add_argument("--match-th", type=float, default=0.4, help="掩膜匹配阈值")
    ap.add_argument("--wire", action="store_true",
                    help="用走线断口定位电容 (走线↔符号互验)")
    ap.add_argument("--template", default=None,
                    help="真实电容模板图 (从准确电容学习, 多尺度匹配)")
    args = ap.parse_args()
    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    pb = None
    if args.wire:
        from common import pure_black_mask
        pb = pure_black_mask(img, gray)
    rtpl = None
    if args.template:
        rtpl = cv2.cvtColor(cv2.imread(args.template), cv2.COLOR_BGR2GRAY)
        print(f"[sch_cap] real template: {rtpl.shape}")

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
            if pb is not None:
                b = detect_with_wire(pb, gray, sx, sy, args.radius)
            else:
                b = detect(gray, sx, sy, args.radius)
            c["symbol_type"] = "cap"
            c["symbol_body"] = b
            c["symbol_orientation"] = b.get("dir") if b else None
            if rtpl is not None and b:
                # 真实模板多尺度匹配 (学习自准确电容)
                m = real_template_match(gray, rtpl, b["cx"], b["cy"])
                if m:
                    rscore, rloc, rscale = m
                    c["real_match"] = round(rscore, 3)
                    c["real_loc"] = rloc
                    c["real_scale"] = round(rscale, 2)
                    c["symbol_pos"] = rloc
                    b["cx"], b["cy"] = rloc
            if mask is not None and b:
                # 按方向生成掩膜 (垂直走线电容旋转 90°)
                cmask = mask
                if b.get("dir") == "v":
                    cmask = cv2.rotate(mask, cv2.ROTATE_90_CLOCKWISE)
                # 掩膜验证: 当前位置对齐好则不移动 (防塌缩)
                cur = mask_align_score(gray, cmask, b["cx"], b["cy"], 120)
                c["mask_align"] = round(cur, 3)
                if cur < 0.7:
                    # 仅在对齐差时探测矫正 (限制范围防塌缩)
                    mp = mask_probe(gray, cmask, b["cx"], b["cy"], span=20)
                    if mp:
                        pscore, ploc = mp
                        if pscore > cur:
                            c["mask_align"] = round(pscore, 3)
                            c["mask_loc"] = ploc
                            c["symbol_pos"] = ploc
                            b["cx"], b["cy"] = ploc
                # 掩膜互验自校准: 不同缩放掩膜提取图区域
                cal = calibrate_size(gray, b["cx"], b["cy"], mask, args.radius)
                if cal:
                    cscore, scale, cw, ch = cal
                    c["mask_align"] = round(cscore, 3)
                    c["calib_scale"] = round(scale, 2)
                    c["calib_size"] = [cw, ch]
                    # 掩膜探索验证 (强无监督): 学习掩膜应在真实黑色电容体上对齐
                    best_mask = cv2.resize(mask, (cw, ch))
                    m = search_mask(gray, best_mask, b["cx"], b["cy"], args.radius)
                    if m:
                        score, mloc = m
                        c["mask_match"] = round(score, 3)
                        c["mask_loc"] = mloc
                        c["symbol_pos"] = mloc
                        b["cx"], b["cy"] = mloc
                        if score >= args.match_th:
                            n_match += 1
            if b:
                n += 1
            c["sym_boundary"] = boundary_from_body(b)
    save_db(db, args.db)
    print(f"[sch_cap] capacitor bodies: {n}")
    if mask is not None:
        print(f"[sch_cap] mask-match confirmed: {n_match}")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()