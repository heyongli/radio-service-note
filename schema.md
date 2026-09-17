
# 全局 schema — nettable/ json 字段规范

**本文件是所有项目共享的 nettable/ json 字段规范**。
每个项目目录下可以有一个 `nettable/schema.md` 引用本规范, 并补充
项目特定的扩展。

---

## 0. 五要素总览 (任何项目 schema.md 必含)

| 节 | 必含 | 说明 |
|---|---|---|
| §1 文件清单 | ✓ | 该目录下所有 json/md 文件, 每个的"用途" |
| §2 目录结构 | ✓ | 整个 nettable/ 目录的层级图, 每层"职责" |
| §3 元数据格式 | ✓ | 每个 json 的字段规范 + 必填/可选 + 完整 json 示例 |
| §4 用法 | ✓ | 上下游谁读, 谁写, 错误处理 |
| §5 目的 | ✓ | 该目录在项目中的作用, 与其他模块的关系 |

---

## 1. 溯源链: 原始 pdf → 任意 dpi

### 1.1 完整的 backtrace 链

```
原始 pdf (例如 pcb-top.pdf)
  ↓ pdftoppm -r <dpi> -png <pdf> <out-prefix>
中间产物 png (例如 render/pcb-top-600-1.png @ 600dpi)
  ↓ ai-ocr 或人工标注
ocr box / 人工 anchor (在某 ocr 输出空间)
  ↓ 转换链 (scale, tile_pos, offset)
components_index.json 的 tgt_dpi 空间 (统一 600dpi)
  ↓ 派生
wpts_*.json (pcb 标注)
  ↓ svg_render.py
最终 svg/png 标注 (给读者看)
```

### 1.2 每一层的元数据 (必须逐层记录)

#### l0: 原始 pdf (真相源)
- `pdf`: 相对项目根路径
- `pdf_page`: 页码 (1-based)
- `pdf_size_pt`: (w_pt, h_pt) — pdf 单位 pt, 1 pt = 1/72 inch
- `pdf_physical_size_inch`: (w_in, h_in) — 物理打印尺寸
- `pdf_provenance`: 扫描/翻拍/厂家提供

**所有坐标的最底层真相**: pdf 空间是绝对的, 任意 dpi 都能精确换算。

#### l1: 中间产物 png (由 pdftoppm 渲染)
- `image`: 相对路径
- `image_dpi`: 渲染 dpi (300/600)
- `image_size_px`: (w_px, h_px) — 像素尺寸
- `render_cmd`: 实际命令 `pdftoppm -r <dpi> -png <pdf> <prefix>`
- `back_to_pdf`: `pdf_px = image_px * (72 / image_dpi)`, 即 `image_px / (image_dpi / 72)`

**关系**: `image_px = pdf_pt * (image_dpi / 72)`, 这是无损换算。

#### l2: 母图上的板边 (铆钉)
- `board_bbox`: (x0, y0, x1, y1) — 在 image_dpi 空间的板边矩形
- `board_bbox_inch`: (x0_in, y0_in, x1_in, y1_in) — 换算到 inch 单位
- 检测方法: otsu 二值化 + 最大连通区域

#### l3: ocr box / 人工 anchor
- `box`: 4 顶点多边形 (在 ocr 输出空间)
- `box_inch`: 4 顶点的物理 inch 坐标 (与 ocr_dpi 无关, 可追溯到 pdf)

#### l4: components_index.json 的 tgt_dpi 空间
- `center` / `box`: 统一存放在某个 `tgt_dpi` (默认 600dpi)
- `tgt_image`: 对应的 png 母图

#### l5: 派生 wpts.json
- `px` / `through`: 与 components_index 同 tgt_dpi 空间

### 1.3 任意 dpi 转换示例

