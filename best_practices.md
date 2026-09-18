
# best practices: icom 维修手册 PDF(电路图/点位图)处理

针对本项目任务:从 `IC-2200H-*.pdf`(信号流程图 / PCB top / PCB bot)中提取信息,
在 PCB 点位图上标注 RX/TX 信号流程。以下为已验证的经验总结。

## 1. 这批 PDF 的特点(实测结论)

| 文件 | 内容 | 文本层 | 矢量图形 |
|---|---|---|---|
| `IC-2200H-rxtxflow.pdf` | MAIN UNIT 电原理图(11-2),带红/蓝/绿/黄信号流配色 | 有大量元件位号文本(R5V、FL-363、NJM3404AV…) | 功能块标签(BPF/MIX/ATT 等)是**矢量描边字形,pdftotext 读不到** |
| `IC-2200H-top.pdf` | 9-2 MAIN UNIT TOP VIEW(PCB 顶视/丝印图) | 仅少量连接器标注(ANT、CHASSIS J1、J11、232TX…) | 其余为图形 |
| `IC-2200H-bot.pdf` | 9-4 BOTTOM VIEW(底视/铜箔图) | 仅连接器标注(DATA、SP、引脚号) | 铜箔图形 + 粉色填充的元件外形 |


* 很多日本机器原理图rx绿线是**贯穿的流程线**(一段接一段, 有分支: AGC/SQL/VCO 辅助),
  不是若干孤立坐标点; PCB 标注必须同样给出**连续可追踪的信号路径**。


关键结论(2026-09 修订):**top/bot 视图 PDF 的文本层确实没有位号,
但页面是内嵌光栅图 —— 渲染成 PNG 后位号清晰可见**(300dpi 已可读,
600dpi 更佳)。`pdftotext` 读不到 ≠ 图上没有。位号级定位直接对渲染图
做 OCR(见 §5 配方),不要被"文本层为空"误导而放弃。

## 2. 文本提取

