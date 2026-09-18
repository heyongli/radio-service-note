# tools/sch-true-finding — 真理发现层 (truth finding)

## §1 文件清单
| 文件 | 用途 |
|---|---|
| `sch_true_greenline.py` | 绿线真理发现: 彩线掩膜 (绿/红/黄/青) + 统计 |
| `note_box_locate.py` | **定位原理图说明框 (虚线方块) + 图例**: OCR找锚点文字→定位→检测dash虚线框→反查OCR取框内图例文字 |
| `legend_extract.py` | 从说明框提取**图例数据库** (文字↔色样本, 颜色→信号权威真值) |
| `legend_region_detect.py` | **用 legend 准确 RGB 识别全部标注区域** (RX/TX/common/POWER): RGB容差掩膜→连通域→红色细线边框圈出 |
| `color_layer.py` | **信号颜色图层** (rx/tx color layer): 白底+灰原理图+目标信号色高亮, 一眼看信号位置 (重要视觉结果) |
| `annotation_detect.py` | 标注区域识别 (彩色连通域→bbox/区域掩膜, 供 ROI 局部化) |
| `de_annotate_lumfrac.py` | **信号流标注去除 (固化版, 用户裁定最终答案 2026-09-17)**: 段内暗芯法, 不断线不变细. 方法简称=lumfrac |
| `de_annotate_chandiff.py` | 标注去除 (chandiff 版, 曾为最终; 会断线/变细) |
| `de_annotate_chmask.py` | 标注去除 (通道掩膜法: 每色显式 ops + 描边扩展) |
| `de_annotate_wirelum.py` | 标注去除 (亮度保走线法, 绿/青/土黄/品红四色) |
| `de_annotate.py` | (实验版, 历史算法合集, 仅供研究) |
| `explore_wire_core.py` | 探索工具: 多种取芯方法对比, 产出中间图供远程检查 |
| `readme.md` | 本文档 (修改前必读) |
| `parameter_space.md` | 参数调优空间学习记录 (各轮参数/指标/结论) |

## §2 定位 (sch 管线中的位置与作用)

**sch 管线的真理发现层 (truth finding)** —— 识别最高可靠的事实, 供全管线复用:

```
sch-true-finding (本目录: 真理发现) → 供所有下游
  ├── sch_true_greenline.py (绿线掩膜, 准确度 95%)
  → sch_trace (沿绿线走线)
  → sch_flow_walk (绿线流鉴别 membership)
  → sch_cap / sch_symbol (符号识别: 绿线触点弱约束/冲突排除)
  → sch_render (渲染: 绿线高亮)
```

| 真理元素 | 准确度 | 作用 |
|---|---|---|
| **绿线掩膜** (RX 主路) | **95%** (实测) | 走线引导 / membership 鉴别 / 冲突排除 / 渲染 |
| 红/黄/青彩线 | 待测 | TX / 控制 / common 同理 |
| (扩展) 文字框/尺寸库 | 90 / 80 | 见 schema §3.5b, 未来可并入本工具统一发现 |

**原理**: 真理元素清单与可信度 → schema.md §3.5b;
真理银行积累复用机制 → architecture §14.1c;
排除来源可扩展 → architecture §14.1e。

## §3 元数据格式
| 参数 | 默认 | 说明 |
|---|---|---|
| `--img` | 必填 | 原理图渲染图 |
| `--color` | green | 彩线颜色 (绿=RX/红=TX/黄=控制/青=common) |
| `--out` | - | 输出掩膜 PNG (0/255) |
| `--stats` | off | 输出掩膜统计 (像素占比/连通域) |
| `--g-th/--r-th/--b-th` | 120/110/110 | 颜色阈值 (参数化, 实测校准) |

输出: uint8 0/255 掩膜, 与原图同尺寸。

## §4 用法
```bash
# 绿线掩膜
python3 tools/sch-true-finding/sch_true_greenline.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --color green --stats --out /tmp/opencode/green_mask.png

# de-annotation: 独立运行 (固化版 = de_annotate_chandiff, 纯 BGR 通道差, 用户裁定最终答案)
python3 tools/sch-true-finding/de_annotate_chandiff.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --out /tmp/opencode/deannot.png --diff-th 40
```