```python
# 任意无损转换: 当前坐标 -> 任意其他 dpi
def convert(ref_info, src_dpi, tgt_dpi):
    scale = tgt_dpi / src_dpi
    return [c * scale for c in ref_info['center']]

# 当前 (tgt_dpi=600) -> 300dpi
center_300 = convert(ref, 600, 300)  # [x*0.5, y*0.5]

# 当前 (tgt_dpi=600) -> 1000dpi
center_1000 = convert(ref, 600, 1000)  # [x*5/3, y*5/3]

# ocr 200dpi box -> 600dpi (scale=3)
box_600 = [[p[0]*3, p[1]*3] for p in ocr_box_200]
```

### 1.4 反向追溯: 任意坐标 -> pdf

```python
# 从 components_index 600dpi 坐标 -> 原始 pdf 物理坐标
center_inch = [c / 600 for c in ref['center']]
center_pt = [c * 72 for c in center_inch]  # pt 单位

# 完全无损, 不依赖任何中间 png
```

---

## 2. components_index.json 元数据规范

### 2.1 顶层结构

```json
{
  "_meta": {
    "purpose": "<项目> 元器件索引(枢纽, 跨图映射), 每条含完整溯源",
    "format": "json dict refdes -> {...}",
    "version": "<semver> <date>",
    "consumers": ["...", "..."],
    "indexed_refdes": <int>,
    "by_view": {"top": <int>, "bot": <int>, "sch": <int>},
    "by_role": <int>,
    "anchor_count": <int>,
    "scale_distribution": {"1.0": <int>, "3.0": <int>}
  },
  "_backtrace": {
    "pdf_root": "<相对项目根的 pdf 目录>",
    "layers": [
      {"l0_pdf": "<pdf>", "page": <int>, "size_pt": [w, h]},
      {"l1_image": "<png>", "dpi": <int>, "size_px": [w, h], "cmd": "pdftoppm ..."},
      {"l2_anchors": {"<image>": {"bbox_px": [x0,y0,x1,y1], "bbox_inch": [...]}}}
    ]
  },
  "_anchor_method": {
    "description": "pcb 板边自动检测作为坐标铆钉, 所有 refdes 必须落在板内",
    "method": "otsu 二值化 + scipy.ndimage.label 最大连通区域 bbox",
    "image": "<母图路径>"
  },
  "_transform_legend": {
    "src_dpi": "原始 ocr/人工输出坐标所在 dpi 空间",
    "tgt_dpi": "存储坐标的目标 dpi 空间",
    "scale": "tgt_dpi / src_dpi 缩放系数",
    "method": "转换方法 (tile_pos, scale, rotation 等)",
    "validated": "是否经过 v8/人工验证 (true=锚点级)"
  },
  "<refdes>": {
    "center": [x, y],
    "box": [[x,y]×4],
    "view": "top|bot|sch",
    "role": "<功能>",
    "flow_note": "<链序中作用>",
    "agree": <bool>,
    "candidates": <int>,

    "src": "<溯源标识>",
    "src_dpi": <int>,                     // box 原始输出空间
    "tgt_image": "<母图路径>",
    "tgt_image_dpi": <int>,
    "tgt_image_size": [w, h],
    "tgt_board_bbox": [x0, y0, x1, y1],   // 铆钉
    "transform": {
      "src_image": "<母图>",
      "src_dpi": <int>,
      "tgt_dpi": <int>,
      "scale": <float>,
      "method": "<转换方法>",
      "tile_pos": [col, row],            // (可选) tile 起点
      "tile_grid": "200x200 px @ 600dpi, stride=160",  // (可选)
      "validated": <bool>
    },
    "scale": <float>,                     // 缩放系数 (= tgt_dpi / src_dpi)
    "validated": <bool>                    // 是否经过人工/v8 验证
  }
}
```

