
# architecture — 设计思路与原则

本文件沉淀项目的架构决策与工作思路(为什么这么设计)。

---

## 0. 目录规范与职责

```
radio-service-note/
├── agent.md                    # 操作规则
├── architecture.md             # 本文档(架构决策)
├── best_practices.md           # 实证配方/参数调优记录
├── TODO.md                     # 后续路线
├── schema.md                   # 全局 JSON 字段规范
├── tools/                      # 核心工具代码
│   ├── rectangle_locator/      # 矩形轮廓检测 + 裁切
│   ├── circle_locator/         # 圆形轮廓检测 + 裁切
│   ├── ic_ocr_scan/            # 多角度 OCR (CPU/DML)
│   ├── ai_ocr_eval/            # AI OCR 评估工具
│   ├── render_rx_flow.py       # RX 流程渲染
│   └── annotate_svg_flow/      # SVG 分层标注
├── projects/
│   └── <机型>/                 # 例如 icom2200h
│       ├── components_index.json   # 元器件索引(枢纽)
│       ├── radio-design.md         # 工程特定设计文档
│       ├── nettable/               # 结构化数据库
│       │   └── wpts_*.json         # waypoints
│       ├── render/                 # PCB 渲染源图(只读)
│       │   ├── pcb-top-600-1.png
│       │   └── pcb-bot-600-1.png
│       ├── crops/                  # 裁切图 + 索引
│       │   ├── rectangle/          # 矩形裁切 + crops_index.json
│       │   ├── circle/             # 圆形裁切 + crops_index.json
│       │   └── board_tiles/        # 全板网格切片
│       ├── annot/                  # 最终标注(仅 SVG + PNG)
│       ├── svg_runs/               # 渲染中间归档
│       └── ocr_runs/               # OCR 运行归档
```

### 目录职责分工

| 目录 | 方向 | 内容 | 负责工具 |
|------|------|------|----------|
| `render/` | 只读输入 | pdftoppm 输出的 PCB 光栅图 | pdf→png |
| `crops/rectangle/` | 中间产物 | 矩形裁切 + 索引 | `rectangle_locator.py` |
| `crops/circle/` | 中间产物 | 圆形裁切 + 索引 | `circle_locator.py` |
| `annot/` | 最终输出 | **仅** SVG + PNG 标注图 | `annotate_svg_flow` |
| `nettable/` | 结构化数据库 | waypoints/链序/锚点 JSON | OCR → 索引 |
| `ocr_runs/` | 只读归档 | OCR 运行 JSON 归档 | `ai_refdes_ocr.py` |

### 清理规则

- `annot/` 仅放最终 `*.svg` `*.png`
- `crops/` 仅存裁切图 + 索引 JSON
- `nettable/` 仅存结构化 JSON
- `ocr_runs/` 仅 OCR 归档
- 根目录不留散落文件

---

## 1. 数据流总架构

```
维修手册 PDF ──pdftoppm 600dpi──> render/(光栅底图)
                │
                ▼
rectangle_locator.py ──> crops/rectangle/*.png + crops_index.json
circle_locator.py    ──> crops/circle/*.png + crops_index.json
                │
                ▼
ic_ocr_scan_dml.py (Windows DirectML GPU)
                │
                ▼
nettable/components_index.json   ← 枢纽: 元器件索引
(ref-des → 类型/名称/各视图坐标/来源/状态)
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
wpts_*.json  chain_order  radio-design.md
    │
    ▼
SVG 分层标注 ──> annot/*.svg + .png
```

核心思想: **元器件索引是跨图映射的枢纽**。原理图读出的信号流
(哪个元件连哪个元件)只有通过"元器件索引"才能落到 PCB 的准确像素位置。

**索引即飞轮**: 任何工具只要能建立"器件→坐标"的识别, 就是净进展。

---

## 2. 坐标系核心假设 + 数据溯源规范

### 2a. 正背面配合: 坐标不跨视图共享

**核心**: 原理图/PCB top/PCB bot 是三张不同图, 各有独立像素坐标系。
同一 refdes 的 px 值在不同视图**不可直接互用**, 但**可以跨视图发现+回填**。

**正确流程**:
1. **每个 refdes 必须标注 view**: `view = "top"|"bot"|"sch"`
2. **同一 refdes 跨视图** 必须在每个 view 各有独立坐标
3. **丝印只在一面的器件**: 哪个 view 的 OCR 找到, 坐标就属于哪个 view
4. **不能跨 view 共享坐标**: 同一物理点在不同图像中像素坐标不同

**components_index 强约束**:
```json
{
  "F13": {
    "view": "bot",
    "center": [2260, 100],
    "src": "ocr_scan_dml"
  }
}
```

### 2b. 三层坐标空间

```
PCB 母图 (render/pcb-top-600-1.png, 5100×6600 @ 600dpi)
  │
  ├── crops/rectangle/*.png    ← 裁切图 (本地坐标 [0,0]~[w,h])
  │     crop_bbox_with_pad: [cx0, cy0, cx1, cy1] ← 在母图中的位置
  │
  ├── crops/rectangle/crops_index.json  ← 矩形索引 (bbox 在母图坐标)
  │
  └── nettable/components_index.json  ← 元器件索引 (center/box 在母图坐标)
```

