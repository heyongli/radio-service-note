# tools/ — 工具索引与研发进度

各工具自带 README(参数用法+实测校准值)。本文件是总索引与研发进度。
架构思路见根目录 `architecture.md`; 操作规则见 `agent.md`。

**目录约定**: `tools/` 只放当前最佳工具; 参考/旧管线一律在 `tools/zref/`
(字母序靠后, 不再使用/迭代)。

## 当前工具 (tools/)

| 工具 | 作用 |
|---|---|
| `rectangle_locator/` | 全板矩形裁切定位 (分类+裁切+crops_index) |
| `circle_locator/` | 全板圆形检测+分类+裁切 |
| `ic_ocr_scan/` | IC 候选矩形多角度 OCR (DML GPU 首选) |
| `ic_package_detect/` | IC 封装定位: crop-ocr + 精确裁切验证 |
| `signal_flow_route/` | 信号流自动路由 (生成 waypoints) |
| `svg_render.py` | RX/TX 信号流标注渲染 (PNG+SVG) |
| `components_index/` | 元器件索引构建 |
| `verify_anchor/` | 坐标锚点验证 |

## 参考工具 (tools/zref/, 不迭代)

| 工具 | 备注 |
|---|---|
| `ai_ocr_eval/` | 旧 AI OCR 管线 (被 rectangle+circle+DML 取代) |
| `annotate_svg_flow/` | 旧 SVG 分层标注 (被 render_rx_flow 取代) |
| `annotate_rx_flow/` | 旧块级/照片标注 |
| `pcb_designator_ocr/` | 旧 tesseract 管线 |
| `font_glyph_decode/`, `svg_glyph_decode/` | 描边字形解析 (原理图功能块标签) |
| `poll_ocr/` | OCR 后台任务轮询 |
| `multi_scale_ocr/` | 多尺度金字塔扫描 |
| `annot_clean/` | 旧渲染版本清理 |
| `ic_locator/` | IC 几何定位 (被 ic_package_detect 取代) |

## 研发进度(2026-09-10)

### 已完成
- AI OCR 选型: 无可用 PCB 专用开源模型 → RapidOCR(PP-OCRv4/v5/v6, onnx CPU)。
  实测: 全页小字检出 v4-mobile 最强; crop+4x 上采样后各引擎几乎全通读难例。
- 两阶段管线投产: 全页网格扫 + 字形聚类候补 crop 读, 双引擎互证(agree)。
  600dpi 整页约 5-9 分钟全流程; fast 预设 17s 初稿。
- 运行归档机制: runs-dir + 版本/日期/参数快照/脚本hash + compare_runs 对比。
- preset fast→细化 工作流 + --reuse-stage1 复用中间结果。
- contour(轮廓+二分细分)模式: 已实现并校准——密集板面不如 grid, 稀疏页面用。
- 旧网表审计: 24 锚点中纠出 5 处错误(IC10/FI1/R221 坐标错、J4/J7 视图错)、
  1 处存疑(IC12)。教训→网表规范(schema.md)。
- SVG 分层标注工具(仿 example): 语义图层/实线确认虚线推断/embed 底图/锁定。
- 元器件索引 components_index.json: 原理图↔PCB 跨图映射枢纽, v0.1。
- 原理图 SVG 分层标注成品(IC-2200H rxtxflow)。

### 进行中/下一步
- bot 视图整页 AI OCR 扫描(当前仅 top 完整跑过; J4/J7 已探针定位)
- FI1/FI3/FI4 在原理图页的位置入库(sch_components_raw 缺 FI1)
- IC12 位号复核(多引擎不可读, 需人工放大图签)
- TX 链条序与 AI 读数入库(rx 链已完整)
- 控制信号(黄)层: 目前只有色块区域级, 需逐线标注

### 历史包袱(待清理)
- archive/old_extract/ 旧中间件(按 agent.md 约定仅存档)
- tesseract 管线保留为对照基线, 不再迭代
