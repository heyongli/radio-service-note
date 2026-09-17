# tools/pcb_label_ocr — 设计文档

## purpose
IC 候选矩形多角度 OCR 扫描 — 对 `crops_index.json` 中候选 (矩形或圆形)做 0/90/270° 旋转 OCR, 找到 IC 编号 (IC10/IC11/IC12 等), 更新 `crops_index.json` 的 `refdes/status` 字段。

## format
Python 3 + RapidOCR (CPU)

## version
0.1 (2026-09-15)

## consumers
- `projects/*/crops/rectangle/crops_index.json` — 被更新 refdes/status 字段

## parent_doc
`../../schema.md` §2.6

---

## 1. 为什么需要这个工具

### 1.1 之前的问题
- `pcb_rect_locator` 检测到 IC 候选矩形, 但不知道里面是什么
- OCR 全图 stage1 grid 对垂直/小字 IC 识别失败
- 没有系统的方法验证 IC 候选身份

### 1.1.2 现在的方案
- 对每个 IC 候选裁切做 0/90/270° 旋转 OCR
- 匹配 IC 编号正则: `IC\s*(\d+)`
- 更新 `crops_index.json` 的 `refdes/status/refdes_source` 字段

---

## 2. 用法

### 2.1 Linux CPU (慢)
```bash
python3 tools/pcb_label_ocr/pcb_label_ocr.py \
    --crops-index projects/icom2200h/crops/rectangle/crops_index.json \
    --pcb projects/icom2200h/render/pcb-top-600-1.png \
    --view top \
    --rots 0,90,270
```

### 2.2 Windows DirectML GPU (快, 推荐)
```bash
# 方式 1: bat 脚本 (本目录下)
tools/pcb_label_ocr/run_ic_ocr_dml.bat          # 全类别 OCR
tools/pcb_label_ocr/run_ic_ocr_dml_test.bat     # 验证 GPU 是否真正加速

# 方式 2: 直接调用
C:\Users\radio\py311\python.exe tools\pcb_label_ocr\pcb_label_ocr_dml.py ^
    --crops-index projects\icom2200h\crops\rectangle\crops_index.json ^
    --pcb projects\icom2200h\render\pcb-top-600-1.png ^
    --view top ^
    --rots 0,90,270
```

**DML 前提**: Windows 原生 Python + onnxruntime-directml + dml_helper.py (monkey-patch ProviderConfig)。
详见 `best_practices.md` §12 + `tools/zref/ai_ocr_eval/dml_helper.py`。

---

## 3. 输出

更新 `crops_index.json` 中每个 IC 候选的字段:
- `refdes`: OCR 找到的 IC 编号 (例如 "IC12")
- `status`: "ocr_found" (找到) 或 "unverified" (未找到)
- `refdes_source`: OCR 来源信息

---

## 4. Best Practices

### 4.1 运行前
- 确认 `crops_index.json` 已生成 (`pcb_rect_locator/pcb_rect_locator.py`)
- 确认 PCB 母图存在

### 4.2 运行后
- 检查 `refdes` 字段: 哪些 IC 候选找到了编号
- 未找到的 IC 候选需目视确认 (`crops/rectangle/*.png`)

### 4.3 metadata 一致性
- 更新 `crops_index.json` 时保持所有字段完整
- 不删除 `_meta` 或 `rectangles[]` 中的任何字段

### 4.4 旋转 OCR 的坐标转换 (重要)

**问题**: `ocr_crop` 对 rot≠0 先 `img_crop.rotate(-rot, expand=True)` 再 OCR。
OCR 返回的 box 坐标在**旋转后坐标系**, 若直接 `+crop 原点` 映射到 PCB,
坐标会系统性偏移 (rot=90/270 全偏移)。

**修复**: box 必须先做**逆旋转**回原始 crop 坐标, 再加 crop 原点:
```
rot=0:   ox = rx,        oy = ry
rot=90:  ox = ry,        oy = Hc - 1 - rx     (Hc = 原始 crop 高度)
rot=270: ox = Wc - 1 - ry, oy = rx            (Wc = 原始 crop 宽度)
```
已固化在 `ocr_crop` (`pcb_label_ocr.py` + `pcb_label_ocr_dml.py`)。

**验证 (2026-09-16)**:
- IC4 校正后 (1487,2516) 与 crop-ocr 确认本体 (1489,2516) 一致
- IC12 校正后 (3429,2767) 精确裁切 OCR 读出 "IC12" (0.96)
-  components_index 中 345 处 rot≠0 坐标已批量校正

**教训**: 任何"先旋转/缩放再 OCR"的管线, box 坐标必须逆变换回源空间,
否则元数据坐标与底图对不上。相关: architecture.md §2b 坐标转换。