**坐标转换公式**:
```
pcb_x = crop_local_x + cx0
pcb_y = crop_local_y + cy0
```

### 2c. dpi 比例映射: 禁止坐标直接相加

**核心规则**: 不同 DPI 空间的坐标之间**只能做比例映射**, **不能直接相加**。

**正确做法**:
1. OCR 用 tile 实际 DPI (推荐): `--img-dpi 600` → 输出 600dpi 空间
2. OCR 保持低 DPI 时按比例映射: `box_600 = box_200 × (600/200)`

### 2d. 数据溯源

任何识别结果必须包含溯源字段, 没有溯源的坐标视为不可信。

---

## 3. 首选元器件标号识别方法: 矩形 + 圆形 + DirectML OCR

### 3.1 方法定义

**首选方法**: 矩形/圆形裁切 + 多角度 OCR + DirectML GPU 加速。

**流程**:
```
PCB 母图
  │
  ├── rectangle_locator.py (OpenCV 轮廓检测 + 分类)
  │     → crops/rectangle/*.png + crops_index.json
  │
  ├── circle_locator.py (HoughCircles + 轮廓圆度)
  │     → crops/circle/*.png + crops_index.json
  │
  ▼
ic_ocr_scan_dml.py (Windows DirectML GPU, 多角度 OCR)
  │ → 读 crops_index.json
  │ → 对每个裁切: 旋转 0°/90°/270° → OCR → 取最高分 refdes
  │ → 坐标转换: crop_local + bbox_offset = 母图坐标
  │ → 写 nettable/components_index.json
  │
  ▼
components_index.json (合并矩形+圆形结果)
```

### 3.2 实测结果 (IC-2200H)

| 检测类型 | 裁切数 | OCR 识别 | 新增 refdes | 累计 |
|---|---|---|---|---|
| 矩形 (Top) | 206 | 191 (93%) | 229 | 229 |
| 矩形 (Bot) | 195 | - | 299 | 502 |
| 圆形 (Top, min-d=120) | 833 | 331 | 87 (新) | **589** |

**Refdes 前缀分布**: C:135, R:80, L:39, Q:19, D:20, IC:8, EP:5, FI:4

### 3.3 矩形检测参数

**rectangle_locator.py**:
- `--min-area 200` — 最小矩形面积
- `--max-area 500000` — 最大矩形面积
- `--aspect-ratio 0.2-5.0` — 长宽比范围

**分类规则**: 按面积/长宽比自动分类为 ic/resistor/capacitor/inductor/...

### 3.4 圆形检测参数

**circle_locator.py**:
- `--min-diameter 120` — 过滤小 pad 噪声
- `--max-diameter 200` — 过滤板框
- `--circularity-min 0.7` — 过滤不规则形状

**注意**: 圆形检测大部分是 pad 噪声, 仅补充矩形未覆盖的元件。

### 3.5 DirectML GPU 加速

- **WSL Linux Python 无法调用 DirectML** (ONNX Runtime DML EP 仅 Windows 原生)
- **必须用 Windows 原生 Python** (`C:\Users\radio\ocr_gpu_venv\Scripts\python.exe`)
- 通过 `dml_helper.py` monkey-patch ProviderConfig 强制 DmlExecutionProvider
- 验证: PowerShell `Get-Counter '\GPU Engine(*)\Utilization Percentage'`
- 实测: AMD RX 590 GME 上 28x 加速, 200 矩形 ~2min

### 3.6 crops_index 与 components_index 的关系

| 字段 | crops_index | components_index |
|---|---|---|
| bbox/center | ✓ (母图坐标) | ✓ (母图坐标) |
| category | ✓ (ic/resistor/...) | ✗ (用 refdes 前缀推断) |
| status | ✓ (unverified/ocr_found) | ✗ |
| refdes | ✓ (OCR 找到的位号) | ✓ (key) |
| role/flow_note | ✗ | ✓ (功能描述) |

**规则**: crops_index 是中间产物, components_index 是最终产物。

### 3.7 替代方案对比 (参考)

| 方法 | 识别率 | 速度 | 适用场景 |
|---|---|---|---|
| **矩形+圆形+DML OCR (首选)** | 93% | ~2min | 全板扫描 |
| 全页网格 tile OCR | 30-50% | 10-30s | 快速粗扫 |
| 全板密集 tile OCR | 60-70% | 5-15min | 补漏, 假阳性高 |
| 人工标注 | 100% | 数小时 | 最终确认 |

---

## 4. 标注架构: svg 分层

### 4.1 核心原则

- **底图自包含**: base64 内嵌, 单文件拷走不失底
- **语义分层**: rx / tx / ctrl-power / blocks / marks / notes 每类一层
- **诚实标注**: 实线=确认, 虚线=推断, "not located"不得臆造
- **渲染即派生**: SVG 由 waypoints JSON 生成

### 4.2 连线布线规范

