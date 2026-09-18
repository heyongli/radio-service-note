# tools/sch_render — 层3 渲染 (识别+鉴别结果到原理图)

## 文件清单
| 文件 | 用途 |
|---|---|
| `sch_render.py` | 读 sch_components.json, 渲染绿线高亮 + 组件着色 + 标号连线 |
| `readme.md` | 本文档 (修改前必读) |

## 定位
sch 管线的**渲染层 (纯消费)**。把识别+鉴别结果可视化到原理图, 供人工检查。
不修改数据库, 只读 `sch_components.json`。

```
sch_trace → sch_label_ocr → sch_flow_walk(鉴别)
  → sch_symbol → sch_symbol_selfcheck → sch_render(渲染) → roundXXX.png
```

## 有效参数
| 参数 | 默认 | 说明 |
|---|---|---|
| `--color` | green | 信号流彩线高亮 (绿=RX) |
| `--show-aux` | off | 渲染非 flow_through 组件 (灰点辅助标记) |
| `--crop` | off | 裁剪大片空白边 (最后一步) |
| `--crop-margin` | 40 | 裁剪后留白 (px) |
| `--redraw-caps` | off | 用学习到的电容掩膜重新描边渲染 (干净统一) |

## 渲染规则
- 绿线高亮为纯绿 overlay
- 组件按 membership 着色: flow_through=黄 / branch=红 / none=灰
- 标号→符号红连线 + 符号中心红点
- 符号边界 (sym_boundary): 圆/方块画黄框
- label 文字框 (text_box): 橙框 (on-label 校验可视化)
- 图例自动放在低墨量象限
- `--redraw-caps`: 电容双板红描边, 引出线对齐 sch_wire 走线 (黑色走线 y 轴探测)

## 数据格式 (输入)
- 读 `sch_components.json` (schema §3.5): `membership` / `symbol_pos` / `text_pos` /
  `refdes` / `sym_boundary` / `text_box` / `symbol_type` / `symbol_body`

## 用法
```bash
python3 tools/sch_render/sch_render.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --color green --db /tmp/opencode/sch_components.json \
  --out projects/icom2200h/annot/rx_flow_sch_round028.png
```

## 目的
每轮迭代输出可检查的渲染图 (annot/rx_flow_sch_roundXXX.png), 供人工复核
识别/鉴别结果, 驱动无监督进化 (architecture §14)。