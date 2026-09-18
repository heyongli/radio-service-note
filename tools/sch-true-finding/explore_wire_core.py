#!/usr/bin/env python3
"""tools/sch-true-finding/explore_wire_core.py — 探索"标注覆盖下走线细芯"提取方法

purpose: chandiff 去标注对绿色标注可能丢线 (绿与走线色调融合). 色调分不开,
        探索**其他图像手段** (结构/亮度相对性) 提取被覆盖的走线细芯:
        只保留每个彩色段内最暗的细芯 (走线), 染回走线色; 其余置白.
        不改动现有 de_annotate_chandiff.py (探索独立).
format: Python 3 + OpenCV
version: 0.1 (2026-09-17)

方法 (每彩色段, 窗口内向量化):
  M1 段内亮度分位数芯: 每段保留亮度最低的 --frac 像素 (相对暗, 非全局)
  M2 段内中轴脊芯: 每段骨架中轴膨胀到局部走线宽
  M3 形态学黑帽: 细暗结构 (走线) 提取, 去掉宽带 (标注)

输出: 每种方法指标 + 最优方法 final PNG (到项目 annot/).
"""

import argparse
import json
import sys

import cv2
import numpy as np
from scipy import ndimage as ndi

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from sch_wirenet import _thin


def load_masks(img, diff_th=40, dark_th=150):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b, g, r = cv2.split(img.astype(int))
    md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    colored = md > diff_th
    dark = gray < dark_th
    return gray, colored, dark, md


def per_segment_windows(colored, margin=15):
    """yield (uc, xa, xb, ya, yb, seg_win) for colored CCs (窗口内)."""
    nu, u_lab, u_stats, _ = cv2.connectedComponentsWithStats(colored.astype(np.uint8), 8)
    H, W = colored.shape
    for uc in range(1, nu):
        x0, y0, w0, h0 = u_stats[uc, 0], u_stats[uc, 1], u_stats[uc, 2], u_stats[uc, 3]
        xa, xb = max(0, x0 - margin), min(W, x0 + w0 + margin)
        ya, yb = max(0, y0 - margin), min(H, y0 + h0 + margin)
        yield uc, xa, xb, ya, yb, (u_lab[ya:yb, xa:xb] == uc)


def method_lum_core(gray, colored, frac=0.25):
    """M1: 每段保留亮度最低 frac 的像素为芯."""
    keep = np.zeros_like(colored, bool)
    for _, xa, xb, ya, yb, seg in per_segment_windows(colored):
        if seg.sum() == 0:
            continue
        gv = gray[ya:yb, xa:xb]
        th = np.percentile(gv[seg], frac * 100)
        keep[ya:yb, xa:xb] |= seg & (gv < th)
    return keep


def method_ridge_core(colored, dark, dark_th=150, wire_radius=3, fixed_width=0):
    """M2: 每段中轴脊膨胀到局部走线宽. fixed_width>0 时用固定核宽 (扫权衡)."""
    keep = np.zeros_like(colored, bool)
    surv = (dark > 0) & (~colored)
    dt = ndi.distance_transform_edt(surv)
    wire_like = (dt > 0) & (dt <= wire_radius)
    for _, xa, xb, ya, yb, seg in per_segment_windows(colored):
        if seg.sum() < 4:
            continue
        if fixed_width > 0:
            seg_width = fixed_width
        else:
            wl = wire_like[ya:yb, xa:xb]
            wdt = dt[ya:yb, xa:xb][wl]
            p90 = float(np.percentile(wdt, 90)) if len(wdt) else float(wire_radius)
            seg_width = int(np.clip(2 * round(p90) + 3, 5, 13))
        dt_s = ndi.distance_transform_edt(seg.astype(np.uint8))
        ridge = (dt_s == ndi.maximum_filter(dt_s, size=3)) & seg
        cseg = ndi.maximum_filter(ridge, size=seg_width) & seg
        keep[ya:yb, xa:xb] |= cseg
    return keep


def method_blackhat(colored, wire_radius=3, band=6):
    """M3: 形态学黑帽提取细暗结构 (走线), 去掉宽带 (标注)."""
    inv = (colored > 0).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * wire_radius + 1, 2 * wire_radius + 1))
    kbig = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * band + 1, 2 * band + 1))
    opened = cv2.morphologyEx(inv, cv2.MORPH_OPEN, k)
    closed = cv2.morphologyEx(inv, cv2.MORPH_CLOSE, kbig)
    # 黑帽 = closed - inv: 窄缺口; 白帽 = inv - opened: 细亮枝 (细芯)
    thin = ((inv > 0) & (opened == 0)) | ((closed > 0) & (inv == 0))
    return thin


def build_output(img, colored, keep, wire_color):
    out = img.copy()
    out[colored & ~keep] = 255
    out[keep] = wire_color
    return out


def wire_color(img, colored):
    b, g, r = cv2.split(img.astype(int))
    md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
    surv = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 150) & (md <= 40)
    px = img[surv]
    return np.median(px, axis=0).astype(np.uint8) if len(px) else np.array([30, 30, 30], np.uint8)


