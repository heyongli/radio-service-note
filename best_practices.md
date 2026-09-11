# Best Practices: Icom 维修手册 PDF(电路图/点位图)处理

针对本项目任务:从 `IC-2200H-*.pdf`(信号流程图 / PCB top / PCB bot)中提取信息,
在 PCB 点位图上标注 RX/TX 信号流程。以下为已验证的经验总结。

## 1. 这批 PDF 的特点(实测结论)

| 文件 | 内容 | 文本层 | 矢量图形 |
|---|---|---|---|
| `IC-2200H-rxtxflow.pdf` | MAIN UNIT 电原理图(11-2),带红/蓝/绿/黄信号流配色 | 有大量元件位号文本(R5V、FL-363、NJM3404AV…) | 功能块标签(BPF/MIX/ATT 等)是**矢量描边字形,pdftotext 读不到** |
| `IC-2200H-top.pdf` | 9-2 MAIN UNIT TOP VIEW(PCB 顶视/丝印图) | 仅少量连接器标注(ANT、CHASSIS J1、J11、232TX…) | 其余为图形 |
| `IC-2200H-bot.pdf` | 9-4 BOTTOM VIEW(底视/铜箔图) | 仅连接器标注(DATA、SP、引脚号) | 铜箔图形 + 粉色填充的元件外形 |

关键结论(2026-09 修订):**top/bot 视图 PDF 的文本层确实没有位号,
但页面是内嵌光栅图 —— 渲染成 PNG 后位号清晰可见**(300dpi 已可读,
600dpi 更佳)。`pdftotext` 读不到 ≠ 图上没有。位号级定位直接对渲染图
做 OCR(见 §5 配方),不要被"文本层为空"误导而放弃。

## 2. 文本提取

```bash
# 1) 元件位号/参数(带坐标,300dpi 图像空间直接可用)
pdftotext -bbox IC-2200H-rxtxflow.pdf out.html
# 坐标换算: px = pt * dpi/72;pdftoppm 渲染已按页面 /Rotate 旋转,bbox 输出与渲染图像同方向
# 2) 纯文本
pdftotext -layout xx.pdf -
# 3) 矢量图形导出(pdftotext 读不到的描边文字会变成 path)
pdftocairo -svg xx.pdf xx.svg
```

- 检查字体:`pdffonts xx.pdf`。若出现 `Symbol`/自定义编码 Type1 字体,
  pdftotext 输出可能是乱码或缺失 —— 此时改用 `pdftocairo -svg` + 字形解析。
- 本批 rxtxflow 的功能块标签(BPF、MIX、20dB ATT、TX VCO…)是描边 path,
  只能靠渲染后视觉读取(放大裁剪 + 逐块确认,警惕"看图脑补"——
  每个关键标签都要在放大裁剪图中复看确认)。

## 3. 渲染与分辨率

```bash
pdftoppm -r 600 -png xx.pdf out600   # 位号 OCR 的标准渲染(7017x4959)
pdftoppm -r 300 -png xx.pdf out300   # 对照/快速底图(3509x2480)
```

- **位号 OCR 一律 600dpi**(300dpi 小字 conf 掉档);300dpi 仅作目录约定底图。
- 600dpi 坐标 ÷2 = 300dpi 坐标(工具 --scale 0.5 即此用途)。
- 注意 `/Rotate`:pdftotext -bbox 与 pdftoppm 输出方向一致(都含旋转),
  但要先用已知词(如 ANT)交叉验证坐标映射再使用。

## 4. 信号流配色(rxtxflow 页,实测)

- **红** = TX 路径(PA→LPF→ANT SW…,数量最多)
- **蓝** = RX 天线入口段(ANT 连接器附近)
- **绿** = RX 中频/检波/低放段
- **黄** = 电源/控制
可用颜色掩膜统计像素并按块定位路径走向。

## 5. OCR: PCB 点位图(top/bot)位号识别的有效配方(2026-09 实战验证)

**适用性分界(重要)**:rxtxflow 原理图的描边字形功能块标签 OCR 无效(§5 旧结论仍成立,
原因:hairline 矢量描边);但 **top/bot PCB 图是光栅位图印刷体,OCR 完全有效**。

配方(命中 FI2/FI3/FI4 conf>90、X2 conf45、IC10/D12/L39 等数十个位号):

```bash
# 1) 600dpi 渲染(位号笔画更饱满)
pdftoppm -r 600 -png xx-top.pdf top600
# 2) 灰度→autocontrast→多档二值化→2-3x LANCZOS 上采样→psm11 TSV
#    多阈值 T=100~250 并行跑, 合并去重交叉验证
```

