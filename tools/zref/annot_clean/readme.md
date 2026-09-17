
# tools/annot_clean — 设计文档

**代码不写在这里, 写在 `annot_clean.py`**。

## §1 目的

每次渲染 rx_flow 新版本 (v8, v9, ..., v12, ...) 后, 旧版本 PNG/SVG 留在
annot/ 目录, 长期堆积。annot/ 目录约定是"仅最终 SVG+PNG"(architecture §0),
所以旧版本必须清理。

## §2 体系结构

```
annot_clean 主循环:
  files = glob(annot_dir, "rx_flow_top_v*.{png,svg}")
  files.sort_by_version_desc()  # v12, v11, v10, ...
  keep(files[:KEEP_LAST])
  for f in files[KEEP_LAST:]:
    if --archive:
      move(f, annot_dir/archive/)
    else:
      unlink(f)
```

## §3 参数

| 参数 | 默认 | 含义 |
|---|---|---|
| `--annot-dir` | `projects/icom2200h/annot` | 目录 |
| `--pattern` | `rx_flow_top_v*.{png,svg}` | glob 模式 |
| `--keep` | `1` | 保留最新 N 个 |
| `--archive` | `False` | 移到 archive/ 而非删除 |
| `--dry-run` | `False` | 只显示不执行 |

## §4 用法

### 标准流程 (渲染新版本后)
```bash
# 1. 渲染新版本
python3 tools/render_rx_flow.py --wpts ... --out-png v13.png --out-svg v13.svg

# 2. 清理旧版本 (留最新 1 个)
python3 tools/annot_clean/annot_clean.py

# 或移到 archive (保留历史, 但不放 annot/)
python3 tools/annot_clean/annot_clean.py --archive
```

### 默认 KEEP_LAST=1 的理由

每次渲染都进新版本, 旧版本意义不大 (可从 git 或 wpts JSON 重新生成)。
但若想保留最近 3 版做对比:
```bash
python3 tools/annot_clean/annot_clean.py --keep 3
```

## §5 设计原则

- **全参数 CLI** (agent.md §2): `--keep`, `--archive`, `--dry-run` 等
- **headmatter 五字段** (architecture.md §10): purpose/format/version/consumers/applies_to
- **默认安全**: 默认 dry-run 不真删要 `去掉 --dry-run` 才执行? 不, 默认即执行
  (除非 `--dry-run`); 渲染流程后立即清理, 减少认知负担
- **归档而非删除**: `--archive` 移到 archive/, 保留历史供 git/对比

## §6 演进方向

- **关联 wpts 自动清理**: 同步清理 `wpts_archive/` 中的旧 wpts JSON
- **git ignore**: annot/ 的最终产物不进 git (v0 目录规范约定), 自动清理避免散落
- **定时清理**: 配合 CI 每日自动清理非最新 N 版本
