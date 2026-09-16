# tools/rectangle_locator — 设计文档

## purpose
PCB 全板矩形裁切定位器 — 在 PCB 600dpi 母图上检测所有矩形轮廓 (IC/电阻/电感/电容/三极管/连接器等), 裁切保存 + 写 schema 合规 `crops_index.json`。

## format
Python 3 + OpenCV + numpy + PIL

## version
0.3 (2026-09-15)

## consumers
- `tools/ic_ocr_scan/ic_ocr_scan.py` — 对 IC 候选做多角度 OCR
- `tools/verify_anchor/verify_anchor.py` — 坐标验证
- `projects/*/crops/rectangle/crops_index.json` — 裁切索引

## parent_doc
`../../schema.md` §2.6

---

## 1. 为什么需要这个工具

### 1.1 之前的问题
- OCR 全图 stage1 grid 经常 "detection result is empty" (模型对 PCB 字体不熟)
- 矩形检测阈值过窄漏检中等灰度 IC 本体
- 单尺度 tile 扫描大字符被切到边界模型识别失败
- 没有系统记录所有矩形, 只找 IC

### 1.2 现在的方案
- **OpenCV findContours** 检测所有矩形轮廓 (多阈值合并)
- **自动分类**: board/ic/resistor/capacitor/inductor/medium_passive/small_passive/tiny_passive/trace_segment/large_passive/unknown
- **裁切保存**: 每个矩形 + pad → `crops/rectangle/*.png`
- **crops_index.json**: schema §2.6 合规, 含 bbox/分类/描述/状态/附近 OCR refdes

---

## 2. 用法

```bash
# Top view
python3 tools/rectangle_locator/rectangle_locator.py \
    --pcb projects/icom2200h/render/pcb-top-600-1.png \
    --view top \
    --crops-dir projects/icom2200h/crops/rectangle/

# Bot view (指定板边)
python3 tools/rectangle_locator/rectangle_locator.py \
    --pcb projects/icom2200h/render/pcb-bot-600-1.png \
    --view bot \
    --board-bbox "1092,539,3962,2931" \
    --crops-dir projects/icom2200h/crops/rectangle_bot/
```

---

## 3. 分类规则

| category | 面积范围 (px² @600dpi) | 长宽比 | 矩形度 | 物理对应 |
|---|---|---|---|---|
| board | > 500000 | - | - | PCB 大板 |
| ic | 5000-200000 | 1-4 | > 0.85 | IC 封装 |
| resistor | 1000-50000 | ≥ 4 | > 0.6 | 电阻 |
| capacitor | 1000-5000 | < 3 | > 0.75 | 电容 |
| inductor | 5000-50000 | < 3 | > 0.8 | 电感 |
| medium_passive | 5000-50000 | - | - | 中型无源器件 |
| small_passive | 1000-5000 | - | - | 小型无源器件 |
| tiny_passive | 300-1000 | - | - | 微型无源器件 |
| trace_segment | 300-1000 | ≥ 3 | - | 走线段 |
| large_passive | > 50000 | - | - | 大型无源器件 |
| unknown | 其他 | - | - | 未分类 |

---

## 4. 输出文件

### 4.1 裁切图
- 路径: `crops/rectangle/r{idx:04d}_{category}_{cx}x{cy}_w{w}h{h}.png`
- 示例: `r0017_ic_3601x1727_w139h111.png`

### 4.2 crops_index.json
- 路径: `crops/rectangle/crops_index.json` (与裁切图同目录)
- 字段规范: `schema.md` §2.6

---

## 5. Best Practices

### 5.1 运行前
- 确认 PCB 母图已生成 (`render/pcb-top-600-1.png`)
- 确认 `render/` 目录下有对应的 600dpi PNG

### 5.2 运行后
- 检查 `crops_index.json` 中 `by_category` 统计
- IC 候选 (category=ic) 用 `ic_ocr_scan/ic_ocr_scan.py` 做多角度 OCR
- 未匹配的矩形 (category=unknown/medium_passive) 需目视确认

### 5.3 metadata 一致性
- `crops_index.json` 的 `_meta` 必须包含: purpose, format, version, consumers, tool, tool_version, indexed_rectangles, by_category, image, image_dpi, view
- 每条 `rectangles[]` 必须包含: idx, bbox, center, wh, area, aspect, rectangularity, gray_range, category, description, status, refdes, refdes_source, nearby_ocr_refs, crop_file, crop_bbox_with_pad, pad_px, view, tgt_image, tgt_image_dpi

### 5.4 与 schema.md 的关系
- schema.md §2.6 定义字段规范
- 本工具的 `_meta.version` 必须与 schema.md §2.6 版本同步
- 新增字段必须先更新 schema.md, 再更新工具