> 注: 本工具是 **de-annotation** (去全部彩线标注), 原名 de_greenline.
> **生产/最终答案 = de_annotate_chandiff.py**; `de_annotate.py` (实验版) 的
> --restore/--wire-lum/线续接均被证伪, 仅供研究. 修改前必读 readme.md 全文.

## §4b 呈现给真人监督员校验 (human supervision)

绿线真理发现结果需**可视化呈现给真人签收** (architecture §6 防幻觉第三道闸:
视觉签收兜底)。生成方式:

```bash
# 1) 叠加图: 灰度底图 + 绿线高亮 (红色), 供整体核查主路走向
python3 tools/sch-true-finding/sch_true_greenline.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png --color green --out /tmp/opencode/green.png

# 2) 叠加渲染: 用 sch_render 生成 roundXXX 图 (绿线高亮 + 组件着色 + 标号)
python3 tools/sch_render/sch_render.py --img ... --color green --db ... --out annot/xxx.png
```

**签收要素** (监督员逐项核对):
| 要素 | 核对点 |
|---|---|
| 主路连续性 | 绿线是否沿走线连续贯穿 RX 链 (ANT→…→SP) |
| 断口合理性 | 绿线断口处是否都是器件 (电容/三极管/IC), 无意外中断 |
| 分支 | 绿色分支是否为合理支路 (AGC/SQL/VCO), 无错误扩展 |
| 误检 | 是否把非绿线像素 (红/灰/文字) 误当绿线 |
| 与 GT 一致性 | 绿线是否覆盖 gt_rx_flow.json 的 14 个主路电容 |

**签收产物**: 确认 OK 的绿线结果标注 `truth_score: 95` (schema §3.5b),
作为后续轮真理源; 发现错误则记录到 `tools/sch-true-greenline/readme.md`
(参数需调校或识别 bug)。

## §5 目的
统一各工具散落的 `color_mask` 复制 (sch_render/sch_trace/sch_flow_walk/
sch_wire/sch_symbol/sch_cap 原各有副本), 提供**单一权威真理发现实现** +
**可复用的高可靠真理源**。绿线识别质量实测: 0.55% 像素, 522 连通域,
主路走线清晰; 绿线在走线上, 距符号本体 30-50px (cap_quality 用 r30+ 触点
作弱约束)。其他工具改为 import 本模块, 不再各自复制。

**真理源保持原始纯净 (忠实原则)**: 绿线掩膜**不做形态学处理** (如闭合填补
空洞), 保持原始阈值提取结果 —— 真理源要忠实反映信号流, 修饰会引入猜测。
需要完整掩膜的**消费端按需自行处理** (如 `cv2.morphologyEx(CLOSE)` 填补
绿线内部空洞, 空洞是绿线实体覆盖但未过阈值像素, 实测闭合后 +21.8%)。
实测: 闭合核 3/5/7/9/11 分别 +13.7%/+21.8%/+25.2%/+25.3%/+25.6%, 核 7 收敛。

**去除已知干扰最佳实践 (de-greenline)**: truth data 的用法 —— 绿线在**最下层**
(被走线/文字盖住, 不遮挡上层内容, best_practices §5b-3), 直接丢弃即可
"绿线从未存在"。但绿线边界有**深色描边** (抗锯齿, 残留淡绿), 需扩展掩膜:
核心颜色阈值 (g>120) + 描边扩展 (色相 55-90° 绿 + 灰度 40-200 + 非核心)。
实测: 核心 184391 px, 描边扩展 +37k, 扩展不含黄 (黄 h<50) 不吞纯黑走线 (灰<40)。

## §6 标注线在走线下方 (关键结论, 2026-09-17 两次确认)

**结论**: 信号流标注线 (绿/红/黄/青) 画在**走线下面**, 不是盖在走线上。
- 走线覆盖处标注**不可见**; 标注只在**走线断开处露出** (亮, 灰度≥150)
- 深色标注线 (如深红 TX 线) 独立存在, 色相红且灰度暗 (灰度<150), 非走线上的标注

**去除标注 = 置白丢弃, 绝不做"填走线色恢复"**:
- ❌ wire-fill (标注填走线色) → 标注线变成**超宽走线段** (视觉错误)
- ✅ 置白 (fill=255) → 标注消失, 走线不受影响

