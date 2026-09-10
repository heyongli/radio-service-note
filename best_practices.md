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
要点:
- **不要加字符白名单**:"IC10" 会因白名单吞掉 I 变成 "C10"/"CC)";
  不加白名单 + 宽松正则后过滤(`\b[IJ]?C?[0-9]{1,3}\b` 等)。
- 逐区域小图 OCR 比全图准(可按底色调阈值);AF 段等密集背景区 OCR 全噪声,
  改 2.2x tile 人工视觉通读。
- 字形聚类补漏(抓全图 OCR 漏的位号):numpy 掩码→`scipy.ndimage.label` 连通域→
  尺寸过滤(字高 5-28px、宽 2-20px、长宽比<6)→`scipy.spatial.cKDTree` 20px 近邻
  并查集聚类成文本框→逐框 4x crop 单词 OCR(--psm 7/8)。实测抓到 D12/FI1/L61/R209。
- **每个 OCR 命中必须视觉双确认**:命中坐标 ±50px 做 5-8x crop 拼图签(黄字标 bbox),
  读图转录,OCR+视觉都符才记"确认锚点",防幻觉。IC10/IC12/X2 即此流程定案。
- 空间先验验证身份:按原理图链序约束搜索区(BNC 正下方找 LPF→L39/D12 命中,
  FI2 旁找 FI1 命中),坐标合理才算数。
- **实物照片不可用**:IC-2200H 实物照片 1861px 位号仅 8-10px,放大后仍不可靠转录;
  PCB 图 3509px(300dpi)/7017px(600dpi) 是位号识别唯一可靠底图。

## 6. 视图方向(mirror)判断

- top 视图(9-2):前缘在页底 —— J11 "to the LOGIC unit J3" 标注在下中;
- bot 视图(9-4):**垂直镜像** —— DATA/SP(前缘件)标注出现在页顶;
- 判断方法:用连接器标注在两个视图中的页边位置互推,不要想当然假设同向。

## 7. 中间文件与脚本管理(项目约定)

- 脚本与文档放 `tools/<tool名>/`,各自目录带 README.md;
- 产出分类放独立目录,**禁止混放**(含旧 `extract/`,已废弃删除):
  `render/`=PDF 渲染底图、`scan/`=读图窗口/图签、`nettable/`=网表 JSON
  (含 waypoints)、`annot/`=标注成品、`archive/old_extract/`=历史调试文件;
- 临时中间件放 `/tmp/opencode/`(600dpi 大图等),网表 JSON 里记录其路径。

## 8. 任务推进建议(已完成部分)

1. 先 `pdftotext` 全文 dump → 建立位号/信号名清单与坐标;
2. `pdftocairo -svg` + 字形解析补齐描边文字;
3. 渲染 PNG,用颜色掩膜定位红/绿信号路径;
4. PCB 视图标注:位号级方案用 `tools/pcb_designator_ocr/`(OCR 位号) +
   `tools/annotate_rx_flow/add_photo_wpts.py`(waypoints JSON 渲染,
   实线=确认/虚线=推断) —— 产出 `projects/<机型>/annot/top_pcb_rx.png`
   与 `nettable/top_pcb.json`、`nettable/top_designators.json`;
   旧的块级 `annotate_rx_flow.py` 仅作备留;
5. 所有视觉读数用第二次独立放大裁剪复核,避免幻觉。
