# TODO — 后续路线

按优先级/依赖排列。架构见 `architecture.md`, 工具进度见 `tools/README.md`。
**总目标(components_index 飞轮)**: 器件→坐标识别每前进一步, 索引就解锁
更高层能力——互联分析 → 原理分析 → 反推原理图(PCB 逆向工程终点)。

## 终局目标 (长期, 依赖索引与前面各项)

- [ ] **互联分析**: 焊盘网络连通(bot 铜箔) + 引脚级坐标 → 每个网络的
      元件/引脚列表 → 图上可回答"这个网络连到哪"。
- [ ] **原理分析**: 在互联分析之上叠加功能块识别(REF DES 前缀 + BLM
      名称 + 拓扑模式), 自动划分 功能区(前端/中频/音频/电源)。
- [ ] **反推原理图**: netlist + 分区 + 自动布局布线(KiCad netlist 格式
      导出, 或直接调 skidl/基于图的绘制), 从 PCB 图恢复出可编辑原理图。
      这是"索引飞轮"的终点站。

## 封装识别与引脚定位链路 (依赖: components_index 已就位)

- [ ] **形状小检测工具**: 快速识别 PCB 图上的 基本体形 — 方块(IC/钽电容)、
      圆柱(电解电容/电感)、两孔焊盘(电阻/二极管)、多脚焊盘(IC)。
      路线: 传统 cv2(轮廓+宽高比+孔数) 起步, 不够再上 YOLO 小模型
      (Roboflow Universe 有 PCB component 检测权重; 本项目数据可自标注微调)。
      **关键用法: 检出的组件体形邻域(±1.5倍体宽)内做 OCR, 命中的位号
      即该组件的编号** — 位号↔组件本体绑定, 比纯文本扫描可靠(位号一定
      印在对应组件旁)。这同时天然给出"位号属于哪个组件体"的关联, 为
      封装库打地基。
- [ ] **封装识别 → 引脚精确定位**: 在组件体形基础上分类封装(0603/0805/
      SOT-23/SOIC-8/TO-252...), 封装尺寸表 + 图纸比例(已知: 600dpi 渲染
      px→mm 换算) → 组件引脚的准确像素坐标 → 信号流 waypoint 可落在
      引脚级而不是组件级。
      依赖: 上一步的体形检测; 需要一张已知比例尺的验证图(用板上 USB-B
      或 BNC 外形反推 mm/px)。
- [ ] **焊盘网络连通提取**: bot 视图铜箔连通域 → 焊盘聚类 → 网络表
      (真正的 netlist, 而不只是信号链序)。依赖: bot 整页 OCR + 焊盘检测。

## 数据补全 (AI-OCR 管线已就位, 待批量跑)

- [x] **bot 视图整页 AI OCR 扫描** (2026-09-10 完成: bot-full 运行, Q16/Q19/Q17/
      Q26/Q39/IC6/Q4/IC1 等落位; 镜像方向修正为 X 镜像)
- [x] **RX/TX/AF 链序完整恢复** (2026-09-10: block 图文本层+原理图文本层交叉,
      IC10 角色修正为 PWR-AMP, chain_order 入 top_pcb.json)
- [x] **IC4 引脚级坐标** (bot PDF 引脚号丝印 → 16 引脚全坐标入表)
- [ ] **Q35/Q27/Q2/D9-D13/D18/L45/L52/IC5/X1 定位**: 标签在两视图均不可读,
      下一步: 高倍局部多预处理变体探针 或 对照丝印图放大镜人工读图签
- [ ] **IC9/IC12 精确坐标**: 已有强推断区(IC9: R125/C188/C192 环; IC12: 8pin+Q37/38),
      待人工图签确认转 confirmed
- [ ] **TX 链条序读数入库**: 已从 block+原理图恢复(见 top_pcb.json chain_order_tx),
      待 PCB 侧 Q35 定位后补全 waypoint

## 标注与工具

- [x] **重出 top/bot PCB 标注** (2026-09-10: top/bot_pcb_flow_v2 分层 SVG+PNG,
      opacity 0.6+箭头+IC4 引脚级+bot 铜箔路由; 旧 raster 标记 stale)
- [x] **bot 铜箔走线路由器** (2026-09-10: route_on_traces.py, Dijkstra 沿铜箔线稿)
- [ ] **wpts 生成器升级**: 现在 wpts_*_v2 是人工整理的链文件(引脚级+跨视图 ghost
      超出 components_index 0.1 表达力); 待 index 升 0.2(package/pins)后回归生成器
- [ ] **图签工具**: ai_refdes_ocr --sheet 产出的拼图签做成可选大图(带索引
      编号), 方便人工逐格勾选回写 status (ocr_hit→confirmed)。

## 规范

- [ ] nettable/SCHEMA.md 随 schema 演进同步更新; components_index 0.2
      (package/pins 字段) 设计时先写规范再动数据。
- [ ] 旧 tesseract 管线(pcb_designator_ocr)确认无引用后移 archive 说明。