**标注识别最佳方法 = BGR 通道差 (2026-09-17 实测最佳)**:
- **走线 = 灰 (BGR 三通道接近, 通道差小)**; **标注 = 彩色 (通道差大)**
- `maxdiff = max(|G-R|, |G-B|, |R-B|)`, 阈值 >40 = 标注
- **比 HSV 饱和/色相可靠**: 暗走线在 HSV 下饱和/色相噪声大 (误删走线),
  BGR 通道差稳定 (走线灰 → 通道差≈0)
- **de-annotation 方案 = chandiff 删彩色** (用户选定, 效果直观):
  `--diff-th 40` 删除高通道差彩色像素 (标注消失), 保留低通道差走线
- ❌ 废弃: 走线宽度恢复 (骨架+原宽) — 线段消失, 效果不好
  ❌ 废弃: 标注填走线色 (wire-fill) — 标注变超宽走线段
- 走线略细是接受的代价 (标注覆盖走线中心, 删标注后中心变细)

**踩坑记录**: 此问题出现**多次** (de-greenline wire-fill / de-annotation wire-fill /
宽度恢复), 均因过度工程 (恢复走线) 而失败。正确做法是**直接删彩色置白** (chandiff)。
每次改 de_annotate 前先读本节, 不要再犯恢复走线的错误。

## §7 自监督指标与分区算法 (v0.3, 2026-09-17) — 修复"部分 net 联通区域丢失"

**问题**: 独立去标注 (置白) 后, 部分 net 连通域丢失. 实测: 主 net 碎成 120 块
(main_CC=120), 主 net 面积保留 73.3%.

**根因**: 标注线叠在走线上 (局部变色) → 置白时走线被一起删 → 连通域被切碎.
主 net (gray<150 最大连通域) **45% 是彩色标注** (绿 19.2%), 不是纯走线.
chandiff 独立模式 彩色残留=0 且走线宽保留 (p90=2.0), 但吃掉 35.5% 主 net
(绿线下的真走线), main_CC=258. **需要恢复被吃掉的走线, 但不能留粗线.**

**自监督 = 用应然指标判断好坏 (不是程序模式)**: 本工具的开发/调参由指标驱动,
agent 每轮改算法后跑指标自判, 不依赖人工看图. 指标与实测基线:

| # | 指标 | 应然 (判断标准) | 实测基线 (IC-2200H rxtx 600dpi) |
|---|---|---|---|
| 1 | **局部连通性** (标注线区域走线不丢失) | 去标注后主走线 net 连通域数 main_CC ≈ 1 (不碎片化) | chandiff main_CC=258; 分区恢复后 =**1** ✓ |
| 2 | **被去除区域连通性不能大变** | 去除的标注段不得切断走线 (segments_cutting_wire ≈ 0) | 分区恢复后 cutting=**0** ✓ |
| 3 | **走线保留率** | main_net kept% 越高越好 (只删标注, 不删走线) | chandiff 64.5% → 分区恢复 ~75.7% |
| 4 | **彩色残留** | 输出中 chandiff>40 的彩色像素 ≈ 0 (标注全删) | chandiff/分区恢复均 =**0** ✓ |
| 5 | **残留粗线宽 ≈ 走线宽** | 输出厚度半宽 p90 ≈ 走线半宽 (~2), 远小于标注宽 | 分区恢复 p90=2.2 ✓ (整段填走线色会 p90=5 ✗) |
| 6 | **分通道精度** | 每色掩膜不吃走线 (主 net 损失越低越好) | 统一 chandiff 35.5% → 分通道核心掩膜 20.2% |
| 7 | **wire 连通域签名** | wire 连通域 = 覆盖面积+长度 都远大于干扰 (排除 label/小噪声/符号体) | 细走线成分 ~5800 个, 覆盖整个主 net |

**分区算法 (用户设计, 2026-09-17) — 不全局共享一组参数**:

核心思想: **既然按区做算法, 就分区调参 + 检测运算区域连通性变化**, 而不是
全图一套参数. 每条标注线段的走线宽/标注宽/背景都不同, 全局参数必然顾此失彼.

