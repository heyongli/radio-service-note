# ic_package_detect — IC 封装定位

三种方法, 从强到弱。**先积累再优化**——各方法已验证值与失效模式如实记录。

## 方法与用法

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

### 3. contour (线稿 Canny 矩形, 备选)

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
