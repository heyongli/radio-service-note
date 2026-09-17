
# tools/verify_anchor — 设计文档

**核心思想**: 坐标可能被错位 (OCR 误读 / DPI 缩放错误 / 母图版本变化),
唯一权威验证 = **回到 PCB 母图, 裁切坐标周围, 重新 OCR, 看是否识别出相同 refdes**。
这就是"自检 OCR"回路。

**代码不写在这里, 写在 `verify_anchor.py`**。

---

## §1 目的

每个 refdes 都有"理论坐标" (components_index.json 里的 center),
但 PCB 真实位置可能不是那里 (OCR 误读 / 缩放错误 / 数据陈旧)。
验证方法: 给定坐标 → 裁切 PCB 图 → OCR → 看是否识别出相同 refdes。

## §2 体系结构

```
verify_anchor 主循环:
  for ref, x, y in coords:
    ┌──────────────────────────┐
    │ crop = PCB.crop(           │
    │   (x-w/2, y-h/2,          │
    │    x+w/2, y+h/2))          │
    │ crop.upscale(2x)            │
    │ ocr(crop)                    │
    │ ├─ 调用 ai_refdes_ocr.py    │
    │ ├─ 单 tile grid OCR         │
    │ ├─ v5s+v4 双引擎 agree     │
    │ └─ 解析 raw_stage1/2        │
    │ compare(crop_ocr, expected)  │
    │ ├─ match: 完全/前缀一致     │
    │ ├─ mismatch: 识别到其他 ref │
    │ └─ not_found: 识别但不含    │
    └──────────────────────────┘
```

## §3 参数 (五要素 §3)

| 参数 | 默认 | 说明 |
|---|---|---|
| `--pcb` | 必填 | PCB 母图 PNG |
| `--coords` | 必填 | `(x,y)=REF (x,y)=REF ...` |
| `--crop-size` | 300x200 | 裁切尺寸 |
| `--fuzzy` | False | 模糊匹配 (OCR 文本含 ref 前缀) |
| `--work-dir` | /tmp | 中间文件 + 报告 |
| `--out` | report.json | 输出报告 |

## §4 用法 (§4)

### 4.1 验证 v10 关键节点
```bash
python3 tools/verify_anchor/verify_anchor.py \
    --pcb projects/icom2200h/render/pcb-top-600-1.png \
    --coords "(1277,1489)=J11 (1646,1159)=F13 (1547,1159)=F14 (1714,1385)=IC12 (1726,709)=D12 (1671,807)=D27 (1919,1094)=FI1 (1921,1345)=FI2" \
    --fuzzy
```

### 4.2 验证 components_index 全量
```bash
python3 tools/verify_anchor/verify_anchor.py \
    --pcb projects/icom2200h/render/pcb-top-600-1.png \
    --coords-from-json projects/icom2200h/nettable/components_index.json \
    --fuzzy
```
(将来扩展)

## §5 退出码
- `0`: 全部 match
- `1`: 有 mismatch
- `2`: 参数错

## §6 关键发现 (重要踩坑)

1. **OCR 在 300dpi 缩放图上失真** — 必须保留原始 600dpi PCB 区域,
   然后 upsample 2x 给 OCR (200x150 → 400x300), 让字相对更大
2. **裁切尺寸**: 太小→ OCR 不见全字, 太大→ 邻接器件混入. 300x200 是经验值
3. **backtick/Windows 路径**: 必须 WSL 调 Windows python.exe, 不能混路径
4. **UnicodeEncodeError**: OCR 输出 \uXXXX 中文失败, bat 设 PYTHONIOENCODING=utf-8

## §7 演进方向

- **批量**: 从 components_index 全量自动生成 coords
- **双向校验**: 给 refdes → OCR → 比对坐标; 给坐标 → OCR → 比对 refdes
- **统计**: 一段时间内的 mismatch rate, 索引健康度指标
- **PDF 直检**: 不依赖 PNG, 直接 pdftoppm 渲染当前 PDF 子图, 抗 PDF 版本漂移
