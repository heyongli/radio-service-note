# tools/sch_wire — 原理图走线识别 (无监督 net 网表)

## 文件清单
| 文件 | 用途 |
|---|---|
| `sch_wire.py` | 纯黑图层 → 连接圆点检测 + Zhang-Suen 骨架化 → 走线端点/交叉点 |
| `sch_wirenet.py` | **无监督 net 网表提取**: 暗像素连通域 = net, 主 net 识别 (真理源) |
| `readme.md` | 本文档 (修改前必读) |

## 定位
sch 管线的**走线识别层 (独立发展, 不依赖任何其他)**。走线是最**连续、最简单**
的完整图形元素, 识别最容易, **无需绿线/标注** (绿线是叠印其上的标注, 非遮挡)。
供走线↔符号互验 + **元器件→net 网表关联** (best_practices §5b-3)。

```
sch_trace → sch_label_ocr → sch_flow_walk → sch_symbol → sch_symbol_selfcheck
  → sch_wire(走线骨架/连接点) → sch_wirenet(net 网表) → 符号↔net 关联 → chain_order
```

## 核心发现 (2026-09-17 实测)
- **每个连通域 = 一个 net** (无监督, 无需标注)
- IC-2200H: **5963 nets**, 主走线网络 = 903588px (**76%** 暗像素), 单一连通域
- **94% 绿线落在主 net 内** → 确认绿线标注的正是主走线网络
- 原图直接连通域即得最完整主 net (绿线属于走线), **无需先去绿线**
- **暗阈值 (gray<150) 自动剥离浅色标注线 (重要特征)**: 深色结构 (走线/
  绿线/元件) 灰度<150 进 net; 浅色标注线被阈值排除:
  | 标注线 | 灰度mean | <150占比 | 主net内 |
  |---|---|---|---|
  | 绿线 | 107 | 100% | 94% (进) |
  | 橙线 | 154 | 2% | 2% (避开) |
  | 青线 | 138 | 66% | 57% (部分进) |
  | 黄线 | 178 | 1% | 1% (避开) |
  即: **橙/黄粗标注线自动避开 net, 只有深色结构进入** (绿线因叠在深色
  走线上灰度被压低而进入)。这是 `gray<150` 阈值的自动筛选效果。
- **net 掩码 = 走线 + 元器件轮廓 + 部分粗结构, 但不含 label** (标号文字
  灰阶>150 被暗阈值剥离)。主 net 13.8% 为粗块 (元件轮廓/符号体, 336 域)
- **统一 net 会在电容处断开 (关键判据)**: 几乎所有器件轮廓都在主 net 内,
  除去了标注; 但**电容处 net 断开**。主net(76%) + 断片(24%) = 全部导体。
  实测: 14 个 GT 电容都在**主 net 与断片的交界处** (两端连通中间断开)
  → 电容 = 连接两个不同 net 的桥 (强判据, 用于电容识别)
- 用途: 主 net 掩膜存为**真理源** (可信度 85, schema §3.5b); 符号必在走线上
  → 可 de-wire 切除走线; 元器件用**本体位置**关联 net (标号位置在小 net 上)
- **后期处理**: de-greenline 剔除绿线 (主net∩绿线 19.2%), 走线半宽
  p90 5.7→2.3 (绿线是主要粗度来源); 元件轮廓分离列为后续任务

## 有效参数
| 参数 | 默认 | 说明 |
|---|---|---|
| `sch_wirenet: --dark-th` | 150 | 暗像素阈值 |
| `--min-area` | 50 | 最小 net 面积 (滤噪声) |
| `--main-min` | 0.5 | 主 net 占暗像素比例阈值 |
| `--save-main` | - | 保存主 net 掩膜 PNG (真理源) |
| `sch_wire: --x, --y, --radius` | 2500,2500,300 | 局部走线区域 |

## 数据格式 (输出 wirenet.json)
```json
{
  "_meta": {"purpose": "sch 走线 net 网表 (无监督连通域)", ...},
  "total_nets": 1005,
  "total_dark_px": 1188795,
  "main_net": {"id": 13, "area": 903588, "ratio": 0.76, "is_main": true,
               "main_mask": "/tmp/wire_main_net.png"},
  "nets": [{"id": 13, "area": 903588, "bbox": [527,549,4034,2805]}, ...]
}
```
- `sch_wire.py` 输出: junction_dots (连接圆点) + wire_nodes (骨架端点/交叉)

## 用法
```bash
# net 网表 + 主 net 真理源
python3 tools/sch-true-finding/sch_wirenet.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --out /tmp/opencode/wirenet.json --save-main /tmp/opencode/wire_main_net.png

# 局部走线骨架/端点
python3 tools/sch-true-finding/sch_wire.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --x 2500 --y 2500 --radius 300 --out /tmp/opencode/wires.json
```

## 目的
无监督建立走线拓扑 (net 网表 + 骨架 + 连接点), 与符号识别互证:
- 走线必终结于符号, 符号必有走线 (双向约束)
- 识别出的元器件可**关联到 net 网表** (符号本体位置落在哪个 net)
- 主走线网络是**最强真理源** (最连续最简单, 不依赖其他, architecture §14.1c)
- 连接点决定走线交叉, 是电路拓扑恢复的基础