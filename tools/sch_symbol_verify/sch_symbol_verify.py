#!/usr/bin/env python3
"""tools/sch_symbol_verify/sch_symbol_verify.py — 符号边界验证 (独立程序)

purpose: 消费前管线结果 (sch_components.json), 对每个 flow_through 组件
        检测符号边界并验证红点位置:
          - 三极管(circle)/IC(rect): 必须有黑色边界包围红点 (黑边轮廓)
          - 电容(cap): 开放符号, 两条平行板线 (-| |-)
          - 电阻(res)/电感(ind): 至少连续线段
          - 红点不得落在 label 文字框内

用法:
  python3 sch_symbol_verify.py --img render/rxtx-sch-600-1.png --db sch_components.json
"""

import argparse
import json
import sys

import cv2
import numpy as np


def _dark_contours(gray, x, y, radius=80, th=150):
    """(x,y) 附近的暗色轮廓 (黑边符号)."""
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return []
    dark = (sub < th).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(dark, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        per = cv2.arcLength(c, True)
        if a < 40 or per <= 0:
            continue
        xx, yy, w, h = cv2.boundingRect(c)
        out.append({"a": a, "x": xx + x - radius, "y": yy + y - radius,
                    "w": w, "h": h, "circ": 4 * np.pi * a / (per * per) if per else 0})
    return out


def in_box(px, py, box, pad=4):
    if not box:
        return False
    xs = [p[0] for p in box]; ys = [p[1] for p in box]
    return (min(xs) - pad <= px <= max(xs) + pad and
            min(ys) - pad <= py <= max(ys) + pad)


def type_from_refdes(refdes):
    """从 refdes 前缀判定符号类型 (refdes 识别准确, 以此为据)."""
    pre = "".join(ch for ch in refdes if ch.isalpha()).upper()
    if pre == "Q" or pre == "TR":
        return "circle"
    if pre in ("IC", "U", "FI", "F", "X"):
        return "ic"
    if pre == "C":
        return "cap"
    if pre == "L":
        return "ind"
    if pre == "R":
        return "res"
    return "cap"


def _hough_circles(gray, x, y, radius=80, rmin=10, rmax=40):
    """(x,y) 附近 Hough 圆 (比暗轮廓圆度可靠, 薄圆+走线不被破坏)."""
    sub = gray[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
    if sub.size == 0:
        return []
    cs = cv2.HoughCircles(sub, cv2.HOUGH_GRADIENT, dp=1.2, minDist=12,
                          param1=80, param2=28, minRadius=rmin, maxRadius=rmax)
    out = []
    if cs is not None:
        for cx, cy, r in np.rint(cs[0]).astype(int):
            out.append({"cx": int(cx) + x - radius, "cy": int(cy) + y - radius, "r": int(r)})
    return out


def correct_to_boundary(gray, c, radius=120):
    """当前 symbol_pos 无黑边边界时, 在 label 附近找真实黑边符号并纠正."""
    tx, ty = c.get("text_pos") or c["symbol_pos"]
    sym = type_from_refdes(c.get("refdes", ""))
    if sym == "circle":
        best = None
        for h in _hough_circles(gray, tx, ty, radius):
            d = abs(h["cx"] - tx) + abs(h["cy"] - ty)
            if best is None or d < best[0]:
                best = (d, [h["cx"], h["cy"]])
        if best:
            return [int(best[1][0]), int(best[1][1])]
        cnts = _dark_contours(gray, tx, ty, radius, th=150)
        for cc in cnts:
            if cc["circ"] > 0.6 and cc["w"] >= 14 and cc["h"] >= 14:
                return [int(cc["x"] + cc["w"] // 2), int(cc["y"] + cc["h"] // 2)]
        return None
    if sym == "ic":
        cnts = _dark_contours(gray, tx, ty, radius, th=150)
        best = None
        for cc in cnts:
            if cc["w"] >= 30 and cc["h"] >= 25:
                d = abs(cc["x"] + cc["w"] / 2 - tx) + abs(cc["y"] + cc["h"] / 2 - ty)
                if best is None or d < best[0]:
                    best = (d, [int(cc["x"] + cc["w"] // 2), int(cc["y"] + cc["h"] // 2)])
        return best[1] if best else None
    # 电阻/电感: 在 label 附近找长暗线段 (连续线)
    cnts = _dark_contours(gray, tx, ty, radius, th=150)
    for cc in sorted(cnts, key=lambda x: -x["w"] * x["h"]):
        if cc["w"] >= 40 or cc["h"] >= 40:
            return [int(cc["x"] + cc["w"] // 2), int(cc["y"] + cc["h"] // 2)]
    return None


def verify_symbol(gray, c, radius=80, correct=True):
    """按符号类型验证红点是否在符号上. 返回 (ok, detail).

    类型以 refdes 前缀为准 (识别准确), 不依赖 Hough 噪声误分类.
    """
    sx, sy = c["symbol_pos"]
    sym = type_from_refdes(c.get("refdes", ""))
    tbox = c.get("text_box")
    if in_box(sx, sy, tbox):
        if correct:
            np2 = correct_to_boundary(gray, c)
            if np2:
                return True, "corrected_on_label", np2
        return False, "on_label", None
    cnts = _dark_contours(gray, sx, sy, radius)

    if sym == "circle":  # 三极管: Hough 圆或黑边圆包围红点
        for h in _hough_circles(gray, sx, sy, radius):
            if (sx - h["cx"]) ** 2 + (sy - h["cy"]) ** 2 <= (h["r"] + 4) ** 2:
                return True, "circle_hough", None
        for cc in cnts:
            if cc["circ"] > 0.7 and cc["w"] >= 15 and cc["h"] >= 15:
                cx, cy = cc["x"] + cc["w"] / 2, cc["y"] + cc["h"] / 2
                r = max(cc["w"], cc["h"]) / 2
                if (sx - cx) ** 2 + (sy - cy) ** 2 <= (r + 4) ** 2:
                    return True, "circle", None
        # 纠正: label 附近找真实圆
        np2 = correct_to_boundary(gray, c)
        if np2:
            return True, "corrected_to_circle", np2
        return False, "no_circle_boundary", None

    if sym == "ic":  # IC: 黑边方块包围红点
        for cc in cnts:
            if cc["w"] >= 30 and cc["h"] >= 30 and cc["a"] / max(1, cc["w"] * cc["h"]) > 0.4:
                if cc["x"] - 4 <= sx <= cc["x"] + cc["w"] + 4 and \
                   cc["y"] - 4 <= sy <= cc["y"] + cc["h"] + 4:
                    return True, "rect", None
        np2 = correct_to_boundary(gray, c)
        if np2:
            return True, "corrected_to_rect", np2
        return False, "no_rect_boundary", None

    if sym == "cap":  # 电容: 开放符号, 两条平行板线 (-| |-)
        edges = cv2.Canny(gray[max(0, sy - radius):sy + radius,
                               max(0, sx - radius):sx + radius], 60, 160)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 25,
                                minLineLength=14, maxLineGap=3)
        if lines is None:
            return False, "no_cap_lines", None
        hh, vv = [], []
        for l in np.asarray(lines).reshape(-1, 4):
            a1, b1, a2, b2 = l
            L = abs(a2 - a1) if abs(a2 - a1) >= abs(b2 - b1) else abs(b2 - b1)
            if L < 14:
                continue
            if abs(a2 - a1) >= abs(b2 - b1):
                hh.append((a1, b1, a2, b2, L))
            else:
                vv.append((a1, b1, a2, b2, L))
        for grp, axis in [(hh, "h"), (vv, "v")]:
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    a, b = grp[i], grp[j]
                    if abs(a[4] - b[4]) > a[4] * 0.5:
                        continue
                    gap = abs(a[1] - b[1]) if axis == "h" else abs(a[0] - b[0])
                    if 8 <= gap <= 45:
                        return True, "cap_pair", None
        return False, "no_cap_pair", None

    # 电阻/电感: 至少连续暗色线段
    for cc in cnts:
        if cc["w"] >= 30 or cc["h"] >= 30:
            return True, "line", None
    return False, "no_line", None


def boundary_from_symbol(gray, c, radius=80):
    """检测并返回 flow_through 组件的符号边界 (存 sch_components.json)."""
    sx, sy = c["symbol_pos"]
    sym = type_from_refdes(c.get("refdes", ""))
    if sym == "circle":
        best = None
        for h in _hough_circles(gray, sx, sy, radius):
            if (sx - h["cx"]) ** 2 + (sy - h["cy"]) ** 2 <= (h["r"] + 4) ** 2:
                d = abs(h["cx"] - sx) + abs(h["cy"] - sy)
                if best is None or d < best[0]:
                    best = (d, {"kind": "circle", "cx": int(h["cx"]), "cy": int(h["cy"]), "r": int(h["r"])})
        if best:
            return best[1]
    elif sym == "ic":
        cnts = _dark_contours(gray, sx, sy, radius)
        for cc in cnts:
            if cc["w"] >= 30 and cc["h"] >= 25:
                if cc["x"] - 4 <= sx <= cc["x"] + cc["w"] + 4 and \
                   cc["y"] - 4 <= sy <= cc["y"] + cc["h"] + 4:
                    return {"kind": "rect", "x": int(cc["x"]), "y": int(cc["y"]),
                            "w": int(cc["w"]), "h": int(cc["h"])}
    return None


def _bounds_overlap(b1, b2, pad=6):
    """两符号边界是否重叠 (电路图符号不能重叠 → 重叠即识别错误)."""
    if b1 is None or b2 is None:
        return False
    if b1["kind"] == "circle" and b2["kind"] == "circle":
        return (b1["cx"] - b2["cx"]) ** 2 + (b1["cy"] - b2["cy"]) ** 2 <= \
               (b1["r"] + b2["r"] + pad) ** 2
    if b1["kind"] == "rect" and b2["kind"] == "rect":
        return not (b1["x"] + b1["w"] + pad < b2["x"] or b2["x"] + b2["w"] + pad < b1["x"] or
                    b1["y"] + b1["h"] + pad < b2["y"] or b2["y"] + b2["h"] + pad < b1["y"])
    # 圆-方块
    c = b1 if b1["kind"] == "circle" else b2
    r = b2 if b1["kind"] == "circle" else b1
    cx, cy, rr = c["cx"], c["cy"], c["r"]
    nx = max(r["x"] - pad, min(cx, r["x"] + r["w"] + pad))
    ny = max(r["y"] - pad, min(cy, r["y"] + r["h"] + pad))
    return (cx - nx) ** 2 + (cy - ny) ** 2 <= (rr + pad) ** 2


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--db", required=True, help="sch_components.json (读写, 加 sym_verify/detail)")
    ap.add_argument("--radius", type=int, default=80)
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    db = json.load(open(args.db))

    n = n_ok = 0
    bad = {}
    corrected = 0
    for c in db["components"]:
        if c.get("membership") != "flow_through" or not c.get("refdes"):
            continue
        sx, sy = c["symbol_pos"]
        n += 1
        ok, detail, np2 = verify_symbol(gray, c, args.radius, correct=True)
        c["sym_verify"] = "ok" if ok else "bad"
        c["sym_verify_detail"] = detail
        if np2:
            c["symbol_pos"] = np2
            c["sym_corrected"] = True
            corrected += 1
        # 存储符号边界 (用于重叠检测 + 渲染)
        c["sym_boundary"] = boundary_from_symbol(gray, c, args.radius)
        if ok:
            n_ok += 1
        else:
            bad[c["refdes"]] = detail
    tmp = args.db + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    import os
    os.replace(tmp, args.db)
    print(f"[sch_symbol_verify] flow_through boundary: ok={n_ok}/{n} (corrected {corrected})")
    for rd, d in sorted(bad.items()):
        print(f"  BAD {rd:6s} {d}")

    # 符号重叠检测: 电路图符号不能重叠, 重叠即识别错误
    ft = [c for c in db["components"]
          if c.get("membership") == "flow_through" and c.get("refdes") and c.get("sym_boundary")]
    overlap_pairs = []
    for i in range(len(ft)):
        for j in range(i + 1, len(ft)):
            if _bounds_overlap(ft[i]["sym_boundary"], ft[j]["sym_boundary"]):
                overlap_pairs.append((ft[i]["refdes"], ft[j]["refdes"]))
    print(f"[sch_symbol_verify] overlapping symbol boundaries: {len(overlap_pairs)}")
    for a, b in overlap_pairs[:20]:
        print(f"  OVERLAP {a} <-> {b}")

    # refdes 去重: 符号不能重叠 → 同 refdes 保留一个 (边界验证 OK + 触点绿线最近)
    from collections import defaultdict
    groups = defaultdict(list)
    for c in db["components"]:
        if c.get("membership") == "flow_through" and c.get("refdes"):
            groups[c["refdes"]].append(c)
    dedup_dropped = 0
    for rd, lst in groups.items():
        if len(lst) <= 1:
            continue
        best = None
        for c in lst:
            score = 0
            if c.get("sym_verify") == "ok":
                score -= 100
            if c.get("sym_boundary"):
                score -= 50
            score += c.get("sym_d", 0) or 0
            if best is None or score < best[0]:
                best = (score, c)
        for c in lst:
            if c is not best[1]:
                c["membership"] = "dup_drop"
                dedup_dropped += 1
    print(f"[sch_symbol_verify] refdes dedup: dropped {dedup_dropped} duplicate entries")
    n_ft = sum(1 for c in db["components"] if c["membership"] == "flow_through")
    print(f"[sch_symbol_verify] flow_through after dedup: {n_ft}")


if __name__ == "__main__":
    main()