# 方法探索历史 (曾试过的方法, 已被取代)

记录被当前管线取代/弃用的方法, 供参考与避免重复踩坑。
当前有效管线见 `architecture.md` §13 (sch/pcb/结合 三大管线)。

## 曾试过的方法 (按工具)

| 曾用工具 | 方法 | 被谁取代 | 经验/教训 |
|---|---|---|---|
| `ai_ocr_eval/ai_refdes_ocr.py` | 两阶段 AI OCR (grid 网格扫 + contour 字形聚类 + 双引擎 agree) | `pcb_label_ocr` (矩形/圆形裁切 + 多角度 DML OCR) | 全页小字 v4-mobile 最强; crop+4x 上采样后各引擎几乎通读难例; 600dpi 整页 5-9 分钟, fast 预设 17s |
| `pcb_designator_ocr/ocr_designators.py` | 旧 tesseract 多阈值管线 | ai_refdes_ocr → pcb_label_ocr | tesseract 被 RapidOCR 取代, 保留为对照基线 |
| `annotate_svg_flow/` | 分层 SVG 标注 (base64 底图) + bot 铜箔 Dijkstra 路由 | `svg_render` | 语义图层/实线确认虚线推断; 路由失败回退正交 |
| `annotate_rx_flow/` | 块级/照片 waypoint 标注 (raster) | `signal_flow_route` + `svg_render` | add_photo_wpts 位级标注思路保留 |
| `ic_locator/ic_locator.py` | IC 几何定位 (深色矩形+圆+内部局部 OCR) | `pcb_package` (crop-ocr + 精确裁切验证) | 多阈值合并 30-150/50-200; 旋转 0/90/270; 候选区分别 OCR |
| `multi_scale_ocr/` | 多尺度金字塔 tile 扫描合并去重 | 矩形/圆形裁切 + 单尺度放大 | 大字体被切碎/小字体过度放大 → 多尺度 |
| `poll_ocr/` | OCR 后台任务轮询 (替代 ad-hoc tail/sleep 循环) | (通用工具思路) | 监控后台长任务封装成工具 |
| `annot_clean/` | 旧渲染版本自动清理 | (通用工具思路) | 旧版本 PNG/SVG 归档而非删除 |
| `font_glyph_decode/` `svg_glyph_decode/` | 描边字形解析 (原理图功能块标签) | (参考) | pdftotext 读不到矢量描边字形, 需图像解码 |

## 关键历史教训 (详见 best_practices.md §13 经验教训)
- 旋转 OCR 坐标转换: rot=90/270 必须逆旋转 (曾偏移 345 处)
- 本体中心 ≠ 标签文字中心, 轮廓框必须用本体 bbox
- OCR 输出永远不可信, 必须 chain_order 上下文校正
- 不同 DPI 空间只能比例映射, 不能直接相加
- 触及 ≠ 主路, 主路需按电路原理甄别