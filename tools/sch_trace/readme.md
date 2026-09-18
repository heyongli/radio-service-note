# tools/sch_trace — 层1a 沿绿线走线 + 局部符号探测

## 文件清单
| 文件 | 用途 |
|---|---|
| `sch_trace.py` | 沿绿线 flow BFS 走线, 局部探测符号 (电容/三极管/IC), 写符号候选 |
| `readme.md` | 本文档 (修改前必读) |

## 定位
sch 管线的**第一层 (识别)**。消费原理图 PNG, 产出 `sch_components.json` 的 `symbols` 候选
(只有绿线触点上的符号, 无需全板识别)。

```
sch_trace(走线+符号探测) → sch_label_ocr(读标号) → sch_flow_walk(鉴别)
  → sch_symbol(本体识别) → sch_symbol_selfcheck(自我监督) → sch_render(渲染)
```

## 有效参数 (实测沉淀)
| 参数 | 默认 | 说明 |
|---|---|---|
| `--seed` | 必填 | 绿线起点 x,y (如 626,1480) |
| `--color` | green | 信号流彩线 (绿=RX/红=TX/黄=控制/青=common) |
| `--cap-gap` | 8,40 | 电容极间距范围 (px) |
| `--plate-len` | 15,90 | 电容板长范围 (px) |
| `--circle-area` | 600,60000 | 三极管圆面积范围 |
| `--ic-area` | 4000,250000 | IC 矩形面积范围 |
| `--touch-r` | 30 | 符号触点绿线判定半径 |
| `--circle-rmin/rmax` | 10,35 | HoughCircles 圆半径范围 |
| `--hough-param2` | 30 | HoughCircles param2 (圆检测灵敏度) |

## 数据格式 (输出 sch_components.json.symbols)
```json
{
  "_meta": {"purpose": "sch components (trace: green-flow symbols)",
            "source": "sch_trace (green line walk + symbol detect)"},
  "symbols": [
    {"x": 1318, "y": 1674, "w": 45, "h": 18, "sym": "cap"},
    {"x": 1398, "y": 1728, "sym": "circle"},
    {"x": 2900, "y": 2200, "sym": "ic"}
  ]
}
```
- `sym`: cap / circle(三极管) / ic
- 只含触点绿线的符号 (BFS 距离场 + touch_r 判定)
- 消费方: `sch_label_ocr` (读标号关联 refdes)

## 用法
```bash
python3 tools/sch_trace/sch_trace.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --color green --seed 626,1480 --db /tmp/opencode/sch_components.json
```

## 目的
只识别绿线上的元器件, 避免全板识别噪声; 走线↔符号互验的起点
(走线必终结于符号, 符号必有走线, best_practices §5b-3)。