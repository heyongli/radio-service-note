# tools/ — 工具索引与全流程

各工具自带 README(参数用法+实测校准值)。本文件是总索引、全流程协作说明与研发进度。
架构思路见根目录 `architecture.md`; 操作规则见 `agent.md`。

**目录约定**: `tools/` 只放当前最佳工具; 参考/旧管线一律在 `tools/zref/`
(字母序靠后, 不再使用/迭代)。

## 全流程管线 (怎么配合)

```
① 原理图 → 学信号流图
   schematic_flow_walk
     彩线掩膜: 绿=RX, 红=TX, 黄=控制, 青=common
     + 符号形状(圆=三极管/双短线=电容/折线=电阻/螺旋=电感) + OCR refdes
     ──► chain_order_rx.json / chain_order_tx.json / chain_order_ctl.json
         (流经元器件图, 固定格式, schema §3)

② 流经元器件图 (中间结构, 权威有序列表)
   sch_px (原理图) + pcb_px (PCB top, bot 已镜像) + role/status

③ waypoint 计算
   make_config_from_chain ──► rx_flow_config.json (自动)
   signal_flow_route ──► wpts JSON (最小交叉/避标签/实虚线/via/IC轮廓)

④ 渲染
   svg_render ──► annot/rx_flow_top.{png,svg}  (PCB 标注)
   radio_design_flow ──► radio_rx_flow.{svg,png}  (radio-design 流经图)
```

**数据流向**: 原理图学流经元器件 → 固定格式中间结构 → waypoint 计算 → 渲染。
每级产物都是 JSON (chain_order / config / wpts), 渲染只是派生视图。

**PCB 侧定位工具** (辅助 ③ waypoint计算 + PCB 定位, 不参与原理图链学习):
rectangle_locator / circle_locator (裁切) → label_ocr_scan (OCR refdes) →
components_index.json (位置索引) → ic_package_detect (封装) / verify_anchor (校验)。
它们给出元器件在 PCB 上的位置 (pcb_px, bot 已镜像), 供 make_config_from_chain
回填 chain_order 与 signal_flow_route 布线计算。链序本身只由原理图学到。

## 当前工具 (tools/)

| 工具 | 作用 |
|---|---|
| `rectangle_locator/` | 全板矩形轮廓检测 → 分类 + 裁切 + crops_index |
| `circle_locator/` | 全板圆形检测 (Hough+轮廓) → 分类 + 裁切 + crops_index |
| `label_ocr_scan/` | 矩形+圆形裁切多角度 OCR, 识别全部 refdes (DML GPU 首选) |
| `ic_package_detect/` | IC 封装定位: crop-ocr + 精确裁切验证 → body/package |
| `signal_flow_route/` | 信号流自动路由: config → waypoints (最小交叉/避标签) |
| `svg-render/svg_render.py` | 读 wpts 渲染信号流标注图 (PNG+SVG) |
| `components_index/` | 元器件索引构建 (components_index.json) |
| `verify_anchor/` | 坐标锚点验证 (OCR 误读/DPI 缩放/母图版本排查) |
| `schematic_flow_walk/` | 原理图信号流走线: 彩线掩膜+BFS走线+符号检测+OCR关联 → chain_order |

## 典型操作

```bash
# 1. 裁切定位
python3 tools/rectangle_locator/rectangle_locator.py --pcb projects/icom2200h/render/pcb-top-600-1.png --out projects/icom2200h/crops/rectangle/
python3 tools/circle_locator/circle_locator.py --pcb projects/icom2200h/render/pcb-top-600-1.png --out projects/icom2200h/crops/circle/

# 2. 识别 refdes (Windows DML, 快)
tools/run_label_ocr_dml.bat

# 3. 封装定位 + 验证
python3 tools/ic_package_detect/detect_ic.py crop-ocr \
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
| `ic_locator/` | IC 几何定位 (被 ic_package_detect 取代) |

## 研发进度(2026-09-16)

### 已完成
- 首选管线投产: rectangle+circle 裁切 → label_ocr_scan (DML) → components_index
- IC 封装定位: crop-ocr + 精确裁切验证 (本体≠标签, 过滤假匹配)
- 信号流自动路由: signal_flow_route (最小交叉/避标签/实虚线/via/IC轮廓)
- 渲染: svg_render (PNG+SVG, via/IC轮廓/箭头)
- 坐标转换修复: 旋转 OCR 逆变换 (rot=90/270 不再偏移)
- 元器件索引 components_index.json: 跨视图坐标枢纽 + 封装字段

### 下一步
- bot 视图圆形裁切 label_ocr_scan 全量跑 (已有 --limit 测试)
- TX 链条序入库
- 控制信号(黄)层逐线标注