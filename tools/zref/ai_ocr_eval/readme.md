# tools/AI_OCR_eval — AI 位号 OCR 管线与评估工具

用开源小型 AI OCR 模型（RapidOCR: PP-OCRv4/v5/v6 det+rec, onnxruntime CPU）替代
tesseract 多阈值管线，在 PCB 维修图（600dpi 光栅渲染）上识别元件位号。
本目录含 4 个工具：

| 脚本 | 用途 |
|---|---|
| `ai_refdes_ocr.py` | **生产管线**：两阶段 OCR（全页扫 + 候补 crop 读），全参数 CLI 化，运行 JSON 永久归档 |
| `eval_refdes.py` | 评估器：单引擎/单配置 vs 网表 confirmed_anchors，出召回报告 |
| `probe_anchor.py` | 探针：对单个锚点做多预处理变体 × 多引擎读数，诊断 det/rec 失败模式 |
| `compare_runs.py` | 对比两次运行 JSON 的命中差异（调参/校准用） |

## 背景（2026-09-10 实测结论）

- **没有可直接读位号的 PCB 专用开源 AI**（PANEL-Net/Redraw/Atlas 等查无此repo；
  现存原理图→网表项目内部都用通用 OCR 提位号）。正确路线 = 通用 det+rec 小模型。
- CPU 首选 **RapidOCR（PP-OCRv5/v6 onnx）**；v4-mobile 在本任务全页小字检出反而最强。
- **整页/大 tile 直接 OCR 会漏小字**：det 内部有输入尺寸限制（rapidocr v3
  `Global.max_side_len` 默认 2000，超出先缩图），3000px tile 实际按 2000 跑。
  1800px tile（不触发缩放）也未必更好——原生分辨率下 5-28px 小字对 DB det 仍偏小。
- **crop + 4x LANCZOS 上采样 + 灰度对比度增强后，几乎全部难例可读**（X2 0.92、
  FI4 0.94、D21 0.97、L60/L61/C256/R203 0.99）——所以两阶段设计：
  stage1 全页抓中大字，stage2 字形聚类找漏、crop 放大读小字。
- AI 双引擎同位一致（v4+v6 同文本同坐标）≈ 免人工预确认；conf≥0.9 且 agree 的
  命中可直接进网表候选，低置信的仍要人工视觉签收（图签 `--sheet`）。
- v6 常在字符间插空格（"I C 1 0"），匹配前先去空格归一（`norm` 字段）。
- **本次还纠正了旧 tesseract 时代网表的 5 处错误锚点**（见下"校准成果"）——
  交叉证据：双引擎高置信 + tesseract 第三方一致才改判。

## ai_refdes_ocr.py 参数用法（已验证的可靠配置）

### 坐标系（先看这个）
- `--img` 主底图（600dpi 渲染），`--img-dpi 600`；
- `--out-dpi 300`：所有输出 px 落在 out-dpi 坐标系（网表约定 300dpi），
  自动换算，`--sheet` 裁剪自动反向映射回主底图。
- `--img-low`：低分辨率底图（stage2 字形聚类在其上做，聚类参数按该图的 px 定）。
  缺省自动把主图缩半（即 300dpi）。**聚类阈值默认值按 300dpi 调过**，
  若给 600dpi 图当 img-low，把 `--glyph-*` 阈值 x2。

### stage 1（全页扫，抓中大字号 + 常规位号）
- `--stage1-engines v4`：默认 v4（实测全页小字检出最多的引擎；v6 全页会漏更多，
  v6 的强项在 crop 内读数）。多引擎逗号并列，代价线性增加。
- `--tile 3000 --overlap 400`：默认值即 e 系列"3000/400"配置。tile 不必 ≤2000——
  缩放由库兜着；经验：3000 tile 的综合召回比 1800 略好（18s vs 78s，见下时间表）。
- `--stage1-upscale 2`：tile 2x 上采样后送引擎（e4 配置）。**抓 R221 这类粘连/低对比
  位号时有效**，但 runtime ×3；只在 stage1 漏检分析后针对性开。
- `--stage1-rots 0,90,270`：竖排位号（边缘连接器标注）需要旋转 pass；0° 一档 60s 级，
  三档约 3 分钟。先跑 0°，把 miss 清单再决定是否加。
- `--max-side-len`：rapidocr(v3) Global.max_side_len 覆盖。**注意**：开 upscale 时若不
  抬高此值，2x 上采样会被库缩回 2000，白做（踩过）。配套：`--stage1-upscale 2
  --tile 1800 --max-side-len 4200`。

### stage 2（候补读，抓 stage1 漏掉的小字/低对比位号）
- `--stage2-engines v4,v6`：双引擎互证（agree 标志）。单跑 v4 也可（快 40%），
  但丢失 agree 信息。
- 字形聚类（在 img-low 上）：`--glyph-min-h 5 --glyph-max-h 28`（300dpi 下位号
  字高实测范围，agent.md 同源）；`--cluster-r 20` 把近邻字形并成候选框；
  `--mask-dark 110 --mask-light 200` 双极性（深字/浅字各扫一遍，白字黑底也能出）。
  **候选爆炸时**先收 `--glyph-max-h`、再收 `--cluster-r`；**漏小字时**降
  `--glyph-min-area`。
- crop：`--crop-pad 14`（候选框外扩，保上下文——X2 案例证明贴边 crop 会丢）；
  `--stage2-upscale 4`（4x LANCZOS 是本图实测最优，2x 不够、8x 边际收益低）；
  `--stage2-preprocess graycontrast`（默认；`invert` 处理白字黑底，如芯片本体丝印）。