### 2.2 字段规范 (每条 refdes)

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `center` | [x, y] | ✓ | 中心点坐标 (`tgt_image_dpi` 空间) |
| `box` | [[x,y]×4] | ✓ | 4 顶点多边形 bbox (同空间) |
| `view` | "top"/"bot"/"sch" | ✓ | 视图 |
| `role` | str | | 功能 |
| `flow_note` | str | | 在链序中的作用 |
| `agree` | bool | | 双引擎同位一致 |
| `candidates` | int | | 跨 ocr 命中聚合候选数 |
| `src` | str | ✓ | 溯源标识 (见 §2.3) |
| `src_dpi` | int | ✓ | src 坐标的 dpi 空间 |
| `tgt_image` | str (相对路径) | ✓ | 存储坐标所在母图 |
| `tgt_image_dpi` | int | ✓ | 母图 dpi |
| `tgt_image_size` | [w, h] | ✓ | 母图尺寸 |
| `tgt_board_bbox` | [x0,y0,x1,y1] | ✓ | 母图板边 (铆钉) |
| `transform` | object | ✓ | 转换链 (见 §2.4) |
| `scale` | float | ✓ | `tgt_dpi / src_dpi` |
| `validated` | bool | | 是否经过 v8/人工验证 (true=锚点级) |
| `body` | object | | 封装本体框 (具体位置): `{bbox:[x0,y0,x1,y1], center:[x,y], wh:[w,h]}` 同母图坐标 |
| `package` | str | | 封装类型 (如 "SSOP-16" / "SOP-8" / "SOT-23"; 未确认标 "?" ) |
| `package_src` | str | | 封装来源: `"crop-ocr"` (精确裁切验证) / `"pin-silk"` / `"manual"` |

**封装字段 (body/package) 规则**:
- `body` = 封装检测确认的本体框 (rectangle/circle 裁切 bbox + 精确裁切验证),
  **不是**标签文字 box。`body.center` ≠ 文字 `center` 时必须分开记录
- `package` 只写经过验证的封装类型, 不确定时加 `?` (遵循"不臆造")
- bot 面本体框坐标是 bot view 空间, 与 `view` 一致

### 2.3 src 字段取值约定

| src 模式 | src_dpi | scale | transform.method |
|---|---|---|---|
| `v8_<pdf_basename>_<dpi>_agree` | 600 | 1.0 | v8 时代全图 ocr + 双引擎 agree + 人工验证 |
| `v8_<pdf_basename>_<dpi>_inferred` | 600 | 1.0 | v8 推断 (sch 比例 + 链序 + 全图 ocr) |
| `<run_id>_board_tiles_<hash>.json [nx]` | n | 1.0/n | board_tiles ocr, n dpi -> 600dpi |
| `manual_<date>_<initials>` | 600 | 1.0 | 人工标注 (要求 validated=true) |

### 2.4 transform 字段

```json
{
  "src_image": "<母图>",
  "src_dpi": <int>,
  "tgt_dpi": <int>,
  "scale": <float>,            // = tgt_dpi / src_dpi
  "method": "<转换方法>",
  "tile_pos": [col, row],      // (可选) tile 起点
  "tile_grid": "200x200 px @ 600dpi, stride=160",  // (可选)
  "validated": <bool>
}
```

### 2.5 验证规则 (加载时强制检查)

```python
def validate(ref, info):
    # 数学一致性
    assert info['scale'] == info['transform']['tgt_dpi'] / info['transform']['src_dpi']
    assert info['tgt_image_dpi'] == info['transform']['tgt_dpi']

    # 母图存在
    img = open(info['tgt_image'])
    assert img.size == tuple(info['tgt_image_size'])

    # 板内
    bb = info['tgt_board_bbox']
    cx, cy = info['center']
    assert bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3], f"{ref} 板外"

    # box 顶点一致
    box = info['box']
    assert len(box) == 4
    assert all(bb[0] <= p[0] <= bb[2] and bb[1] <= p[1] <= bb[3] for p in box)
```

### 2.6 rectangle_crops_index.json 元数据规范

**用途**: 记录 PCB 母图上检测到的**所有矩形轮廓** (IC/电阻/电感/电容/三极管/连接器等),
含 bbox/分类/裁切文件路径。由 `tools/rectangle_locator/rectangle_locator.py` 生成。

**与 components_index 的关系**: components_index 记录已知 refdes (通过 OCR/人工确认);
rectangle_crops_index 记录所有几何检测到的矩形 (尚未确认身份, 等待 OCR 验证)。

