# tools/sch_flow_walk — 层2 鉴别: 绿线流走线 (flow walk)

## 文件清单
| 文件 | 用途 |
|---|---|
| `sch_flow_walk.py` | 鉴别: 读 sch_components.json, 判定绿线流经 membership |
| `readme.md` | 本文档 (修改前必读) |

## 定位
三层管线的**层2**: 判定每个组件是否属于绿线流经。
更新 `sch_components.json` (schema §3.5) 的 `membership` 字段。

```
sch_recognize(识别) → sch_flow_walk(鉴别) → sch_render(渲染)
          └────────── 经 sch_components.json 交互 ──────────┘
```

## 鉴别判定 (ICOM/Yaesu 域特征, best_practices §5b-3)
| membership | 含义 | 判据 |
|---|---|---|
| `flow_through` | 主路, 绿线真正流过 | 符号两侧沿流向**共线**有绿 (E+W 或 N+S) |
| `branch` | 支路/死端 | 触点绿线但只有单侧 |
| `none` | 非流经 | 符号不触点绿线 |

- **主路 = 绿线两侧共线通过** (入+出); 支路只有单侧
- 绿线经过电容基本连续 (只变细), 无完整断口 → 靠符号触点 + 侧边判定

## 有效参数 (实测, 沉淀为知识)
| 参数 | 默认 | 实测结论 |
|---|---|---|
| `--band` | 22 | 绿线侧边探测带宽; **22 最优** (recall 24/31), 14→17/31 |
| `--side-dist` | 20,50 | 侧边绿线探测距离; **20,50 最优** (近侧边), 30,70→21/31 |
| `--touch-r` | 25 | 符号触点绿线半径 |
| `--seed` | - | 给则 chain_order 按 BFS 走线排序 |

**扫描结论**: band 越大 recall 越高 (但误检增多), side 越近越好。
ground truth: 31 组件 (gt_rx_flow.json), 最佳组合 band=22/side=20,50 → 24/31。

## 用法
```bash
python3 tools/sch_flow_walk/sch_flow_walk.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --color green --db nettable/sch_components.json
```

## 输出
更新 db 的每个组件: `membership` / `green_touch` / `green_sides` / `flow_dir`