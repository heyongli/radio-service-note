#!/usr/bin/env python3
"""tools/run_sch_round.py — 跑一轮完整 sch→PCB 管线, 输出全部结果 (roundXXX 命名)

用途: 迭代探索时每轮输出所有管线产物, 便于查看进度/对比.

输出 (annot/ 下, roundXXX 命名):
  rx_flow_sch_roundXXX.png    — sch 侧识别+鉴别标注
  rx_flow_pcb_roundXXX.png/svg — PCB 侧 flow 标注
  nettable/chain_order_rx.json — sch 识别的链序
  nettable/sch_components.json — sch 识别+鉴别数据库

用法:
  python3 tools/run_sch_round.py [--round XXX] [--seed 626,1480]
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "projects/icom2200h/render/rxtx-sch-600-1.png"
PCB = ROOT / "projects/icom2200h/render/pcb-top-600-1.png"
REFDES = ROOT / "projects/icom2200h/render" / "sch_refdes.json"
DB = ROOT / "projects/icom2200h/nettable/sch_components.json"
CHAIN = ROOT / "projects/icom2200h/nettable/chain_order_rx.json"


def run(cmd):
    print(f"\n>>> {' '.join(map(str, cmd))}")
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()
    for line in tail[-6:]:
        print("  " + line)
    if r.returncode != 0:
        print("  ERR:", (r.stderr or "")[-500:])
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--round", type=int, default=0, help="round 编号")
    ap.add_argument("--seed", default="626,1480")
    ap.add_argument("--refdes", default=str(ROOT / "/tmp/opencode/sch_refdes_600.json"))
    ap.add_argument("--db", default="/tmp/opencode/sch_components.json")
    # 可搜索参数 (量化值全部可调)
    ap.add_argument("--assoc-dist", type=int, default=220, help="标号→符号关联距离")
    ap.add_argument("--type-bonus", type=int, default=40)
    ap.add_argument("--band", type=int, default=22, help="绿线侧边带宽")
    ap.add_argument("--side-dist", default="20,50", help="侧边探测距离")
    ap.add_argument("--verify-rots", default="0", help="验证旋转集")
    ap.add_argument("--trace-extra", default="", help="额外传给 sch_trace 的参数 (如 --circle-rmax 40)")
    args = ap.parse_args()

    rn = args.round
    annot = ROOT / "projects/icom2200h/annot"

    print(f"=== Round {rn}: sch 管线 ===")
    trace_cmd = [sys.executable, "tools/sch_trace/sch_trace.py", "--img", IMG,
                 "--color", "green", "--seed", args.seed, "--db", args.db]
    # 可传搜索参数
    if args.trace_extra:
        trace_cmd += args.trace_extra.split()
    run(trace_cmd)
    run([sys.executable, "tools/sch_label_ocr/sch_label_ocr.py", "--img", IMG,
         "--refdes", args.refdes, "--db", args.db,
         "--assoc-dist", str(args.assoc_dist), "--type-bonus", str(args.type_bonus)])
    run([sys.executable, "tools/sch_verify/sch_flow_walk.py", "--img", IMG,
         "--color", "green", "--db", args.db, "--chain", CHAIN, "--seed", args.seed,
         "--band", str(args.band), "--side-dist", args.side_dist,
         "--verify-rots", args.verify_rots])

    print(f"=== Round {rn}: sch 符号识别+验证 (sch 管线之后) ===")
    run([sys.executable, "tools/sch_symbol/sch_symbol.py", "--img", IMG, "--db", args.db])
    run([sys.executable, "tools/sch_symbol_verify/sch_symbol_verify.py",
         "--img", IMG, "--db", args.db, "--correct"])

    print(f"\n=== Round {rn}: sch 渲染 ===")
    run([sys.executable, "tools/sch_render/sch_render.py", "--img", IMG,
         "--color", "green", "--db", args.db,
         "--out", annot / f"rx_flow_sch_round{rn:03d}.png"])

    print(f"\n=== Round {rn}: 结合管线 (sch flow → PCB) ===")
    cfg = "/tmp/opencode/rx_cfg_r{}.json".format(rn)
    wpts = "/tmp/opencode/wpts_r{}.json".format(rn)
    run([sys.executable, "tools/signal_flow_route/make_config_from_chain.py",
         "--chain", CHAIN, "--index", ROOT / "projects/icom2200h/nettable/components_index.json",
         "--out", cfg, "--mirror-x", "2530"])
    run([sys.executable, "tools/signal_flow_route/signal_flow_route.py",
         "--config", cfg, "--out", wpts, "--pcb", PCB,
         "--out-png", annot / f"rx_flow_pcb_round{rn:03d}.png"])

    print(f"\n=== Round {rn} 完成: 产物在 annot/ (rx_flow_sch/pcb_round{rn:03d}.*) ===")


if __name__ == "__main__":
    main()