**存放位置**: `projects/<机型>/crops/rectangle/crops_index.json` (与裁切图同目录)

```json
{
  "_meta": {
    "purpose": "PCB 全板矩形裁切索引 — 所有检测到的矩形轮廓, 含 bbox/pad/分类/裁切文件",
    "format": "json dict: _meta + _backtrace + board_bbox + rectangles[]",
    "version": "<semver> <date>",
    "consumers": ["rectangle_locator/rectangle_locator.py", "tools/verify_anchor/verify_anchor.py"],
    "tool": "tools/rectangle_locator/rectangle_locator.py",
    "tool_version": "<float>",
    "indexed_rectangles": <int>,
    "by_category": {"ic": <int>, "resistor": <int>, ...},
    "image": "<母图路径>",
    "image_dpi": <int>,
    "view": "top|bot"
  },
  "_backtrace": { ... },          // 同 §2.1
  "_anchor_method": { ... },      // 同 §2.1
  "_rectangle_detection": {
    "method": "OpenCV findContours, 多阈值合并",
    "area_range": [<int>, <int>],
    "aspect_max": <float>,
    "rectangularity_min": <float>,
    "classification": {
      "board": "面积 > 500000 (PCB 大板)",
      "ic": "5000-200000, aspect < 4, rectangularity > 0.85",
      "resistor": "1000-50000, aspect >= 4, rectangularity > 0.6",
      "capacitor": "1000-5000, aspect < 3, rectangularity > 0.75",
      "inductor": "5000-50000, aspect < 3, rectangularity > 0.8",
      "medium_passive": "5000-50000, 未匹配以上",
      "small_passive": "1000-5000, 未匹配以上",
      "tiny_passive": "300-1000",
      "trace_segment": "300-1000, aspect >= 3",
      "large_passive": "> 50000, 未匹配以上",
      "unknown": "其他"
    }
  },
  "_transform_legend": {
    "src_dpi": "原始检测坐标所在 dpi 空间",
    "tgt_dpi": "存储坐标的目标 dpi 空间 (同母图)",
    "scale": "1.0 (坐标同母图, 无需转换)",
    "method": "直接从母图轮廓检测, 无 tile/缩放"
  },
  "board_bbox": [x0, y0, x1, y1],
  "rectangles": [
    {
      "idx": <int>,
      "bbox": [x0, y0, x1, y1],
      "center": [x, y],
      "wh": [w, h],
      "area": <float>,
      "aspect": <float>,
      "rectangularity": <float>,
      "gray_range": [lo, hi],
      "category": "board|ic|resistor|capacitor|inductor|medium_passive|small_passive|tiny_passive|trace_segment|large_passive|unknown",
      "description": "<自动分类说明 + 附近 OCR 文字提示>",
      "status": "unverified|ocr_found|confirmed",
      "refdes": "<OCR 找到的位号, 可 null>",
      "refdes_source": "<OCR 来源 (run_id + rot), 可 null>",
      "nearby_ocr_refs": ["<附近 100px 内已知 refdes>"],
      "crop_file": "<filename>.png",
      "crop_bbox_with_pad": [x0, y0, x1, y1],
      "pad_px": <int>,
      "view": "top|bot",
      "tgt_image": "<母图文件名>",
      "tgt_image_dpi": <int>
    },
    ...
  ]
}
```

#### 2.6.1 category 分类规则

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

#### 2.6.2 crop 文件命名

```
r{idx:04d}_{category}_{cx}x{cy}_w{w}h{h}.png
```

示例: `r0012_ic_3293x2262_w179h71.png`

---

## 3. chain_order_*.json 元数据规范 (流经元器件图)

**定位**: 这是**中间数据结构**——原理图学到的信号流经元器件图 (固定格式)。
串联三端:
```
schematic_flow_walk ──► chain_order_rx.json ──► radio_design_flow (radio-design.md 流经图)
                          │
                          └──► make_config_from_chain ──► signal_flow_route ──► PCB 标注
```
本结构 = 信号流经元器件的**权威有序列表**, 任何下游 (框图/PCB 标注/设计文档) 只读它。

