# pcb_designator_ocr — 维修 PCB 图位号 OCR（已验证配方固化）

2026-09 IC-2200H 实战验证：top/bot 视图（内嵌光栅位图印刷体）的位号 OCR 有效。
本工具是 session 中一次性管道的固化版。

## 用法

```bash
# PNG 输入（coords 按 0.5 缩到 300dpi 空间）
python3 tools/pcb_designator_ocr/ocr_designators.py projects/IC-2200H/render/top_hi-1.png \
    --out projects/IC-2200H/nettable/top_designators.json

# PDF 输入（内部先 pdftoppm 600dpi）
python3 tools/pcb_designator_ocr/ocr_designators.py IC-2200H-top.pdf --dpi 600
```

## 管线（与 best_practices.md §5 对应）

1. 灰度 → `ImageOps.autocontrast`
2. 多档二值化扫描（默认 T=140/170/200/230，`--thresh` 可调）
3. LANCZOS 3x 上采样 → `tesseract --psm 11 TSV`
4. 位号正则过滤（**不加 tesseract 字符白名单**——会吞 IC10 的 I）+ conf 下限
5. 跨阈值合并：同 label 且坐标近（40px 网格）→ 取最高 conf，多阈值命中提高可信度
6. 字形聚类兜底：连通域（高 5-28px 宽 2-20px 长宽比<6）→ cKDTree 20px 并查集聚类
   → 逐框 4x crop psm7 —— 抓全图 OCR 漏掉的位号
7. 输出 JSON：`label -> [{x, y, conf, src}]`，按 conf 降序

## 局限（必读）

- **密集背景区（AF 段等）双通道全失效** → 放 2.2x tile 人工视觉通读，
  见 best_practices.md §5
- OCR 结果必须视觉双确认（命中 ±50px 高倍 crop）后才算"确认锚点"
- 输出坐标是 label 文本左上角，元件本体需再定位
- 描边字形原理图（rxtxflow 功能块标签）不适用本工具 → 用 svg_glyph_decode

## 依赖

tesseract（系统）、PIL、numpy、scipy
