* 通过pdf或者图片的电路图, 信号流程图, 在实物pcb照片或者维修pcb的点位图上标注信号流程
* 注意合理利用各种现有工具
* 用到脚本放入 tools/目录
* 总结 best practice, 记录如何处理pdf, 丝印, pcb文件, png,svg等
* 注意开发工具来完成常用任务,并记录工具的设计, 使用文档. 放入tools/ 各自目录
* 旧约定"extract目录"已废弃(2026-09): 中间文件按类型分目录(见下条), 禁止新建/混入 extract/
* 每个设备/机型(如 IC-2200H)建立项目目录 projects/<机型>/: 源PDF放项目根, 中间文件按类型分目录(禁混放): render/(PDF渲染底图) scan/(读图窗口) nettable/(网表+waypoints JSON) annot/(标注成品) archive/(历史文件); 临时中间件放 /tmp/opencode/ 并在网表JSON记录路径
* 开始任务前先 load best_practices.md, 按其中的已验证结论操作, 避免重复踩坑

## 位号识别与标注要求（本次验证的有效方法）
* 优先用维修 PCB 图(top.pdf/bot.pdf)而非实物照片: 照片位号太小不可读, PCB图渲染分辨率高2倍以上且坐标与原理图同向
* 渲染一律用 `pdftoppm -r 600`（600dpi 优先, 300dpi 仅作对照）
* OCR 管线: 灰度→autocontrast→多档二值化(T=100~250扫描)→LANCZOS 2-3x上采样→`tesseract --psm 11 TSV`; 多阈值并行跑后按坐标合并去重, 交叉验证置信度
* OCR 不要加字符白名单（IC10 会被误读吞掉 I）; 用宽松正则后过滤
* 字形聚类补漏: numpy掩码→scipy.ndimage.label→尺寸过滤(字高5-28px)→cKDTree 20px聚类成文本框→逐框4x crop 单词OCR(--psm 7/8); 用于抓全图OCR漏掉的位号
* OCR 失效区（密集背景）改 2.2x tile 人工视觉通读
* 每个OCR命中必须视觉双确认（命中坐标±50px 高倍5-8x crop 拼图签, 黄字标bbox）才算"确认锚点", 防幻觉
* 用原理图信号链顺序做空间先验定位: BNC正下方找LPF, X2旁找IC4, FI2旁找FI1 等空间关系验证元件身份
* 未确认的链路段必须画虚线+标注"not located", 不得臆造坐标
* 标注渲染用 tools/annotate_rx_flow/add_photo_wpts.py: waypoints JSON(px/label/dot/dash/through), 实线=确认, 虚线=推断, 半尺寸view校验后出全尺寸成品
* 网表 JSON 必含: confirmed_anchors(坐标+置信来源), not_located 清单, chain_order_schematic, artifacts 索引
