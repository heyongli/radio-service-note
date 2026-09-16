
# circle_locator — PCB 圆形裁切定位器

检测 PCB 600dpi 母图上所有圆形轮廓，裁切保存 + 写 `crops_index.json`。

## 用法

```bash
python tools/circle_locator/circle_locator.py \
    --pcb projects/icom2200h/render/pcb-top-600-1.png \
    --view top \
    --crops-dir projects/icom2200h/crops/circle/
```

## 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--pcb` | (必填) | PCB 母图 PNG 路径 |
| `--view` | top | 视图 (top/bot) |
| `--crops-dir` | (必填) | 裁切图保存目录 |
| `--out` | crops-dir/crops_index.json | 输出索引路径 |
| `--min-diameter` | 10 | 最小直径 (px) |
| `--max-diameter` | 200 | 最大直径 (px) |
| `--circularity-min` | 0.6 | 最小圆度 (0-1) |

## 分类规则

| 类别 | 直径 | 面积 | 说明 |
|---|---|---|---|
| via | < 15px | - | 过孔 |
| test_point | 15-30px | - | 测试点 |
| crystal | 30-80px | > 3000 | 晶振/振荡器 |
| inductor_round | 30-80px | ≤ 3000 | 圆形电感 |
| capacitor_elec | 80-150px | - | 电解电容 |
| large_circle | > 150px | - | 大型圆形 |
| unknown | 其他 | - | 未分类 |

## 检测方法

1. **HoughCircles**: 多参数组合 (dp=1/1.5/2, minDist=20/30/40, p1=50/80/100, p2=20/30/40)
2. **轮廓圆度**: 4π×area / perimeter² > 0.6
3. **去重**: 合并重叠圆 (中心距 < max(r1,r2)×0.6)

## 输出

- `crops/circle/*.png` — 圆形裁切图
- `crops/circle/crops_index.json` — 圆形索引 (bbox/center/diameter/category)

## 与 rectangle_locator 配合

```bash
# 1. 矩形检测
python tools/rectangle_locator/rectangle_locator.py --pcb ... --crops-dir crops/rectangle/

# 2. 圆形检测
python tools/circle_locator/circle_locator.py --pcb ... --crops-dir crops/circle/

# 3. 合并 OCR
python tools/ic_ocr_scan/ic_ocr_scan.py \
    --crops-index crops/rectangle/crops_index.json \
    --crops-index2 crops/circle/crops_index.json \
    --pcb ... --out nettable/components_index.json
```
