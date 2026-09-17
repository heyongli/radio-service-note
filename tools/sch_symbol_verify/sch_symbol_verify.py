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
            out.append({"cx": cx + x - radius, "cy": cy + y - radius, "r": int(r)})
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
            return best[1]
        cnts = _dark_contours(gray, tx, ty, radius, th=150)
        for cc in cnts:
            if cc["circ"] > 0.6 and cc["w"] >= 14 and cc["h"] >= 14:
                return [cc["x"] + cc["w"] // 2, cc["y"] + cc["h"] // 2]
        return None
    if sym == "ic":
        cnts = _dark_contours(gray, tx, ty, radius, th=150)
        best = None
        for cc in cnts:
            if cc["w"] >= 30 and cc["h"] >= 25:
                d = abs(cc["x"] + cc["w"] / 2 - tx) + abs(cc["y"] + cc["h"] / 2 - ty)
                if best is None or d < best[0]:
                    best = (d, [cc["x"] + cc["w"] // 2, cc["y"] + cc["h"] // 2])
        return best[1] if best else None
    # 电阻/电感: 在 label 附近找长暗线段 (连续线)
    cnts = _dark_contours(gray, tx, ty, radius, th=150)
    for cc in sorted(cnts, key=lambda x: -x["w"] * x["h"]):
        if cc["w"] >= 40 or cc["h"] >= 40:
            return [cc["x"] + cc["w"] // 2, cc["y"] + cc["h"] // 2]
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
            # 反馈: 纠正符号位置 (反向推理: 用黑边边界锚定真实符号)
            c["symbol_pos"] = np2
            c["sym_corrected"] = True
            corrected += 1
        if ok:
            n_ok += 1
        else:
            bad[c["refdes"]] = detail
    with open(args.db, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    print(f"[sch_symbol_verify] flow_through boundary: ok={n_ok}/{n} (corrected {corrected})")
    for rd, d in sorted(bad.items()):
        print(f"  BAD {rd:6s} {d}")


if __name__ == "__main__":
    main()