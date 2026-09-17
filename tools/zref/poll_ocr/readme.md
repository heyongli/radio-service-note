
# tools/poll_ocr — 设计文档

**代码不写在这里, 写在 `poll_ocr.py`**。本文档记录**为什么**这么设计、
**结构**如何、**重要发现**和**踩坑**。

---

## 1. 目的 (§1 文件清单 + §5 目的)

| 文件 | 类型 | 用途 |
|---|---|---|
| poll_ocr.py | Python 3 | 轮询主程序 (代码本身) |
| readme.md | Markdown | 本设计文档 |

工具**存在的原因**: 之前用 `for i in $(seq 1 30); do tail; sleep; done`
ad-hoc 循环监控 OCR 后台任务, 散落在 shell 历史里, 没人知道参数怎么改、什么时候退出。

**核心抽象**: "监控后台长任务的进度"是通用需求, 应封装成工具。

---

## 2. 体系结构 (§2 目录结构 + §3 元数据格式)

```
poll_ocr (主循环):
  ┌──────────────────────────────┐
  │ for i in 1..max_iterations:  │
  │   ├─ pgrep(pid_pattern)       │  ← 进程活着?
  │   │  └─ 否 → break (退出)     │
  │   ├─ tail(log_path)            │  ← 读最新日志
  │   ├─ grep done_marker in log   │  ← 任务完成?
  │   │  └─ 是 → break (退出)     │
  │   ├─ print "{ts} | {line}"     │  ← 显示进度
  │   └─ sleep(interval)            │
  └──────────────────────────────┘
```

**三个退出条件** (按优先级):
1. 进程消失 (pgrep 返回非 0)
2. 日志含 done-marker
3. 达到 max-iterations 上限

**参数化**: 4 个核心参数全 CLI 化 (见 §3)。

---

## 3. 功能定义 (§3)

| 参数 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `--log-path` | Path | 必填 | OCR stdout 日志路径 |
| `--pid-pattern` | str | batch_tile_ocr | pgrep -f 模式 |
| `--interval` | int | 30 | 轮询间隔秒 |
| `--max-iterations` | int | 120 | 最大轮询次数 (默认 1 小时) |
| `--done-marker` | str | "done" | 日志结束标记 (大小写不敏感) |
| `--progress-pattern` | str | "[BATCH]" | 进度行正则 |

**关键设计决策**:
- `pgrep` 而非 `ps + grep`: pgrep 跨平台, 退出码明确 (0=找到, 1=无)
- 日志末尾检测 `done` 而非精确行号: OCR 工具输出格式可能变化, 关键字更鲁棒
- `max-iterations` 而非无限循环: 防止超时失控, 超时手动可重启

---

## 4. 重要发现 (§4 用法 + 踩坑)

### 4.1 windows CRLF 处理
Windows 写出的日志是 `\r\n`, Linux `tail` 读出来每行带 `\r`, grep `\r$` 后过滤。
解决方案: `last_line.replace("\r", "")` 单行处理。

### 4.2 跨平台进程检查
WSL/Linux: `pgrep -f <pattern>` (退出码 0=找到, 1=无)
Windows: `tasklist | grep <pattern>` (但 grep 不在 Windows 默认 PATH)
**当前**: Linux 优先, Windows 需安装 `grep` (Git Bash / WSL 互通)。

### 4.3 日志轮转
大文件 log 用 `tail -n 1` 会读整个文件, 浪费。
**优化**: `file.seek(-8192, 2)` 只读末尾 8KB, 找最后一行。

### 4.4 异常退出 vs 正常退出
- 进程被 kill → pgrep 返回 1 → break (正常退出)
- 日志被删 → `FileNotFoundError` → 报错退出 (异常)
- 日志持续不更新 (hang) → 靠 max-iterations 上限 (超时退出)

---

## 5. 用法 (§4)

### 5.1 标准用法
```bash
python3 tools/poll_ocr/poll_ocr.py \
    --log-path /mnt/c/Users/radio/<project>/ocr_runs/logs/top_stdout.log \
    --pid-pattern batch_tile_ocr \
    --interval 30 \
    --max-iterations 120
```

### 5.2 推荐工作流
1. 后台启动 OCR (`cmd /c start /b run_ocr.bat`)
2. 立即启动 poll_ocr (另开终端)
3. poll_ocr 自动监控到任务完成 (3 个退出条件任一触发)
4. 启动下一批 OCR, 复用同一 poll_ocr

### 5.3 退出码
- `0`: 任务完成 (任一退出条件触发)
- `2`: 日志文件不存在 (配置错误)
- `1`: 异常 (其他错误)

---

## 6. 演进方向 (§5)

- **多日志源**: 同时监控多个 OCR 任务 (top/bot 并行)
- **JSON 进度**: 日志改成 JSON Lines, poll_ocr 直接 parse
- **告警**: 任务卡死 / 失败率超阈值 → push 通知
- **Web 仪表盘**: 实时显示所有 OCR 任务进度

---

## 7. 相关工具

| 工具 | 用途 |
|---|---|
| `tools/ai_ocr_eval/ai_refdes_ocr.py` | 主 OCR 工具 (被 poll) |
| `tools/ai_ocr_eval/batch_tile_ocr.py` (将来) | 批量 OCR (被 poll) |
| `tools/render_rx_flow.py` | RX flow 渲染 (OCR 后处理) |
