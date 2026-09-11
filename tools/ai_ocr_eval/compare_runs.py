#!/usr/bin/env python3
"""对比两次(或多次) ai_refdes_ocr 运行 JSON 的命中差异 — 调参/校准/回归检查.

用法:
  python3 compare_runs.py runs/A.json runs/B.json
  python3 compare_runs.py runs/A.json runs/B.json runs/C.json   # 多 run 逐对与 A 比
  python3 compare_runs.py A.json B.json --label R22             # 只看某位号族
  python3 compare_runs.py A.json B.json --near 2622 1790 200    # 只看某区域(px@out-dpi)
  python3 compare_runs.py A.json B.json --refdes-only           # 只看位号样式命中
"""
import argparse
import json


def load(p):
    return json.load(open(p))


def params_diff(a, b):
    pa, pb = a.get("params", {}), b.get("params", {})
    keys = sorted(set(pa) | set(pb))
    return {k: (pa.get(k), pb.get(k)) for k in keys if pa.get(k) != pb.get(k)}


def near(h, x, y, r):
    return abs(h["px"][0] - x) <= r and abs(h["px"][1] - y) <= r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="两个及以上运行 JSON; 第一个为基准")
    ap.add_argument("--dist", type=int, default=40, help="同位判定半径 px")
    ap.add_argument("--label", help="按 norm 前缀过滤, 如 R22 / FI / J")
    ap.add_argument("--near", nargs=3, type=float, metavar=("X", "Y", "R"),
                    help="按区域过滤: X Y R (px@out-dpi)")
    ap.add_argument("--refdes-only", action="store_true")
    ap.add_argument("--min-conf", type=float, default=0.0)
    args = ap.parse_args()

    runs = [load(p) for p in args.runs]
    A = runs[0]

    def filt(hs):
        out = hs
        if args.refdes_only:
            out = [h for h in out if h.get("refdes_like")]
        if args.min_conf:
            out = [h for h in out if h["conf"] >= args.min_conf]
        if args.label:
            out = [h for h in out if h["norm"].startswith(args.label.upper())]
        if args.near:
            x, y, r = args.near
            out = [h for h in out if near(h, x, y, r)]
        return out

    print(f"基准: {args.runs[0]}")
    print(f"  {A['tool_version']} {A['date']} tag={A['params'].get('tag','')} "
          f"hits={A['n_merged']} refdes={A['n_refdes']} agree={A['n_agree']} {A['time_s']}s")

    for bi, B in enumerate(runs[1:], 1):
        print(f"\n{'='*70}\n对比: {args.runs[bi]}")
        print(f"  {B['tool_version']} {B['date']} tag={B['params'].get('tag','')} "
              f"hits={B['n_merged']} refdes={B['n_refdes']} agree={B['n_agree']} {B['time_s']}s")
        pd = params_diff(A, B)
        if pd:
            print(f"  参数差异({len(pd)}):")
            for k, (va, vb) in pd.items():
                print(f"    {k}: {va!r} -> {vb!r}")
        else:
            print("  参数完全一致(仅时间/输入不同)")

        ha, hb = filt(A["hits"]), filt(B["hits"])
        # 同位同文本 = 共同; 同位异文本 = 冲突
        common, a_only, conflicts = [], [], []
        used_b = set()
        for h in sorted(ha, key=lambda z: -z["conf"]):
            cand = [(i, g) for i, g in enumerate(hb)
                    if i not in used_b
                    and abs(g["px"][0] - h["px"][0]) <= args.dist
                    and abs(g["px"][1] - h["px"][1]) <= args.dist]
            cand = [c for c in cand if c[1]["norm"] == h["norm"]]
            if cand:
                i, g = max(cand, key=lambda c: c[1]["conf"])
                used_b.add(i)
                dc = round(g["conf"] - h["conf"], 3)
                dpx = (g["px"][0] - h["px"][0], g["px"][1] - h["px"][1])
                common.append((h, g, dc, dpx))
            else:
                near_any = [g for _, g in
                            [(i, g) for i, g in enumerate(hb)
                             if abs(g["px"][0] - h["px"][0]) <= args.dist
                             and abs(g["px"][1] - h["px"][1]) <= args.dist]]
                if near_any:
                    conflicts.append((h, near_any))
                else:
                    a_only.append(h)
        b_only = [g for i, g in enumerate(hb) if i not in used_b]

        print(f"  共同命中 {len(common)} | 仅基准 {len(a_only)} | 仅对比 {len(b_only)} "
              f"| 同位异文 {len(conflicts)}")
        interesting = [(h, g, dc) for h, g, dc, _ in common if dc != 0]
        if interesting:
            print(f"  -- 共同但 conf 变化 (top10) --")
            for h, g, dc in sorted(interesting, key=lambda t: -abs(t[2]))[:10]:
                print(f"     {h['norm']:>8}: {h['conf']:.2f}->{g['conf']:.2f} ({dc:+.2f}) "
                      f"eng={','.join(h['engines'])}->{','.join(g['engines'])} @{g['px']}")
        if conflicts:
            print(f"  -- 同位异文 (识别冲突, 需人工/探针裁决) --")
            for h, gs in conflicts:
                print(f"     @{h['px']} 基准='{h['norm']}'({h['conf']:.2f}) vs "
                      f"对比={[g['norm'] for g in gs]}")
        if a_only:
            print(f"  -- 仅基准有 (回归!) --")
            for h in sorted(a_only, key=lambda z: -z["conf"])[:15]:
                print(f"     {h['norm']:>8} conf={h['conf']:.2f} @{h['px']} "
                      f"{','.join(h['engines'])} s{h['stage']}")
        if b_only:
            print(f"  -- 仅对比有 (增益) --")
            for h in sorted(b_only, key=lambda z: -z["conf"])[:15]:
                print(f"     {h['norm']:>8} conf={h['conf']:.2f} @{h['px']} "
                      f"{','.join(h['engines'])} s{h['stage']}")


if __name__ == "__main__":
    main()