```
对每个标注段 S (连通域):
  1. 局部走线厚度 = 邻接细走线 (dt≤wire_radius) 的中位 dt
  2. 恢复核宽 = clamp(2*局部厚度 + 2, 3, 11)   ← 每段不同, 不用全局 --bridge-width
  3. 恢复核 = S 的中轴脊膨胀到该核宽 (只填走线宽的中心条, 防粗线)
  4. 局部连通性校验 (运算区域内 before/after):
       段窗口(bbox+margin)内 连通域数 after - before > 0 = 该段断开走线
       → 上报 segments_conn_changed / max_conn_delta (应然 0)
```

**关键点**:
- **运算只在需要去除的部分** (标注像素 9-邻域), 不做全图运算 → ~14s (全图 33M px).
- 每段核宽由**局部走线宽度**决定 → 粗细线自适应, 不产生超宽段.
- 每段**局部连通性校验**就是该区的自监督指标 (分区验证, 非全局).
- 桥段判定: 标注段邻接 **≥2 个细走线成分** = 走线上的标注 (桥); 其余置白
  (标注在断口/符号处, 本就该断).

**实测效果** (chandiff 掩膜 + 分区恢复, IC-2200H rxtx 600dpi):
| 指标 | chandiff 独立 | +分区细核恢复 |
|---|---|---|
| 彩色残留 | 0 | 0 |
| main_CC (走线连通) | 258 | **1** ✓ |
| cutting_segments | - | **0** ✓ |
| main_kept | 64.5% | ~75.7% |
| 残留粗线 (半宽>3) | 0 | ~2651 px (待优化) |

**关键测量 (记录, 供后续探测/复用)**:
- 主 net (gray<150 最大连通域) **45% 是彩色标注** (绿 19.2%), 不是纯走线
  → 对比基线须排除标注/label, 用 wire 连通域 (面积+长度签名), 勿用污染的主 net.
- chandiff 独立模式 (--diff-th 40 --color all): 彩色残留=0, 走线宽 p90=2.0,
  main_kept 64.5%, main_CC=258 — 是**视觉参考**; 但吃掉绿线下真走线.
- 分通道掩膜逐色主 net 损失: green 19.2% (碎片来源) / red 0.3% / cyan 0.7% /
  yellow 0.0% (main_CC=1 不碎). 绿色通道是唯一碎片来源 → 恢复逻辑主要作用于绿.
- 与 readme §6 关系: §6 的"❌ 恢复走线"指**全标注填走线色** (→超宽走线段, 已废弃);
  分区恢复只把**真实走线上被打断的桥段中轴**填回走线色 (细核, 不超宽), 二者不同.

## §9 legend_extract 工作流 (2026-09-18 固化) — 自动发现图例色彩样本真值

**主线 = 提取图例数据库** (颜色→信号 权威真值). note_box_locate 是工具链的**一环**
(定位虚线框), 不是主线. 完整管线:

```
① OCR 找锚点文字 (说明框标题, 如 "Explanatory"; 不同机型文字不同但结构类似,
   从 OCR 数据库可读懂含义) → 大致位置
   - note_box_locate --ocr-json/--anchor-text, 坐标按 dpi 换算
② note_box_locate: 锚点 ± --search 区域内检测 dash 虚线边框 → box bbox
   - dash 参数化: 实测 600dpi dash 13px 段+11px 间隔 (--dash-lo 8 --dash-hi 25)
③ legend_extract: 框内反查 OCR 文字 + 按行提取色彩样本, 文字↔色带按 y 对齐
   (--match-dist) → legend 条目 → **自动发现图例色彩样本准确值**
```

**自动发现图例真值 (关键)**: 框内每行 = 文字标签 + 色彩样本. 从 OCR 数据库
读文字, 从框内提取色样本 → 准确 "颜色→信号" 映射, 无需人工读图:

| 图例 (OCR) | 色样本 BGR | 信号 |
|---|---|---|
| VOLTAGE LINE | (138,6,227) 品红 | 电压 |
| TX LINE | (19,135,246) 橙/土黄 | TX |
| RX LINE | (80,166,0) 绿 | RX |
| COMMON LINE | (239,173,0) 青 | common |

**用途**: 图例数据库 = "颜色→信号" 权威校准源, COLOR_SPEC 探测校准 (§8) 直接
读 explanatory_notes.json (projects/<机型>/nettable/), 不必靠猜测.

