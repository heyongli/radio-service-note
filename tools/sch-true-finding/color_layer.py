#!/usr/bin/env python3
"""tools/sch-true-finding/color_layer.py — 信号颜色图层 (rx/tx color layer)

purpose: 用**图例准确色** (explanatory_notes.json) 输出**颜色图层**: 白底 +
        非目标内容调淡 (褪色) + 指定信号色高亮. 重要视觉结果: 一眼看出该
        信号的标注位置. 通用工具 (信号可组合, 如 RX+COMMON).
        **Stage-2 (--pure)**: 图层去灰 (饱和度阈值) → **纯区域图** (白底+
        纯目标色, 无灰色干扰).
format: Python 3 + OpenCV
version: 0.3 (2026-09-18)

用法:
  stage1 (图层): python3 color_layer.py --img sch-600.png \
    --legend explanatory_notes.json --signals RX --out rx_color_layer.png
  stage2 (纯区域图): ... --pure --sat-min 100 --out rx_line_region.png
  [--tol 60] [--fade 0.45] [--dark 150]
"""

import argparse
import json
import sys

import cv2
import numpy as np


def legend_colors(legend_json):
    with open(legend_json) as f:
        d = json.load(f)
    out = {}
    for e in d.get("entries", []):
        if e.get("color_bgr") and e.get("label"):
            out[e["label"].upper()] = e["color_bgr"]
    return out


def rgb_mask(img, sample_bgr, tol):
    b, g, r = cv2.split(img.astype(int))
    sb, sg, sr = sample_bgr
    return ((np.abs(b - sb) <= tol) & (np.abs(g - sg) <= tol)
            & (np.abs(r - sr) <= tol)).astype(np.uint8)


