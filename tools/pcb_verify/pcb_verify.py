#!/usr/bin/env python3
"""pcb_verify.py - 坐标自检工具 (新规范核心工具)

purpose: 给定 refdes 列表 + 坐标, 在 PCB 图上裁切 200x150 px 小图, OCR 跑一次,
    看 OCR 识别结果是否与原 refdes 一致. 一致→坐标正确, 不一致→坐标错位.

format: Python 3 + PIL + onnxruntime (调用 ai_refdes_ocr 工具)
version: 0.1 (2026-09-15 初版)
consumers: 任何 rx_flow 标注校验流程, 索引质量保证
parent_doc: ../../schema.md

输出:
  report.json: 每个 refdes 的 verify 结果 (match/mismatch/not_found)

算法 (回环校验):
  1. 对每个 (ref, x, y):
  2. 在 PCB 图 (px, py) 裁切 crop (默认 300x200)
  3. upsample 2x (把 600dpi 缩放得到更大字)
  4. 调 ai_refdes_ocr --img crop --stage1 grid 单 tile
  5. 拿 OCR 识别结果, 检查是否含 ref (允许前缀匹配 e.g. F13, F1, F13_FL)
  6. 输出: match (完全一致/前缀一致) / mismatch (识别到其他 ref) / not_found (识别成功但不含 ref)

用法:
  python3 tools/pcb_verify/pcb_verify.py \
      --pcb projects/icom2200h/render/pcb-top-600-1.png \
      --coords "(1277,1489)=J11 (1646,1159)=F13 (1547,1159)=F14 (1714,1385)=IC12" \
      --crop-size 300x200 \
      --out /tmp/verify_report.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image


def parse_coords(s: str):
    """parse "(x1,y1)=R1 (x2,y2)=R2 ..." 格式"""
    items = []
    pattern = re.compile(r"\((\d+),(\d+)\)\s*=\s*(\w+)")
    for m in pattern.finditer(s):
        x, y, r = int(m.group(1)), int(m.group(2)), m.group(3)
        items.append((r, x, y))
    return items


def crop_around(pcb_img_path, x, y, w, h):
    """裁切 (x-w/2, y-h/2) 到 (x+w/2, y+h/2), 自动 clamp"""
    img = Image.open(pcb_img_path).convert("RGB")
    W, H = img.size
    x0, y0 = max(0, x - w // 2), max(0, y - h // 2)
    x1, y1 = min(W, x + w // 2), min(H, y + h // 2)
    return img.crop((x0, y0, x1, y1)), (x0, y0)


def wsl_to_win(path: Path) -> str:
    """把 WSL Path 转为 Windows 路径 (用于 Windows python 调用)"""
    p = str(path)
    if p.startswith("/mnt/"):
        # /mnt/c/Users/radio/foo -> C:\Users\radio\foo
        drive = p[5].upper()
        rest = p[6:].replace("/", "\\")
        return f"{drive}:{rest}"
    return p.replace("/", "\\")


def ocr_crop(crop: Image, work_dir: Path):
    """对 crop 跑 OCR, 返回识别结果文本列表"""
    # 保存 crop 到临时文件
    crop_path = work_dir / "verify_crop.png"
    crop.save(crop_path)
    # upsample 2x 提升 OCR 识别率
    big = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    big_path = work_dir / "verify_crop_2x.png"
    big.save(big_path)

    # 调用 ai_refdes_ocr.py (Windows 原生)
    out_dir = work_dir / "ocr_out"
    out_dir.mkdir(exist_ok=True)

    # 把 WSL 路径转 Windows 路径 + cp crop 到 Windows 用户目录 (避免 UNC)
    img_win = wsl_to_win(big_path)
    out_win = wsl_to_win(out_dir)
    # Windows 工作目录: C:\Users\radio\verify_<ts>\
    win_work = "C:\\Users\\radio\\verify_" + work_dir.name.replace("/", "_").replace(":", "_")
    bat_win = win_work + "\\run_ocr.bat"
    # 把 big_path 文件拷到 Windows 工作目录
    import shutil
    Path(win_work).mkdir(parents=True, exist_ok=True)
    shutil.copy(big_path, win_work + "\\crop.png")
    img_win_run = win_work + "\\crop.png"

    bat_content = (
        f"@echo off\n"
        f"chcp 65001 > nul\n"
        f"set PYTHONIOENCODING=utf-8\n"
        f"set PYTHONUTF8=1\n"
        f'cd /d C:\\Users\\radio\\tools_full\n'
        f'"C:\\Users\\radio\\ocr_gpu_venv\\Scripts\\python.exe" -c '
        f'"import sys; sys.path.insert(0, r\'C:\\Users\\radio\\tools_full\'); '
        f'from ai_refdes_ocr import main; '
        f"sys.argv = ['x', "
        f"'--img', r'{img_win_run}', "
        f"'--img-dpi', '600', '--out-dpi', '600', "
        f"'--stage1-mode', 'grid', '--stage1-engines', 'v5s,v4', "
        f"'--tile', '500', '--overlap', '100', "
        f"'--stage1-upscale', '2.0', '--stage1-rots', '0', "
        f"'--stages', '1', '--jobs', '1', '--dml', "
        f"'--runs-dir', r'{win_work}\\out', "
        f"'--tag', 'verify', '--only-refdes', '--keep-raw']; main()\"\n"
    )
    bat_file = Path(win_work) / "run_ocr.bat"
    bat_file.write_text(bat_content)
    # 把 bat 拷到 Windows 用户目录 (避免 WSL UNC)
    bat_win_path = Path("C:/Users/radio/verify_ocr_run.bat")
    bat_path.write_bytes(bat_path.read_bytes())
    try:
        r = subprocess.run(
            ["cmd.exe", "/c", f"cd /d C:\\Users\\radio && {bat_path.name}"],
            capture_output=True, text=True, timeout=120,
            cwd="C:\\Users\\radio",
        )
    except subprocess.TimeoutExpired:
        return [], "timeout"
    except Exception as e:
        return [], str(e)

    # 解析输出 JSON
    json_files = list(out_dir.glob("*.json"))
    if not json_files:
        return [], f"no_output (rc={r.returncode}, stderr={r.stderr[:200]})"
    try:
        d = json.load(open(json_files[0]))
    except Exception as e:
        return [], f"parse_error: {e}"

    # 收集所有识别文本
    texts = []
    for h in d.get("raw_stage1", []) + d.get("raw_stage2", []):
        ref = h.get("text", "").strip()
        if ref:
            texts.append(ref)
    # 失败原因
    if r.returncode != 0:
        reason = f"rc={r.returncode}"
        if "UnicodeEncodeError" in (r.stderr or ""):
            reason = "unicode_error"
        return texts, reason
    return texts, "ok"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pcb", required=True, help="PCB 母图路径 (PNG)")
    ap.add_argument("--coords", required=True,
                    help='坐标+refdes, 格式 "(x,y)=REF (x,y)=REF ...',)
    ap.add_argument("--crop-size", default="300x200",
                    help="裁切尺寸 WxH (默认 300x200)")
    ap.add_argument("--work-dir", default=None,
                    help="工作目录 (默认 /tmp/verify_anchor_<ts>)")
    ap.add_argument("--out", default=None,
                    help="报告输出 JSON (默认 work_dir/report.json)")
    ap.add_argument("--fuzzy", action="store_true",
                    help="模糊匹配: OCR 文本含 ref 前缀也算 match")
    args = ap.parse_args()

    coords = parse_coords(args.coords)
    if not coords:
        print("错误: --coords 无效", file=sys.stderr)
        sys.exit(2)

    w, h = map(int, args.crop_size.split("x"))
    work_dir = Path(args.work_dir or tempfile.mkdtemp(prefix="verify_anchor_"))
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out or work_dir / "report.json")

    print(f"[verify] PCB: {args.pcb}")
    print(f"[verify] crop: {w}x{h}, work_dir: {work_dir}")
    print(f"[verify] 校验 {len(coords)} 个 refdes")

    results = []
    for ref, x, y in coords:
        print(f"\n[verify] {ref} @ ({x},{y})", flush=True)
        crop, (x0, y0) = crop_around(args.pcb, x, y, w, h)
        crop.save(work_dir / f"{ref}_{x}_{y}_crop.png")
        texts, reason = ocr_crop(crop, work_dir)
        # 匹配逻辑
        matched = False
        match_detail = None
        for t in texts:
            if args.fuzzy:
                if ref in t or t in ref or t.startswith(ref[:2]):
                    matched = True
                    match_detail = t
                    break
            else:
                if t == ref:
                    matched = True
                    match_detail = t
                    break
        results.append({
            "ref": ref,
            "expected_xy": [x, y],
            "crop_offset": [x0, y0],
            "ocr_texts": texts,
            "reason": reason,
            "matched": matched,
            "match_detail": match_detail,
            "verdict": "match" if matched else ("not_found" if reason == "ok" and not texts else reason),
        })
        status = "MATCH" if matched else f"MISMATCH ({reason}, ocr={texts[:5]})"
        print(f"[verify] {ref}: {status}", flush=True)

    out_path.write_text(json.dumps({
        "_meta": {
            "purpose": "坐标自检报告 - 给定 refdes+坐标, 裁切 PCB 图 OCR 验证",
            "format": "JSON list of {ref, expected_xy, ocr_texts, matched, verdict}",
            "version": "0.1",
            "pcb": args.pcb,
            "crop_size": [w, h],
            "fuzzy": args.fuzzy,
        },
        "results": results,
    }, ensure_ascii=False, indent=2))
    print(f"\n[verify] 报告: {out_path}")

    # 汇总
    n_match = sum(1 for r in results if r["matched"])
    n_mismatch = len(results) - n_match
    print(f"\n=== 汇总: {n_match}/{len(results)} match, {n_mismatch} mismatch ===")
    sys.exit(0 if n_mismatch == 0 else 1)


if __name__ == "__main__":
    main()
