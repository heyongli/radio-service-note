
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
pcb_index.json 的 tgt_dpi 空间 (统一 600dpi)
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

#### l4: pcb_index.json 的 tgt_dpi 空间
- `center` / `box`: 统一存放在某个 `tgt_dpi` (默认 600dpi)
- `tgt_image`: 对应的 png 母图

#### l5: 派生 wpts.json
- `px` / `through`: 与 pcb_index 同 tgt_dpi 空间

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
# 从 pcb_index 600dpi 坐标 -> 原始 pdf 物理坐标
center_inch = [c / 600 for c in ref['center']]
center_pt = [c * 72 for c in center_inch]  # pt 单位

# 完全无损, 不依赖任何中间 png
```

---

## 2. pcb_index.json 元数据规范

### 2.1 顶层结构

**数据来源** (数据从哪来、怎么来的): 每条 refdes 坐标 = PCB 母图
(`render/pcb-{top,bot}-600-1.png`) 上**该 refdes 丝印文字的实际位置**: 经
矩形/圆形裁切 (crops/, 含母图 bbox) → OCR 识别文字 → 坐标变换 (crop 原点 +
dpi 换算, §2b) → 按 `view` (top/bot/sch) 独立记录. 丝印只在单面的器件坐标
只属该面; 视图镜像关系按板框对齐验证. 程序 (pcb_rect_locator/label_ocr 等)
只是实现载体, 数据本质是"图上丝印位置 + 溯源链".

**用途**: **元器件索引枢纽** —— 跨视图坐标映射的唯一权威源. 消费方:
`make_config_from_chain` (chain 回填 pcb 位置)、`signal_flow_route`、`svg_render`
(标注渲染)、`pcb_verify` (坐标校验)、`wpts` 生成器.

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
含 bbox/分类/裁切文件路径。由 `tools/pcb_rect_locator/pcb_rect_locator.py` 生成。

**与 pcb_index 的关系**: pcb_index 记录已知 refdes (通过 OCR/人工确认);
rectangle_crops_index 记录所有几何检测到的矩形 (尚未确认身份, 等待 OCR 验证)。

**存放位置**: `projects/<机型>/crops/rectangle/crops_index.json` (与裁切图同目录)

```json
{
  "_meta": {
    "purpose": "PCB 全板矩形裁切索引 — 所有检测到的矩形轮廓, 含 bbox/pad/分类/裁切文件",
    "format": "json dict: _meta + _backtrace + board_bbox + rectangles[]",
    "version": "<semver> <date>",
    "consumers": ["pcb_rect_locator/pcb_rect_locator.py", "tools/pcb_verify/pcb_verify.py"],
    "tool": "tools/pcb_rect_locator/pcb_rect_locator.py",
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

**数据来源** (数据从哪来、怎么来的): 信号链序 = 原理图
(`render/rxtx-sch-600-1.png`) 上的**彩线** (绿=RX/红或土黄=TX/黄=控制/青=common)
掩膜 → 沿彩线 BFS 走线 → 局部符号检测 (电容/三极管/IC) → 标号 OCR 关联;
绿线流经顺序与 block 图/文本层交叉验证得有序链. 程序 (sch_trace/label_ocr/
flow_walk/symbol) 只是实现载体, 数据本质是"图上信号流经的元器件序".

**用途**: **信号流经元器件图** (有序链, RX/TX/Control). 消费方:
`make_config_from_chain` (chain + pcb 位置 → 路由 config)、`signal_flow_route`
(waypoint 计算)、PCB 标注 (sch flow → PCB 落点).

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
  从 pcb_index 回填; 未定位留空 (不臆造)
- 下游 PCB 标注 (signal_flow_route) 只读 `pcb_px`, 生成 wpts

### 3.3 字段溯源要求

- `sch_px` 必须含 `sch_image` + `sch_image_dpi`
- `pcb_px` 必须含 `pcb_view`, 由 `pcb_index` 溯源

### 3.5 原理图元器件数据库 sch_components.json (像 PCB 侧 pcb_index 管理)

**定位**: 原理图侧识别+鉴别的中间数据库, 与 PCB 侧 `pcb_index.json` 对应。
由 `schematic_flow_walk` 三层管线 (识别→鉴别→渲染) 生成, 是 sch 侧唯一权威库。

```json
{
  "_meta": {
    "purpose": "<机型> 原理图元器件 (识别+绿线鉴别)",
    "format": "json {components[]}",
    "version": "<semver>",
    "view": "sch_600dpi",
    "source": "schematic_flow_walk (OCR+符号检测+绿线鉴别)"
  },
  "components": [
    {
      "refdes": "C77",
      "text_pos": [1309, 1638],        // 标号文字位置 (600dpi)
      "symbol_pos": [1316, 1674],      // 原理图符号位置 (600dpi)
      "symbol_type": "cap|circle|ic",  // 符号形状
      "symbol_orientation": "h|v",     // 符号方向 (电容: 走线水平=h/垂直=v; 板线与之垂直)
      "symbol_body": {                 // 符号本体 (sch_symbol 识别)
        "kind": "circle|rect|cap|line|diode",
        "cx": 2381, "cy": 1706,        // 本体中心
        "gap": 9, "len": 27,           // cap: 板间距/板长
        "dir": "v"                     // cap 方向
      },
      "sym_boundary": {                // 符号最小包含 (sch_symbol 识别产出, boundary_from_body)
        "kind": "circle|rect",         // 归一化: 圆=外接圆, 其余=外接框
        "cx": 2381, "cy": 1706,        // circle: 中心
        "r": 22,                       // circle: 半径
        "x": 1369, "y": 1693, "w": 27, "h": 22   // rect: 外接框 (cap=len×gap)
      },
      "text_symbol_dist": 42,          // 标号→符号距离
      "green_touch": true,             // 符号是否触点绿线
      "green_sides": ["E", "W"],       // 符号侧边绿线方向
      "membership": "flow_through|branch|none",  // 绿线鉴别结果
      "flow_dir": "H|V"
    }
  ]
}
```

**三层管线 (识别→鉴别→渲染, 分开管理)**:
- **层1 识别** `recognize_components()`: OCR 全量 refdes + 符号检测 → 标号→符号关联
- **层2 鉴别** `verify_green_membership()`: 判定每个组件是否属于绿线
  (`flow_through` 主路 / `branch` 支路 / `none` 非流经)
- **层3 渲染** `render_sch_flow()`: 独立渲染识别+鉴别结果到 sch

**字段规则**:
- `symbol_pos` 是符号位置, ≠ `text_pos` (标号在符号上方)
- `symbol_body` 本体由 sch_symbol 识别; `sym_boundary` = 本体最小包含 (归一化 rect/circle),
  由 `common.boundary_from_body()` 生成, 供 check_overlap (重叠) / sch_render (边界绘制) /
  尺寸知识库 (body_size) 消费
- `membership` 三态: flow_through (绿线两侧共线通过=主路) / branch (单侧=支路) /
  none (不触点绿线)
- 鉴别依据 (ICOM/Yaesu 域特征, best_practices §5b-3)

### 3.5b 真理元素清单 (truth elements, 自我监督排错真理源)

**定位**: 已确认的高可靠事实 = **真理元素**, 不断积累、随处可作真理源
反哺识别 (architecture §14.1c)。本清单列出**所有可作为真理元素的数据字段**、
其存放位置、生产者、**可信度评分**、复用方式 (约束强度)。

**可信度评分 (confidence score, 0-100)**:
| 分档 | 含义 | 来源示例 |
|---|---|---|
| 100 | **人工/用户确认** | 用户明确告诉 (如 GT, 权威) |
| 90 | **OCR 高置信产出** | 文字框 `text_box` (OCR 边框识别准) |
| 80 | 结构化库累积 | `sch_symbol_sizes.json` 典型尺寸 |
| 60 | 掩膜/彩线识别 | 绿线掩膜 (覆盖广, 需弱约束用) |
| 40 | 单源推断 | 走线断口/单次识别位置 |

| 真理元素 | 存放位置 | 生产者 | 可信度 | 复用方式 |
|---|---|---|---|---|
| 用户确认坐标/GT | `gt_*.json` / 人工回写 | 用户 | **100** | 权威锚点, 直接采用 |
| OCR 标号文字框 | `text_box` (sch_components) | sch_label_ocr | **90** | **硬约束**: 符号候选落文字框内 → 拒 (负例排除) |
| 符号本体尺寸 | `sch_symbol_sizes.json` (schema §3.6) | sch_symbol_selfcheck | 80 | 弱约束: 候选尺寸校验 (典型范围 ±60%) |
| 已确认符号位置 | `symbol_pos` (selfcheck 后) | sch_symbol_selfcheck | 80 | 后续轮直接使用 + 周边上下文 |
| 信号流彩线掩膜 | `green_touch`/`green_sides` | sch_flow_walk | 60 | 弱约束: 主路符号应在绿线附近 (排序加权) |
| 走线/连接点 | sch_wire 输出 | sch_wire | 40 | 弱约束: 符号引出线应对齐走线 |
| **走线主网络** | `wire_main_net.png` (掩膜) | 暗像素最大连通域 | **85** (实测: 76% 暗像素单一 net) | 强约束: 符号必在走线上; de-wire 切除走线 |
| 主路链序 | `chain_order_rx.json` | sch_flow_walk | 40 | 弱约束: 上下游约束符号身份/顺序 |

> **wire 真理度待标定 (2026-09-17)**: sch_wire 的走线识别失败率尚未评估
> (骨架化/连接点噪声未量化), 故暂定可信度 40 仅弱约束。待评估后若准确率高,
> 可升档作较强约束 (符号引出线应对齐走线 → 冲突排除)。
> 评估方法: 抽检 N 个符号的引出线是否对齐走线, 算对齐率。

**规则**:
1. **只增不改**: 真理元素 append 累积 (如 sizes db), 不覆盖历史, 可追溯
2. **随处可用**: 存入共享库 (sch_components / sch_symbol_sizes), 任何工具可读
3. **分层强度 (按可信度)**: 可信度 ≥90 (用户确认/OCR 边框) → **硬约束直接拒/采用**;
   可信度 40-80 (尺寸/绿线/走线/链序) → **排序加权不硬拒**
   —— 真理源本身也可能错, 只在可信度高时作强约束

**评分入数据 (truth_score 字段)**: 可信度评分是真理度的标志, 必须**随数据记录**,
不只存在于本文档。每条真理元素在数据中带 `truth_score` (0-100):
- sch_components.json: 每条组件记录 `truth_score` (该条字段的可信度分档, 默认按生产者)
- sch_symbol_sizes.json: 每条尺寸记录 `score` (默认 80, 用户确认升 100)
- gt_*.json: `truth_score: 100` (用户/GT 权威)
- 消费工具读取 `truth_score` 决定约束强度 (≥90 硬约束, <90 排序加权)

**真理度可调整 (truth score 动态更新)**: `truth_score` 不是一次性赋值,
随识别/校验过程**动态升降** (自我监督的自我修正):

| 事件 | 调整 | 示例 |
|---|---|---|
| selfcheck 确认 (reverse OCR/边界/重叠 OK) | **+10** | 候选通过全部校验 → 可信度升 |
| 用户/人工确认 | **=100** | 人工图签确认 → 封顶 |
| 校验失败 (on_label/越界/重叠) | **-20** | 落在文字框内 → 降 |
| 与强真理冲突 (落其他 text_box) | **-30** | 负例排除 → 大降 |
| 跨轮多次确认 (连续 N 轮 OK) | 逐步 +10 | 稳定性累积 |

- 写入: 每个**消费/校验工具** (selfcheck/detect) 更新 `truth_score` 并回写数据
- 读取: 工具按 `truth_score` 分层使用 (≥90 硬约束, 40-80 加权, <40 忽略)
- 轨迹: 建议保留 `truth_history` (轮次+变化), 可追溯 "为何信/为何降"

### 3.6 原理图符号尺寸知识库 sch_symbol_sizes.json (不断丰富的封装知识)

**定位**: 从电路图学习到的**符号封装知识**——随确认符号**不断累积**的尺寸记录,
用于校验印证新符号 (同类型符号边界应接近典型尺寸).

**数据位置**: `projects/<机型>/nettable/sch_symbol_sizes.json`

```json
{
  "cap": [
    {"size": [45, 22], "refdes": "C124"},
    {"size": [48, 20], "refdes": "C133"}
  ],
  "circle": [
    {"size": [44, 44], "refdes": "Q27"}
  ],
  "ic": [
    {"size": [120, 90], "refdes": "IC4"}
  ]
}
```

| 字段 | 类型 | 含义 |
|---|---|---|
| key | str | 符号类型 (cap/circle/ic/res/ind/diode/varactor) |
| `size` | [w, h] | 符号本体尺寸 (px, 600dpi) |
| `refdes` | str | 记录来源 (溯源) |

**不断丰富机制** (sch_symbol_selfcheck 消费):
- 每个**确认 OK** 的符号, 其本体尺寸**追加**到知识库 (append, 不覆盖)
- `typical_size()`: 中位宽/高 = 该类型典型尺寸 (随样本增多趋于稳定)
- `check_size()`: 新符号尺寸偏离典型 ±60% 以上 → 标记 `size_dev` (疑似识别错误)
- 知识库越用越准; 跨机型/跨图纸可复用同类型符号的典型尺寸

---

### 3.7 图例数据库 explanatory_notes.json (颜色→信号 权威真值)

**定位**: 原理图说明框 (虚线方块) 的**图例** —— 每条 = OCR 文字标签 +
对应**色彩样本** (准确线条颜色). 是 "颜色→信号" 的**权威校准源**
(绿=RX / 橙土黄=TX / 青=common / 品红=电压), 供 COLOR_SPEC 探测校准
(tools/sch-true-finding/readme §9, legend_extract.py) 直接读取, 不必猜测.

**数据来源 (provenance)**: 
- 说明框由 `note_box_locate.py` 定位 (OCR 锚点文字 → dash 虚线边框, `_meta.box`)
- 文字标签 = OCR 数据库反查 (框内文字, `entries[].label/px/conf`)
- 色彩样本 = 从框内按行提取的彩色像素中位色 (`entries[].color_bgr`)
- 坐标统一 img 空间 (600dpi), dpi 换算见 §1.3

**用途 (consumers)**:
- `COLOR_SPEC` 探测校准 (tools/sch-true-finding/de_annotate_*.py): 读取本库得
  各信号线的准确颜色阈值, 不靠猜测
- 信号流区分 (RX/TX/common/电压 线): 按 `label` 映射信号类型
- 跨机型复用: 不同机型锚点文字不同但结构类似, 提取后入库统一校准

**数据位置**: `projects/<机型>/nettable/explanatory_notes.json`

```json
{
  "_meta": {"purpose": "explanatory notes legend (color->signal truth)",
            "format": "json", "version": "0.1",
            "source": "projects/.../render/rxtx-sch-600-1.png",
            "box": [4115, 982, 298, 207]},
  "entries": [
    {"label": "VOLTAGE LINE", "px": [4334, 1044], "conf": 0.91,
     "color_bgr": [138, 6, 227]},
    {"label": "TX LINE", "px": [4302, 1084], "conf": 0.93,
     "color_bgr": [19, 135, 246]},
    {"label": "RX LINE", "px": [4304, 1124], "conf": 0.85,
     "color_bgr": [80, 166, 0]},
    {"label": "COMMON LINE", "px": [4334, 1164], "conf": 0.92,
     "color_bgr": [239, 173, 0]}
  ]
}
```

| 字段 | 类型 | 含义 |
|---|---|---|
| `_meta.box` | [x,y,w,h] | 说明框 bbox (img 空间, 虚线框定位所得) |
| `entries[].label` | str | OCR 文字标签 (图例名) |
| `entries[].px` | [x,y] | 文字中心 (img 空间, OCR 反查) |
| `entries[].conf` | float | OCR 置信度 |
| `entries[].color_bgr` | [b,g,r] | 该行色彩样本中位色 (OpenCV BGR) |

**生产流程** (legend_extract 工作流, tools/sch-true-finding/readme §9):
1. `note_box_locate.py`: OCR 找锚点文字 → 定位虚线框 → `_meta.box`
2. `legend_extract.py`: 框内反查 OCR 文字 + 按行提色样本, 文字↔色带按 y 对齐
3. 色彩样本 = 准确线条颜色 → 校准 COLOR_SPEC 阈值 (readme §8)

**不同机型**: 锚点文字可能不同 (Explanatory/LEGEND/注...), 但结构类似;
工作流不变, 只需在 OCR 数据库里识别说明框标题类文字作锚点.

---

### 3.8 去标注图 deannot_*.png + 走线网表 wirenet.json + 彩线掩膜 (sch 中间产物)

**数据来源** (数据从哪来、怎么来的):
- `deannot_*.png`: 原理图 (`render/rxtx-sch-*.png`) 上去除信号流标注线后的
  纯净底图. 方法见 de_annotate_* (lumfrac/chandiff/chmask/wirelum), 数据本质是
  "标注从未存在的原理图".
- `wirenet.json`: 去标注图上暗像素连通域 = 走线 net 网表 (无监督, 不依赖其他).
  数据本质是"每个连通域 = 一个走线网络".
- `*_mask.png` (彩线/绿线掩膜): 原理图上彩线 (绿=RX/红=TX/青=common) 颜色阈值
  掩膜 (0/255), 数据本质是"信号流标注线的像素集合" (真理源, 可信度 95).

**用途** (consumers):
- `deannot_*.png` → `sch_wirenet` (走线 net 识别), 原理图纯净底图备查
- `wirenet.json` → 主 net 掩膜 (真理源, 可信度 85), 元器件→net 关联, 电容判据
  (真电容两侧 net 不同), de-wire 切除走线
- 彩线掩膜 → 走线引导 / 符号识别 (绿线触点弱约束) / 冲突排除 / 渲染

**数据位置**: `projects/<机型>/annot/deannot_*.png` (图) / `nettable/wirenet.json` (网表)

```json
// wirenet.json
{"_meta": {"purpose": "sch 走线 net 网表 (无监督连通域)", "format": "json {nets[]}", ...},
 "total_nets": 5963, "total_dark_px": 1188795,
 "main_net": {"id": 13, "area": 903588, "ratio": 0.76, "is_main": true},
 "nets": [{"id": 13, "area": 903588, "bbox": [x,y,w,h]}]}
```

---

### 3.9 标注区域 annot_regions.json (annotation_detect)

**数据来源** (数据从哪来、怎么来的): 原理图 (`render/rxtx-sch-*.png`) 上
**彩色标注像素** (BGR 通道差 > 阈值) 的连通域 → 每个区域 bbox + 主色 (中位 BGR).
数据本质是"图上标注线条的矩形区域".

**用途** (consumers): ROI 局部化 (de-annotation 只在这些区域 ±scale 内处理,
避免全局参数顾此失彼); 区域染纯色 (识别→分段矩形→填充); 标注区域数据库.

**数据位置**: `projects/<机型>/nettable/annot_regions.json` + `annot_regions_mask.png`

```json
{"_meta": {"purpose": "annotation region detect", ...},
 "count": 375,
 "regions": [{"id": 1, "bbox": [x,y,w,h], "area": 139, "color_bgr": [b,g,r]}]}
```

---

### 3.10 OCR 运行数据库 ocr_runs/*.json

**数据来源** (数据从哪来、怎么来的): 对某张图跑 OCR 的一次运行归档
(RapidOCR PP-OCRv4/v5/v6, 参数/引擎/输入图快照). 每字含 `text/conf/px/box`.
数据本质是"图上文字识别结果 + 运行参数溯源".

**用途** (consumers): 文字→位置反查 (如图例锚点 `note_box_locate`)、
refdes 定位 (`pcb_index`)、调参对比 (`compare_runs.py`)、真理源 (text_box 排除).

**数据位置**: `projects/<机型>/ocr_runs/` (只增不删, 严禁 annot/crops/svg_runs 子目录)

```json
{"run_id": "...", "tool_version": "0.2.0", "date": "...",
 "params": {"img": "...", "img_dpi": 300, "preset": "fast", ...},
 "engines": {"stage1": {"v4": "..."}, "stage2": {...}},
 "hits": [{"text": "...", "conf": 0.96, "px": [x,y], "box": [[...]]}]}
```

---

## 4. wpts_*.json 元数据规范

### 4.1 顶层 (每个 wpts 文件首个条目)

**数据来源** (数据从哪来、怎么来的): waypoint = **sch 链序** (chain_order:
原理图信号流经元器件) 与 **pcb 位置** (pcb_index: PCB 丝印坐标) 的结合:
make_config 把 chain 每个器件映射到 pcb 坐标 → 路由算法 (signal_flow_route)
计算拐点/避让/跨面方式 → 得每个连接段的 `px/through` 等. `source` 字段记录
组成来源 (chain + index). 程序只是实现载体, 数据本质是"信号流在 PCB 上的
标注路径".

**用途**: **渲染的唯一输入** —— `svg_render.py` 读 wpts 渲染标注图 (PNG/SVG).
所有坐标统一 600dpi top view 空间, 实线=确认/虚线=推断.

```json
{
  "description": "<标注描述>",
  "source": "chain_order_*.json + pcb_index.json",
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
| pcb_index.json | 元器件索引枢纽 |
| chain_order_rx.json | RX 链序 |
| wpts_rx_top_v1.json | RX top 标注 |

## §2 目录结构

```
nettable/
├── pcb_index.json   # 索引
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
| 0.1 | 2026-09-15 | 初版: 五要素总览 + pcb_index/chain_order/wpts 三类核心字段规范 |
