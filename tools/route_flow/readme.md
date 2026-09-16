# route_flow.py -- Signal Flow Auto-Router

## 文件清单
| 文件 | 用途 |
|---|---|
| `route_flow.py` | 主程序: 根据坐标+连接关系自动规划路径 |
| `readme.md` | 本文档 |

## 路由算法

### 输入数据格式

config JSON 结构:
```json
{
  "meta": {
    "purpose": "描述",
    "version": "1.0",
    "consumers": ["tools/route_flow/route_flow.py"],
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

**connections 字段说明**:

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `[0]` | string | 是 | 起点 refdes (必须在 components 中) |
| `[1]` | string | 是 | 终点 refdes (必须在 components 中) |

连接顺序即信号流方向: `ANT → Q27 → IC4 → F13 → ...`

### 坐标变换
- bot 组件自动镜像到 top view: `top_x = board_center_x + (board_center_x - bot_x)`
- 所有路径在 top view 坐标系中计算

### 候选路径生成
对每对连接点 `(p1, p2)`, 生成最多 8 条 Manhattan 候选路径:
1. **先垂直再水平**: `[p1] → (x1, y2) → [p2]`
2. **先水平再垂直**: `[p1] → (x2, y1) → [p2]`
3. **折返垂直段** (6 条): 经过 y 偏移 ±100/±200/±400 的中间水平线

### 评分函数
每条候选路径按以下加权评分, 取最低分:
```
score = crossings × 10 + label_hits × 5
```
- **crossings**: 与已布线路径的交叉次数 (严格 T 形交叉才算)
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
- **同面** (top→top): 实线, 无标记
- **跨面** (bot→top): 虚线, 目标处标红色空心圆 (via)
- **箭头**: 每段连线终点有箭头, 跟随信号流方向

### 输出格式

输出 wpts JSON, 格式与 `render_rx_flow.py` 兼容:

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

## 用法

```bash
# 生成 wpts
python3 tools/route_flow/route_flow.py \
  --config projects/icom2200h/nettable/rx_flow_config.json \
  --out projects/icom2200h/nettable/wpts_rx_auto.json

# 生成 wpts + 预览图
python3 tools/route_flow/route_flow.py \
  --config projects/icom2200h/nettable/rx_flow_config.json \
  --out projects/icom2200h/nettable/wpts_rx_auto.json \
  --out-png projects/icom2200h/annot/rx_flow_auto.png \
  --pcb projects/icom2200h/render/pcb-top-600-1.png
```

## 扩展
- 添加新机型: 复制 `rx_flow_config.json`, 修改 components + connections
- 调整评分权重: 修改 `score()` 中 crossings/label_hits 的系数
- 添加障碍物避让: 在 `count_label_hits` 中加入 PCB 板上禁区检测
