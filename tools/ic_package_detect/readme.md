# IC_package_detect — IC 封装定位

四种方法, 从强到弱。**先积累再优化**——各方法已验证值与失效模式如实记录。

## 方法边界 (重要)

- `crop-ocr` 是**寻找封装**的方法: 从矩形/圆形裁切中匹配 refdes → 候选本体框
- **不是**寻找"某个 refdes 在板上真实位置"的算法。标签文字可能印在封装旁边,
  裁切 padding 里的邻近文字会造成假匹配 → 必须用**精确裁切验证**过滤
- 验证法: 沿检测方块 bbox 精确裁切源图再 OCR, **若正好只识别出该 refdes**,
  才确认这个框是该 IC 的封装

## 方法与用法

### 0. crop-ocr (首选, 矩形+圆形裁切 + 旋转 OCR + refdes 匹配)

配合 rectangle_locator / circle_locator 的裁切搜索一起用:
对每个 ic 类矩形裁切 (circle 类也兼容) 做 0/90/180/270 旋转 OCR,
读到已知 refdes 的裁切, 其 bbox 即 IC 本体坐标+尺寸。

```bash
# 混合 top/bot 的矩形裁切
python3 detect_ic.py crop-ocr \
  --crops projects/icom2200h/crops/rectangle/crops_index.json,projects/icom2200h/crops/rectangle_bot/crops_index.json \
  --refdes "IC4,IC12,IC6,IC11,IC1" \
  --categories ic --local-ocr [--out ic_body.json]
```

**可靠性**:
- 默认只读同目录预计算的 `ic_ocr_results.json` (DML OCR, 可靠且快)
- 无预计算结果时, 加 `--local-ocr` 用本地 rapidocr 兜底 (ic 类裁切少, 快)
- 全类别扫描 (如 `--categories ""` 扫全部圆形) 很慢, 慎用
- 提供 `--confirm-image <源图>` 时, 对每个命中做精确裁切验证:
  沿 bbox 裁切源图再 OCR, 只有正好识别出该 refdes 才保留 (过滤 padding 假匹配)
  (源图需按 bbox 所在 view 给: top 用 pcb-top-600-1.png, bot 用 pcb-bot-600-1.png)

**实测 (IC-2200H, 已精确裁切验证)**:

| refdes | view | 本体中心 | 尺寸 | 确认 OCR |
|---|---|---|---|---|
| IC11 | top | (3156, 1772) | 82×104 | IC11 ✓ |
| IC1 | bot | (2443, 2463) | 104×130 | IC1 ✓ |
| IC4 | bot | (1489, 2516) | 104×121 | IC4 ✓ (恰好只有 IC4) |
| IC6 | bot | (1850, 1774) | 83×105 | IC6 ✓ |

**过滤的假匹配**: top r0023 (3360,2624) 曾被 DML 判为 IC12, 但精确裁切验证
沿 bbox OCR 读不到 IC12 → 丢弃。**教训**: 裁切 padding 里的邻近文字会造成假匹配,
必须精确裁切验证后才能用。IC12 真实本体尚未确认 (位置算法另见 signal_flow_route)。

**教训**: 本体中心 ≠ 标签文字中心。components_index 的 center 是 OCR 标签位置,
画轮廓框必须用本体 bbox (如 IC12 标签 (3555,2719) vs r0023 (3360,2624), 差 ~200px,
但 r0023 经验证并非 IC12 本体)。**只信经过精确裁切验证的本体框**。

### 1. pin-silk (首选, PDF 文本层引脚号丝印)

```bash
python3 detect_ic.py pin-silk --pdf projects/IC-2200H/IC-2200H-bot.pdf [--out ic.json]
```

原理: 维修手册 PCB 视图常在 IC 引脚旁印引脚号(孤立数字)。PDF 文本层
(pdftotext -bbox, 坐标已含 /Rotate)直接给出这些数字的坐标 →
同行成对(Δy<14, Δx 20-320)的数字 = IC 同一边的两个角引脚;
x 范围相近(±30)的两对 = 同一 IC 的对边 → 内插**全引脚坐标+本体框+方向**。

- 精度 = 文本层坐标(无图像处理误差); 无引脚号丝印的板/视图无效
- 实测 IC-2200H:
  - bot.pdf: 检出 4 个 IC = 16pin(IC4 TA31136FN, 角标 1/16/8/9)、
    16pin#2(bot 1620-1730,1640-1730)、24pin(IC1 PLL 候选)、8pin(IC6, 33px 跨 VSSOP)
  - top.pdf: 检出 3 个 = 8pin(IC11 NJM3404V @2165-2205,1140-1240)、
    16pin(top 1660-1770,1860-1950, 旋转180°)、8pin#2(2340-2430,1880-1930, 疑 IC12)
- 引脚内插规则: 含 pin1 的列 1→k、含 pinN 的列 N→k+1, 按标签实际位置定向;
  16pin 例: Δy=76px → pitch=76/7≈10.9px(300dpi)≈0.92mm(SSOP 细距)

### 2. body (渲染图暗矩形, 需已知标签位置)

```bash
python3 detect_ic.py body --img /tmp/opencode/top600-1.png --near 1000,1770
# → {"x":971,"y":1772,"w":73,"h":88,"fill":0.81}  (IC9 TA7252AP)
```

原理: 阈值(130)反相 + 闭运算 + 轮廓, 过滤面积 3k-120k@600dpi / 长宽比 0.3-3.5 /
矩形度>0.7, 取离标签最近的候选。

- 实测: IC9 (971,1772) 73x88 ✓(与输入网络环 R125/C188/C192 互证)、
  IC11 (2161,1160) 59x86 ✓
- 失效: IC10 S-AV36(模块非暗矩形)、IC12(周边杂波干扰) → 未检出

### 3. contour (线稿 canny 矩形, 备选)

```bash
python3 detect_ic.py contour --img /tmp/opencode/bot600-1.png --near 990,1726
# → {"x":1033,"y":1733,"w":129,"h":93}  (bot 线稿面)
```

- 实测: IC1 24pin ≈可用; IC4 检出框相对 pin-silk 真值偏移(129x93 vs 100x92)
- 稳定性差(铜箔线稿特征杂), 仅 body 失败时用

## 坐标约定

- `--near` 输入 300dpi px; 输出统一 300dpi px
- pin-silk 输出 `body`(含 12px 边距)与 `pins`(每引脚 xy)与 `corners`(四角引脚号→方向)

## 已知限制 / 待优化(积累清单)

- [ ] pin-silk 依赖角引脚号成对完整(1/N 与 k/k+1); 单边缺号时丢 IC
- [ ] body 方法对贴片电容排/屏蔽罩会误检(靠"最近标签"消歧, 标签错则全错)
- [ ] 封装类型分类(SOIC/SSOP/QFP 尺寸表)未做——现在只给 bbox+pin 数
- [ ] pin-1 圆点/斜角视觉确认未做(方向完全依赖丝印号)
- [ ] IC10(S-AV36 模块)、IC12 需另想办法(轮廓模板/局部放大人工图签)
