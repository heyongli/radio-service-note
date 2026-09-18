#!/usr/bin/env python3
"""tools/sch-true-finding/de_annotate.py — 去除信号流标注线 (de-annotation)

注意: 本工具名为 de-annotation, 而非 de-greenline —— 它去除全部彩线标注
(绿=RX/红=TX/黄=控制/青=common), --color green 仅是其中一个选项 (兼容旧称).

purpose: 从原理图中去除信号流标注线 (绿=RX/红=TX/黄=控制/青=common),
        得到"标注从未存在"的纯净底图. 标注线叠在深色走线上 (best_practices §4),
        直接丢弃即可; 但边界有深色描边 (抗锯齿), 需扩展掩膜覆盖.
format: Python 3 + OpenCV
version: 0.3 (2026-09-17) — 分通道掩膜修正 (每色显式 ops) + 自监督桥恢复 + 指标报告

算法 (独立模式, 默认):
  1. 核心掩膜: 颜色阈值 (对应色, 每色显式通道关系)
  2. 描边扩展: 色相范围 + 灰度 40-200 (深色非纯黑) + 非核心
  3. 掩膜像素置白 (丢弃)

算法 (--restore 桥恢复, 2026-09-17):
  去标注时走线会随标注一起被删 (标注叠在走线上, 局部变色) -> net 连通域被切碎
  (实测 main_CC 120 块). 自监督恢复 (architecture §14.1f-2 + 实测):
  - 分通道核心掩膜 (比统一 chandiff 更准: 主net损失 35.5%->20.2%)
  - 细走线成分 (dt<=wire_radius, 面积+长度远大于干扰, 排除符号体/label)
  - 标注段邻接 >=2 个细走线成分 = 桥 (走线上的标注) -> 恢复为走线色
  - 其余标注 -> 置白
  - 指标 (--metrics): local 连通性 (标注区走线不丢失), 被去除区域连通性
      不能大变 (segments_cutting_wire~0), main_net 保留率. 自监督 = 用指标
      判断好坏 (agent 判断依据), 不是程序模式.

用法:
  python3 de_annotate.py --img sch.png --out sch_no_green.png          # 去绿线 (兼容)
  python3 de_annotate.py --img sch.png --out sch_no_annot.png --color all   # 去全部标注
  python3 de_annotate.py --img sch.png --out x.png --color all --restore     # 桥恢复
  python3 de_annotate.py --img sch.png --out x.png --color all --metrics m.json   # 指标

消费方: sch_wire (走线识别前去除标注干扰) 等.
"""

import argparse
import json
import sys

import cv2
import numpy as np

# 标注色中心 (OpenCV 色相 0-180): green=70, red=160, cyan=90, yellow=30
# ops: 每色显式通道关系 (通道, 算子, 阈值). core_mask 按 ops 计算, 不再假设"绿式".
COLOR_SPEC = {
    "green":  {"h_center": 70, "h_tol": 12,
               "ops": [("g", ">", 120), ("r", "<", 110), ("b", "<", 110)]},
    "red":    {"h_center": 160, "h_tol": 12,
               "ops": [("r", ">", 150), ("g", "<", 110), ("b", "<", 200)],
               "h_ranges": [(0, 25), (150, 170)]},  # 红橙(TX) + 品红
    "cyan":   {"h_center": 90, "h_tol": 10,
               "ops": [("g", ">", 120), ("r", "<", 110), ("b", ">", 120)]},
    "yellow": {"h_center": 30, "h_tol": 12,
               "ops": [("g", ">", 120), ("r", ">", 120), ("b", "<", 100)]},
}


