#!/usr/bin/env python3
"""tools/multi_scale_ocr/multi_scale_ocr.py - 多尺度 OCR 扫描

purpose: 对 PCB 全图用多尺度 tile 扫描, 解决 v4+v5s 单尺度漏检大字体器件 (如 IF 滤波器) 的问题
format: Python 3 + 多次 Windows DML OCR 调用
version: 0.1 (2026-09-15 初版)

consumers: 任何 PCB 全图 OCR (前序 ai_refdes_ocr.py 单尺度漏检的场景)
parent_doc: ../../schema.md
applies_to: Windows 原生 DML OCR, PCB 600dpi 全图扫描

算法 (多尺度金字塔):
  对每个尺度 (--scales, 默认 1500/750/300/150):
    跑 ai_refdes_ocr.py stage1 grid --tile {scale}
    合并结果, 大字体器件在小尺度 tile 也被切到, 不漏
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def wsl_to_win(p: Path) -> str:
    s = str(p)
    if s.startswith("/mnt/"):
        drive = s[5].upper()
        rest = s[6:].replace("/", "\\")
        return f"{drive}:{rest}"
    return s.replace("/", "\\")


def run_ocr_at_scale(win_img, scale, dpi, out_dir, win_work):
    """跑一次 ai_refdes_ocr.py, tile = scale (stage1 grid)"""
    env_python = r"C:\Users\radio\ocr_gpu_venv\Scripts\python.exe"
    env_tools = r"C:\Users\radio\tools_full"
    run_id = f"ms_{scale}"
    bat = Path(win_work) / f"run_{run_id}.bat"
    bat.write_text(f"""@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d {env_tools}
"{env_python}" -c "import sys; sys.path.insert(0, r'{env_tools}'); from ai_refdes_ocr import main; sys.argv = ['x', '--img', r'{win_img}', '--img-dpi', '{dpi}', '--out-dpi', '{dpi}', '--stage1-mode', 'grid', '--stage1-engines', 'v4,v5s', '--tile', '{scale}', '--overlap', '{scale // 5}', '--stage1-upscale', '1.5', '--stage1-rots', '0', '--stages', '1', '--jobs', '1', '--dml', '--runs-dir', r'{win_work}\\out_{scale}', '--tag', 'ms_{scale}', '--only-refdes', '--keep-raw']; main()" > {win_work}\\{run_id}.log 2>&1
""")
    r = subprocess.run(
        ["cmd.exe", "/c", bat.name],
        capture_output=True, text=True, timeout=1800,
        cwd=win_work,
    )
    return r.returncode == 0


def collect_results(win_work, scales):
    """从各尺度输出目录收集所有 OCR hits, 合并"""
    all_hits = []
    seen = set()  # (ref, x, y) 去重
    for scale in scales:
        out_dir = Path(win_work) / f"out_{scale}"
        if not out_dir.exists():
            continue
        for f in out_dir.glob("*.json"):
            try:
                d = json.load(open(f))
            except Exception:
                continue
            for h in d.get("raw_stage1", []) + d.get("raw_stage2", []):
                ref = h.get("text", "").strip()
                box = h.get("box")
                if not ref or not box:
                    continue
                cx = sum(p[0] for p in box) // 4
                cy = sum(p[1] for p in box) // 4
                key = (ref, cx // 10, cy // 10)  # 容差 10 px 去重
                if key in seen:
                    continue
                seen.add(key)
                all_hits.append({
                    "ref": ref,
                    "box": box,
                    "center": [cx, cy],
                    "conf": h.get("conf", 0),
                    "engine": h.get("engine"),
                    "agree": h.get("agree", False),
                    "scale": scale,
                })
    return all_hits


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pcb", required=True, help="PCB 母图 PNG (Windows 路径)")
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--scales", default="1500,750,400,200",
                    help="逗号分隔的 tile 尺寸, 从大到小 (默认 1500,750,400,200)")
    ap.add_argument("--work-dir", default=None,
                    help="Windows 工作目录 (默认 C:\\Users\\radio\\multi_scale_<ts>)")
    ap.add_argument("--out", default=None,
                    help="合并结果输出 JSON (默认 stdout)")
    args = ap.parse_args()

    # 转 Windows 路径
    win_img = wsl_to_win(Path(args.pcb))
    import time
    work = args.work_dir or f"C:\\Users\\radio\\multi_scale_{int(time.time())}"
    Path(work).mkdir(parents=True, exist_ok=True)

    scales = [int(s) for s in args.scales.split(",")]
    print(f"[multi_scale_ocr] PCB: {args.pcb}")
    print(f"[multi_scale_ocr] DPI: {args.dpi}, scales: {scales}")
    print(f"[multi_scale_ocr] work_dir: {work}")

    for scale in scales:
        print(f"\n[multi_scale_ocr] === scale={scale} ===")
        ok = run_ocr_at_scale(win_img, scale, args.dpi, work, work)
        print(f"  → exit ok={ok}")

    print("\n[multi_scale_ocr] 合并结果...")
    hits = collect_results(work, scales)
    print(f"  总 hits (去重): {len(hits)}")

    # 按 refdes 统计
    from collections import Counter, defaultdict
    by_ref = defaultdict(list)
    for h in hits:
        by_ref[h['ref']].append(h)
    print(f"  unique refdes: {len(by_ref)}")

    out = {
        "_meta": {
            "purpose": "多尺度 OCR 合并结果",
            "pcb": args.pcb,
            "dpi": args.dpi,
            "scales": scales,
            "tool_version": "0.1",
        },
        "results": hits,
    }
    if args.out:
        with open(args.out, 'w') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n[multi_scale_ocr] saved: {args.out}")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
