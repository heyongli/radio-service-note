# tools/sch_symbol — sch 细分管线: 原理图符号本体识别

## §1 文件清单
| 文件 | 用途 |
|---|---|
| `sch_symbol.py` | 统一入口: 按 refdes 前缀分派到各类型识别 (可独立运行) |
| `sch_cap.py` | 电容识别: 双板本体 + 走线断口互验 + 掩膜匹配/尺寸自校准 (**精确识别**) |
| `sch_res.py` | 电阻识别: 黑线断口 = 端点, 中心 = 断口中点 (2 端器件) |
| `sch_ind.py` | 电感识别: 与电阻同策略 (复用 `sch_res.detect`) |
| `sch_ic.py` | IC 识别: 黑边空心方块本体 + 反向 OCR 型号 (尺寸按型号键) |
| `sch_transistor.py` | 三极管识别: Hough/黑边圆本体 |
| `sch_diode.py` | 二极管识别: 三角形 + 短竖杠阴极 |
| `sch_varactor.py` | 变容二极管识别: 三角 + 两平行短线阴极 (独立程序) |
| `common.py` | **辅助性第一轮检测**: 圆/方块/线/电容板线的**粗筛候选提取**, 供各类型精识别使用 |
| `readme.md` | 本文档 (修改前必读) |

## §2 定位

**sch 三大细分管线之一 (符号识别管线)**, 专注 sch 侧符号本体识别:
```
① sch_trace/sch_label_ocr (标号识别)
   → ② sch_flow_walk (绿线流鉴别)
   → ③ sch_symbol (本管线: 符号本体识别) → sch_symbol_selfcheck (自我监督校验)
      → sch_wire (走线)
        └────────── 经 sch_components.json 交互 ──────────┘
```
- 输入: `sch_components.json` 中 `membership == flow_through` 的组件
  (已有 `refdes` + `symbol_pos` 候选位置)
- 输出: 每个组件的 `symbol_type` + `symbol_body` (本体框/中心) + `symbol_orientation`
- 对应 PCB 侧 `pcb_package`; 下游 `sch_symbol_selfcheck` (对应 `pcb_verify`) 自我监督校验位置。

## §3 两级识别分工 (重要设计)

### 3.1 common.py = 辅助性第一轮检测 (粗筛候选)
- 只做**候选提取**, 不判定归属。容忍噪声, 宁多勿漏:
  - `find_cap_pairs`: 双平行短线对 (板长 10-40, 板距 8-30) → 大量假板线混入
  - `find_lines`: 走线断口中点 (2 端器件端点)
  - `find_circles` / `find_rects`: 圆/方块轮廓
  - `pure_black_mask`: 纯黑图层 (去绿线干扰)
- 这些函数的板线/走线参数**宽松**, 返回的候选必须经各类型精确识别筛选。

### 3.2 sch_*.py = 利用现存信息精确识别 (精筛归属)
各类型程序**不只依赖 common 粗筛**, 还利用管线已沉淀的信息做互验:
| 现存信息 | 来源 | 电容精识别如何使用 |
|---|---|---|
| `symbol_pos` | sch_trace 沿绿线给的符号位置 | 在候选里取**离 symbol_pos 最近**者 |
| `membership=flow_through` | sch_flow_walk 绿线流鉴别 | 只处理主路组件 |
| 走线断口 | sch_wire 走线↔符号互验 | 断口中点 = 电容中心候选 (`detect_with_wire`) |
| 绿线方向/触点 | sch_flow_walk `green_sides` | 电容方向判定 (走线水平=板线垂直) |
| 典型尺寸知识库 | `sch_symbol_sizes.json` (schema §3.6) | 合成掩膜 + 尺寸自校准 |
| 已确认电容模板 | 从准确电容裁剪 | 真实模板多尺度匹配 |

**电容精识别优先级** (`sch_cap.py`):
1. `detect_plates_on_wire` — 走线上垂直粗线 = 极板 (方向已知, 首选)
2. `detect_with_wire` — 走线断口互验 + 板线对确认
3. `find_cap_pairs` — 双板线对 (common 粗筛, 兜底)
4. 掩膜验证/自校准: `mask_align_score` → `mask_probe` → `calibrate_size`
   → `search_mask` → `real_template_match` (学习自确认电容)

## §4 元数据格式 (sch_components.json, schema §3.5)

每个组件的识别输出字段:
| 字段 | 类型 | 含义 |
|---|---|---|
| `symbol_type` | str | `cap/circle/ic/res/ind/diode/varactor` |
| `symbol_body` | dict | 本体: `{kind, cx, cy, r\|w,h}`; cap 另含 `gap/len/dir` |
| `sym_boundary` | dict | **符号最小包含** (识别产出): 归一化 `{kind: circle\|rect, ...}`, 由 `boundary_from_body()` 生成 |
| `symbol_orientation` | str | 电容: `h` 走线水平 / `v` 走线垂直 |
| `ic_model` | str | IC 型号 (sch_ic --model 反向 OCR) |
| `mask_align/mask_loc/mask_match` | - | 掩膜互验字段 (电容) |
| `calib_scale/calib_size` | - | 尺寸自校准结果 (电容) |
| `real_match/real_loc/real_scale` | - | 真实模板匹配结果 (电容) |

`sym_boundary` 生成规则 (`common.boundary_from_body`):
- circle → `{kind:circle, cx, cy, r}` (外接圆 = 本体圆)
- rect → `{kind:rect, x, y, w, h}` (本体框)
- cap → `{kind:rect, x, y, w=len, h=gap}` (双板线外接框)
- line → `{kind:rect, x, y, w=20, h=20}` (断口小方框)
- diode → `{kind:rect, x, y, w, h}` (三角外接框)

## §5 用法

统一入口 (按 refdes 前缀自动分派):
```bash
python3 tools/sch_symbol/sch_symbol.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --db projects/icom2200h/nettable/sch_components.json \
  --radius 80
```

分类型独立运行 (利用现存信息精识别):
```bash
# 电容 (走线↔符号互验 + 掩膜)
python3 tools/sch_symbol/sch_cap.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --db projects/icom2200h/nettable/sch_components.json \
  --wire --sizes-db projects/icom2200h/nettable/sch_symbol_sizes.json \
  --match-th 0.4
# IC (识别型号)
python3 tools/sch_symbol/sch_ic.py --img ... --db ... --model
# 其他类型
python3 tools/sch_symbol/sch_res.py --img ... --db ...
python3 tools/sch_symbol/sch_ind.py --img ... --db ...
python3 tools/sch_symbol/sch_transistor.py --img ... --db ...
python3 tools/sch_symbol/sch_diode.py --img ... --db ...
python3 tools/sch_symbol/sch_varactor.py --img ... --db ...
```

**注意**: 各 sch_*.py 都**只处理 `membership == flow_through`** 组件
(即必须先跑 sch_flow_walk)。运行前需有 `symbol_pos` 候选 (sch_trace 产出)。

## §6 目的

**sch 细分管线 (符号识别)** 的核心职责: 从原理图自动识别各元器件**符号本体**
(区分本体 vs 引出线, 区分标号 vs 符号), 供:
- `sch_symbol_selfcheck` (tools/sch_symbol_selfcheck/) 自我监督校验位置/关联 + 积累尺寸知识
- `sch_render --redraw-caps` 用学习掩膜重描电容 (干净统一渲染)
- 最终 chain_order 输出符号级坐标 (非标号坐标)
与 PCB 侧 `pcb_package` (封装定位) 对应; 识别(本目录)与自我监督校验(sch_symbol_selfcheck)
分层, 防止位置误判直接污染链序。