def core_mask(img, spec, g_th=None, r_th=None, b_th=None, hsv=None):
    """核心掩膜 (按 spec['ops'] 显式通道关系计算). g_th/r_th/b_th 覆写对应通道.

    spec 带 h_ranges 时强制色相 (如红=橙红+品红, 防灰暖色误入).
    """
    b, g, r = cv2.split(img.astype(int))
    override = {"g": g_th, "r": r_th, "b": b_th}
    cond = np.ones(img.shape[:2], bool)
    for ch, op, thr in spec["ops"]:
        v = {"g": g, "r": r, "b": b}[ch]
        t = override[ch] if override[ch] is not None else thr
        if op == ">":
            cond &= (v > t)
        else:
            cond &= (v < t)
    if spec.get("h_ranges"):
        if hsv is None:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h = hsv[:, :, 0]
        hm = np.zeros(img.shape[:2], bool)
        for lo, hi in spec["h_ranges"]:
            hm |= (h >= lo) & (h <= hi)
        cond &= hm
    return cond.astype(np.uint8)


def hue_mask(img, spec, gray_lo=40, gray_hi=200, h_tol=None, s_min=30):
    """色相掩膜 (标注色 + 灰度范围). 用于核心掩膜补充 (抗锯齿边缘).

    支持 h_ranges (多色相范围, 如红=橙红0-25 + 品红150-170).
    s_min: 饱和度下限 (关键!). 灰像素色相是噪声, 无饱和度约束会把大量灰色
      抗锯齿边/走线误当标注 (实测 red edge 568k 中 344k sat==0). 真标注
      边缘高饱和 (绿/青 sat p50>250), s_min=30 保留 99%, red 假阳性 -344k.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    gv = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if spec.get("h_ranges"):
        hm = np.zeros(img.shape[:2], np.uint8)
        for lo, hi in spec["h_ranges"]:
            hm |= ((h >= lo) & (h <= hi)).astype(np.uint8)
    else:
        hc = spec["h_center"]
        tol = h_tol if h_tol is not None else spec["h_tol"]
        # 色相环上取范围 (含 0/180 环绕)
        if hc - tol < 0:
            hm = ((h >= hc - tol + 180) | (h <= hc + tol)).astype(np.uint8)
        elif hc + tol > 180:
            hm = ((h >= hc - tol) | (h <= hc + tol - 180)).astype(np.uint8)
        else:
            hm = ((h >= hc - tol) & (h <= hc + tol)).astype(np.uint8)
    return ((hm > 0) & (gv >= gray_lo) & (gv < gray_hi) & (s > s_min)).astype(np.uint8)


def annotation_mask(img, color="green", g_th=None, r_th=None, b_th=None,
                    gray_lo=40, gray_hi=200, h_tol=None, wire_net=None,
                    s_min=0, diff_th=0, edge=True):
    """标注线掩膜. color: green/red/cyan/yellow/all.

    diff_th (BGR 通道差法, 推荐): >0 时用 maxdiff = max(|G-R|,|G-B|,|R-B|),
      通道差 > diff_th = 标注 (彩色), 保留低通道差 (灰走线).
      **比 HSV 可靠**: 走线灰 → 通道差≈0, 标注彩色 → 通道差大;
      暗走线在 HSV 下饱和/色相噪声大会误删.
    s_min: 饱和度下限 (原 HSV 方法, 默认0全收).
    edge: 是否包含色相描边扩展 (自监督模式建议 False, 防吃走线边).
    wire_net: 若给, 只保留 wire 导体结构上的标注 (高置信约束, 防误删)."""
    if diff_th > 0:
        b, g, r = cv2.split(img.astype(int))
        maxdiff = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
        total = (maxdiff > diff_th).astype(np.uint8)
        if wire_net is not None:
            total = (total & wire_net).astype(np.uint8)
        return total
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1]
    colors = list(COLOR_SPEC) if color == "all" else [color]
    total = None
    for c in colors:
        spec = COLOR_SPEC[c]
        core = core_mask(img, spec, g_th, r_th, b_th, hsv)
        m = core
        if edge:
            edge_m = hue_mask(img, spec, gray_lo, gray_hi, h_tol)
            m = ((core > 0) | (edge_m > 0)).astype(np.uint8)
        if s_min > 0:
            m = (m & (s > s_min)).astype(np.uint8)
        total = m if total is None else ((total > 0) | (m > 0)).astype(np.uint8)
    if wire_net is not None and total is not None:
        total = (total & wire_net).astype(np.uint8)
    return total


def bridge_restore(img, annot, dark_th=150, wire_radius=3, min_bridge_wire=2):
    """自监督桥恢复 + 分区参数化 (2026-09-17).

    原理 (architecture §14.1f 应然态): 去标注后走线连通性不恶化.
    - 细走线成分 (dt<=wire_radius) = 真实走线 (面积+长度远大于干扰, 排除 label/符号体)
    - 标注段邻接 >=min_bridge_wire 个细走线成分 -> 该段是"走线上的标注" (桥)

    **分区参数化 (用户设计, 2026-09-17)**: 不全局共享一组参数.
    - 每个标注段独立处理, 用自己的**局部走线宽度**定恢复核宽
      (局部走线厚度 = 邻接细走线 dt 中位数 → 核宽 = 2*med+2, 段间不同).
    - 每段恢复核 = 该段中轴脊膨胀到局部核宽 (防粗线, 走线宽度自适应).
    - 每段做**局部连通性校验** (运算区域内连通域数 before/after 对比):
      段窗口内 after_CC - before_CC > 0 = 该段断开走线 (连通性变化), 报告.

    返回 (core_mask, metrics_dict). core_mask = 各桥段细核的并集.
    """
    from scipy import ndimage as ndi
    from collections import defaultdict

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark = (gray < dark_th).astype(np.uint8)
    annot_b = (annot > 0)
    surv = (dark > 0) & (~annot_b)

    dt = ndi.distance_transform_edt(surv)
    wire_like = (dt > 0) & (dt <= wire_radius)
    nw, w_lab = cv2.connectedComponentsWithStats(wire_like.astype(np.uint8), 8)[:2]
    nu, u_lab = cv2.connectedComponentsWithStats(annot.astype(np.uint8), 8)[:2]
    u_stats = cv2.connectedComponentsWithStats(annot.astype(np.uint8), 8)[2]

    # vectorized adjacency: ONLY on annotation pixels (需要去除的部分), 9-neighborhood
    # 正确: 标注像素自身 annot 标签 × 其 9 邻域内的 wire 标签 (wire 与 annot 不相交)
    H, W = annot.shape
    shifts = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    ys, xs = np.nonzero(annot)
    N = len(ys)
    nbr_w = np.empty((9, N), np.int32)
    for i, (dy, dx) in enumerate(shifts):
        y2 = np.clip(ys + dy, 0, H - 1)
        x2 = np.clip(xs + dx, 0, W - 1)
        nbr_w[i] = w_lab[y2, x2]
    a_self = u_lab[ys, xs]
    m = nbr_w > 0
    aw = np.repeat(a_self[None, :], 9, axis=0)
    pairs = np.unique(np.stack([aw[m], nbr_w[m]], axis=1), axis=0)

    adj = defaultdict(set)
    for a, w in pairs:
        adj[int(a)].add(int(w))

    bridge_ids = set()
    removed_w_2plus = 0
    for uc, wset in adj.items():
        if len(wset) >= min_bridge_wire:
            bridge_ids.add(uc)
        elif len(wset) >= 2:
            removed_w_2plus += 1

    # ---- 分区参数化: 每桥段用局部走线宽度定核宽, 生成细核 ----
    # 性能: 每段只在自身 bbox+margin 窗口内做形态学, 不做全图 filter
    core = np.zeros_like(annot, bool)
    margin = 15
    cc_before_after = []   # (seg_id, before_cc, after_cc, delta)
    for uc in sorted(bridge_ids):
        x0, y0, w0, h0 = u_stats[uc, 0], u_stats[uc, 1], u_stats[uc, 2], u_stats[uc, 3]
        xa, xb = max(0, x0 - margin), min(W, x0 + w0 + margin)
        ya, yb = max(0, y0 - margin), min(H, y0 + h0 + margin)
        seg_w = (u_lab[ya:yb, xa:xb] == uc)
        # 局部走线厚度 = 邻接细走线 dt (走线残端全宽, 用 p90 防被标注侵蚀的低估)
        dil = ndi.maximum_filter(seg_w.astype(np.uint8), size=7)
        wl_w = wire_like[ya:yb, xa:xb]
        wdt = dt[ya:yb, xa:xb][(dil > 0) & wl_w]
        p90 = float(np.percentile(wdt, 90)) if len(wdt) else float(wire_radius)
        # 奇数核宽 (偶数 footprint 无中心像素, 膨胀错位导致连不上), 最小5
        seg_width = int(np.clip(2 * round(p90) + 3, 5, 13))
        # 该段细核 = 中轴脊膨胀到 seg_width (窗口内)
        dt_s = ndi.distance_transform_edt(seg_w.astype(np.uint8))
        ridge = (dt_s == ndi.maximum_filter(dt_s, size=3)) & seg_w
        cseg = ndi.maximum_filter(ridge, size=seg_width) & seg_w
        core[ya:yb, xa:xb] |= cseg
        # ---- 局部连通性校验 (运算区域内 before/after) ----
        bb = dark[ya:yb, xa:xb]
        ab = ((surv | core)[ya:yb, xa:xb])
        nbb = cv2.connectedComponents(bb.astype(np.uint8), 8)[0] - 1
        nab = cv2.connectedComponents(ab.astype(np.uint8), 8)[0] - 1
        cc_before_after.append((int(uc), int(nbb), int(nab), int(nab - nbb)))

    bridge = np.zeros_like(annot, bool)
    for uc in bridge_ids:
        bridge |= (u_lab == uc)

    # metrics
    n, lab, st, _ = cv2.connectedComponentsWithStats(dark, 8)
    mi = int(np.argmax(st[1:, 4])) + 1
    main_area = int(st[mi, 4])
    final = surv | core
    nf, lf, sf, _ = cv2.connectedComponentsWithStats(final.astype(np.uint8), 8)
    in_main = final & (lab == mi)
    nc, _, _, _ = cv2.connectedComponentsWithStats(in_main.astype(np.uint8), 8)
    kept = int((final & (lab == mi)).sum())

    deltas = [d[3] for d in cc_before_after]
    n_conn_changed = sum(1 for d in deltas if d > 0)
    metrics = {
        "annot_total": int(annot.sum()),
        "bridge_restored": int(core.sum()),
        "removed": int(annot.sum()) - int(core.sum()),
        "wire_cc": int(nw - 1),
        "main_net": {"area_before": main_area, "kept": kept,
                     "kept_pct": round(kept / main_area, 4), "main_cc_after": int(nc - 1)},
        "local_connectivity": {"segments": int(nu - 1),
                               "bridges": len(bridge_ids),
                               "removed_segments": int(nu - 1 - len(bridge_ids))},
        "removed_region_delta": {"segments_cutting_wire": removed_w_2plus,
                                 "segments_conn_changed": n_conn_changed,
                                 "max_conn_delta": max(deltas) if deltas else 0,
                                 "cc_after": int(nf - 1)},
    }
    return core, metrics


def thin_to_wire(bridge, full_width=5):
    """桥恢复只填细走线核: 桥的中轴脊 (ridge) 膨胀到走线宽.

    绿色带常比走线宽 (实测绿带 12px vs 走线 2-4px). 整条桥填走线色会留粗线
    (残留粗线 = 自监督指标, architecture §14.1f). 只恢复脊膨胀到 full_width,
    多余部分置白 → 连通保持 + 无线宽污染.
    """
    from scipy import ndimage as ndi
    dt_b = ndi.distance_transform_edt(bridge.astype(np.uint8))
    ridge = (dt_b == ndi.maximum_filter(dt_b, size=3)) & (bridge > 0)
    core = ndi.maximum_filter(ridge, size=full_width) & (bridge > 0)
    return core


def residual_thick_metric(out, annot, dark_th=150, wire_radius=3):
    """残留粗线指标 (architecture §14.1f): 输出中"原标注位置"的暗像素,
    厚度半宽 > wire_radius 的数量. 应然: 残留粗线 ≈ 走线宽, 远小于标注宽."""
    from scipy import ndimage as ndi
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    od = gray < dark_th
    dt = ndi.distance_transform_edt(od)
    resid = od & (annot > 0) & (dt > wire_radius)
    return int(resid.sum())


def wire_fill_color(img, surv):
    """估计走线颜色 (surv 像素中位数), 用于桥恢复填充."""
    px = img[surv > 0]
    if len(px):
        return np.median(px, axis=0).astype(np.uint8)
    return np.array([30, 30, 30], np.uint8)


def de_annotation(img, mask, fill=255):
    """去除标注线: 掩膜像素用 fill 填充."""
    out = img.copy()
    out[mask > 0] = fill
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--color", default="green",
                    choices=["green", "red", "cyan", "yellow", "all"],
                    help="去除哪种标注 (green=RX/red=TX/yellow=控制/cyan=common/all)")
    ap.add_argument("--fill", type=int, default=255, help="填充色 (255=白)")
    ap.add_argument("--g-th", type=int, default=None)
    ap.add_argument("--r-th", type=int, default=None)
    ap.add_argument("--b-th", type=int, default=None)
    ap.add_argument("--h-tol", type=int, default=None, help="色相容差 (覆盖 spec)")
    ap.add_argument("--s-min", type=int, default=0,
                    help="饱和度下限 (标注高饱和; >80 排除低饱和走线, 防误删)")
    ap.add_argument("--diff-th", type=int, default=0,
                    help="BGR 通道差阈值 (标注识别最佳; >40=彩色标注, 保留灰走线)")
    ap.add_argument("--dark-th", type=int, default=150,
                    help="暗像素阈值 (走线/net 判定, 默认150)")
    ap.add_argument("--gray-lo", type=int, default=40, help="排除纯黑走线下限")
    ap.add_argument("--gray-hi", type=int, default=200, help="排除亮背景上限")
    ap.add_argument("--wire-net", default=None,
                    help="wire net 掩膜 PNG (只去除其上的标注, 防误删)")
    ap.add_argument("--restore", action="store_true",
                    help="桥恢复 (标注段邻接>=2细走线=走线上标注, 填走线色; 修复连通域切碎)")
    ap.add_argument("--wire-radius", type=int, default=3,
                    help="细走线判定半径 (dt<=此值=走线, 排除符号体)")
    ap.add_argument("--min-bridge-wire", type=int, default=2,
                    help="桥恢复所需邻接细走线成分数")
    ap.add_argument("--no-edge", action="store_true",
                    help="用纯核心掩膜 (不吃走线抗锯齿边; 默认独立模式含描边扩展)")
    ap.add_argument("--bridge-width", type=int, default=5,
                    help="桥恢复只填细走线核 (脊膨胀全宽; 防残留粗线, 实测走线全宽~4-5)")
    ap.add_argument("--wire-lum", type=int, default=0,
                    help="亮度保走线 (用户洞察: 绿标注与走线融合区, 按亮度更暗判走线). "
                         ">0 时: 去除=标注 & 亮度>=wire_lum, 保留=标注 & 亮度<wire_lum "
                         "(染回走线色). 实测 L=120 → main_kept 98.8% main_CC=5")
    ap.add_argument("--metrics", default=None,
                    help="自监督指标 JSON 输出 (两种模式均可, 供 agent 判断好坏)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    wn = None
    if args.wire_net:
        wn = cv2.imread(args.wire_net, cv2.IMREAD_GRAYSCALE)
        if wn is None:
            sys.exit(f"cannot read wire net {args.wire_net}")
        wn = (wn > 0).astype(np.uint8)

    # 桥恢复用纯核心掩膜 (更准, 不吃走线边); 独立模式默认含描边扩展
    edge = not args.no_edge
    if args.restore:
        edge = False
    mask = annotation_mask(img, args.color, args.g_th, args.r_th, args.b_th,
                           args.gray_lo, args.gray_hi, args.h_tol, wn,
                           args.s_min, args.diff_th, edge=edge)

    metrics = None
    if args.restore:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        dark = (gray < args.dark_th).astype(np.uint8)
        # 亮度保走线 (用户洞察): 去除=标注 & 亮度>=wire_lum; 保留=标注 & 亮度<wire_lum
        if args.wire_lum > 0:
            keep = (mask > 0) & (gray < args.wire_lum)
            remask = (mask > 0) & (gray >= args.wire_lum)
        else:
            keep = np.zeros_like(mask, bool)
            remask = mask > 0
        core, metrics = bridge_restore(img, mask, dark_th=args.dark_th,
                                       wire_radius=args.wire_radius,
                                       min_bridge_wire=args.min_bridge_wire)
        out = de_annotation(img, remask.astype(np.uint8), args.fill)
        wcolor = wire_fill_color(img, (dark > 0) & (remask == 0))
        # 保留的暗彩色 (绿融合走线) 染回走线色; 桥核也染回走线色
        out[keep > 0] = wcolor
        out[core > 0] = wcolor
        cv2.imwrite(args.out, out)
        resid = residual_thick_metric(out, (remask > 0) | keep, args.dark_th, args.wire_radius)
        metrics["residual_thick_gt_wire"] = resid
        metrics["wire_lum_kept"] = int(keep.sum())
        metrics["removed"] = int(remask.sum())
        metrics["annot_total"] = int(mask.sum())
        print(f"[de-annotation:restore] removed {metrics['removed']} px, "
              f"lum_kept={int(keep.sum())}, restored {int(core.sum())} px wire-core, "
              f"main_net kept {metrics['main_net']['kept_pct']:.1%} "
              f"main_CC={metrics['main_net']['main_cc_after']}, "
              f"cutting_segments={metrics['removed_region_delta']['segments_cutting_wire']}, "
              f"conn_changed={metrics['removed_region_delta']['segments_conn_changed']}, "
              f"residual_thick={resid}, saved {args.out}")
    else:
        out = de_annotation(img, mask, args.fill)
        cv2.imwrite(args.out, out)
        print(f"[de-annotation] color={args.color} removed {int(mask.sum())} px, "
              f"fill={args.fill}, wire_net={'on' if wn is not None else 'off'}, "
              f"saved {args.out}")

    if args.metrics:
        if metrics is None:
            metrics = _independent_metrics(img, mask, args.dark_th)
        metrics["_meta"] = {
            "purpose": "de-annotation self-supervised metrics",
            "format": "json", "version": "0.3",
            "source": args.img, "params": vars(args),
        }
        with open(args.metrics, "w") as f:
            json.dump(metrics, f, indent=1, ensure_ascii=False)
        print(f"[de-annotation] metrics saved {args.metrics}")


def _independent_metrics(img, annot, dark_th=150):
    """独立模式 (不恢复) 的指标: 去除量 + 主 net 连通性 (供判断碎片化)."""
    from scipy import ndimage as ndi
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark = (gray < dark_th).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(dark, 8)
    mi = int(np.argmax(st[1:, 4])) + 1
    main_area = int(st[mi, 4])
    surv = (dark > 0) & (annot == 0)
    kept = int((surv & (lab == mi)).sum())
    in_main = (surv > 0) & (lab == mi)
    nc, _, _, _ = cv2.connectedComponentsWithStats(in_main.astype(np.uint8), 8)
    return {
        "annot_total": int(annot.sum()),
        "bridge_restored": 0,
        "removed": int(annot.sum()),
        "main_net": {"area_before": main_area, "kept": kept,
                     "kept_pct": round(kept / main_area, 4),
                     "main_cc_after": int(nc - 1)},
        "removed_region_delta": {"segments_cutting_wire": None,
                                 "cc_after": int(nc - 1)},
    }


if __name__ == "__main__":
    main()