#!/usr/bin/env python3
"""tools/annot_clean/annot_clean.py - 清理 annot/ 旧版本渲染产物

purpose: 删除 rx_flow_top_v{N}.{png,svg} 旧版本, 默认仅保留最新 N 个
format: Python 3; 全参数 CLI
version: 0.1 (2026-09-15 初版)
consumers: 渲染新版本后自动清理, 避免 annot/ 堆积旧 PNG/SVG
parent_doc: ../../schema.md
applies_to: projects/<机型>/annot/rx_flow_top_*.{png,svg}

默认行为:
  - 删除所有 rx_flow_top_v{N}.{png,svg} 除最新 KEEP_LAST 个 (默认 1)
  - 默认 KEEP_LAST=1 (只留最新版本, 旧版本全删)
  - 加 --keep 指定保留 N 个 (e.g. --keep 2 留最新 2 版)
  - 加 --archive 把旧版移到 archive/ (instead of 删除)
  - --dry-run 只显示要删的, 不真删
"""
import argparse
import re
import shutil
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--annot-dir", default="projects/icom2200h/annot",
                    help="annot 目录 (默认 projects/icom2200h/annot)")
    ap.add_argument("--pattern", default="rx_flow_top_v*.{png,svg}",
                    help="要清理的 glob 模式")
    ap.add_argument("--keep", type=int, default=1,
                    help="保留最新 N 个 (默认 1, 即只留最新版)")
    ap.add_argument("--archive", action="store_true",
                    help="不删, 移到 <annot>/archive/")
    ap.add_argument("--dry-run", action="store_true",
                    help="只显示要删的, 不真删")
    args = ap.parse_args()

    annot = Path(args.annot_dir)
    if not annot.exists():
        print(f"错误: {annot} 不存在")
        return 2

    # 收集所有匹配文件
    files = []
    for ext in ['png', 'svg']:
        for f in annot.glob(args.pattern.replace('{png,svg}', ext)):
            files.append(f)
    if not files:
        print(f"{annot} 中无匹配 {args.pattern} 文件")
        return 0

    # 按版本号 N 排序 (从大到小)
    def version_key(p):
        m = re.search(r'v(\d+)', p.name)
        return int(m.group(1)) if m else 0
    files.sort(key=version_key, reverse=True)

    print(f"=== 清理 {annot} ===")
    print(f"保留最新 {args.keep} 个, 删除/归档其余:")
    to_remove = files[args.keep:]
    if not to_remove:
        print("  (无需删除, 已只保留最新)")
        return 0
    for f in to_remove:
        if args.archive:
            archive = annot / 'archive'
            dst = archive / f.name
            if not args.dry_run:
                archive.mkdir(exist_ok=True)
                shutil.move(str(f), str(dst))
            print(f"  [archive] {f.name} -> archive/{f.name}")
        else:
            if not args.dry_run:
                f.unlink()
            print(f"  [remove]  {f.name}")
    if args.dry_run:
        print("(dry-run, 未真删)")
    else:
        print(f"\n保留 {args.keep} 个最新: {[f.name for f in files[:args.keep]]}")
    return 0


if __name__ == "__main__":
    main()
