# tools/sch_symbol_selfcheck — 符号自我监督校验 (自我监督层)

## 文件清单
| 文件 | 用途 |
|---|---|
| `sch_symbol_selfcheck.py` | 主校验: 边界包含 / on-label / --correct 校准 / 尺寸知识自学习 |
| `check_reverse_ocr.py` | 反向 OCR 反查: 符号中心 OCR 读出 refdes 与关联一致 = 关联正确 |
| `check_overlap.py` | 符号重叠反查: 两符号边界重叠 = 误关联 |
| `readme.md` | 本文档 (修改前必读) |

## 定位
sch 管线的**自我监督校验层** (原名 sch_symbol_verify, 2026-09-17 更名)。
消费 `sch_symbol` 的 `symbol_body`, **内置自我监督算法自证识别是否准确**
(非被动验证, 属 architecture §14 无监督进化闭环的自我校验手段)。

```
sch_symbol(符号本体识别) → sch_symbol_selfcheck(自我监督校验)
  ├── 边界包含 (红点在圆/方块本体?)
  ├── on-label 检测 (红点落 label 文字框 = 错)
  ├── 反向 OCR (check_reverse_ocr)
  ├── 重叠检测 (check_overlap)
  └── 尺寸知识自学习 (OK 的尺寸 append 知识库, 中位=典型, 反哺校验)
```

## 有效参数
| 参数 | 默认 | 说明 |
|---|---|---|
| `--correct` | off | 红点不在本体上时用本体中心修正 symbol_pos (自我校准) |
| `--sizes-db` | db 同目录 | 符号尺寸知识库路径 (默认 sch_symbol_sizes.json) |
| `--size-tol` | 0.6 | 尺寸偏差容差 (典型尺寸 ±60%) |
| `check_reverse_ocr: --radius/--rots` | 45 / 0,90,180,270 | 反向 OCR 窗口/旋转集 |
| `check_overlap: --pad` | 6 | 重叠容差 (px) |

## 数据格式 (sch_components.json 新增字段, schema §3.5)
| 字段 | 含义 |
|---|---|
| `sym_verify` | `ok` (红点在本体) / `on_label` (落文字框) / `corrected` (已校准) / `bad` |
| `size_dev` | 尺寸偏离典型值比例 (None=符合, 数值=偏差) |
| `reverse_ocr_ok` | bool, 反向 OCR 关联确认 (check_reverse_ocr 写) |
| `size_check` | check_size 结果 (True=符合典型) |

## 用法
```bash
# 主校验 + 自我校准 + 尺寸知识累积
python3 tools/sch_symbol_selfcheck/sch_symbol_selfcheck.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --db /tmp/opencode/sch_components.json --correct

# 反向 OCR 反查 (确认 refdes 关联)
python3 tools/sch_symbol_selfcheck/check_reverse_ocr.py \
  --img ... --db /tmp/opencode/sch_components.json --rots 0,90,180,270

# 重叠反查
python3 tools/sch_symbol_selfcheck/check_overlap.py --db /tmp/opencode/sch_components.json
```

## 目的
识别( sch_symbol)与自我监督校验(本目录)分层, 防止位置/关联误判直接污染链序。
内置算法全部自证, 无人工标注; 尺寸知识库 append 累积, 越用越准 (schema §3.6)。
对应 PCB 侧 `pcb_verify`。