```bash
# 1) 元件位号/参数(带坐标,300dpi 图像空间直接可用)
pdftotext -bbox IC-2200H-rxtxflow.pdf out.html
# 坐标换算: px = pt * dpi/72;pdftoppm 渲染已按页面 /rotate 旋转,bbox 输出与渲染图像同方向
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

## 5. OCR: PCB 点位图(top/bot)位号识别的有效配方

**适用性分界(重要)**:rxtxflow 原理图的描边字形功能块标签 OCR 无效(§5 旧结论仍成立,
原因:hairline 矢量描边);但 **top/bot PCB 图是光栅位图印刷体,OCR 完全有效**。

配方(命中 FI2/FI3/FI4 conf>90、X2 conf45、IC10/D12/L39 等数十个位号):

```bash
# 1) 600dpi 渲染(位号笔画更饱满)
pdftoppm -r 600 -png xx-top.pdf top600
# 2) 灰度→autocontrast→多档二值化→2-3x LANCZOS 上采样→psm11 TSV
# 多阈值 t=100~250 并行跑, 合并去重交叉验证
```

配方已固化为工具:`tools/zref/pcb_designator_ocr/ocr_designators.py`
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

## 5a. AI-OCR 管线(替代 §5 作首选)

**结论: 没有可直接读位号的 PCB 专用开源 AI**(PANEL-Net/Redraw/Atlas 查无
此 repo; 现存原理图→网表项目内部都用通用 OCR)。CPU 首选 **RapidOCR
(PP-OCRv4/v5/v6, onnxruntime)**。工具: `tools/zref/ai_ocr_eval/ai_refdes_ocr.py`。

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
- 参数全部 CLI 可调, 已验证值与踩坑记在 `tools/zref/ai_ocr_eval/README.md`;
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

## 5b. block 图(ic-2200h-block.pdf)——流程恢复首选源

- **block 图有真文本层**(Helvetica Type1C, 526 词, pdftotext 直读)——与 rxtxflow 的
  描边字形不同, 拓扑恢复应从它入手; bbox 坐标已含 /Rotate 90, 直接对齐横版 300dpi 渲染。
- 块间箭头是矢量线, 文本层读不到; 需配合原理图文本层(pdftotext -bbox)交叉确认链序。
- **教训: 手读零件角色不可信**——IC10 "S-AV36" 曾被当成前端 ATT, 实为 PWR-AMP 末级
  (block 图 PWR AMP 框内; VGG 引脚 TX:6.7V/RX:0V 栅偏佐证); RX 前端 ATT 实为 D18
  PIN 二极管+SQLATT。角色认定一律回到 block 图框内标注。

## 5b-2. rxtxflow 绿线 = rx 路径权威, 但"触及≠主路"

- 绿线掩膜(g>120,r/b<110)约 1.1% 像素; 膨胀 25px + 位号 55px 邻近判定得"触及集"
  (146 器件)——这只是**候选**, 必须按电路原理甄别主路:
  - **主路(串行)**: 管子(Q)/IC/晶体与陶瓷滤波器(FI/X)/串行耦合电容/串行线圈(L45/L46/L43/L38...)
  - **非主路(绿线也碰到)**: 10µ/2.2µ 电源扼流圈(L62/L25)、栅/漏偏置电阻(R110/R113...)、
    旁路电容、AGC 检波分支(D29/R55...)、静噪管(Q34)、静音开关(Q21)、W/N 切换网络(D23-26+R135-140)
- 绿线还证实: Q27(RF-AMP)与 Q16(IF-AMP)都在主路; X2/C100 在 IC4 MIXIN 入口通道上。
- 方法: 触及集 ∩ 原理分类 → 主路链; 与 block 图链序交叉验证。

### 5b-3. ICOM/Yaesu 电台电路图特征 (2026-09-16, schematic_flow_walk 实测)

以下是 ICOM/Yaesu 电台维修手册原理图 (rxtxflow 页) 的**域特征**, 自动识别须按此设计:

- **信号流彩线**: 绿=RX, 红=TX, 黄=控制, 青=common line
- **绿线经过元器件断开**: 断口位置 = 电容/三极管/IC; 断口 gap = 元器件尺度
  (15-18px=小电容/电阻, 25-80px=三极管/中器件, 127-228px=IC 大封装)
- **电容 `-| |-`**: 两条平行短线, **两板间必须为空 + 两侧必有接线**; 绿线经过电容
  **基本连续** (只变细, 无完整断口) → 电容要按符号检测, 不能靠断口
- **三极管=圆, IC=矩形本体**, 简单易识别
- **空心箭头**: 流向箭头是**封闭边框** (空心三角轮廓); 黑色箭头截断绿线,
  某方向宽度 > 绿线宽 → 需剔除 (非元器件)
- **几像素小断层 = 联通**: 绿线可 flood 过去, 不算断口 (先强闭合弥合)
- **只有沿线方向的端口才是器件断口**: 骨架端点处是曲线/切向的不是器件;
  须沿线方向探测
- **断口处向所有方向探索流出口**, 一个元器件可有多个流出口 (IC 多引脚)
- **细黑走线横穿绿线不是器件**: 黑走线横穿绿线导致误判, 特征: 宽度 < 绿线 1/5,
  沿法向小范围截图到图边沿 → 忽略
- **绿线一般沿一条黑线走** (重要): 彩线叠加在黑色走线上, 断口 = 绿线离开黑线处
- **走线必终结于符号, 符号必有走线** (双向约束, 2026-09-17):
  - 每条走线 (端点) 必然连到元器件符号或连接圆点
  - 每个元器件符号必有引出线/走线
  - 用于互验: 走线端点应落在符号位置/连接点; 符号应被走线连接
  - 无监督方法: 走线↔符号互相印证, 一端错则另一端也错
- **符号有方向 (orientation)**: 电容等 2 端器件板线垂直于走线方向 —
  走线水平则板线垂直 (dir=h), 走线垂直则板线水平 (dir=v).
  掩膜/引出线须按方向旋转, 数据库记录 symbol_orientation
- **绿断时沿未断黑线前进**: 器件处绿线断但黑走线连续, 沿黑线穿过器件到下一段绿
- **小黑圆点 = 交叉点**: 沿有绿线覆盖的黑线走 (选绿覆盖支路)

这些特征是 ICOM/Yaesu 电台图纸的通用规律, 其他品牌可能不同, 需重新实测。


## 5c. IC 封装定位三法(pin-silk / body / contour)

**工具: `tools/pcb_package/detect_ic.py`(CLI, 方法+实测值见其 README)。**

1. **pin-silk(首选)**: PCB 视图 PDF 文本层的引脚号丝印(孤立 "1"/"16"/"8"/"9")
   → 同行成对=同边角引脚, x 相近的两对=同一 IC 对边 → 内插**全引脚坐标+方向**,
   零图像处理误差。IC-2200H 实测: bot 4 个 IC(含 IC4 16pin 全引脚)、top 3 个。
   条件: 板上印了引脚号(维修手册常见)。
2. **body(暗矩形)**: 已知标签位附近找暗色矩形(阈值+轮廓+面积/长宽比/矩形度,
   取最近候选)。实测: IC9(971,1772)73x88 ✓、IC11 ✓; 失效于 S-AV36 模块(非矩形)。
3. **contour(线稿 Canny)**: 稳定性差, 备选。
- 引脚内插规则: 含 pin1 的列 1→k, 含 pinN 的列 N→k+1, 按丝印实际位置定向;
  pin-silk 的 `corners` 字段给出四角引脚号即封装方向。
- 优先级: pin-silk > body > contour; 定位结果与"功能伴生部件环"互证后才入 nettable
  (例: IC9 body 检出 ↔ R125/C188/C192 输入网络环)。




## 5d. 旋转扫描: 竖排丝印位号必杀技

**问题**: bot 视图部分位号丝印是**竖排文字**(旋转 90° 印刷, 如 BPF2 条带 C124-C162、Q27),
0° OCR 完全读不到 → 曾被误判"标签不可读"。

- **配方**: 对 crop 做 `im.rotate(90/270, expand=True)` × 引擎(v4/v6) × 预处理(orig/autocontrast-L)
  扫描; 竖排文字只在旋转后可读。**PIL rotate 正角=逆时针**, 逆变换:
  rot90(CCW): `x = W - by, y = bx`;rot270: `x = by, y = H - bx`(写反则 90/270 结果互换,
  Q27 扫描首轮即犯此错, 用已知 0° 读数如 C97 交叉验证坐标数学)。
- **交叉验证**: 弱读数用多旋转/多预处理变体一致性确认(如 Q27 = 'Q27'/'027' 5 变体 0.85-0.91),
  再用**功能伴生件**佐证(Q27 旁恰有 R110 栅偏电阻; D18 与 R127 同簇 = ATT 网络,
  且原理图上 D18 邻 R127)。
- 实测战果: Q27 3SK299 bot(1006,1323)、D18+R127 ATT bot(1198-1219,1270)、
  BPF2 级间条带 18 个位号(C124…C162/C222/C164/C286/R90/R93/R101/R128/R129/R76/R233/C108/C245/C293)。
- 后续"标签不可读"结论前, 先跑一轮 90/270° 旋转扫描再放弃。

## 6. 视图方向(mirror)判断

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
  `render/`=PDF 渲染底图、`crops/`=切片/裁切+索引、`nettable/`=网表 JSON
  (含 waypoints/SCHEMA.md/pcb_index)、`annot/`=标注成品(**仅** SVG+PNG, 严禁子目录)、
  `svg_runs/`=SVG 渲染归档(含参数快照)、`ocr_runs/`=AI-OCR 运行归档(只增不删,
  严禁 annot/crops/svg_runs 子目录); 详见 architecture.md 第 0 章;
- 新增目录约定(2026-09-10): `nettable/ai_ocr_runs/`=AI-OCR 运行归档(只增
  不删)、`nettable/pcb_index.json`=元器件索引(枢纽, 必须保持新鲜)、
  `svg_runs/`=SVG 渲染归档(2026-09-15 从 annot/ 提升至项目根);
- 临时中间件放 `/tmp/opencode/`(600dpi 大图等),网表 JSON 里记录其路径。

## 8. 标注与数据层

- **原理图/PCB 标注首选 SVG 分层**(`tools/zref/annotate_svg_flow/`): 仿
  `example/talkabout-bot.svg` 分层原则; 底图 base64 内嵌+图层锁定;
  实线=确认/虚线=推断/not-located 进 notes 层。旧 raster 标注
  (add_photo_wpts) 保留给照片场景。
- **waypoints 从 pcb_index 生成**(`make_wpts_from_index.py`),
  不再手写; 信号流跨图(原理图链序→PCB 落点)一律经
  `nettable/pcb_index.json` 解析坐标(架构见 architecture.md)。
- **nettable 数据规范**见 `projects/<机型>/nettable/SCHEMA.md`:
  300dpi 统一坐标空间、provenance 必填、状态三态、revisions 留痕。
- 中间结果常态化保存: AI 运行 JSON 归档 `ocr_runs/`(2026-09-15 移出
  nettable/)(校准资产, 只在确认乱套时删); SVG 渲染归档 `svg_runs/`。

## 9. 任务推进建议(已完成部分)

1. 先 `pdftotext` 全文 dump → 建立位号/信号名清单与坐标;
2. `pdftocairo -svg` + 字形解析补齐描边文字;
3. 渲染 PNG,用颜色掩膜定位红/绿信号路径;
4. PCB 视图标注:位号级方案用 `tools/zref/pcb_designator_ocr/`(OCR 位号) +
   `tools/zref/annotate_rx_flow/add_photo_wpts.py`(waypoints JSON 渲染,
   实线=确认/虚线=推断) —— 产出 `projects/<机型>/annot/top_pcb_rx.png`
   与 `nettable/top_pcb.json`、`nettable/top_designators.json`;
   旧的块级 `annotate_rx_flow.py` 仅作备留;
5. 所有视觉读数用第二次独立放大裁剪复核,避免幻觉。

## 10. 小工具创建规范
工具创建规范(位置/命名/readme/CLI/检查清单)见 architecture.md §5.6-5.11。

## 11. 坐标数据验证方法

**核心原则**: 数据错的概率 > 渲染错的概率。任何标注流程必须是
**"先验证数据，再渲染"**，否则一错全错。

### 11.1 反例 (v10 错位案例)

2026-09-15 修复 v10 RX flow 时发现:
- 用了 v8 时代的坐标 (1646, 1159) (F13)
- 但 v8 坐标来自**300dpi 图像** OCR, v10 渲染到 **600dpi 底图**
- 300dpi → 600dpi 直接嵌入 → 实际渲染的 F13 位置是 v8 的 2 倍偏移
- 用工具 `pcb_verify.py` 验证: 在 v10 给的坐标处裁切 PCB 图, OCR 找不到 F13

### 11.2 正解: pcb_verify 自检

工具: `tools/pcb_verify/pcb_verify.py` (新建)

**核心思想**: 坐标可能错位, 唯一权威验证 = **回到 PCB 母图, 裁切坐标周围, 重新 OCR, 看是否识别出相同 refdes**。

算法 (回环校验):
```
for ref, x, y in coords:
    crop = PCB.crop((x-w/2, y-h/2, x+w/2, y+h/2))
    crop.upscale(2x)  # OCR 需更大字体
    ocr_texts = ai_refdes_ocr(crop)
    if ref in ocr_texts or ref prefix in ocr_texts:
        → match (坐标正确)
    else:
        → mismatch (坐标错位)