### 3.1 顶层

```json
{
  "_meta": {
    "purpose": "<机型> <链名> (流经元器件图)",
    "format": "json {chain[], auxiliary[]}",
    "version": "<semver>",
    "consumers": ["radio-design.md 流经图", "make_config_from_chain.py"],
    "source": "schematic_flow_walk (彩线掩膜+BFS+符号+OCR)"
  },
  "chain": [
    {
      "idx": <int>,           // 1-based 链序号 (信号流经顺序)
      "name": "<显示名>",
      "refdes": "<r/c>",      // 可 null (如 BPF 无位号)
      "role": "<功能>",
      "type": "<connector|filter|amplifier|mixer|detector|oscillator>",
      "sch_px": [x, y],      // sch 300dpi 空间
      "sch_image": "<sch 母图>",
      "sch_image_dpi": <int>,
      "pcb_px": [x, y],      // PCB top 600dpi 空间 (bot 已镜像), 可缺省
      "pcb_view": "top|bot",
      "status": "confirmed|unverified|inferred"
    },
    ...
  ],
  "auxiliary": [...]         // 旁路/控制, 不进主流程 (architecture §4c)
}
```

### 3.2 跨视图关联 (sch → pcb)

- `sch_px` = 原理图坐标 (300dpi), 由 schematic_flow_walk 从彩线走线排定
- `pcb_px` = PCB top 坐标 (600dpi, bot 已镜像), 由 make_config_from_chain
  从 components_index 回填; 未定位留空 (不臆造)
- 下游 PCB 标注 (signal_flow_route) 只读 `pcb_px`, 生成 wpts

### 3.3 字段溯源要求

- `sch_px` 必须含 `sch_image` + `sch_image_dpi`
- `pcb_px` 必须含 `pcb_view`, 由 `components_index` 溯源

### 3.4 原理图 refdes 位置 JSON (schematic_flow_walk 输入)

`schematic_flow_walk --refdes` 的输入: 原理图上已定位的 refdes 列表
(OCR 网格 tile 识别, 600dpi 空间)。用于断口附近 OCR 关联最相关元器件。

```json
[
  {"refdes": "Q27", "x": 1532, "y": 858,
   "role": "RF-AMP", "category": "transistor"}
]
```

| 字段 | 类型 | 必填 | 含义 |
|---|---|---|---|
| `refdes` | str | ✓ | 位号 (IC/Q/C/R/L/F...) |
| `x` / `y` | int | ✓ | 原理图文字位置 (600dpi) |
| `role` | str | | 功能 (可选) |
| `category` | str | | 类型 (可选, 辅助类型匹配) |

坐标空间与 `--img` 一致 (600dpi 原理图)。

---

## 4. wpts_*.json 元数据规范

### 4.1 顶层 (每个 wpts 文件首个条目)

```json
{
  "description": "<标注描述>",
  "source": "chain_order_*.json + components_index.json",
  "view": "pcb_top_600dpi|pcb_bot_600dpi",
  "dpi": <int>,                 // 与 view 后缀一致
  "tgt_image": "<母图>",
  "tgt_image_dpi": <int>,
  "tgt_board_bbox": [x0, y0, x1, y1]
}
```

### 4.2 每条标注

| layer | kind | 必含字段 |
|---|---|---|
| `rx` | `line` | `px`, `through[]`, `dash`, `label`, `lpos`, `fs` |
| `rx` | `mark` (在 marks 层) | `px`, `label`, `dot`, `fs`, `lpos`, `note` |
| `ctrl` | `rect` | `px`, `w`, `h`, `dash`, `label` |
| `notes` | `text` | `px`, `label`, `fs` |

### 4.3 信号流过原则 (architecture.md §4c)
- `kind=line` (主流程) 只包含信号"流过"的串联器件
- 旁路/控制/调谐不进主流程, 用 marks 单独标注

---

## 5. 跨 dpi 转换的正确做法