**不同机型**: 锚点文字可能不同 (Explanatory/LEGEND/注...), 工作流不变, 只需在
OCR 数据库里识别出说明框标题类的文字作锚点.

### 输出模式: color layer (颜色图层, 2026-09-18 定稿)

**四 stage 管线** (工具 `color_layer.py`, 用 legend 准确色; 自监督线宽=legend
色样本条带厚度, 实测 16px):

```
stage1 图层:       白底 + 非目标内容调淡(--fade 0.45) + 目标信号色高亮
                    → <signal>_color_layer.png   (一眼看信号位置)
stage2 去灰纯区域:  --pure → 白底+纯目标色 (饱和度阈值 --sat-min 100 去灰)
                    → <signal>_line_region.png
stage3 填实:        --heal → 直接 legend 色掩膜纯填实 (3over2样式)
                    → <signal>_healed.png   (--border 加1px框 / --continu 方向闭接续)
stage4 走向探测:    --direction → 在图层(目标色掩膜)上运算, 分类各段:
                    L形直角拐弯(蓝框) / 真斜线10-80°(红框) / 直段(红箭头标走向)
                    走向 = 远离上游(chain前部) → 下游 (链序 chain_order_rx.json)
```

**stage-4 段分类** (用户: "倾斜的多是直角拐弯"):
- **L 形拐弯** (两端点方向垂直 60-120°) — 实为横+竖拐角, 非真斜线 (58个)
- **真斜线** (10-80°) — 真对角段 (13个)
- **直段** (横/竖) — 画走向箭头 (115个)

命令:
```bash
python3 tools/sch-true-finding/color_layer.py --img sch-600.png \
  --legend explanatory_notes.json --signals RX --out rx_color_layer.png   # stage1
python3 tools/sch-true-finding/color_layer.py --img sch-600.png \
  --legend explanatory_notes.json --signals RX --pure --out rx_line_region.png
python3 tools/sch-true-finding/color_layer.py --img sch-600.png \
  --legend explanatory_notes.json --signals RX --heal --out rx_healed.png
python3 tools/sch-true-finding/color_layer.py --img sch-600.png \
  --legend explanatory_notes.json --signals RX --heal --direction --out rx_s4_direction.png
```

**自监督线宽**: stage3/4 合并核与判据默认 = 参考线宽 (legend 色样本条带厚度).
线宽学习剔除"突然最大值" (胖体/元器件). 缝隙 ≤ 线宽 = 同一条线 (填), > 线宽 = 不同线.

**不同机型**: 锚点文字可能不同 (Explanatory/LEGEND/注...), 工作流不变, 只需在
OCR 数据库里识别出说明框标题类的文字作锚点.

**命令**:
```bash
# ①+② note_box_locate: OCR 数据库找锚点 → 定位虚线框
python3 tools/sch-true-finding/note_box_locate.py --img sch-600.png \
  --ocr-json ocr.json --anchor-text "Explanatory" --ocr-dpi 300 --img-dpi 600 \
  --out-box box.png --out-json box.json
# ③ legend_extract: 框内反查 OCR + 色样本 → 图例数据库
python3 tools/sch-true-finding/legend_extract.py --img sch-600.png \
  --ocr-json ocr.json --box-json box.json --out-json explanatory_notes.json
```

## §8 COLOR_SPEC 需探测 (probe), 不能硬编码

**标注色因印刷/渲染漂移, 每张图都要探测校准**, 不能盲用 COLOR_SPEC 阈值:
- 本图实测 (best_practices §5a): 红=深红/品红 **r150-255/g0-110/b0-200** 且须
  色相约束 (橙红0-25 + 品红150-170). 曾缺 g 约束 → 灰暖色误入 (red core 922k->67k).
- core_mask 曾固化为"绿式" (r,b 均<阈值), cyan 需要 b**>** / yellow 需要 r**>** 被算反
  → 改为**每色显式 ops** (`COLOR_SPEC[*]["ops"]`), 通道关系逐色声明.
- 校准方法: 对目标图统计标注色像素的 BGR/HSV 分布 (如 sch_true_greenline --stats),
  按实测区间更新 ops; 探测逻辑 (自动聚类标注色) 列为后续任务 (todo).
- **参数调优轨迹** (每轮参数快照/指标/结论, 含 red 描边扩展假阳性修正) 见
  **`parameter_space.md`**.