```

### 11.3 验证流程 (OCR 工具产出索引后必走)

1. **OCR 跑完一轮** (如 `ai_refdes_ocr.py` 跑 `pcb-top-600-1.png`)
2. **聚合**: 从 `raw_stage1` + `raw_stage2` 聚合 refdes → pcb_index.json
3. **校验 (新)**: 用 `pcb_verify.py` 对**每个关键 refdes** 做自检
4. **mismatch 处理**:
   - 重新跑 OCR (换引擎/参数)
   - 检查缩放/坐标变换是否正确
   - 检查母图是否最新版本
   - 标 `not_located` 不画主流程
5. **match 后才渲染**: rx_flow / svg 等下游

### 11.4 关键尺寸参数 (经验值)

- `crop_size`: 300x200 (太小→字符不全, 太大→邻接器件混入)
- `upscale`: 2x (300x200 → 600x400, 让 OCR 看到清晰字)
- `OCR stage1 tile`: 500, overlap=100 (单 tile 模式, 不需要 grid)
- `engines`: `v5s,v4` (灵敏度+保守双引擎)

### 11.5 完整命令

```bash
# 验证 v10 关键节点 (示例)
python3 tools/pcb_verify/pcb_verify.py \
    --pcb projects/icom2200h/render/pcb-top-600-1.png \
    --coords "(1277,1489)=J11 (1646,1159)=F13 (1547,1159)=F14 (1714,1385)=IC12 (1726,709)=D12 (1671,807)=D27 (1919,1094)=FI1 (1921,1345)=FI2" \
    --crop-size 350x230 \
    --fuzzy

