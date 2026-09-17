
# tools/multi_scale_ocr — 设计文档

**代码不写在这里, 写在 `multi_scale_ocr.py`**。

## §1 目的

PCB 上的丝印字符大小差异巨大:
- R/C/D 等小元件: 字高 ~3mm = 12 px @ 600dpi
- 大 IC/连接器/IF 滤波器: 字高 ~6-10mm = 24-40 px @ 600dpi

单尺度 OCR (如 stage1 tile=1500 + overlap=300) 容易:
- **大字体被切碎或漏检** (tile 内只占 200 字符之一部分)
- **小字体在 upsample 1.5x 后过度放大** → 失真

解决: **多尺度金字塔扫描** — 多尺度 tile 扫描合并去重。

## §2 体系结构

```
multi_scale_ocr 主循环:
  for scale in [1500, 750, 400, 200]:
    run_ai_refdes_ocr(tile=scale)
    collects hits in out_dir_<scale>/
  merge_hits(scale=*) → dedup by (ref, box[0]//10, box[1]//10)
  report:
    每个 refdes 的最佳位置 (按 agree + conf 优先)
```

## §3 参数

| 参数 | 默认 | 含义 |
|---|---|---|
| `--pcb` | 必填 | PCB 母图 PNG |
| `--dpi` | 600 | 输入 DPI |
| `--scales` | `1500,750,400,200` | tile 尺寸逗号分隔 |
| `--work-dir` | `C:\Users\radio\multi_scale_<ts>` | Windows 工作目录 |
| `--out` | stdout | 输出 JSON 路径 |

## §4 用法

### 4.1 完整多尺度扫描 (推荐)
```bash
python3 tools/multi_scale_ocr/multi_scale_ocr.py \
    --pcb projects/icom2200h/render/pcb-bot-600-1.png \
    --dpi 600 \
    --scales 1500,750,400,200 \
    --out ocr_runs/bot_ms/bot600_ms.json
```

### 4.2 单尺度快速 (与之前 bat 等效)
```bash
python3 tools/multi_scale_ocr/multi_scale_ocr.py \
    --pcb projects/icom2200h/render/pcb-top-600-1.png \
    --scales 1500 \
    --out ocr_runs/top_ms/top1500.json
```

## §5 设计原则

- **全参数 CLI** (agent.md §2)
- **headmatter 4 字段** (architecture.md §10)
- **scale 默认值选择**: 1500 = 大字符(F13/F14/IC), 750 = 中字符(IC 中号), 400 = 小字符(R/C 大), 200 = 极小字(R/C 极小)
- **去重策略**: (ref, box_x//10, box_y//10) — 同一 ref 在 10px 内只保留一次, 避免多尺度重复

## §6 已知踩坑

- **v4+v5s 在 stage1 grid 经常 "detection result is empty"** — 多尺度可缓解但不能完全解决
- **UnicodeEncodeError**: Windows python 默认 charmap 编码 → bat 必加 `set PYTHONIOENCODING=utf-8`
- **cmd UNC 路径**: bat 文件必须放 Windows 路径 (`C:\Users\...`), 不能 `/mnt/c/...`

## §7 演进方向

- **跨尺度合并去重**: 当前按 10px 半径, 可改成按 box 重叠率
- **置信度优先**: 高 scale 高 conf > 低 scale, 排序输出
- **OCR + 形状检测结合**: v5s OCR 之外, 加 opencv 形态学找大字体区作为 fallback
- **自动 bot/top 切换**: 检测到 bot 大字体 → 自动标 bot, top 小字 → 自动标 top