def legend_line_width(img, legend_json, tol=40):
    """从 legend 说明框量**参考线宽** (色样本条带厚度, 600dpi).

    说明框 (explanatory_notes.json _meta.box) 内有各信号色样本短条, 其厚度
    = 真实标注线宽. 取各色样本条带厚度的中位作参考.
    """
    with open(legend_json) as f:
        d = json.load(f)
    box = d.get("_meta", {}).get("box")
    if not box:
        return 0.0
    x, y, w, h = map(int, box)
    sub = img[max(0, y):y + h, max(0, x):x + w]
    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    thick = []
    for e in d.get("entries", []):
        if not e.get("color_bgr"):
            continue
        m = rgb_mask(sub, e["color_bgr"], tol) > 0
        if m.sum() == 0:
            continue
        # 色样本条带厚度 = 掩膜行方向的连续厚度 (多数行的厚度)
        rowsum = m.sum(1)
        runs = rowsum > 0
        if not runs.any():
            continue
        # 每列连续厚度
        colsum = m.sum(0)
        rr = colsum[colsum > 0]
        if len(rr):
            thick.append(float(np.median(rr)))
    return float(np.median(thick)) if thick else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--legend", required=True, help="explanatory_notes.json")
    ap.add_argument("--signals", required=True,
                    help="高亮哪些信号 (逗号分隔, 如 RX,COMMON / TX,COMMON)")
    ap.add_argument("--out", required=True, help="输出图 (如 rx_color_layer.png)")
    ap.add_argument("--tol", type=int, default=60, help="RGB 容差")
    ap.add_argument("--fade", type=float, default=0.45,
                    help="非目标内容褪色度: 向白混合比例 (0=全白, 1=原样; 目标信号突出)")
    ap.add_argument("--pure", action="store_true",
                    help="Stage-2: 图层去灰 (饱和度阈值) → 纯区域图 (白底+纯目标色)")
    ap.add_argument("--sat-min", type=int, default=100,
                    help="Stage-2 饱和度阈值 (灰度像素低饱和, 剔除; 目标信号高饱和保留)")
    ap.add_argument("--heal", action="store_true",
                    help="Stage-3: 线身填实 + 外1px边框")
    ap.add_argument("--continu", action="store_true",
                    help="Stage-3 先方向闭接续 (填同向间隙) 再填实; 默认不接续")
    ap.add_argument("--heal-k", type=int, default=0,
                    help="Stage-3 合并核. 0=自动用 legend 参考线宽 (色样本条带厚度)")
    ap.add_argument("--border", action="store_true",
                    help="Stage-3 额外加 1px 黑边框 (默认纯填实)")
    ap.add_argument("--stage4", action="store_true",
                    help="Stage-4: 合并面积相同的左右/上下两块 → 大矩形")
    ap.add_argument("--area-tol", type=float, default=0.15,
                    help="Stage-4 面积相同容差 (相对差)")
    ap.add_argument("--shape-tol", type=float, default=0.15,
                    help="Stage-4 形状匹配容差 (同宽同高, 防平行线误并)")
    ap.add_argument("--align-tol", type=int, default=12,
                    help="Stage-4 对齐容差 (左右对顶对齐/上下对左对齐, px)")
    ap.add_argument("--gap", type=int, default=20,
                    help="Stage-4 相邻间隙容差 (px)")
    ap.add_argument("--min-area", type=int, default=100,
                    help="最小区域面积 (滤噪声)")
    ap.add_argument("--min-fill", type=float, default=0.55,
                    help="Stage-4 自监督: 合并矩形最小填充率 (两块面积和/矩形面积; "
                         "长条并排高, 平行挤一起/交叉低=错)")
    ap.add_argument("--direction", action="store_true",
                    help="Stage-4b 走向探测: 每段箭头标走向 (chain_order 上下游判流向)")
    ap.add_argument("--chain", default=None,
                    help="走向探测用 chain_order JSON (上下游位置判流向); 缺省读 "
                         "projects/<机型>/nettable/chain_order_rx.json 模式")
    ap.add_argument("--upstream", nargs=2, type=int, default=None,
                    help="走向探测上游坐标 (不读 chain 时手动给)")
    ap.add_argument("--downstream", nargs=2, type=int, default=None,
                    help="走向探测下游坐标")
    ap.add_argument("--compact", action="store_true",
                    help="Stage-4 只合并紧凑矩形块 (自身bbox填充率高, 排除细长条碎片)")
    ap.add_argument("--compact-fill", type=float, default=0.5,
                    help="紧凑块判据: 自身 bbox 填充率 >= 此值")
    ap.add_argument("--contained", action="store_true",
                    help="Stage-4 长度包含合并: 一块范围含在另一块内+相邻")
    ap.add_argument("--close-k", type=int, default=0,
                    help="沿邻近绿填缝核. 0=自动用 legend 参考线宽 (缝隙<=线宽=同一条线, "
                         ">线宽=不同线不填)")
    ap.add_argument("--holefill", action="store_true",
                    help="Stage-4b: 小闭运算填走线缝 → bbox填充高=矩形 → 填实")
    ap.add_argument("--hole-ratio", type=float, default=0.7,
                    help="矩形有孔判据: 自身 bbox 填充率 < 此值 (有孔)")
    ap.add_argument("--rect-ratio", type=float, default=0.85,
                    help="矩形有孔判据: fill_holes 后 bbox 填充率 >= 此值 (外轮廓矩形)")
    ap.add_argument("--wire-ratio", type=float, default=0.6,
                    help="矩形有孔判据: 空洞中暗走线占比 >= 此值 (走线穿过的孔)")
    ap.add_argument("--gray-bg", action="store_true",
                    help="背景只留灰度 (其它彩色像素也变灰)")
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    colors = legend_colors(args.legend)
    if not colors:
        sys.exit("legend 无色彩样本")

    want = [s.strip().upper() for s in args.signals.split(",")]
    targets = {k: v for k, v in colors.items() if any(w in k for w in want)}
    if not targets:
        sys.exit(f"legend 无 {args.signals} 色")

    # 图层效果 (用户定稿): 白底 + 非目标内容**调淡** (向白混合, 变浅不黑) + 目标信号彩色
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    content = gray < 245                                   # 非背景 (白底排除)
    faded = np.clip(gray * args.fade + 255 * (1 - args.fade), 0, 255).astype(np.uint8)
    out = np.full_like(img, 255)
    out[content, 0] = faded[content]
    out[content, 1] = faded[content]
    out[content, 2] = faded[content]
    # 目标信号像素恢复彩色
    for label, bgr in targets.items():
        m = rgb_mask(img, bgr, args.tol) > 0
        out[m] = img[m]
    if args.pure:
        # Stage-2: 去灰 (饱和度阈值) → 纯区域图 (白底+纯目标色)
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1] > args.sat_min
        pure = np.full_like(img, 255)
        pure[sat] = out[sat]
        out = pure
    if args.heal:
        # Stage-3 (用户定稿): 线身**填实** (直接 legend 准确色掩膜) + 外 1px 边框.
        #   可选方向闭接续 (--continu); 宽度约束不增宽.
        from scipy import ndimage as ndi
        ksize = args.heal_k if args.heal_k > 0 else int(legend_line_width(img, args.legend))
        if ksize <= 0:
            ksize = 13
        print(f"[stage3-heal] 参考线宽={ksize}px (直接色掩膜填实+1px框)")
        merged = np.zeros(img.shape[:2], bool)
        for label, bgr in targets.items():
            merged |= rgb_mask(img, bgr, args.tol) > 0
        if args.continu:
            kh = cv2.getStructuringElement(cv2.MORPH_RECT, (ksize, 1))
            kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, ksize))
            merged = cv2.morphologyEx(merged.astype(np.uint8), cv2.MORPH_CLOSE, kh)
            merged |= cv2.morphologyEx(merged.astype(np.uint8), cv2.MORPH_CLOSE, kv)
            merged = merged > 0
            dtm = ndi.distance_transform_edt(merged)
            merged[dtm > ksize / 2] = False
        # 填实 (用户定稿: rx_outline_band_3over2 样式 = 纯填实) + 可选 1px 边框
        healed = np.full_like(img, 255)
        fill_color = targets[list(targets)[0]] if targets else (0, 160, 0)
        healed[merged > 0] = fill_color
        if args.border:
            n, lab, st, _ = cv2.connectedComponentsWithStats((merged > 0).astype(np.uint8), 8)
            for i in range(1, n):
                if st[i, 4] < 20:
                    continue
                cs, _ = cv2.findContours((lab == i).astype(np.uint8) * 255,
                                         cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                cv2.drawContours(healed, cs, -1, (0, 0, 0), 1)
        out = healed
    if args.stage4:
        # Stage-4: 合并面积相同的左右/上下两块 → 一个大矩形
        b, g, r = cv2.split(out.astype(int))
        md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
        mask = md > args.sat_min
        n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        boxes = []
        for i in range(1, n):
            if st[i, 4] < args.min_area:
                continue
            w_, h_ = int(st[i, 2]), int(st[i, 3])
            own_fill = st[i, 4] / (w_ * h_) if w_ * h_ > 0 else 0
            if args.compact and own_fill < args.compact_fill:
                continue   # 只合并紧凑矩形块 (排除细长条碎片)
            boxes.append([i, int(st[i, 0]), int(st[i, 1]), w_, h_,
                          int(st[i, 4])])  # id,x,y,w,h,area
        merged_rects = set()
        rejected = {"low_fill": 0}
        cands = 0
        out4 = out.copy()   # 保留未合并块, 只叠加合并矩形
        for a in boxes:
            for b_ in boxes:
                if a[0] >= b_[0]:
                    continue
                ax, ay, aw, ah = a[1:5]
                bx, by, bw, bh = b_[1:5]
                # 自监督形状匹配: 同宽同高 (不只面积, 防平行线同面积误并)
                w_tol = args.shape_tol * max(aw, bw)
                h_tol = args.shape_tol * max(ah, bh)
                if abs(aw - bw) > w_tol or abs(ah - bh) > h_tol:
                    continue
                is_pair = False
                # 左右对: 顶对齐 (y差小) + x相邻
                if abs(ay - by) <= args.align_tol and abs((ax + aw) - bx) <= args.gap:
                    is_pair = True
                # 上下对: 左对齐 (x差小) + y相邻
                elif abs(ax - bx) <= args.align_tol and abs((ay + ah) - by) <= args.gap:
                    is_pair = True
                # 长度包含对 (用户): 一块的垂直/水平范围被另一块包含 + 相邻
                if not is_pair and args.contained:
                    # 上下相邻 + x 范围互相包含 (长度含在另一半)
                    if abs((ay + ah) - by) <= args.gap and (
                            (ax <= bx and ax + aw >= bx + bw) or (bx <= ax and bx + bw >= ax + aw)):
                        is_pair = True
                    # 左右相邻 + y 范围互相包含
                    elif abs((ax + aw) - bx) <= args.gap and (
                            (ay <= by and ay + ah >= by + bh) or (by <= ay and by + bh >= ay + ah)):
                        is_pair = True
                if not is_pair:
                    continue
                cands += 1
                # 自监督: 合并矩形填充率 (两块面积和 / 矩形面积)
                x0 = min(ax, bx); y0 = min(ay, by)
                x1 = max(ax + aw, bx + bw); y1 = max(ay + ah, by + bh)
                union_area = (x1 - x0) * (y1 - y0)
                fill = (a[5] + b_[5]) / union_area if union_area > 0 else 0
                if fill < args.min_fill:
                    rejected["low_fill"] += 1   # 平行挤一起/面积膨胀, 错
                    continue
                merged_rects.add((a[0], b_[0]))
        for i, j in merged_rects:
            bi = next(x for x in boxes if x[0] == i)
            bj = next(x for x in boxes if x[0] == j)
            x0 = min(bi[1], bj[1]); y0 = min(bi[2], bj[2])
            x1 = max(bi[1] + bi[3], bj[1] + bj[3]); y1 = max(bi[2] + bi[4], bj[2] + bj[4])
            fill_color = targets[list(targets)[0]] if targets else (0, 160, 0)
            out4[y0:y1, x0:x1] = fill_color
        out = out4
        print(f"[stage4-merge] 候选{cands} 合并{len(merged_rects)} 对 "
              f"拒绝[低填充率(平行/膨胀)]={rejected['low_fill']}")
    if args.direction:
        # Stage-4b 走向探测 (用户): 分类并标注各段.
        #   L形直角拐弯 (两端点方向垂直) / 真斜线 (10-80°) / 直横竖段.
        #   走向 = 远离上游(chain前部) → 下游.
        from sch_wirenet import _thin
        from math import hypot, atan2, degrees
        if args.upstream and args.downstream:
            up, dn = args.upstream, args.downstream
        else:
            chain_p = args.chain or "projects/icom2200h/nettable/chain_order_rx.json"
            with open(chain_p) as f:
                d = json.load(f)
            ch = d.get("chain", [])
            up = np.mean([c["sch_px"] for c in ch[:3]], axis=0)
            dn = np.mean([c["sch_px"] for c in ch[-3:]], axis=0)
        # 在图层输出上运算: mask = 目标色 legend 准确色掩膜 (非原图全彩)
        mask = np.zeros(img.shape[:2], bool)
        for label, bgr in targets.items():
            mask |= rgb_mask(img, bgr, args.tol) > 0
        n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        nbr = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        stat = {"L": 0, "tilt": 0, "straight": 0}
        for i in range(1, n):
            if st[i, 4] < 300:
                continue
            x, y, w, h = map(int, (st[i, 0], st[i, 1], st[i, 2], st[i, 3]))
            xa, xb = max(0, x - 10), min(img.shape[1], x + w + 10)
            ya, yb = max(0, y - 10), min(img.shape[0], y + h + 10)
            sk = _thin((lab[ya:yb, xa:xb] == i).astype(np.uint8) * 255) > 0
            ends, dirs = [], []
            for yy in range(1, sk.shape[0] - 1):
                for xx in range(1, sk.shape[1] - 1):
                    if sk[yy, xx]:
                        dd = sum(1 for dyy, dxx in nbr if sk[yy + dyy, xx + dxx])
                        if dd == 1:
                            ends.append((yy, xx))
                            for dyy, dxx in nbr:
                                if sk[yy + dyy, xx + dxx]:
                                    dirs.append((dyy, dxx))
                                    break
            if len(ends) < 2:
                continue
            # 分类: L形 (两端点方向垂直) / 真斜线 / 直段
            a1 = degrees(atan2(dirs[0][0], dirs[0][1]))
            a2 = degrees(atan2(dirs[1][0], dirs[1][1]))
            diff = abs(a1 - a2) % 180
            diff = min(diff, 180 - diff)
            if 60 <= diff <= 120:
                cls = "L"
                stat["L"] += 1
                cv2.rectangle(out, (x, y), (x + w, y + h), (255, 0, 0), 2)
                cv2.putText(out, "L", (x + 2, y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
                continue
            ang = abs(degrees(atan2(dirs[0][0], dirs[0][1])))
            ang = min(ang, 180 - ang)
            if 10 <= ang <= 80:
                cls = "tilt"
                stat["tilt"] += 1
                cv2.rectangle(out, (x, y), (x + w, y + h), (0, 0, 255), 2)
                cv2.putText(out, "T", (x + 2, y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                continue
            cls = "straight"
            stat["straight"] += 1
            # 直段: 画走向箭头 (远离上游→下游)
            p1 = (xa + ends[0][1], ya + ends[0][0])
            p2 = (xa + ends[1][1], ya + ends[1][0])
            d1 = hypot(p1[0] - up[0], p1[1] - up[1])
            d2 = hypot(p2[0] - up[0], p2[1] - up[1])
            tail, head = (p2, p1) if d1 > d2 else (p1, p2)
            mx, my = (tail[0] + head[0]) / 2, (tail[1] + head[1]) / 2
            ang2 = atan2(head[1] - tail[1], head[0] - tail[0])
            Ls = int(legend_line_width(img, args.legend))
            tip = (int(mx + np.cos(ang2) * Ls), int(my + np.sin(ang2) * Ls))
            back = (int(mx - np.cos(ang2) * Ls), int(my - np.sin(ang2) * Ls))
            cv2.arrowedLine(out, back, tip, (0, 0, 255), 2, cv2.LINE_AA, tipLength=0.4)
        print(f"[stage4-direction] 上游{up} 下游{dn} 分类: L拐弯{stat['L']} "
              f"真斜线{stat['tilt']} 直段{stat['straight']}")
    if args.holefill:
        # Stage-4b: 沿邻近绿填走线缝 (用户: 用参考线宽判同一条线):
        #   缝隙 <= 线宽 = 同一条线 (填); > 线宽 = 不同线 (不填).
        #   小方向闭 (横/竖 close_k=参考线宽) + 宽度约束不增宽.
        from scipy import ndimage as ndi
        b, g, r = cv2.split(out.astype(int))
        md = np.maximum.reduce([np.abs(g - r), np.abs(g - b), np.abs(r - b)])
        mask = (md > args.sat_min).astype(np.uint8)
        ck = args.close_k if args.close_k > 0 else int(legend_line_width(img, args.legend))
        kh = cv2.getStructuringElement(cv2.MORPH_RECT, (ck, 1))
        kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, ck))
        filled = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kh)
        filled |= cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kv)
        filled = filled > 0
        dtm = ndi.distance_transform_edt(filled)
        filled[dtm > ck / 2] = False   # 宽度约束 = 线宽/2 (不增宽)
        added = int(filled.sum() - mask.sum())
        n, lab, st, _ = cv2.connectedComponentsWithStats(filled.astype(np.uint8), 8)
        out2 = np.full_like(img, 255)
        fill_color = targets[list(targets)[0]] if targets else (0, 160, 0)
        out2[filled] = fill_color
        out = out2
        print(f"[stage4b-holefill] 沿邻近绿填走线缝: +{added}px, 连通域 {n - 1}")
    cv2.imwrite(args.out, out)
    print(f"[color_layer] signals={args.signals} targets={list(targets)} "
          f"-> {args.out}")


if __name__ == "__main__":
    main()