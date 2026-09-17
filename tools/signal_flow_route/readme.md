# signal_flow_route.py -- Signal Flow Auto-Router

> **必读**: 修改本工具前必须完整阅读本文档, 尤其是「连线规范」「评分函数」「输出格式」。
> 算法固化了 architecture.md §4.4 标注规范, 任何改动不得破坏:
> 同面/跨面虚实线、via 标记、IC 轮廓、平行线间距、标签避让。

## 文件清单
| 文件 | 用途 |
|---|---|
| `signal_flow_route.py` | 主程序: 根据坐标+连接关系自动规划路径 |
| `readme.md` | 本文档 (修改前必读) |

## 路由算法

### 输入数据格式

config JSON 结构:
```json
{
  "meta": {
    "purpose": "描述",
    "version": "1.0",
    "consumers": ["tools/signal_flow_route/signal_flow_route.py"],
    "view": "pcb_top_600dpi"
  },
  "components": {
    "<REFDES>": {
      "x": 3676,
      "y": 675,
      "view": "top",
      "lpos": "ur",
      "fs": 44
    }
  },
  "connections": [
    ["ANT", "Q27"],
    ["Q27", "IC4"]
  ]
}
```

**components 字段说明**:

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `x` | int | 是 | 元器件中心 x 坐标 (600dpi PCB 空间) |
| `y` | int | 是 | 元器件中心 y 坐标 (600dpi PCB 空间) |
| `view` | string | 是 | `"top"` 或 `"bot"`, 标号在哪一面 |
| `lpos` | string | 是 | 标号位置: `u/d/l/r/ul/ur/dl/dr` |
| `fs` | int | 否 | 标号字号, 默认 36 |
| `outline` | bool | 否 | `true` = flow 设计 IC, 标轮廓矩形 |
| `outline_w` | int | 否 | 轮廓宽 (px), 默认 220 |
| `outline_h` | int | 否 | 轮廓高 (px), 默认 160 |

**connections 字段说明**:

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `[0]` | string | 是 | 起点 refdes (必须在 components 中) |
| `[1]` | string | 是 | 终点 refdes (必须在 components 中) |

连接顺序即信号流方向: `ANT → Q27 → IC4 → F13 → ...`

### 坐标约定

- **config 坐标 = top-view 空间**: 所有组件坐标统一为 top view 坐标
- **bot 组件**: config 创建时已从 bot 镜像到 top: `top_x = board_center_x + (board_center_x - bot_x)`, 创建后坐标不再变换
- `view` 字段仅用于**虚线/via 判定** (跨面), 不做坐标变换

### 候选路径生成
对每对连接点 `(p1, p2)`, 生成最多 8 条 Manhattan 候选路径:
1. **先垂直再水平**: `[p1] → (x1, y2) → [p2]`
2. **先水平再垂直**: `[p1] → (x2, y1) → [p2]`
3. **折返垂直段** (6 条): 经过 y 偏移 ±100/±200/±400 的中间水平线

### 评分函数
每条候选路径按以下加权评分, 取最低分:
```
score = crossings × 10 + proximity × 8 + label_hits × 5
```
- **crossings**: 与已布线路径的交叉次数 (严格 T 形交叉才算)
- **proximity**: 与已布线路径**平行且间距 < 40px** 的重叠次数 (避免水平线/垂直线视觉重叠)
- **label_hits**: 路径穿过元器件标号文字区域的次数

### 标号避让 (Label Avoidance)
每个元器件根据 `lpos` 定义一个矩形 keep-out 区域:

| lpos | 标号位置 | keep-out 区域 |
|---|---|---|
| `u` | 上方 | 中心上方 |
| `d` | 下方 | 中心下方 |
| `l` | 左方 | 中心左方 |
| `r` | 右方 | 中心右方 |
| `ul` | 左上 | 左上方 |
| `ur` | 右上 | 右上方 |
| `dl` | 左下 | 左下方 |
| `dr` | 右下 | 右下方 |

keep-out 矩形尺寸: `宽度 = len(name) × fs × 0.6 + margin`, `高度 = fs + margin`

### 折返垂直段规则
当路径需要先向左再向右 (或反之), 必须先走一段垂直线, 避免水平线重叠。算法通过生成带 y 偏移的中间点来满足此约束。

### 连线规范 (§4.4)
- **横平竖直**: 所有线段水平或垂直
- **同面/跨面**: 两端 view 相同 → 实线; view 不同 (top↔bot) → 虚线
- **via 标记**: 跨面连接的**到达端**标红色空心圆, 表示过孔
- **箭头**: 每段连线终点有箭头, 跟随信号流方向

### IC 轮廓标注
- config 中设 `"outline": true` 的组件 (flow 设计 IC) 标轮廓矩形
- 轮廓尺寸: `outline_w` × `outline_h` (px, 600dpi)
- 同面 (view=top): 红色实线矩形; 另一面 (view=bot): **紫色虚线矩形**
- **坐标必须为 IC 本体中心, 非标签文字中心**; 未经封装检测确认的 IC **不画轮廓**
  (遵循"未确认坐标不得臆造"原则)。IC12 因标签中心与本体不一致 (rect 索引 3555,2719
  vs circle 索引 3281,2702), 本体未检出, 暂不标轮廓

### 输出格式

输出 wpts JSON, 格式与 `svg_render.py` 兼容:

**line 条目** (信号连线):
```json
{
  "layer": "rx",
  "kind": "line",
  "px": [3676, 675],
  "through": [[3676, 1948], [3438, 1948]],
  "dash": true,
  "label": "",
  "lpos": "d",
  "fs": 28,
  "dot": false
}
```

| 字段 | 说明 |
|---|---|
| `px` | 起点坐标 |
| `through` | 拐点 + 终点坐标列表 |
| `dash` | `true` = 虚线 (跨面), `false` = 实线 (同面) |

**mark 条目** (元器件标记):
```json
{
  "layer": "marks",
  "px": [3438, 1948],
  "label": "Q27",
  "dot": false,
  "fs": 36,
  "lpos": "ul",
  "mark_type": "via"
}
```

| 字段 | 说明 |
|---|---|
| `px` | 元器件坐标 |
| `label` | refdes 标号 |
| `mark_type` | `"via"` = 跨面目标 (红色空心圆), 省略 = 无标记 |
| `outline` | `true` = 画 IC 轮廓矩形 |
| `outline_view` | `"top"` = 红色实线, `"bot"` = 紫色虚线 |
| `outline_w/h` | 轮廓尺寸 (px) |

## 用法

```bash
# 生成 wpts
python3 tools/signal_flow_route/signal_flow_route.py \
  --config projects/icom2200h/nettable/rx_flow_config.json \
  --out projects/icom2200h/nettable/wpts_rx_auto.json

# 生成 wpts + 预览图
python3 tools/signal_flow_route/signal_flow_route.py \
  --config projects/icom2200h/nettable/rx_flow_config.json \
  --out projects/icom2200h/nettable/wpts_rx_auto.json \
  --out-png projects/icom2200h/annot/rx_flow_auto.png \
  --pcb projects/icom2200h/render/pcb-top-600-1.png
```

## 扩展
- 添加新机型: 复制 `projects/<机型>/nettable/rx_flow_config.json`, 修改 components + connections
- 调整评分权重: 修改 `score()` 中 crossings/label_hits 的系数
- 添加障碍物避让: 在 `count_label_hits` 中加入 PCB 板上禁区检测