配方已固化为工具:`tools/pcb_designator_ocr/ocr_designators.py`
(多阈值 psm11 + 字形聚类兜底 + 同位去重 + 误读归一 F1x→FIx/D1z→D12)。
要领(部分仍适用于 AI 管线, 保留):
- **不要加字符白名单**:"IC10" 会因白名单吞掉 I 变成 "C10"/"CC)";
  不加白名单 + 宽松正则后过滤。
- 字形聚类找候选、逐区域小图 OCR、空间先验验证身份——这些思想已被
  AI 管线继承(stage2 + 防幻觉闸)。
- **每个锚点必须视觉双确认才可 confirmed**(AI 时代是 ±50px crop 拼图签
  `--sheet` 人工过一遍; AI 双引擎 agree 可当预确认, 不是替代)。
- 空间先验仍有效: BNC 正下方找 LPF, FI2 旁找 FI1, 坐标与链序相容才算数。
- **实物照片不可用**(1861px 位号仅 8-10px): PCB 维修 PDF 渲染图
  (300/600dpi) 是唯一可靠底图。
- tesseract 管线保留为对照基线, 不再迭代。

## 5A. AI-OCR 管线(2026-09-10 起, 替代 §5 作首选)

**结论: 没有可直接读位号的 PCB 专用开源 AI**(PANEL-Net/Redraw/Atlas 查无
此 repo; 现存原理图→网表项目内部都用通用 OCR)。CPU 首选 **RapidOCR
(PP-OCRv4/v5/v6, onnxruntime)**。工具: `tools/ai_ocr_eval/ai_refdes_ocr.py`。

实测要点(600dpi PCB top, 7017x4959):
- **全页直接 OCR 会漏小字**(det 输入尺寸限制, rapidocr v3 Global.max_side_len
  默认 2000); 两阶段才是正解: stage1 全页网格抓中大字(fast 预设 v4 约 17s) +
  stage2 字形聚类候选→crop 4x LANCZOS 上采样+灰度对比度→读(全流程 ~9 分钟);
- **crop+4x 上采样后各引擎几乎通读难例**(X2 0.92 / FI4 0.94 / D21 0.97 /
  L60/L61/C256/R203 0.99)——AI rec 不是瓶颈, 全页 det 才是;
- 引擎分工: **v4-mobile 全页小字检出最强**; v6 crop 内读数稳但爱插空格
  ("I C 1 0", 匹配前先去空格); 双引擎同位一致(agree)≈自动预确认;
- contour(内容轮廓+二分细分)模式: 用 cv2 传统工具(轮廓检测是成熟问题,
  不需要 AI), 密集板面不如 grid(29s/58 refdes vs 17.5s/68), 稀疏页面才用;
- 参数全部 CLI 可调, 已验证值与踩坑记在 `tools/ai_ocr_eval/README.md`;
  **每次运行 JSON 归档**(版本/参数/日期), 用 compare_runs.py 对比调参,
  `--reuse-stage1` 复用中间结果避免重复烧算力。
- **对旧网表审计成果**: 24 锚点纠出 5 错(IC10/FI1/R221 坐标错、J4/J7 视图
  错) + 1 存疑(IC12)。旧"视觉确认"错误率 ~20%, AI 双引擎+坐标一致性校验
  应作为锚点强制复核步骤。

### 原理图页(rxtxflow)颜色实测(校准 §4)
- "红"实际是**深红/品红 RGB≈[236,4,142]**(b 通道可达 182!):
  掩膜用 6 值区间 `150,255,0,110,0,200`, 不是简单 r>150,g<110,b<110;
- 黄色在此页**几乎为零**(约 10px)——§4 的"黄=电源/控制"在 300dpi 渲染
  上不成立, 电源/控制线未着色;
- 绿(RX IF/AF)约 1.2%, 蓝(RX 前端)约 0.04%。TX 红路径遍布图面,
  区域级 zone 无意义(bbox 覆盖 >30% 应丢弃), 待逐线读序(todo)。

## 5B. Block 图(IC-2200H-block.pdf)——流程恢复首选源 (2026-09-10)

- **block 图有真文本层**(Helvetica Type1C, 526 词, pdftotext 直读)——与 rxtxflow 的
  描边字形不同, 拓扑恢复应从它入手; bbox 坐标已含 /Rotate 90, 直接对齐横版 300dpi 渲染。
- 块间箭头是矢量线, 文本层读不到; 需配合原理图文本层(pdftotext -bbox)交叉确认链序。
- **教训: 手读零件角色不可信**——IC10 "S-AV36" 曾被当成前端 ATT, 实为 PWR-AMP 末级
  (block 图 PWR AMP 框内; VGG 引脚 TX:6.7V/RX:0V 栅偏佐证); RX 前端 ATT 实为 D18
  PIN 二极管+SQLATT。角色认定一律回到 block 图框内标注。

