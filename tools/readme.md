# tools/ — 工具索引与全流程

各工具自带 README(参数用法+实测校准值)。本文件是总索引、全流程协作说明与研发进度。
架构思路见根目录 `architecture.md`; 操作规则见 `agent.md`。

**目录约定**: `tools/` 只放当前最佳工具; 参考/旧管线一律在 `tools/zref/`
(字母序靠后, 不再使用/迭代)。

## 全流程管线 (三大管线 + 同步闭环)

```
┌─ ① sch 管线 (原理图识别信号流) ─────────────────────────────┐
│   sch_trace(沿绿线走线+符号) → sch_label_ocr(读标号)          │
│     → sch_flow_walk(绿线流鉴别) → chain_order_rx.json        │
│     → sch_symbol(符号本体识别) → sch_symbol_selfcheck(自我监督校验)   │
│     → sch_wire(走线识别: 引出线对齐黑走线+连接点)            │
│        └──────── 经 sch_components.json 数据库 ──────┘       │
└────────────────────────────────────────────────────────────┘
                        │  chain_order (流经元器件图, schema §3)
                        ▼
┌─ ③ 结合管线 (sch flow → PCB 标注) ──────────────────────────┐
│   make_config_from_chain (chain + pcb 位置 → 路由 config)     │
│     → signal_flow_route (waypoint 计算)                      │
│     → svg_render (渲染) → annot/rx_flow_roundXXX.{png,svg}   │
└────────────────────────────────────────────────────────────┘
                        ▲
┌─ ② pcb 管线 (PCB 定位元器件, 提供 pcb 位置) ─────────────────┐
│   pcb_rect_locator → pcb_circle_locator → pcb_label_ocr      │
│     → pcb_components (components_index.json)                 │
│     → pcb_package (封装) / pcb_verify (校验)                 │
└────────────────────────────────────────────────────────────┘
```

**同步闭环 (关键)**: sch 识别出的 flow 必须同步到 PCB。
`sch_flow_walk --chain` 产出 chain_order → `make_config_from_chain`
读 components_index.json 回填 pcb 位置 → 标注 PCB。
sch 识别结果与 PCB 标注保持一致。

**round 命名**: 每轮探索产出带 `roundXXX` 编号 (sch_flow_roundXXX.png,
rx_flow_roundXXX.png), 便于对比迭代结果。

**彩线颜色**: 绿=RX, 红=TX, 黄=控制, 青=common。

**数据流向**: 原理图学流经元器件 → 固定格式中间结构 → waypoint 计算 → 渲染。
每级产物都是 JSON (chain_order / config / wpts), 渲染只是派生视图。

**PCB 侧定位工具** (辅助 ③ waypoint计算 + PCB 定位, 不参与原理图链学习):
pcb_rect_locator / pcb_circle_locator (裁切) → pcb_label_ocr (OCR refdes) →
pcb_components.json (位置索引) → pcb_package (封装) / pcb_verify (校验)。
它们给出元器件在 PCB 上的位置 (pcb_px, bot 已镜像), 供 make_config_from_chain
回填 chain_order 与 signal_flow_route 布线计算。链序本身只由原理图学到。

## 当前工具 (tools/)

| 工具 | 作用 |
|---|---|
| `pcb_rect_locator/` | 全板矩形轮廓检测 → 分类 + 裁切 + crops_index |
| `pcb_circle_locator/` | 全板圆形检测 (Hough+轮廓) → 分类 + 裁切 + crops_index |
| `pcb_label_ocr/` | 矩形+圆形裁切多角度 OCR, 识别全部 refdes (DML GPU 首选) |
| `pcb_package/` | IC 封装定位: crop-ocr + 精确裁切验证 → body/package |
| `signal_flow_route/` | 信号流自动路由: config → waypoints (最小交叉/避标签) |
| `svg-render/svg_render.py` | 读 wpts 渲染信号流标注图 (PNG+SVG) |
| `pcb_components/` | 元器件索引构建 (pcb_components.json) |
| `pcb_verify/` | 坐标锚点验证 (OCR 误读/DPI 缩放/母图版本排查) |
| `schematic_flow_walk/` | 原理图信号流走线: 彩线掩膜+BFS走线+符号检测+OCR关联 → chain_order |

### sch 细分管线工具 (符号识别链, 工具间关系)

sch 侧符号识别拆成 **识别→自我监督校验** 两层 (对应 PCB 侧 pcb_package→pcb_verify),
经 `sch_components.json` 交互, 每层只依赖前一层产物:

```
sch_trace → sch_label_ocr → sch_flow_walk (产出 symbol_pos + membership)
   ↓
sch_symbol/ (符号本体识别, 消费 flow_through + symbol_pos)
   ├── sch_symbol.py   统一入口 (按 refdes 前缀分派)
   ├── common.py       辅助第一轮粗筛候选 (圆/方块/线/板线, 宁多勿漏)
   └── sch_{cap,res,ind,ic,transistor,diode,varactor}.py  利用现存信息精识别
   ↓
sch_symbol_selfcheck/ (自我监督校验, 消费 symbol_body)
   ├── sch_symbol_selfcheck.py  边界包含/on-label + --correct 校准 + 尺寸知识累积
   ├── check_reverse_ocr.py     反向 OCR 反查关联
   └── check_overlap.py         符号重叠反查
   ↓
sch_wire/ (走线↔符号互验) → sch_render (渲染) → chain_order_rx.json
```

