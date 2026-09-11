#!/usr/bin/env python3
"""IC 封装定位工具: 三种方法, 从强到弱.

方法 pin-silk (首选, 数据驱动):
  PCB 视图 PDF 文本层里的引脚号丝印(孤立的 "1" "16" "8" "9" 等)给出 IC 的
  本体位置+方向+引脚数. 同行成对(Δy<12, Δx 20-300)的引脚号 = IC 同一边的
  两个角引脚; x 范围相近的两对 = 同一 IC 的上下两边 → 内插全引脚坐标.
  无需图像处理, 精度=文本层坐标. 适用: 维修手册 PCB 视图(常印引脚号).

方法 body (渲染图暗矩形):
  在已知标签位号附近找暗色矩形(阈值+轮廓+面积/长宽比/矩形度过滤,
  取最近候选). 适用: 照片式渲染(top 视图). 对 S-AV36 等非矩形模块失效.

方法 contour (线稿 Canny 矩形):
  线稿图(bot 铜箔视图)的 Canny 边缘 + approxPolyDP 四边形. 稳定性差,
  仅作 body 失败时的备选.

用法:
  python3 detect_ic.py pin-silk --pdf bot.pdf [--out ic_pins.json]
  python3 detect_ic.py body --img top600.png --near 2000,3540 [--radius 420]
  python3 detect_ic.py contour --img bot600.png --near 1980,3452
坐标: 输入 --near 为 300dpi px; 输出统一 300dpi px.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile


def pdf_number_words(pdf):
    """pdftotext -bbox → [(x,y,数字)] 坐标已含 /Rotate, ×300/72 → 300dpi px."""
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        out = f.name
    subprocess.run(["pdftotext", "-bbox", pdf, out], check=True)
    txt = open(out).read()
    os.unlink(out)
    S = 300.0 / 72.0
    words = re.findall(
        r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="[\d.]+">(\d+)</word>',
        txt)
    return [(float(x) * S, float(y) * S, int(n)) for x, y, n in words
            if 1 <= int(n) <= 64]


def pair_rows(nums, dy=14, dx=(20, 320)):
    """同一行(边)上的引脚号对."""
    pairs = []
    for i, (x1, y1, n1) in enumerate(nums):
        for x2, y2, n2 in nums[i + 1:]:
            if abs(y1 - y2) < dy and dx[0] < abs(x2 - x1) < dx[1]:
                L, R = ((x1, y1, n1), (x2, y2, n2)) if x1 < x2 else ((x2, y2, n2), (x1, y1, n1))
                pairs.append(dict(left=dict(x=round(L[0]), y=round(L[1]), pin=L[2]),
                                  right=dict(x=round(R[0]), y=round(R[1]), pin=R[2])))
    return pairs


def group_ics(pairs, tol=30):
    """x 范围相近的两对 = 同一 IC 的对边."""
    ics = []
    used = [False] * len(pairs)
    for i, p1 in enumerate(pairs):
        if used[i]:
            continue
        for j in range(i + 1, len(pairs)):
            if used[j]:
                continue
            p2 = pairs[j]
            if (abs(p1["left"]["x"] - p2["left"]["x"]) < tol
                    and abs(p1["right"]["x"] - p2["right"]["x"]) < tol
                    and abs(p1["left"]["y"] - p2["left"]["y"]) > 25):
                used[i] = used[j] = True
                top, bot = (p1, p2) if p1["left"]["y"] < p2["left"]["y"] else (p2, p1)
                ics.append(dict(edges=[top, bot]))
                break
    return ics


def interpolate_pins(ic):
    """按两边的角引脚号内插全引脚. 规则: 含 pin1 的列 1→k 向下(或向上),
    含 pinN 的列 N→k+1; 由标签实际位置决定方向."""
    top, bot = ic["edges"]
    N = max(top["left"]["pin"], top["right"]["pin"], bot["left"]["pin"], bot["right"]["pin"])
    k = N // 2
    pins = {}
    for side in ("left", "right"):
        a, b = top[side], bot[side]  # a=上边标签, b=下边标签
        n_a, n_b = a["pin"], b["pin"]
        n = abs(n_a - n_b) + 1  # 该列引脚数
        if n < 2:
            continue
        for i in range(n):
            pin = n_a + (n_b - n_a) * i // (n - 1)
            t = i / (n - 1)
            pins[pin] = dict(x=round(a["x"] + (b["x"] - a["x"]) * t),
                             y=round(a["y"] + (b["y"] - a["y"]) * t))
    xs = [p["x"] for p in pins.values()]
    ys = [p["y"] for p in pins.values()]
    return dict(pin_count=N, pins={str(p): v for p, v in sorted(pins.items())},
                body=dict(x=round(min(xs) - 12), y=round(min(ys) - 12),
                          w=round(max(xs) - min(xs) + 24), h=round(max(ys) - min(ys) + 24)),
                corners=dict(top_left=f"pin{top['left']['pin']}",
                             top_right=f"pin{top['right']['pin']}",
                             bottom_left=f"pin{bot['left']['pin']}",
                             bottom_right=f"pin{bot['right']['pin']}"))


def method_pin_silk(pdf):
    nums = pdf_number_words(pdf)
    pairs = pair_rows(nums)
    ics = group_ics(pairs)
    out = []
    for ic in ics:
        r = interpolate_pins(ic)
        out.append(r)
    return out


def method_body(img, near, radius=420, thr=130, min_a=3000, max_a=120000,
                ar=(0.3, 3.5), fill_min=0.7):
    import cv2
    import numpy as np
    cx, cy = near
    g = cv2.imread(img, cv2.IMREAD_GRAYSCALE)
    H, W = g.shape
    f = H / 2480.0  # 图高/300dpi页高 = dpi/300 放大比
    cx6, cy6 = int(cx * f), int(cy * f)  # 300dpi -> 图像px
    r6 = int(radius * f)
    x0, y0 = max(0, cx6 - r6), max(0, cy6 - r6)
    sub = g[y0:cy6 + r6, x0:cx6 + r6]
    _, th = cv2.threshold(sub, thr, 255, cv2.THRESH_BINARY_INV)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        a = cv2.contourArea(c)
        if not (min_a < a < max_a and ar[0] < min(w, h) / max(w, h) < ar[1]):
            continue
        if a / (w * h) < fill_min:
            continue
        bx, by = (x + x0) / f, (y + y0) / f  # 图像px -> 300dpi
        d = abs(bx - cx) + abs(by - cy)
        if best is None or d < best[0]:
            best = (d, dict(x=round(bx), y=round(by), w=round(w / f), h=round(h / f),
                            fill=round(a / (w * h), 2)))
    return best[1] if best else None


def method_contour(img, near, radius=400):
    import cv2
    import numpy as np
    cx, cy = near
    g = cv2.imread(img, cv2.IMREAD_GRAYSCALE)
    H, W = g.shape
    f = H / 2480.0
    cx6, cy6 = int(cx * f), int(cy * f)
    r6 = int(radius * f)
    x0, y0 = max(0, cx6 - r6), max(0, cy6 - r6)
    sub = g[y0:cy6 + r6, x0:cx6 + r6]
    edges = cv2.Canny(sub, 60, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        a = cv2.contourArea(c)
        if not (2500 < a < 80000 and 0.3 < min(w, h) / max(w, h) < 2.5):
            continue
        peri = cv2.arcLength(c, True)
        if len(cv2.approxPolyDP(c, 0.02 * peri, True)) < 4:
            continue
        bx, by = (x + x0) / f, (y + y0) / f
        d = abs(bx - cx) + abs(by - cy)
        if best is None or d < best[0]:
            best = (d, dict(x=round(bx), y=round(by), w=round(w / f), h=round(h / f)))
    return best[1] if best else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="method", required=True)
    s1 = sub.add_parser("pin-silk", help="PDF文本层引脚号丝印 → 全引脚坐标")
    s1.add_argument("--pdf", required=True)
    s1.add_argument("--out")
    s2 = sub.add_parser("body", help="渲染图暗矩形本体检测")
    s2.add_argument("--img", required=True)
    s2.add_argument("--near", required=True, help="标签位置 x,y (300dpi px)")
    s2.add_argument("--radius", type=int, default=420)
    s3 = sub.add_parser("contour", help="线稿Canny矩形(备选)")
    s3.add_argument("--img", required=True)
    s3.add_argument("--near", required=True)
    s3.add_argument("--radius", type=int, default=400)
    args = ap.parse_args()

    if args.method == "pin-silk":
        ics = method_pin_silk(args.pdf)
        print(json.dumps(ics, indent=1, ensure_ascii=False))
        print(f"# 检出 {len(ics)} 个 IC (含引脚坐标)")
        if args.out:
            json.dump(ics, open(args.out, "w"), indent=1, ensure_ascii=False)
    elif args.method == "body":
        x, y = (float(v) for v in args.near.split(","))
        r = method_body(args.img, (x, y), args.radius)
        print(json.dumps(r, indent=1) if r else "未检出")
    else:
        x, y = (float(v) for v in args.near.split(","))
        r = method_contour(args.img, (x, y), args.radius)
        print(json.dumps(r, indent=1) if r else "未检出")


if __name__ == "__main__":
    main()
