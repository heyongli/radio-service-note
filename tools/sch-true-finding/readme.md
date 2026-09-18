# tools/sch-true-finding — 真理发现层 (truth finding)

## §1 文件清单
| 文件 | 用途 |
|---|---|
| `sch_true_greenline.py` | 绿线真理发现: 彩线掩膜 (绿/红/黄/青) + 统计 |
| `de_greenline.py` | **去除绿线** (de-greenline): 从原理图移除绿线 (含深色描边扩展), 得"绿线从未存在"底图 |
| `readme.md` | 本文档 (修改前必读) |

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

# de-annotation: 独立运行, 不依赖其他真理元素 (纯 BGR 通道差, 推荐)
python3 tools/sch-true-finding/de_greenline.py \
  --img projects/icom2200h/render/rxtx-sch-600-1.png \
  --out /tmp/opencode/deannot.png --color all --diff-th 40
```

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
每次改 de_greenline 前先读本节, 不要再犯恢复走线的错误。