# 报告输出: report.json
# 退出码 0=全部 match, 1=有 mismatch, 2=参数错
```

### 11.6 与 schema.md 的关系

pcb_verify 是 schema.md §5B "数据溯源规范"的具体实施工具:
- 每个 refdes 坐标必须**可验证** (回到母图 OCR 仍识别到)
- 任何坐标变更必须先验证再入库
- 不验证的坐标等同"临时数据", 应标 `validated: false`

### 11.7 与 best_practices §10 的关系

§10 定义"小工具创建规范" — pcb_verify 是该规范的典型应用:
- 路径在 `tools/pcb_verify/`
- readme.md (五要素设计文档)
- 全参数 CLI 化
- 头部 docstring 含 purpose/format/version/consumers

## 12. WSL 调 Windows python.exe 跑 GPU OCR

**场景**: 本机是 WSL2 Linux, 但 RapidOCR + onnxruntime-directml 必须 Windows
原生才能跑 DirectML GPU 加速。WSL 内 Linux Python 没有 DML EP。

### 12.1 路径问题 (根本原因)

- WSL 路径: `/mnt/c/Users/radio/foo.png` (Linux 视角)
- Windows 路径: `C:\Users\radio\foo.png` (Windows 视角)
- Linux Python 看到 WSL 路径 ✓
- **Windows Python 不认 WSL 路径** (`/mnt/c/...`) ✗
- 反之 Windows 路径 (`C:\...`) 在 WSL Linux 里通常可读, 但 cmd.exe 拒绝从 UNC 路径启动
  (报错: "UNC paths are not supported. Defaulting to Windows directory.")

### 12.2 反例 (5 次踩坑模式)

| # | 错误做法 | 症状 |
|---|---|---|
| 1 | `cmd.exe /c "cmd /c script.bat"` 从 WSL cwd | UNC paths are not supported |
| 2 | bat 里直接传 `--img /mnt/c/Users/radio/foo.png` | Windows PIL `FileNotFoundError` |
| 3 | bat 里 `cd /d C:\Users\radio\tools_full` 但 ai_refdes_ocr.py 不在 sys.path | `ModuleNotFoundError` |
| 4 | 用 bash 的 `\"...\"` 转义嵌套 5 层 | 引号解析错乱 |
| 5 | 子进程传 `cwd="C:\\Users\\radio"` (WSL 视角找不到 `C:\\`) | `FileNotFoundError: C:\\Users\\radio` |