- **横平竖直**: 优先水平/垂直走向, 拐点用 `through` 字段
- **避免自交叉**: 不同信号路径不得相交
- **连接器标注**: 焊盘环+孔符号, 小字标注连接目标

### 4.3 视觉编码规则

- **实线绿**: 本面确认走线
- **虚线绿**: 背面走线
- **黄色高亮区**: 未确认路径
- **箭头**: 每段连线终点必须有箭头

---

## 5. 工具设计五原则

1. **工具是工具, 参数是参数**: 一切阈值走 CLI, 不留魔法常数
2. **多引擎协同**: 按阶段/场景分工, 同位双引擎一致才算预确认
3. **每次运行都归档**: 含 tool_version/日期/参数快照, 可比较可校准
4. **快速模式→逐步细化**: 先 `--preset fast` 出初稿, 再针对性细化
5. **中间结果是资产**: JSON 是"源", 渲染只是派生视图

---

## 6. 防幻觉三道闸

1. **AI 双引擎同位一致**: v4+v6 同文本同坐标才算预确认
2. **坐标空间校验**: 命中必须落在图内且与空间先验相容
3. **视觉签收兜底**: 高倍 crop 拼图签人工过一遍

---

## 7. 坐标校验规则

- **坐标必须在板框内**: 超出合理范围必须回溯验证
- **IC/晶体管定位优先级**: pin-silk > body > contour
- **多位置元件**: 链序路径启发式选点(总曼哈顿距离最小)
- **单一坐标系**: 所有 px 统一 300dpi 渲染空间, 600dpi 必须换算
- **每个坐标必有来源**: 无来源的"confirmed"视同存疑
- **状态三态**: confirmed / inferred / not_located

---

## 8. 元器件标号识别与标注要求

### 8.1 元器件标号识别

**首选**: 矩形+圆形裁切+DirectML OCR (§3)

**旧管线** (参考): `ai_refdes_ocr.py` (RapidOCR PP-OCRv4/v5/v6)
- 工作流: `--preset fast` → `--reuse-stage1` → 针对性细化
- 运行 JSON 归档于 ocr_runs/

### 8.2 标注流程

- 信号流跨图标注一律经元器件索引 `components_index.json`
- 生成 waypoints 用 `make_wpts_from_index.py`, 不手写坐标
- 分层 SVG, 实线=确认/虚线=推断/not-located 不臆造

### 8.3 渲染规范

- 渲染一律用 `pdftoppm -r 600`(识别)/300(标注)
- 600dpi 坐标 ÷2 入网表 (300dpi 统一空间)

---

## 9. 知识/设计文档分层

| 文档 | 位置 | 内容 |
|---|---|---|
| **radio-knowledge.md** | 仓库根 | 通用无线电知识 |
| **radio-design.md** | `projects/<机型>/` | 工程特定设计: RX/TX/Control/Power 链路 |

**规则**: 通用的放通用, 工程特定的进 radio-design.md。

---

## 10. 文件元数据强制规则

每个新建文件头部必须包含:
- **功能 (purpose)**
- **格式 (format)**
- **版本 (version)**
- **用途 (consumers)**

---

## 11. schema.md 作为数据使用规范

任何结构化 JSON 必须配套 schema.md, 写清五要素: 文件、目录、元数据格式、用法、目的。

溯源原则: 每个坐标必须能 backtrace 到原始 PDF。

---

## 12. 经验教训

### 12.1 坐标系踩坑

**v10/v11 错位根因**: F13/F14 的 v8 坐标是从 top view OCR 找到的, 但 F13/F14 实际只在 bot view 有丝印。教训: **坐标必须标注 view, 不能跨 view 共享**。

**v9 渲染严重错位**: board_tiles 是 600dpi 切的, 但 OCR 用了 `--img-dpi 200`, 坐标直接相加导致偏移 3 倍。教训: **不同 DPI 空间只能比例映射, 不能直接相加**。

### 12.2 OCR 识别踩坑

**v6 幻觉问题**: PP-OCRv6 small/mobile 容易产生假位号 (IC169/IR78)。教训: **默认用 v4 server, v6 仅作交叉验证**。

**全页 OCR 无效**: 600dpi 全页扫仅 1-5 个命中, 丝印字太小。教训: **必须按 200px tile 切块才出效果**。

### 13.3 圆形检测踩坑

**pad 噪声**: 圆形检测 1791 个中大部分是铜 pad 圆角。教训: **min-diameter 需要 120+ 才能过滤小 pad, 但仍有大量噪声**。

**IC 被间接发现**: IC 附近有圆形 pad, OCR 在圆形裁切中读到了 IC 丝印。教训: **圆形检测是补充手段, 不是独立方法**。

### 13.4 工具协作踩坑

**WSL→Windows 路径**: WSL 的 `/mnt/c/` UNC 路径 Windows Python 无法访问。教训: **必须把文件 cp 到 Windows 原生路径, 用 `cd /d` 启动**。

**DirectML 假阳性**: WSL 中 `use_dml=True` 不报错但 GPU 负载为 0。教训: **必须用 Windows 原生 Python 运行 DML**。