### 5.1 公式

```
任意无损换算:
  coord_inch = coord_px / dpi
  coord_pt = coord_inch * 72 = coord_px * 72 / dpi
  coord_other_dpi = coord_inch * other_dpi = coord_px * other_dpi / dpi
```

### 5.2 禁止

- 跨 dpi 空间直接相加坐标 (例: 200dpi_box + 600dpi_tile_pos)
- 跨 pdf 页/视图共享 px 坐标 (比例可共享, 绝对 px 不可)
- 缩放后忘记更新 scale / src_dpi / tgt_dpi 字段

### 5.3 推荐: 每条 refdes 都用 tgt_dpi=600

统一存储到 600dpi, 转换仅在消费时计算:

```python
# 渲染到任意 dpi 图
def render_at_dpi(ref_info, out_dpi):
    scale = out_dpi / ref_info['tgt_image_dpi']
    return [c * scale for c in ref_info['center']]
```

---
---

## 附录 a: schema.md 编写规范 (项目级 schema.md 五要素)

**适用范围**: 任何新项目 (或现有项目) 的 `projects/<机型>/nettable/schema.md` 
必须包含以下 5 大要素。本节定义每节要写什么。

### 五要素总览

| 节 | 必含 | 说明 |
|---|---|---|
| §1 文件清单 | ✓ | 该目录下所有 json/md 文件, 每个的"用途" |
| §2 目录结构 | ✓ | 整个 nettable/ 目录的层级图, 每层"职责" |
| §3 元数据格式 | ✓ | 每个 json 的字段规范 + 必填/可选 + 完整 json 示例 |
| §4 用法 | ✓ | 上下游谁读, 谁写, 错误处理 |
| §5 目的 | ✓ | 该目录在项目中的作用, 与其他模块的关系 |

### §1 文件清单
列出每个 json 文件名 + 一句话用途 + 当前版本 + 主要字段,
每个 md 文件名 + 一句话用途, 子目录 + 一句话用途。

### §2 目录结构
ASCII 树状图 (含所有文件/子目录), 每层/每个目录的"职责"一句话,
与 architecture.md §0 的链接。

### §3 元数据格式
每个 json 文件单独一节, 字段表格 (字段名 / 类型 / 必填 / 默认 / 含义),
完整 json 示例, 字段取值约定, 溯源元数据。

### §4 用法
- 消费者清单: 哪些工具/脚本读这个文件, 读哪些字段
- 生产者: 谁生成, 何时更新
- 修改流程: 修改时如何保持向后兼容 (version bump 规则)
- 校验规则: 加载时如何验证完整性
- 错误处理: 字段缺失/格式不对时如何处理

### §5 目的
- 该目录的核心目的
- 它与 architecture.md 的关系 (哪个原则/章节)
- 它与其他模块 (render/, crops/, ocr_runs/, annot/) 的边界
- 演进方向 (未来会怎么扩展)

### 附录: 最小化完整示例

```markdown
# schema — IC-2200H nettable/

## §1 文件清单

| 文件 | 用途 |
|---|---|
| components_index.json | 元器件索引枢纽 |
| chain_order_rx.json | RX 链序 |
| wpts_rx_top_v1.json | RX top 标注 |

## §2 目录结构

```
nettable/
├── components_index.json   # 索引
├── chain_order_rx.json      # 链序
├── wpts_rx_top_v1.json      # waypoints
```

## §3 元数据格式
[实现项目特定字段表格]

## §4 用法
[项目特定消费者/生产者]

## §5 目的
[项目特定核心/边界]
```

---

## 修订日志

| version | date | 变更 |
|---|---|---|
| 0.3 | 2026-09-15 | 加入"schema.md 编写规范(五要素)"附录; 合并项目 schema.md |
| 0.2 | 2026-09-15 | 加入 pdf backtrace 链, 实现任意缩放/转换无损 |
| 0.1 | 2026-09-15 | 初版: 五要素总览 + components_index/chain_order/wpts 三类核心字段规范 |
