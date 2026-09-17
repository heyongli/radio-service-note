#!/usr/bin/env python3
"""poll_ocr — 后台 OCR 任务进度轮询 (按 schema.md 五要素规范的工具)

功能 (purpose): poll 后台 batch_tile_ocr 进程, 每 N 秒读取 stdout 日志最新进度行,
    在控制台打印时间戳+进度, 任务结束自动退出 (避免人工 for 循环 sleep)。

格式 (format): Python 3 (WSL/Linux 调用 Windows Python 通过 .bat)

版本 (version): 0.1 (2026-09-15 初版)

用途 (consumers/usage):
    # 后台跑 Windows DML OCR
    ./run_top_dml_full.bat &   # Windows 侧启动 OCR 后台任务, 写日志到 logs/<task>.log

    # WSL/Linux 轮询进度
    python3 tools/poll_ocr/poll_ocr.py \
        --log-path /mnt/c/Users/radio/<project>/ocr_runs/logs/top_stdout.log \
        --pid-pattern batch_tile_ocr \
        --interval 30 \
        --max-iterations 120

退出条件:
    1. --pid-pattern 匹配不到任何进程 (pgrep -f) → 退出
    2. --max-iterations 达到上限 → 退出
    3. 日志末尾出现 "done" → 退出
"""
import argparse
import re
import sys
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--log-path", required=True, type=Path,
                    help="OCR 后台任务输出日志文件路径")
    ap.add_argument("--pid-pattern", default="batch_tile_ocr",
                    help="pgrep -f 模式, 匹配进程是否还活着 (默认 batch_tile_ocr)")
    ap.add_argument("--interval", type=int, default=30, help="轮询间隔秒数 (默认 30)")
    ap.add_argument("--max-iterations", type=int, default=120,
                    help="最大轮询次数, 防止无限循环 (默认 120 次 * 30s = 1 小时)")
    ap.add_argument("--done-marker", default="done",
                    help="日志中判定任务结束的标记字符串 (默认 'done')")
    ap.add_argument("--progress-pattern", default=r"\[BATCH\]",
                    help="日志中进度行的正则 (默认 '[BATCH]')")
    args = ap.parse_args()

    log_path: Path = args.log_path
    if not log_path.exists():
        print(f"[poll_ocr] 错误: 日志文件不存在 {log_path}", file=sys.stderr)
        sys.exit(2)

    print(f"[poll_ocr] 监控日志: {log_path}", file=sys.stderr)
    print(f"[poll_ocr] 进程匹配: {args.pid_pattern}", file=sys.stderr)
    print(f"[poll_ocr] 轮询间隔: {args.interval}s, 上限: {args.max_iterations} 次", file=sys.stderr)

    progress_re = re.compile(args.progress_pattern)
    done_re = re.compile(args.done_marker, re.IGNORECASE)

    for i in range(1, args.max_iterations + 1):
        # 检查进程是否还活着
        result = run_pgrep(args.pid_pattern)
        if result.returncode != 0:
            print(f"\n=== 进程结束 (pgrep 返回 {result.returncode}) ===")
            break

        # 读取日志最新进度
        try:
            last_line = tail_last_line(log_path)
            ts = time.strftime("%H:%M:%S")
            if last_line and progress_re.search(last_line):
                # 转 Windows CRLF 为 LF
                last_line = last_line.replace("\r", "")
                print(f"{ts} | {last_line}")
            elif last_line:
                last_line = last_line.replace("\r", "")
                ts = time.strftime("%H:%M:%S")
                print(f"{ts} | (无 BATCH 标记) {last_line[:120]}")
        except FileNotFoundError:
            print(f"[poll_ocr] 日志被删除? {log_path}", file=sys.stderr)

        # 检查日志末尾是否含 done
        try:
            content = log_path.read_text(errors="ignore")
            if done_re.search(content):
                print(f"\n=== 检测到 '{args.done_marker}', 任务完成 ===")
                break
        except FileNotFoundError:
            pass

        time.sleep(args.interval)
    else:
        print(f"\n=== 达到最大轮询次数 {args.max_iterations}, 退出 ===")


def tail_last_line(path: Path) -> str:
    """读文件最后一行 (高效: 不全读)"""
    with path.open("rb") as f:
        # seek 到末尾倒数 8KB
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 8192))
        chunk = f.read().decode("utf-8", errors="ignore")
    lines = chunk.splitlines()
    return lines[-1] if lines else ""


def run_pgrep(pattern: str):
    """运行 pgrep, 跨平台"""
    import subprocess
    try:
        return subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        # Windows 上没有 pgrep, 用 tasklist
        return subprocess.run(
            ["tasklist"],
            capture_output=True, text=True,
        )


if __name__ == "__main__":
    main()
