# tools/sch_label_ocr — 层1b 读绿线符号的标号 (OCR 关联 refdes)

## 文件清单
| 文件 | 用途 |
|---|---|
| `sch_label_ocr.py` | 对 sch_trace 的符号候选局部 OCR, 关联 refdes → components |
| `readme.md` | 本文档 (修改前必读) |

## 定位
sch 管线的**第二层 (识别: 标号)**。消费 `sch_components.json` 的 `symbols` 候选,
为每个符号关联一个 refdes (标号→符号关联), 产出带标号的 `components`。

```
sch_trace(走线+符号探测) → sch_label_ocr(读标号) → sch_flow_walk(鉴别)
  → sch_symbol(本体识别) → sch_symbol_selfcheck(自我监督) → sch_render(渲染)
```

## 有效参数
| 参数 | 默认 | 说明 |
|---|---|---|
| `--refdes` | - | 全量 refdes 位置 JSON (可选, 优先用; 无则局部 OCR 兜底) |
| `--assoc-dist` | 120 | 标号→符号关联最大距离 (px) |
| `--type-bonus` | 40 | 类型匹配加分 (降低距离惩罚) |

## 数据格式
- 输入: `sch_components.json` 的 `symbols` (sch_trace 产出)
- 输出: `components[]` (schema §3.5):
```json
{"refdes": "C77", "symbol_pos": [1318, 1674],
 "symbol_type": "cap", "text_symbol_dist": 42,
 "text_box": [[x0,y0],[x1,y1],...]}   // refdes 文字框 (供 on-label 校验)
```
- 关联策略: 对每个符号找**最近 refdes** (类型匹配加分), 距离超限则局部 OCR 兜底
- 消费方: `sch_flow_walk` (鉴别) → `sch_symbol` (本体识别)

## 用法
```bash
python3 tools/sch_label_ocr/sch_label_ocr.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --refdes /tmp/opencode/sch_refdes_600.json \
  --db /tmp/opencode/sch_components.json \
  --assoc-dist 220 --type-bonus 40
```

## 目的
建立符号→refdes 关联, 使下游能按类型识别本体 (sch_symbol) 并按链序组织
(chain_order)。内部含反向 OCR 检查 (reverse_ocr_check) 做关联自证。