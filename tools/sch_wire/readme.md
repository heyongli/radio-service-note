# tools/sch_wire — 原理图走线识别 (走线↔符号互验)

## 文件清单
| 文件 | 用途 |
|---|---|
| `sch_wire.py` | 纯黑图层 → 连接圆点检测 + Zhang-Suen 骨架化 → 走线端点/交叉点 |
| `readme.md` | 本文档 (修改前必读) |

## 定位
sch 管线的**走线识别层 (独立发展)**。识别原理图黑色走线网络与连接点,
供走线↔符号互验 (走线必终结于符号, 符号必有走线, best_practices §5b-3)。

```
sch_trace → sch_label_ocr → sch_flow_walk → sch_symbol → sch_symbol_selfcheck
  → sch_wire(走线骨架/连接点) → 引出线对齐走线 → chain_order
```

## 有效参数
| 参数 | 默认 | 说明 |
|---|---|---|
| `--x, --y` | 2500,2500 | 关注区域中心 |
| `--radius` | 300 | 区域半径 |
| `--out` | - | 输出 wires.json (可选) |

## 数据格式 (输出 wires.json)
```json
{
  "junction_dots": [{"x": 1316, "y": 1675, "r": 4}],   // 小黑圆 = 交叉/连接点
  "wire_nodes":    [{"x": 1280, "y": 1754, "deg": 1}], // 度1=端点, 度3+=交叉
  "region": [x0, y0, x1, y1]
}
```
- 消费方: `sch_render --redraw-caps` (电容引出线对齐走线), 后续 chain 拓扑

## 用法
```bash
python3 tools/sch_wire/sch_wire.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --x 2500 --y 2500 --radius 300 --out /tmp/opencode/wires.json
```

## 目的
无监督建立走线拓扑 (端点在符号处/连接点), 与符号识别互证;
连接点决定走线交叉, 是电路拓扑恢复的基础。