def metrics(out, orig_dark, orig_lab, orig_mi, dark_th=150, diff_th=40, wire_radius=3):
    """对照原图主 net 的指标 (kept/main_CC 相对原图, 非输出自身)."""
    og = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    od = og < dark_th
    odt = ndi.distance_transform_edt(od)
    wide = int((od & (odt > wire_radius) & (odt <= 12)).sum())
    kept = int((od & (orig_lab == orig_mi)).sum())
    inm = od & (orig_lab == orig_mi)
    nc, _, _, _ = cv2.connectedComponentsWithStats(inm.astype(np.uint8), 8)
    ob, og2, or2 = cv2.split(out.astype(int))
    omd = np.maximum.reduce([np.abs(og2 - or2), np.abs(og2 - ob), np.abs(or2 - ob)])
    resid = int((od & (omd > diff_th)).sum())
    return {"main_kept": round(kept / orig_dark[orig_lab == orig_mi].sum(), 4),
            "main_cc": int(nc - 1), "wide": wide, "colored_resid": resid}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--out-final", required=True, help="最优方法 final PNG")
    ap.add_argument("--out-dir", default=".", help="各方法 PNG 输出目录")
    ap.add_argument("--diff-th", type=int, default=40)
    ap.add_argument("--dark-th", type=int, default=150)
    ap.add_argument("--frac", type=float, default=0.25, help="M1 段内最暗比例")
    ap.add_argument("--wire-radius", type=int, default=3)
    ap.add_argument("--metrics", default=None, help="指标 JSON 输出")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray, colored, dark, _ = load_masks(img, args.diff_th, args.dark_th)
    wc = wire_color(img, colored)
    n, lab, st, _ = cv2.connectedComponentsWithStats(dark.astype(np.uint8), 8)
    orig_mi = int(np.argmax(st[1:, 4])) + 1

    methods = {
        "lum_frac25": method_lum_core(gray, colored, 0.25),
        "lum_frac50": method_lum_core(gray, colored, 0.50),
        "ridge_p90": method_ridge_core(colored, dark, args.dark_th, args.wire_radius),
        "ridge_w5": method_ridge_core(colored, dark, args.dark_th, args.wire_radius, 5),
        "ridge_w7": method_ridge_core(colored, dark, args.dark_th, args.wire_radius, 7),
        "blackhat": method_blackhat(colored, args.wire_radius),
    }

    results = {}
    best = None
    import os
    os.makedirs(args.out_dir, exist_ok=True)
    # ---- 中间可视化 1: 彩色标注掩膜 (远程检查用) ----
    cv2.imwrite(os.path.join(args.out_dir, "vis_colored_mask.png"),
                (colored.astype(np.uint8) * 255))
    for name, keep in methods.items():
        out = build_output(img, colored, keep, wc)
        p = os.path.join(args.out_dir, f"explore_{name}.png")
        cv2.imwrite(p, out)
        # ---- 中间可视化 2: 核心高亮覆盖 (去标注底图 + 保留芯标红) ----
        ov = out.copy()
        ov[keep] = (0, 0, 255)
        cv2.imwrite(os.path.join(args.out_dir, f"vis_{name}_core_red.png"), ov)
        # ---- 中间可视化 3: 局部裁剪对比 (原图 | 去标注) ----
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        hmask = (hsv[:, :, 0] >= 55) & (hsv[:, :, 0] <= 90) & (gray < 150)
        ys, xs = np.nonzero(hmask)
        if len(ys) > 10:
            cy, cx = int(np.median(ys)), int(np.median(xs))
            R = 120
            c_o = img[max(0, cy-R):cy+R, max(0, cx-R):cx+R]
            c_d = out[max(0, cy-R):cy+R, max(0, cx-R):cx+R]
            c_k = np.zeros_like(c_o)
            c_k[keep[max(0, cy-R):cy+R, max(0, cx-R):cx+R]] = (0, 0, 255)
            h = max(c_o.shape[0], c_d.shape[0])
            pad = lambda a: cv2.copyMakeBorder(a, 0, h-a.shape[0], 0, 0,
                                               cv2.BORDER_CONSTANT, value=(255,255,255))
            mont = np.hstack([pad(c_o), pad(c_d), pad(c_k)])
            cv2.imwrite(os.path.join(args.out_dir, f"vis_{name}_crop.png"), mont)
        m = metrics(out, dark, lab, orig_mi, args.dark_th, args.diff_th,
                    args.wire_radius)
        results[name] = m
        print(f"[{name}] main_kept={m['main_kept']:.1%} main_CC={m['main_cc']} "
              f"wide={m['wide']} colored_resid={m['colored_resid']} -> {p}")
        # 最优 = 先避免厚线 (用户拒绝厚线), 再看连通, 最后保留率
        key = (m["wide"] > 60000, m["main_cc"], -m["main_kept"])
        if best is None or key < best[0]:
            best = (key, name, out)

    _, best_name, best_out = best
    cv2.imwrite(args.out_final, best_out)
    print(f"[best] {best_name} -> {args.out_final}")
    results["_best"] = best_name
    results["_meta"] = {"purpose": "explore_wire_core", "format": "json",
                        "version": "0.1", "source": args.img, "params": vars(args)}
    if args.metrics:
        with open(args.metrics, "w") as f:
            json.dump(results, f, indent=1, ensure_ascii=False)
        print(f"metrics saved {args.metrics}")


if __name__ == "__main__":
    main()