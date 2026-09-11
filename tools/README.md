# tools/ — 工具索引与研发进度

各工具自带 README(参数用法+实测校准值)。本文件是总索引与研发进度。
架构思路见根目录 `architecture.md`; 操作规则见 `agent.md`。

## 工具索引

| 工具 | 作用 | 状态 |
|---|---|---|
| `ai_ocr_eval/ai_refdes_ocr.py` | AI 位号 OCR 两阶段管线(grid/contour, preset fast, reuse 复用, 运行归档) | ✅ 可用 v0.2 |
| `ai_ocr_eval/eval_refdes.py` | 单配置 vs 锚点召回评估 | ✅ 可用 |
| `ai_ocr_eval/probe_anchor.py` | 单锚点多变体×多引擎诊断探针 | ✅ 可用 |
| `ai_ocr_eval/compare_runs.py` | 运行间差异对比(调参/校准/回归) | ✅ 可用 |
| `annotate_svg_flow/annotate_svg_flow.py` | 分层 SVG 标注(base64 内嵌+底图锁定, cairosvg 导 PNG; ldx/ldy 标签偏移) | ✅ 可用 v0.1.1 |
| `annotate_svg_flow/route_on_traces.py` | bot 视图铜箔线稿 Dijkstra 路由(顺走线 polyline, 失败回退正交) | ✅ 可用 v0.1 |
| `annotate_svg_flow/make_wpts_from_index.py` | 从 components_index 生成 wpts | ✅ 可用 |
| `components_index/build_index.py` | 元器件索引(跨视图坐标枢纽) | ✅ 可用 v0.1 |
| `pcb_designator_ocr/ocr_designators.py` | 旧 tesseract 多阈值管线 | ⚠️ 备留(被 ai_refdes_ocr 取代) |
| `annotate_rx_flow/add_photo_wpts.py` | 照片位级 waypoint 标注(raster) | ✅ 保留 |
| `annotate_rx_flow/annotate_rx_flow.py` | 旧块级标注(raster) | ⚠️ 备留 |
| `font_glyph_decode/`, `svg_glyph_decode/` | 描边字形解析(原理图功能块标签用) | ✅ 保留 |

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
  1 处存疑(IC12)。教训→网表规范(SCHEMA.md)。
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