- **covered 抑制**：stage1 已出 box 的区域 stage2 跳过。若某位号被 stage1 误读文本
  邻框"霸占"，stage2 不会重读——这时用 `--stages 2` 单独跑一遍（covered 为空）对比
  JSON 找差集（compare_runs.py）。

### 后处理（拼装与去重）
- `--asm-gap 12 --asm-dh 6 --asm-maxfrag 6`：碎片拼装参数。R221 在原生分辨率下会被
  读成 "C"+"22"+"5" 三段，同 baseline 12px 内拼回。**gap 不要超过字高**，否则会把
  相邻独立位号粘连（试过 22px：refdes 数从 155 掉到 55，灾难）。
- `--dedup-dist 25`：跨引擎同文本同位合并半径；同位不同文本（如 FI3/F13）不并，
  由 compare_runs/人工裁决。

### 运行归档与复现（校准的核心机制）
- 每次运行强制写入 `--runs-dir`（默认 `<img 同目录>/ai_ocr_runs/`），文件名
  `日期_标签_版本_脚本hash.json`，JSON 内含：`tool_version`、`date`、
  `params`（全部 CLI 参数）、`engine_versions`、`script_sha1`。
- **调参流程**：改一个参数 → 新标签跑一轮 → `compare_runs.py A.json B.json`
  看增益/回归。标签建议带参数含义（如 `--tag asm12-vs22`）。
- 确认某次运行完全乱套时才手动删；否则全留，供以后校准（回溯"哪个参数组合当时
  读对了什么"）。
- `--keep-raw` 附 stage1/stage2 未拼装原始 hits（文件大，只在做失败分析时开）。
- `--out`：只是把最新 run 复制一份到固定路径（给下游工具对接用），归档不受影响。

### 时间参考（本机 CPU，600dpi 7017x4959 整页）
| 配置 | 用时 | 说明 |
|---|---|---|
| stage1 v4 tile3000/400 | ~16s | 基线全页扫 |
| stage1 v6 tile1800 native | ~78s | 召回不升反降 |
| stage1 v4 rots 0,90,270 | ~185s | 竖排位号必需 |
| stage2 双引擎全页候选(~300 crop) | ~100s | 与 stage1 独立 |
| 全管线 v4+v6 默认参数 | ~290s | 生产基线 |

### 与网表/标注工具的衔接
- 输出 hits 的 `px` 是 out-dpi(300) 坐标，直接对齐 `nettable/top_pcb.json` 的
  `label_px` 空间与 `tools/annotate_rx_flow/add_photo_wpts.py` 的 waypoints。
- 建议流程：跑管线 → `--sheet` 出图签 → 人工扫图签勾选（agree && conf≥0.9 可直通）→
  勾选项写回 nettable confirmed_anchors（note 记 "aiocr agree=2 conf=x"）→
  低置信项走 probe_anchor.py 定位失败模式再决策。

## 校准成果（IC-2200H top，2026-09-10）

本管线复核旧网表 24 个 confirmed 锚点：
- 18 个验证正确（J1 L39 D12 X2 FI2 FI3 FI4 D19 D20 D21 D27 L60 L61 R203 R209 C256 J11 J3）
- **3 个坐标错**：IC10→[1311,895]（v4 0.99+v6 0.98+tess 三方一致；旧值是 600dpi
  原始坐标混入）、FI1→[2680,1495]（8 种预处理变体全读出 0.91-0.94；旧值附近
  实为 R203 簇）、R221→[2121,1205]（e4 配置 0.999；旧锚点处实为 R228）
- **2 个视图错**：J4/J7 实在 bot 视图（v4 0.88/0.98），旧网表误放进 top 列表
- **1 个存疑**：IC12[2082,1521]：多引擎×多预处理均不可读，旧"视觉6x确认"存疑，
  从 confirmed 降级到 not_located 待人工复核

教训：**旧管线"视觉确认"的锚点错误率 ~20%**（5/24），主要错法是坐标空间混记
（600dpi 原始值当 300dpi 存）与看图脑补。AI 双引擎+坐标一致性校验应作为网表
锚点的强制复核步骤。

## eval_refdes.py 用法

```bash
python3 eval_refdes.py --engine v4 --img /tmp/opencode/top600-1.png --dpi 600 \
    --tile 3000 --overlap 400 --out /tmp/opencode/aiocr/v4_t600.json
```
`--engine v4|v5|v6`，锚点默认读 `projects/IC-2200H/nettable/top_pcb.json` 的
confirmed_anchors_top（`--anchors` 可换）。注意其匹配是**精确文本**（判据可从严），
对"unit J1"、"D19G"等粘连文本会判 MISS——评估尾随垃圾/词组匹配用 probe 或
compare_runs 更直观。

## probe_anchor.py 用法

```bash
python3 probe_anchor.py --anchor IC10 --anchor X2        # 指定锚点
python3 probe_anchor.py --all-missed <eval报告.json>      # 某次评估全部漏检
python3 probe_anchor.py --anchor J4 --engines v4,v6,v5en  # 换引擎
```
每个锚点出 orig4x/gray4x 两变体 × 引擎读数。定位失败模式专用：
- 附近有 box 但文本错 → rec 问题（换引擎/预处理/上采样）
- 完全无 box → det 问题（检查 covered 抑制、候选聚类参数、极性掩码）

## compare_runs.py 用法

```bash
python3 compare_runs.py runs/A.json runs/B.json            # 命中差异总表
python3 compare_runs.py runs/A.json runs/B.json --label IC10   # 只看指定位号族
python3 compare_runs.py runs/A.json runs/B.json --near 2622 1790 200  # 看某区域
```
输出：两次 run 的参数 diff、共同命中（Δconf/Δ坐标/引擎并集差异）、各自独有命中。
调参是否有效、引擎升级是否回归，看这张表定论。