### 12.3 正解模式 (5 步)

```bash
# Step 1: 把要 Windows 访问的文件 cp 到 Windows 路径 (避免 UNC)
cp /home/.../crop.png /mnt/c/Users/radio/verify_<ts>/crop.png
# WSL 视角下, 该路径是 /mnt/c/Users/radio/verify_<ts>/crop.png
# Windows 视角下, 是 C:\Users\radio\verify_<ts>\crop.png

# Step 2: 写 bat 文件, 内容:
#   - cd /d C:\Users\radio\tools_full (工具目录)
#   - 用 python.exe -c "import sys; sys.path.insert(0, r'C:\Users\radio\tools_full'); from ai_refdes_ocr import main; sys.argv=..."

# Step 3: bat 文件本身也放 Windows 路径 (不能用 /mnt/c/...)

# Step 4: 从 WSL 用 cmd.exe /c 启动 (不传 cwd, 让 bat 自己 cd)
cmd.exe /c "C:\\Users\\radio\\verify_<ts>\\run_ocr.bat"

# Step 5: OCR 输出 JSON 也会在 C:\Users\radio\verify_<ts>\out\, 用 WSL 读时
#          路径是 /mnt/c/Users/radio/verify_<ts>/out/*.json
```

### 12.4 关键点速记

