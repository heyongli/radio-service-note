* 通过pdf或者图片的电路图, 信号流程图, 在实物pcb照片或者维修pcb的点位图上标注信号流程
* 注意合理利用各种现有工具
* 用到脚本放入 tools/目录; 工具全参数 CLI 化, 参数可靠用法记各工具 README
* 文档分工: agent.md=操作规则 | best_practices.md=实证配方(任务前必读) |
  architecture.md=设计思路与原则 | todo.md=后续路线 | tools/README.md=工具索引与研发进度
* 旧约定"extract目录"已废弃(2026-09): 中间文件按类型分目录(见下条), 禁止新建/混入 extract/
* 每个设备/机型(如 IC-2200H)建立项目目录 projects/<机型>/: 源PDF放项目根, 中间文件按类型分目录(禁混放): render/(PDF渲染底图) scan/(读图窗口/图签) nettable/(网表+元器件索引+waypoints JSON, 规范见其 SCHEMA.md) annot/(标注成品, 含 svg_runs/) archive/(历史文件); 临时中间件放 /tmp/opencode/ 并在网表JSON记录路径
* 开始任务前先 load best_practices.md, 按其中的已验证结论操作, 避免重复踩坑

## 最终目的 (用户明确, 2026-09-14 记录)

* **本项目的最终交付物**: 在 PCB **top/bot 实拍或点位图**上, 复现原理图
  (rxtx-flow-sch.pdf) 中那根 **绿色粗 RX 信号流线** —— 信号从 ANT 进,
  依次穿过 BPF → RF-AMP(Q27) → Mixer(IC4) → IF Filter(F13/F14) →
  IF-AMP(Q16) → Detector(IC4) → AF Preamp(IC12), 一直连到输出。
* 原理图绿线是**贯穿的流程线**(一段接一段, 有分支: AGC/SQL/VCO 辅助),
  不是若干孤立坐标点; PCB 标注必须同样给出**连续可追踪的信号路径**。
* 因此每个「位号 OCR 定位」只是手段, 最终要落到 **waypoints 的 rx/tx
  层 line/through 实体**(绿色粗线+箭头+拐点), 让 RX 流程在 PCB 图上一眼
  可见; 只标 marks(圆点+文字) 未连流程线 = 未完成。

## 位号识别与标注要求(2026-09-10 大版本更新)

* **位号识别首选 AI-OCR 管线** `tools/ai_ocr_eval/ai_refdes_ocr.py`
  (RapidOCR PP-OCRv4/v5/v6, onnx CPU; 无可用 PCB 专用开源 AI——已调研证实)。
  工作流: `--preset fast` 出初稿 → `--reuse-stage1` 复用 → 针对性细化;
  运行 JSON 永久归档于 nettable/ai_ocr_runs/, 用 compare_runs.py 调参对比。
  旧 tesseract 管线仅作对照基线。
* **信号流跨图标注一律经元器件索引** `nettable/components_index.json`
  (ref-des → 各视图坐标/状态/链序), 生成 waypoints 用
  `tools/annotate_svg_flow/make_wpts_from_index.py`, 不手写坐标映射
* **标注成品用分层 SVG** `tools/annotate_svg_flow/annotate_svg_flow.py`
  (仿 example/talkabout-bot.svg: 底图 base64 内嵌+图层锁定; rx/tx/ctrl/
  blocks/marks/notes 语义分层; 实线=确认, 虚线=推断, not-located 不臆造)
* 渲染一律用 `pdftoppm -r 600`(位号识别)/300(底图与标注); 600dpi 坐标 ÷2
  才能入网表(300dpi 统一空间, 网表 SCHEMA.md 强制)
* 未确认的链路段必须虚线+not-located, 不得臆造坐标
* 防幻觉三道闸: 双引擎同位一致 / 坐标空间与链序先验校验 / 视觉图签兜底
  (agent 见 architecture.md §6)
* nettable 必含: confirmed_anchors(坐标+置信来源), not_located 清单,
  chain_order_schematic, artifacts 索引, revisions 留痕
* **git 提交纪律 (2026-09-10 用户指示)**: 不要自动 commit;
  工作完成后停下汇报, 等用户明确要求 commit 才执行。