| 工具 | 消费 | 产出 | 关系 |
|---|---|---|---|
| `sch_trace/` | 原理图 PNG (绿线) | `symbols` 候选 (触点绿线) | 层1a 识别: 沿绿线走线+符号探测 |
| `sch_label_ocr/` | symbols 候选 | `components` (refdes 关联) | 层1b 识别: 读标号 (schema §3.5) |
| `sch_verify/` (sch_flow_walk) | components | `membership` + chain_order | 层2 鉴别: 绿线流 membership |
| `sch_symbol/` | flow_through + symbol_pos | symbol_body / symbol_type / orientation | 识别层, 对应 pcb_package |
| `sch_symbol_selfcheck/` | symbol_body | sym_verify / 修正后 symbol_pos / 尺寸知识 | **自我监督层**, 校验+校准+学习, 对应 pcb_verify; 内置反向OCR/边界/重叠/尺寸算法, 属 architecture §14 进化闭环 |
| `sch_wire/` | 纯黑图层 | 走线骨架 / 连接圆点 | 走线↔符号互验, 引出线对齐 |
| `sch_render/` | sch_components.json | roundXXX.png | 渲染层, 供人工检查 |

## 典型操作

```bash
# 1. 裁切定位
python3 tools/pcb_rect_locator/pcb_rect_locator.py --pcb projects/icom2200h/render/pcb-top-600-1.png --out projects/icom2200h/crops/rectangle/
python3 tools/pcb_circle_locator/pcb_circle_locator.py --pcb projects/icom2200h/render/pcb-top-600-1.png --out projects/icom2200h/crops/circle/

# 2. 识别 refdes (Windows DML, 快)
tools/run_label_ocr_dml.bat

# 3. 封装定位 + 验证
python3 tools/pcb_package/detect_ic.py crop-ocr \
  --crops projects/icom2200h/crops/rectangle/crops_index.json,projects/icom2200h/crops/rectangle_bot/crops_index.json \
  --refdes "IC4,IC12,IC6,IC11,IC1" --categories ic --local-ocr

# 4. 布线 + 渲染
python3 tools/signal_flow_route/signal_flow_route.py \
  --config projects/icom2200h/nettable/rx_flow_config.json \
  --out projects/icom2200h/nettable/wpts_rx_auto.json \
  --out-png projects/icom2200h/annot/rx_flow_auto.png \
  --pcb projects/icom2200h/render/pcb-top-600-1.png
```

## 参考工具 (tools/zref/, 不迭代)

| 工具 | 备注 |
|---|---|
| `ai_ocr_eval/` | 旧 AI OCR 管线 (被 rectangle+circle+DML 取代) |
| `annotate_svg_flow/` | 旧 SVG 分层标注 (被 svg_render 取代) |
| `annotate_rx_flow/` | 旧块级/照片标注 |
| `pcb_designator_ocr/` | 旧 tesseract 管线 |
| `font_glyph_decode/`, `svg_glyph_decode/` | 描边字形解析 (原理图功能块标签) |
| `poll_ocr/` | OCR 后台任务轮询 |
| `multi_scale_ocr/` | 多尺度金字塔扫描 |
| `annot_clean/` | 旧渲染版本清理 |
| `ic_locator/` | IC 几何定位 (被 pcb_package 取代) |

## 研发进度(2026-09-16)

### 已完成
- 首选管线投产: rectangle+circle 裁切 → pcb_label_ocr (DML) → pcb_components
- IC 封装定位: crop-ocr + 精确裁切验证 (本体≠标签, 过滤假匹配)
- 信号流自动路由: signal_flow_route (最小交叉/避标签/实虚线/via/IC轮廓)
- 渲染: svg_render (PNG+SVG, via/IC轮廓/箭头)
- 坐标转换修复: 旋转 OCR 逆变换 (rot=90/270 不再偏移)
- 元器件索引 pcb_components.json: 跨视图坐标枢纽 + 封装字段
- **sch_symbol_verify 改名 sch_symbol_selfcheck (2026-09-17)**: 该层不只是"被动验证",
  内置自我监督算法 (反向OCR/符号边界包含/on-label/重叠检测) + 尺寸知识自学习
  (schema §3.6 append 累积) + --correct 自我校准。属 architecture §14 无监督进化闭环,
  目录 `tools/sch_symbol_selfcheck/` (check_reverse_ocr.py / check_overlap.py /
  sch_symbol_selfcheck.py)。

### 下一步
- bot 视图圆形裁切 pcb_label_ocr 全量跑 (已有 --limit 测试)
- TX 链条序入库
- 控制信号(黄)层逐线标注