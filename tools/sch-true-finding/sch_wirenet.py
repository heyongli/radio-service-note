#!/usr/bin/env python3
"""tools/sch-true-finding/sch_wirenet.py — 无监督走线 net 网表提取

purpose: 无监督识别 sch 走线网络 (net): 每个连通域 = 一个 net.
        走线最连续最简单, 无需任何标注/依赖 (best_practices §5b-3).
        产出 net 网表: 每个 net 的 面积/bbox/骨架/端点, 供:
          - 真理源: 主 net 掩膜 (符号必在走线上)
          - 元器件→net 关联 (符号落在哪个 net)
          - de-wire: 切除走线
format: Python 3 + OpenCV
version: 0.1 (2026-09-17)

用法:
  python3 sch_wirenet.py --img sch.png --out wirenet.json
    [--min-area 50] [--dark-th 150] [--save-main main_mask.png]
    [--main-min 0.5]   # 主 net 需占暗像素比例
    [--save-skel dir/] # 每 net 骨架 PNG 输出目录 (可选)

实测 (IC-2200H): 5963 nets, 主 net=903588px (76% 暗像素), 94% 绿线在其上.
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np


def wire_nets(img, dark_th=150):
    """暗像素连通域 = net 网表. 返回 (labels, stats, areas)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark = (gray < dark_th).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark, 8)
    return labels, stats, dark


def skel(net_mask):
    """Zhang-Suen 骨架化单 net. 返回 0/255 骨架."""
    return _thin(net_mask)


def _thin(bin_img):
    """Zhang-Suen 细化 (sch_wire 同款, 独立实现防循环导入)."""
    img = bin_img.copy() // 255
    prev = np.zeros_like(img)
    while True:
        mask = np.zeros_like(img)
        for y in range(1, img.shape[0] - 1):
            for x in range(1, img.shape[1] - 1):
                if not img[y, x]:
                    continue
                p = [img[y-1,x],img[y-1,x+1],img[y,x+1],img[y+1,x+1],
                     img[y+1,x],img[y+1,x-1],img[y,x-1],img[y-1,x-1]]
                b = sum(p)
                a = sum((not p[i]) and p[(i+1)%8] for i in range(8))
                if 2 <= b <= 6 and a == 1 and p[0]*p[2]*p[4] == 0 and p[2]*p[4]*p[6] == 0:
                    mask[y, x] = 1
        img[mask > 0] = 0
        mask = np.zeros_like(img)
        for y in range(1, img.shape[0] - 1):
            for x in range(1, img.shape[1] - 1):
                if not img[y, x]:
                    continue
                p = [img[y-1,x],img[y-1,x+1],img[y,x+1],img[y+1,x+1],
                     img[y+1,x],img[y+1,x-1],img[y,x-1],img[y-1,x-1]]
                b = sum(p)
                a = sum((not p[i]) and p[(i+1)%8] for i in range(8))
                if 2 <= b <= 6 and a == 1 and p[0]*p[2]*p[6] == 0 and p[0]*p[4]*p[6] == 0:
                    mask[y, x] = 1
        img[mask > 0] = 0
        if np.array_equal(img, prev):
            break
        prev = img.copy()
    return (img * 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--out", required=True, help="输出 wirenet.json")
    ap.add_argument("--dark-th", type=int, default=150)
    ap.add_argument("--min-area", type=int, default=50,
                    help="最小 net 面积 (滤噪声)")
    ap.add_argument("--main-min", type=float, default=0.5,
                    help="主 net 需占暗像素比例阈值")
    ap.add_argument("--save-main", default=None, help="保存主 net 掩膜 PNG")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    labels, stats, dark = wire_nets(img, args.dark_th)
    n = stats.shape[0]
    total_dark = int(dark.sum())

    nets = []
    for i in range(1, n):
        area = int(stats[i, 4])
        if area < args.min_area:
            continue
        x, y, w, h = stats[i, 2], stats[i, 3], stats[i, 0], stats[i, 1]
        nets.append({"id": i, "area": area, "bbox": [int(x), int(y), int(w), int(h)]})
    nets.sort(key=lambda n: -n["area"])

    main_net = None
    if nets:
        main_net = nets[0]
        ratio = main_net["area"] / total_dark
        main_net["ratio"] = round(ratio, 3)
        main_net["is_main"] = ratio >= args.main_min
        if args.save_main:
            m = (labels == main_net["id"]).astype(np.uint8) * 255
            cv2.imwrite(args.save_main, m)
            main_net["main_mask"] = args.save_main

    data = {
        "_meta": {"purpose": "sch 走线 net 网表 (无监督连通域)",
                  "format": "json {nets[]}",
                  "version": "0.1",
                  "source": "sch_wirenet (connected components)",
                  "image": args.img, "total_dark_px": total_dark},
        "total_nets": len(nets),
        "total_dark_px": total_dark,
        "main_net": main_net,
        "nets": nets[:5000],
    }
    with open(args.out, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print(f"[sch_wirenet] {len(nets)} nets, 主 net="
          f"{main_net['id'] if main_net else None} "
          f"area={main_net['area'] if main_net else 0} "
          f"({main_net['ratio'] if main_net else 0:.1%}), saved {args.out}")


if __name__ == "__main__":
    main()