| 关键点 | 说明 |
|---|---|
| **bat 必须用 `cd /d` + `-c "import sys; sys.path.insert..."`** | ai_refdes_ocr.py 在 tools_full/ 下, 必须 sys.path 加 |
| **.bat 文件放 Windows 路径** | 不能 /mnt/c/... (cmd 拒绝 UNC) |
| **OCR 输入输出图片 cp 到 Windows 路径** | PIL/onnxruntime 不认 /mnt/c/... |
| **cmd.exe /c 不传 cwd** | 让 bat 自己 cd /d, 避免 WSL UNC cwd |
| **stdout/stderr 重定向到 log.txt** | 避免中文 UnicodeEncodeError |

### 12.5 反例: 不要这样做

```python
# ❌ 在 WSL cwd 下直接 cmd.exe /c (UNC 问题)
subprocess.run(["cmd.exe", "/c", "script.bat"], cwd="/home/radio")

# ❌ bat 里传 WSL 路径给 Windows python
python.exe ai_refdes_ocr.py --img /mnt/c/Users/radio/crop.png  # FileNotFoundError

# ❌ Windows Python 找不到脚本 (sys.path 没加)
python.exe C:\Users\radio\tools_full\ai_refdes_ocr.py  # ModuleNotFoundError

# ❌ 在 Linux bash 用 5 层嵌套引号
cmd.exe /c "\"C:\\Users\\radio\\ocr_gpu_venv\\Scripts\\python.exe\" \"C:\\Users\\radio\\tools_full\\ai_refdes_ocr.py\" --img \\\"/mnt/c/...\\\"\"  # 解析错乱
```

### 12.6 验证工具: `tools/pcb_verify/`

完整实现了 §12.3 模式 + OCR 验证 + match/mismatch 报告。
详见 `tools/pcb_verify/readme.md`。

### 11.8 真实案例: v10 错位 2x 教训

**症状**: v10 渲染后用户报告 "F13, F14 位置根本不对"。

**根因**: v10 用了 v8 时代的坐标 (1646, 1159) (F13)。v8 来自 300dpi 全图 OCR,
**数值是 300dpi 像素** (1646, 1159 = PCB 上 ~5.5 inch x ~3.9 inch)。
但 v10 渲染到 **600dpi 底图** (5100x6600), 把 300dpi 数值直接当 600dpi 用:
- 1646 / 5100 ≈ 32% 横坐标 → 实际位置在板中央偏右, 不是 PCB 的 F13 真位置
- OCR v12 (600dpi 全图, DML 双引擎) 找到 J11 (2556, 2978), 与 v10 的 (1277, 1489) 比例 = 2.00

**教训**:
1. **跨 DPI 空间坐标不能直接嵌入**, 必须按 scale 转换 (300dpi → 600dpi 应 ×2)
2. **从历史数据继承坐标时**, 必须验证 src_dpi 和 tgt_dpi 是否一致
3. **渲染前必须 pcb_verify 自检**, 在 v10 坐标处裁切 PCB 图, OCR 跑一次, 看识别结果
4. **板边铆钉校验是必要的**: J11 (2556, 2978) 在 OCR 找到的位置, 但 y=2978 超板边 y=2929,
   仍在板上标签区(印刷区 label 237 = (2572-3290, 2966-3276))

### 11.9 v11 修复方案

**流程**:
1. 跑 OCR v12 (Windows DML, 600dpi 全图, v4+v5s 双引擎) → 144 hits, 47 agree
2. 用 OCR 真实坐标 (而非历史坐标) 写 wpts_rx_top_v11.json
3. F13/F14/IC12/Q27/IC4/D23 OCR 仍没找到 → 标"待 pcb_verify"虚位, 不作主流程锚点
4. 红点聚类精度 0px (renderer 渲染位置完全落在 OCR 报告位置)

**验证方法**: 红点聚类 (scipy.ndimage.label) 找红色像素的中心, 应等于 OCR 报告的 (cx, cy)。

### 11.10 ocr_runs 目录位置

**症状**: 仓库根出现 `ocr_runs/` 目录, 违反 architecture.md §0 (ocr_runs 必须在 `projects/<机型>/ocr_runs/`)。

**根因**: Windows OCR bat 文件 `--runs-dir` 用了相对路径 `ocr_runs/<sub>`, 而 `cmd.exe` 的当前目录 (cwd) 是 `C:\Users\radio\tools_full` (由 bat 里的 `cd /d` 切了), 但 Python 子进程可能仍以 Windows 默认 cwd 启动, 导致 OCR JSON 写到 `C:\Users\radio\icom2200h\ocr_runs\...` (这是 Windows 工作区, OK) **或** 偶尔落到仓库根 `ocr_runs/` (如果 cmd cwd 不是 Windows home)。