## 5C. PCB 视图的 IC 引脚号丝印 = 免费的地标 (2026-09-10)

- top/bot PDF 文本层含引脚号标注(如 bot 的 "1/16/8/9"、"1/24/12/13"): 直接给出
  IC 本体位置+方向+引脚间距, 是引脚级 waypoint 的数据源(例: IC4 TA31136FN
  bot(940-1040,1680-1770) 16 引脚坐标全由此+内插得出)。
- IC10 的教训同 5B。另: bot 面大 IC(IC4/IC1 PLL/IC6)与 top 面伴生 IC 背靠背
  (IC11top/IC6bot), 定位一枚后按功能环找另一枚。



## 6. 视图方向(mirror)判断 (2026-09-10 修正)

- **bot 视图(9-4)是 top 视图的 X 镜像(左右翻转): top_equiv_x = 3509 - bot_x, y 不变**(300dpi)
- 证据(10项功能聚类一致性, 详见 top_pcb.json view_mapping):
  Q16+D29(IF-AMP) bot→top-equiv 恰在 FI3/FI4 与 FI1/FI2 之间的 IC4 旁;
  Q26/Q39/IC6(APC) bot→top-equiv 与 IC11(top) 背靠背; Q28/IC7 bot→top-equiv 落 DC power 区;
  Q19 bot→top-equiv 在 BPF 条带与 FI4 之间; REF-OSC Q4(bot) 紧邻 24pin PLL。
- 判断方法: 用"功能伴生部件"(IF放大挨滤波器、APC挨功放、稳压挨电源入口)验证,
  不要只看连接器页边位置(旧结论"垂直镜像"即由此误判, 已废弃)。
- 板框两视图尺寸一致(2043x1622 vs 2040x1621 @300dpi); top 视图 y>2016 的 J11/J3
  是画在板外的独立附图条带, 勿计入板框。

## 7. 中间文件与脚本管理(项目约定)

- 脚本与文档放 `tools/<tool名>/`,各自目录带 README.md;
- 产出分类放独立目录,**禁止混放**(含旧 `extract/`,已废弃删除):
  `render/`=PDF 渲染底图、`scan/`=读图窗口/图签、`nettable/`=网表 JSON
  (含 waypoints)、`annot/`=标注成品、`archive/old_extract/`=历史调试文件;
- 新增目录约定(2026-09-10): `nettable/ai_ocr_runs/`=AI-OCR 运行归档(只增
  不删)、`nettable/components_index.json`=元器件索引(枢纽, 必须保持新鲜)、
  `annot/svg_runs/`=SVG 渲染归档;
- 临时中间件放 `/tmp/opencode/`(600dpi 大图等),网表 JSON 里记录其路径。

## 8. 标注与数据层(2026-09-10 新增)

- **原理图/PCB 标注首选 SVG 分层**(`tools/annotate_svg_flow/`): 仿
  `example/talkabout-bot.svg` 分层原则; 底图 base64 内嵌+图层锁定;
  实线=确认/虚线=推断/not-located 进 notes 层。旧 raster 标注
  (add_photo_wpts) 保留给照片场景。
- **waypoints 从 components_index 生成**(`make_wpts_from_index.py`),
  不再手写; 信号流跨图(原理图链序→PCB 落点)一律经
  `nettable/components_index.json` 解析坐标(架构见 architecture.md)。
- **nettable 数据规范**见 `projects/<机型>/nettable/SCHEMA.md`:
  300dpi 统一坐标空间、provenance 必填、状态三态、revisions 留痕。
- 中间结果常态化保存: AI 运行 JSON 归档 `nettable/ai_ocr_runs/`(校准
  资产, 只在确认乱套时删); SVG 渲染归档 `annot/svg_runs/`。

## 9. 任务推进建议(已完成部分)

1. 先 `pdftotext` 全文 dump → 建立位号/信号名清单与坐标;
2. `pdftocairo -svg` + 字形解析补齐描边文字;
3. 渲染 PNG,用颜色掩膜定位红/绿信号路径;
4. PCB 视图标注:位号级方案用 `tools/pcb_designator_ocr/`(OCR 位号) +
   `tools/annotate_rx_flow/add_photo_wpts.py`(waypoints JSON 渲染,
   实线=确认/虚线=推断) —— 产出 `projects/<机型>/annot/top_pcb_rx.png`
   与 `nettable/top_pcb.json`、`nettable/top_designators.json`;
   旧的块级 `annotate_rx_flow.py` 仅作备留;
5. 所有视觉读数用第二次独立放大裁剪复核,避免幻觉。