**修复**: bat 文件 `--runs-dir` 必须用**绝对 Windows 路径** `C:\Users\radio\icom2200h\ocr_runs\<sub>`, 不允许相对路径。

**已修**: 所有 bat 文件 (`run_top_full.bat`, `run_top600_v12.bat`, `run_bot600_v12.bat` 等) 都改为绝对路径。

**用户要求保留的目录位置**:
- **Windows OCR 工作区**: `C:\Users\radio\icom2200h\ocr_runs\` (bat 输出实际写到这, 方便 Windows python 直接读)
- **仓库规范目录**: `projects/icom2200h/ocr_runs/` (git 不追踪, 仅作为 WSL 视角的镜像位置)
- **不要**在仓库根创建 `ocr_runs/` 或 `render/` `annot/` 等任何规范目录的子集

### 11.11 PCB OCR 常见误识别 (1↔I, 0↔O 等)

**症状**: OCR v12 把 PCB top 上的 **F13 误识别为 FI3**, **F14 误识别为 FI4**
(数字 `1` 被识别成大写 `I`)。

**根因**: PCB 丝印字体小 + 印刷质量差异, OCR 模型在低置信度时容易:
- `1` ↔ `I` (最常见)
- `0` ↔ `O`
- `5` ↔ `S`
- `B` ↔ `8`
- `Q` ↔ `O`

**程序内化修正**: `MISREAD_MAP` + `fix_misread()` 实现见 `tools/zref/ai_ocr_eval/ai_refdes_ocr.py`。

**手动修正案例**:
- OCR "FI3" @ (3292, 2319) → 修正为 "F13" (chain_order 里有 F13)
- OCR "FI4" @ (3094, 2319) → 修正为 "F14" (chain_order 里有 F14)
- OCR "FI1" @ (3840, 2188) → 不修正 (chain_order 里有 FI1, 这是真值)
- OCR "FI2" @ (3843, 2691) → 不修正 (FI2 是真值)

**规则**:
- **OCR 输出永远不可信** (含 1↔I 等误识别), 必须用 chain_order 上下文校正
- **校正后必须 pcb_verify 验证** (裁切+OCR 自检)
- **校正写入 _meta.correction**: 保留原始 OCR 文本, 标记修正原因, 可追溯

## 13. 经验教训

### 13.1 坐标系踩坑

**v10/v11 错位根因**: F13/F14 的 v8 坐标是从 top view OCR 找到的, 但 F13/F14 实际只在 bot view 有丝印。教训: **坐标必须标注 view, 不能跨 view 共享**。

**v9 渲染严重错位**: board_tiles 是 600dpi 切的, 但 OCR 用了 `--img-dpi 200`, 坐标直接相加导致偏移 3 倍。教训: **不同 DPI 空间只能比例映射, 不能直接相加**。

### 13.2 OCR 识别踩坑

**v6 幻觉问题**: PP-OCRv6 small/mobile 容易产生假位号 (IC169/IR78)。教训: **默认用 v4 server, v6 仅作交叉验证**。

**全页 OCR 无效**: 600dpi 全页扫仅 1-5 个命中, 丝印字太小。教训: **必须按 200px tile 切块才出效果**。

### 13.3 圆形检测踩坑

**pad 噪声**: 圆形检测 1791 个中大部分是铜 pad 圆角。教训: **min-diameter 需要 120+ 才能过滤小 pad, 但仍有大量噪声**。

**IC 被间接发现**: IC 附近有圆形 pad, OCR 在圆形裁切中读到了 IC 丝印。教训: **圆形检测是补充手段, 不是独立方法**。

### 17.4 工具协作踩坑

**WSL→Windows 路径**: WSL 的 `/mnt/c/` UNC 路径 Windows Python 无法访问。教训: **必须把文件 cp 到 Windows 原生路径, 用 `cd /d` 启动**。

**DirectML 假阳性**: WSL 中 `use_dml=True` 不报错但 GPU 负载为 0。教训: **必须用 Windows 原生 Python 运行 DML**。
