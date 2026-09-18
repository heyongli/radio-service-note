
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
│   ├── pcb_rect_locator/      # 矩形轮廓检测 + 裁切
│   ├── pcb_circle_locator/         # 圆形轮廓检测 + 裁切
│   ├── ic_ocr_scan/            # 多角度 OCR (CPU/DML)
│   ├── pcb_package/      # IC 封装定位
│   ├── svg-render/             # 信号流标注渲染 (PNG+SVG)
│   ├── signal_flow_route/      # 信号流自动路由
│   ├── pcb_components/       # 元器件索引构建
│   ├── pcb_verify/          # 坐标锚点验证
│   └── ref/                    # 参考/旧管线 (ai_ocr_eval, annotate_svg_flow 等)
├── projects/
│   └── <机型>/                 # 例如 icom2200h
│       ├── pcb_components.json   # 元器件索引(枢纽)
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
| `crops/rectangle/` | 中间产物 | 矩形裁切 + 索引 | `pcb_rect_locator.py` |
| `crops/circle/` | 中间产物 | 圆形裁切 + 索引 | `pcb_circle_locator.py` |
| `annot/` | 最终输出 | **仅** SVG + PNG 标注图 | `svg_render.py` |
| `nettable/` | 结构化数据库 | waypoints/链序/锚点 JSON | OCR → 索引 |
| `ocr_runs/` | 只读归档 | OCR 运行 JSON 归档 | `tools/zref/ai_ocr_eval/ai_refdes_ocr.py` |

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
pcb_rect_locator.py ──> crops/rectangle/*.png + crops_index.json
pcb_circle_locator.py    ──> crops/circle/*.png + crops_index.json
                │
                ▼
ic_ocr_scan_dml.py (Windows DirectML GPU)
                │
                ▼
nettable/pcb_components.json   ← 枢纽: 元器件索引
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

**pcb_components 强约束**:
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
  └── nettable/pcb_components.json  ← 元器件索引 (center/box 在母图坐标)
```

**坐标转换公式**:
```
pcb_x = crop_local_x + cx0
pcb_y = crop_local_y + cy0
```

**旋转修正 (必读)**: 若 OCR 前 crop 被旋转 (rot=90/270), OCR box 坐标在旋转后
坐标系, 必须**先逆旋转**再加 crop 原点:
```
rot=90:  ox = ry,        oy = Hc - 1 - rx     (Hc = 原始 crop 高度)
rot=270: ox = Wc - 1 - ry, oy = rx            (Wc = 原始 crop 宽度)
```
未逆旋转会导致坐标系统性偏移 (曾影响 345 处, 见 §13.1)。

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
  ├── pcb_rect_locator.py (OpenCV 轮廓检测 + 分类)
  │     → crops/rectangle/*.png + crops_index.json
  │
  ├── pcb_circle_locator.py (HoughCircles + 轮廓圆度)
  │     → crops/circle/*.png + crops_index.json
  │
  ▼
ic_ocr_scan_dml.py (Windows DirectML GPU, 多角度 OCR)
  │ → 读 crops_index.json
  │ → 对每个裁切: 旋转 0°/90°/270° → OCR → 取最高分 refdes
  │ → 坐标转换: crop_local + bbox_offset = 母图坐标
  │ → 写 nettable/pcb_components.json
  │
  ▼
pcb_components.json (合并矩形+圆形结果)
```

### 3.2 实测结果 (IC-2200H)

| 检测类型 | 裁切数 | OCR 识别 | 新增 refdes | 累计 |
|---|---|---|---|---|
| 矩形 (Top) | 206 | 191 (93%) | 229 | 229 |
| 矩形 (Bot) | 195 | - | 299 | 502 |
| 圆形 (Top, min-d=120) | 833 | 331 | 87 (新) | **589** |

**Refdes 前缀分布**: C:135, R:80, L:39, Q:19, D:20, IC:8, EP:5, FI:4

### 3.3 矩形检测参数

**pcb_rect_locator.py**:
- `--min-area 200` — 最小矩形面积
- `--max-area 500000` — 最大矩形面积
- `--aspect-ratio 0.2-5.0` — 长宽比范围

**分类规则**: 按面积/长宽比自动分类为 ic/resistor/capacitor/inductor/...

### 3.4 圆形检测参数

**pcb_circle_locator.py**:
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

### 3.6 crops_index 与 pcb_components 的关系

| 字段 | crops_index | pcb_components |
|---|---|---|
| bbox/center | ✓ (母图坐标) | ✓ (母图坐标) |
| category | ✓ (ic/resistor/...) | ✗ (用 refdes 前缀推断) |
| status | ✓ (unverified/ocr_found) | ✗ |
| refdes | ✓ (OCR 找到的位号) | ✓ (key) |
| role/flow_note | ✗ | ✓ (功能描述) |

**规则**: crops_index 是中间产物, pcb_components 是最终产物。

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
- **红色实心圆点+黑心**: top view 元器件
- **紫色空心圆+十字**: bot view 元器件 (过孔图标), 标签用紫色
- **箭头**: 每段连线终点必须有箭头

### 4.4 信号流标注规范

**bot 组件标注**:
- bot view 组件在 top view 上用 **过孔图标** (空心圆+十字) 标注
- wpts 中设置 `"inferred": true` 即可触发过孔样式
- 坐标需从 bot 镜像到 top: `top_x = board_center_x + (board_center_x - bot_x)`
- 连线用 **虚线** 表示背面走线

**连线规范**:
- **横平竖直**: 所有连线尽量水平或垂直, 拐点用 `through` 字段
- **避免交叉**: 不同信号路径尽量不相交
- **走线优先级**: 先垂直再水平 (或反过来), 选择不交叉的路径
- **折返垂直段**: 向左再向右 (或反之) 必须先走一段垂直线, 避免水平线重叠
- **箭头**: 每段连线终点必须有箭头，跟随信号流方向
- **同面 vs 跨面**: 同面连线用实线; 跨面连线用虚线 + 过孔图标 (圆+十字)

**标记规范**:
- **同面** (如 top→top): 无圆点, 无过孔, 实线
- **到达另一面** 放一个小红圈中空，意思是这是个过孔（via），如 bot→top
- 标签位置: 用 `lpos` 控制, 避免与连线重叠

**输出要求**:
- PNG: 600dpi, 仅标注 RX/TX 信号流程
- SVG: 分层可编辑, base64 内嵌底图
- waypoints JSON: 所有坐标的唯一来源, 渲染只读取此文件

---

## 5. 工具设计五原则

1. **工具是工具, 参数是参数**: 一切阈值走 CLI, 不留魔法常数
2. **多引擎协同**: 按阶段/场景分工, 同位双引擎一致才算预确认
3. **每次运行都归档**: 含 tool_version/日期/参数快照, 可比较可校准
4. **快速模式→逐步细化**: 先 `--preset fast` 出初稿, 再针对性细化
5. **中间结果是资产**: JSON 是"源", 渲染只是派生视图

### 5.6 位置与命名
- 路径: `tools/<tool_name>/` (子目录, 不要平铺在 tools/)
- 命名: 全小写, 下划线分隔 (`poll_ocr`, `convert_dpi`, `batch_ocr`)
- 不放在根目录, 不放在 projects/ 下

### 5.7 文件清单
每个工具子目录必含:
```
tools/<tool_name>/
├── <tool_name>.py       # 主程序 (与目录同名)
├── readme.md            # 使用文档 (五要素: 文件/目录/格式/用法/目的)
└── __init__.py          # (可选) Python 包标识
```

### 5.8 readme.md 五要素
| 节 | 内容 |
|---|---|
| §1 文件清单 | 列目录每个文件 + 一句话用途 |
| §2 目录结构 | (子目录一般简单, 此节可省略) |
| §3 元数据格式 | 参数表 (参数名/类型/默认/说明) + CLI 示例 |
| §4 用法 | 完整 CLI 命令 + 退出条件 + 错误处理 |
| §5 目的 | 这个工具为什么存在, 与其他工具/流程的关系 |

### 5.9 主程序规范
- 全参数 CLI 化 (`argparse`, 不允许硬编码路径/阈值)
- 头部注释必含功能/格式/版本/用途四字段 (§10)
- 跨平台优先 (WSL+Windows 通用, 如 pgrep/tasklist fallback)
- 不假定环境 (检查文件存在, 给出友好错误而非 traceback)

### 5.10 反例
```bash
# ❌ 在 shell 历史里临时写一个 poll 循环
# ❌ 复制 tools/ 里某个工具改一改就叫新工具 (无 readme, 无五要素)
# ❌ 把脚本放在根目录
```

### 5.11 检查清单
- [ ] 路径在 `tools/<tool_name>/`
- [ ] 主程序头部 4 字段 (功能/格式/版本/用途)
- [ ] 所有路径/阈值/间隔 走 CLI 参数
- [ ] readme.md 五要素齐全
- [ ] 文件名/目录名全小写
- [ ] 不在根目录散落

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

**旧管线** (参考, `tools/zref/`): `ai_refdes_ocr.py` (RapidOCR PP-OCRv4/v5/v6)
- 工作流: `--preset fast` → `--reuse-stage1` → 针对性细化
- 运行 JSON 归档于 ocr_runs/

### 8.2 标注流程

- 信号流跨图标注一律经元器件索引 `pcb_components.json`
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

## 13. 全流程工具链

将探索阶段验证过的方法和原则固化为可复用工具, 确保流程一致、可追溯。

**三大工作管线** (各自独立, 职责分离):
```
① sch 管线   : 原理图识别信号流 → chain_order
② pcb 管线   : PCB 定位元器件 → components_index (pcb 位置)
③ 结合管线   : sch flow + pcb 位置 → waypoint → 标注 (sch→PCB)
```

### 13.0 管线总览
| 管线 | 工具链 | 产物 | 职责 |
|---|---|---|---|
| **sch** | `sch_trace` → `sch_label_ocr` → `sch_flow_walk` → `sch_render` | chain_order_rx.json | 从原理图学信号流经元器件 |
| **pcb** | `pcb_rect_locator` → `pcb_circle_locator` → `pcb_label_ocr` → `pcb_components` → `pcb_package` → `pcb_verify` | pcb_components.json | 定位元器件在 PCB 的位置 |
| **结合** | `make_config_from_chain` → `signal_flow_route` → `svg_render` | wpts + annot PNG/SVG | 把 sch flow 标注到 PCB |

- sch/pcb 各自独立发展, 只通过 chain_order / pcb_components 数据库交互
- 结合管线消费两者: chain_order (sch 链序) + pcb_components (pcb 位置) → 标注

### 13.1 OCR 识别
| 工具 | 路径 | 用途 |
|---|---|---|
| `pcb_rect_locator.py` | `tools/pcb_rect_locator/` | 矩形轮廓检测, 定位 refdes 标号 |
| `pcb_circle_locator.py` | `tools/pcb_circle_locator/` | 圆形轮廓检测, 补充识别 |
| `pcb_label_ocr_dml.py` | `tools/pcb_label_ocr/` | 矩形+圆形裁切多角度 OCR (DML GPU) |
| `detect_ic.py` | `tools/pcb_package/` | IC 封装定位: 矩形+圆形裁切+旋转OCR+refdes 匹配 → 本体框 |
| `schematic_flow_walk.py` | `tools/schematic_flow_walk/` | 原理图信号流走线: 彩线掩膜+BFS+符号检测 → chain_order |

**detect_ic.py crop-ocr (IC 本体定位首选)**: 配合 rectangle/pcb_circle_locator 的裁切,
旋转 OCR 读到已知 refdes 的裁切 bbox 即 IC 本体。默认用预计算 DML OCR 结果,
`--local-ocr` 兜底。**本体中心 ≠ 标签文字中心**, 轮廓框必须用本体 bbox。
命中必须**精确裁切验证** (沿 bbox 裁切源图再 OCR, 只有该 refdes 才算真命中),
否则 padding 里的邻近文字会造成假匹配。

**旋转 OCR 坐标转换 (关键, 2026-09-16 修复)**: 任何"先旋转再 OCR"的管线,
OCR box 坐标在**旋转后坐标系**, 必须**逆旋转**回原始 crop 坐标再加 crop 原点,
否则 rot=90/270 坐标系统性偏移:
```
rot=0:   ox = rx,        oy = ry
rot=90:  ox = ry,        oy = Hc - 1 - rx     (Hc = 原始 crop 高度)
rot=270: ox = Wc - 1 - ry, oy = rx            (Wc = 原始 crop 宽度)
```
已固化在 `ic_ocr_scan.py` + `ic_ocr_scan_dml.py` 的 `ocr_crop`。
曾导致 pcb_components 345 处 rot≠0 坐标偏移 (如 IC12 从错误的 (3555,2719)
校正到正确的 (3429,2768))。任何"变换后再识别"的中间结果, box 必须逆变换回源空间。

### 13.2 信号流渲染
| 工具 | 路径 | 用途 |
|---|---|---|
| `signal_flow_route.py` | `tools/signal_flow_route/` | 信号流自动路由, 生成 waypoints |
| `svg_render.py` | `tools/svg-render/` | 渲染 RX/TX 信号流标注图 |

**waypoints (wpts)**: 描述信号流路径的 JSON 文件, 是渲染的唯一输入。每条记录包含起点
 `px`、拐点 `through`、线型 `dash`、标记 `mark_type` 等。所有坐标统一在 600dpi top view 空间。

**signal_flow_route.py 算法** (固化 §4.4 标注规范):
1. **横平竖直**: 所有线段水平或垂直, 候选路径含折返垂直段 (先垂直再水平 / 先水平再垂直 / 经 y 偏移中转)
2. **避免交叉**: 评分 `crossings × 10 + proximity × 8 + label_hits × 5`, 逐条路由, 后续路径避开已有路径
3. **折返垂直段**: 生成带 y 偏移 (±100/±200/±400) 的候选路径, 自动插入垂直段
4. **平行线间距**: proximity 检测与已布线路径平行且间距 < 40px 的重叠, 避免水平/垂直线视觉重叠
5. **标签避让**: 按 `lpos` 定义 keep-out 矩形, 路径不穿过标号文字区域
6. **bot 镜像**: config 坐标已统一为 top-view 空间 (bot 组件创建时镜像), 算法不再变换; `view` 字段仅用于虚线/via 判定
7. **同面/跨面**: 两端 view 相同 (top→top / bot→bot) 输出实线; view 不同 (top↔bot) 输出虚线
8. **via 标记**: 跨面连接的到达端标红色空心圆 (过孔), wpts 中 `mark_type: "via"`
9. **IC 轮廓**: flow 设计 IC (`outline: true`) 标轮廓矩形; 同面红色实线, 另一面紫色虚线

**svg_render.py** (固化渲染规则):
- 实线/虚线: 虚线用 semi-transparent 绘制, 避免遮挡 PCB 底图
- via 标记: 红色空心圆 (width=12, r=18)
- 箭头: 每段连线终点, 跟随信号流方向

**输入**: JSON config (components 坐标/view/lpos + connections 列表)
**输出**: wpts JSON, 与 `svg_render.py` 兼容

### 13.3 原理图侧信号流识别 (sch workflow, 分层如 PCB)

**分层管线** (各程序独立发展, 经 `sch_components.json` 数据库交互, schema §3.5):
```
sch_trace(沿绿线走线+符号) → sch_label_ocr(读标号) → sch_flow_walk(绿线流鉴别)
   → sch_symbol(符号本体识别) → sch_symbol_selfcheck(自我监督校验)
   → sch_render(渲染)     → chain_order (有序链)
```

| 工具 | 路径 | 职责 |
|---|---|---|
| `sch_trace.py` | `tools/sch_trace/` | 沿绿线 BFS 走线, 局部探测符号 (电容/三极管/IC), 只识别绿线上的 |
| `sch_label_ocr.py` | `tools/sch_label_ocr/` | 读绿线符号旁的标号 (OCR 关联) |
| `sch_flow_walk.py` | `tools/sch_verify/` | 绿线流鉴别: membership (flow_through 主路/branch 支路/none) |
| `sch_symbol/` | `tools/sch_symbol/` | **符号本体识别** (识别层): 按类型识别本体 (对应 pcb_package) |
| `sch_symbol_selfcheck/` | `tools/sch_symbol_selfcheck/` | **自我监督校验** (校验层): 边界/反向OCR/重叠 + 尺寸知识累积 (对应 pcb_verify) |
| `sch_render.py` | `tools/sch_render/` | 渲染识别+鉴别结果到原理图 |
| `sch-true-finding/` | `tools/sch-true-finding/` | **走线识别**: 黑走线骨架+连接圆点 (引出线对齐走线) |

**sch_wire (走线识别, 独立发展)**: 纯黑图层 (去绿线) → 走线骨架 (Zhang-Suen 细化)
→ 端点/交叉点 (度 1/度 3+), 连接圆点 (小黑圆 = 交叉/连接).
元件引出线应**对齐走线** (黑线); 连接点决定走线交叉. 无监督方法提高准确度.

**数据库交互** (`sch_components.json`, schema §3.5): 每层读/写同一库,
识别输出 symbols → label_ocr 填 refdes → flow_walk 填 membership → render 消费。

**鉴别判定 (ICOM/Yaesu 域特征)**: 主路 = 符号两侧沿流向共线有绿 (E+W 或 N+S);
支路 = 单侧绿; 非流经 = 不触点绿线。

**产物**: `chain_order_rx.json` (flow_through 有序链), 供 make_config_from_chain →
PCB 标注全自动闭环。

---

## 14. 无监督进化方法 (自我学习+自我校验, 2026-09-17 沉淀)

**核心**: 无需人工标注, 识别→校验→积累知识→反哺识别, 逐步进化变准。

### 14.1 自我校验手段 (识别后自证)
| 方法 | 原理 | 判定 |
|---|---|---|
| **反向 OCR** | 在符号中心 OCR, 验证读出 refdes 与关联一致 | 一致=OK, 否则关联错误 |
| **label 方框定位** | OCR 预计算文字框, 红点不得落在框内 | on_label = 错误 |
| **符号边界包含** | 三极管圆/IC 方块须包围红点 (黑边轮廓/Hough) | 不包含 = 错误 |
| **符号重叠检测** | 电路图符号不能重叠 | 重叠 = 误关联, 触发去重 |
| **refdes 去重** | 同一 refdes 只能一个符号 (符号不重叠) | 保留验证 OK 的 |
| **终端定位** | 2 端器件 (C/R/L) 黑线断口=端点, 中心=断口中点 | 位置自证 |
| **走线↔符号互验** | 走线必终结于符号, 符号必有走线 (双向约束) | 走线端点应落符号/连接点 |
| **合成掩膜探索** | 学习掩膜 (典型尺寸合成) 与图中元素对齐匹配 | 高分对齐处 = 真实符号 (强无监督验证) |
| **连通性自监督** | 处理后目标的连通性应与"应然"一致 (去标注后走线应变连续, 而非更碎) | 连通域数越少越接近正确; 变碎=误删 (2026-09-17: de-annotation 验证) |

### 14.1f 自监督方法选取 (agent 操作规则, 2026-09-17)

**核心**: 调参/算法选择前, 先想**该操作对应的自监督指标** —— 每个处理
步骤都有一个"处理后应然状态", 用它来验证效果, 无需人工。

| 操作 | 应然状态 (自监督指标) | 异常判定 |
|---|---|---|
| de-annotation 去标注 | 走线连通性**不恶化** (标注在走线下, 不该影响走线) | 连通域数暴增 = 误删走线 |
| wire 线宽离散化 | 细颈断口消除, 主 net 保持单一连通 | 腐蚀后域数大 = 未修复 |
| 电容候选筛选 | 真电容两侧 net 不同 (桥) | 两侧同 net = 假候选 |
| 符号识别 | 符号必在走线上 / 不落 label 框 | 违背 = 误识别 |
| **de-annotation 去标注** | 输出残留粗线宽 **≈ 走线宽**, 远小于标注线宽 | 输出粗线宽≈标注宽 = 标注残留 (2026-09-17 实测: 残留半宽6-9段 63154px vs 标注3754px, 判定有残留) |
| de-annotation 走线保持 | 去标注后主 net 100% 保留, 连通性不恶化 | 主net丢失/变碎 = 误删走线 |

> **de-annotation 自监督指标详细定标** (局部连通性/被去除区域连通性/分通道精度/
> wire 连通域签名 + 实测基线) 见 **`tools/sch-true-finding/readme.md` §7** ——
> 指标是指导**具体工具**开发的, 放工具目录 readme, 不放架构文档。

**操作方法**: 每次改算法/参数, 先定义应然指标 → 跑前后对比 → 指标验证。
这是"识别→校验→进化"闭环的自动版本 (architecture §14.3), agent 应主动
寻找合适的自监督指标, 而非依赖人工看图。

### 14.1b 高可靠证据源 (truth sources, 排错关键, 2026-09-17)

自我监督排错依赖**高可靠证据源** —— OCR/掩膜本身可能错, 但以下两类
经实测**识别很准**, 可作反向证据 (negative/positive 约束):

| 真理源 | 可靠性 | 用途 (排错) |
|---|---|---|
| **OCR 标号文字框 (text_box)** | OCR 质量高, 文字框定位准确 (504/537 有框) | **反向排除**: 符号候选落在文字框内 = 那是标号不是符号, 拒. 实测 26 个 flow_through 电容 symbol_pos 落在自身 label 框内 (sch_trace 误把标号当符号), 靠此修正 |
| **信号流彩线掩膜 (绿线)** | 绿线是 RX 主路权威标注 (best_practices §4), 掩膜识别准 | 正/反向: 真符号应在绿线路径附近 (电容板线垂直穿过绿线); 远离绿线的候选多为主路外干扰 |

**用法**:
- `text_box` → 负例排除: `_in_box(cx,cy,text_box)` 为真则拒候选
- 绿线 → 正例约束: 候选中心需触点绿线 (flow_through 器件必然在绿线上)
- 两者都是**无监督真理源**: 来自 OCR/彩线掩膜, 不依赖人工标注

> 注意: 绿线触点**不能单独作为充分条件** (绿线覆盖面积大, 假候选也触点);
> 应作排序加权/弱约束, text_box 排除作强约束 (直接拒)。

### 14.1c 真理元素积累与复用 (truth bank, 2026-09-17)

**走线主网络 = 最强真理源 (2026-09-17 实测)**:
- 走线是最**连续、最简单**的元素 (完整图形), 识别最容易, **不依赖任何其他**
  (绿线是叠印其上的标注, 非遮挡)
- 实测: 暗像素连通域中**最大域 = 903588 px (76% 暗像素)**, 单一连通域,
  沿走线跑即可找到这个 net
- **94% 的绿线落在主 net 内** → 确认绿线标注的正是主走线网络
- 用途:
  1. **真理源**: 主 net 掩膜可存 (如 `wire_main_net.png`), 供符号识别对齐走线
  2. **de-wire**: 可从 sch 切除所有走线 (走线也是可去除的已知层)
- 与绿线关系: 绿线(标注) ⊂ 主net(走线) ⊂ 暗像素。绿线帮确认走线身份,
  走线 net 帮确认符号位置 (符号必在走线上, best_practices §5b-3)

**标注↔wire 相互提高子管线 (two-pass, 2026-09-17 沉淀)**:
```
┌─ 阶段1: 基础 wire 识别 (无依赖)
│   sch_wirenet: 暗像素连通域 = net → 主 net / 断片
│   产出: wirenet.json (nets/主net掩膜) — 高置信真理源 (85)
│
├─ 阶段2: 用 wire net 辅助识别标注 (标注↔wire 互证)
│   标注 = wire net 上的高饱和彩色像素 (色相+饱和度+wire约束)
│   → de-annotation (de_annotate.py): 去除标注, 标注下走线填走线色恢复
│   产出: 去标注图 sch_no_annot.png
│
└─ 阶段3: 高级 wire 识别 (去标注后, 无污染)
    在无标注图上做连通域/骨架/线宽离散化
    → 更纯净的 net 网表 → 反哺阶段2 (更准标注) → 循环进化
```
- **互证机制**: 标注必在 wire 上 (wire 高置信约束, 防误删走线); 标注去除后
  wire 更纯净 (无颜色污染/断裂) → **相互支持, 逐轮提高精度**
- **子管线独立性 (关键)**: 每个阶段/辅助真理源**参数化、可独立运行**:
  - sch_wirenet 单跑 → 粗 net (阶段1)
  - de_annotate 单跑 --color all → 去标注 (阶段2, 不需 wire)
  - 组合跑 → 三阶段闭环, 精度逐步提升
  - 单步可验证 (每阶段对照 GT/可视化), 组合可进化 (§14.3 进化闭环)
- **标注↔wire 具体特征** (de_annotate 实测):
  - 标注高饱和 (s>80), 走线低饱和 (s≤80) → --s-min 过滤防误删
  - 标注 96-100% 盖在走线上 → 去标注需填走线色恢复, 非置白
  - 红 = 橙红(0-25°) + 品红(150-170°); 绿 = 55-90°; 黄 = 12-26°

**核心原则**: 任何**已确认的事实** (高可靠证据) 都是**真理元素** (truth element)。
真理元素**不断积累** (每轮确认新事实 → 入库), 并且**可被到处复用**
来提高识别率 —— 不管哪条管线、哪个工具, 只要遇到同类判断, 都可以引用。

**工作原理** (truth bank 的运行机制):

```
生产端 (识别管线, 每轮):
  OCR/彩线/走线/自监督 → 确认的事实 → 写入共享库 (sch_components / sizes)

存储端 (真理银行, 只增不改):
  text_box / green / sizes / confirmed_pos / wires / chain_order
  └── 每条带来源 (refdes/round), 可追溯

消费端 (任何工具, 随时查):
  sch_symbol / sch_wire / sch_render / selfcheck ...
  └── 遇判断 → 查真理银行 → 强真理硬约束 / 弱真理排序加权
```

| 环节 | 机制 | 说明 |
|---|---|---|
| **生产** | 每轮识别+自监督确认的事实 → 入库 | 只增不改, 越积越多 |
| **存储** | 共享库 (sch_components.json / sch_symbol_sizes.json) | 任何工具可读, 跨工具复用 |
| **消费** | 遇同类判断 → 引用真理元素 | 强真理 (text_box) 硬约束拒; 弱真理 (绿线/尺寸) 排序加权 |
| **回馈** | 新确认事实反哺下一轮 | 每轮新增真理源 → 后续识别更聚焦, 精度↑误检↓ |

**闭环本质**: 识别消费真理 → 确认新事实 → 补充真理 → 更准识别。
真理银行是 architecture §14 无监督进化闭环的**共享事实层**,
跨机型/跨图纸可复用 (同类型符号的尺寸/域特征).

**数据存放处 + 可信度清单**: 见 schema.md §3.5b
(每个真理元素的字段位置 / 生产者 / 可信度 / 复用方式)。

### 14.1d 与 AI 原理的对应 (低维度仿真, 2026-09-17)

truth bank 这套机制在**非常低的维度** (无神经网络, 纯规则) 下仿真了
几个核心 AI 原理 —— 理解对应关系, 可指导后续改进方向:

| 本项目机制 | 对应 AI 原理 | 说明 |
|---|---|---|
| truth_score 可信度 | **置信度校准** (confidence calibration) | 每条事实带分, 按分分层使用, 防过度自信/轻信 |
| 真理元素不断积累 | **证据积累 / 主动学习** | 确认的事实入库, 越多判断越准 |
| 校验失败降分 (on_label 等) | **伪标签过滤 / 置信门控** (pseudo-label filtering) | 低置信/冲突样本降权或剔除, 防止误导 |
| 多次确认逐步加分 | **一致性正则 / mean-teacher** | 跨轮稳定一致 = 更可信 (对应 EMA teacher 思想) |
| 强真理硬约束 / 弱真理加权 | **先验注入 / 后验融合** | 高可靠先验 (text_box/GT) 直接约束, 弱证据加权 |
| 识别→校验→入库→反哺 | **自我训练** (self-training) | 每轮确认样本反馈模型, 越滚越准 |

**启示**:
- 无需真正训练模型, 也能获得类 AI 的**渐进式精度提升** (round 越跑越准)
- 若未来上 CNN/YOLO, 这套 truth bank 可直接作为**伪标签来源 + 置信门控**,
  是半监督学习的现成地基 (标注自动生成 + 可信度筛选)
- 低维度仿真已验证: text_box (90) 作硬约束正确排错 26 个误位电容 (§14.1b)

### 14.1e agent 驱动 = 对识别系统做局部优化 (2026-09-17)

**定位**: 本项目用 AI (agent) 推动**程序本身的进步**, 本质是**对识别系统
做局部优化** —— 每轮: 运行管线 → 对照 GT 评估 → 定位具体弱点 → 修正一处
算法/参数/证据源 → 下一轮。与 §14.5 (数据滚动) 互补: 数据滚的是**事实**,
agent 滚的是**系统本身**。

**冲突排除逐层收紧 (conflict elimination)**: 每多用一个真理源
(text_box 边框 / 绿线 / 尺寸) 做排除, 就少一批干扰候选,
候选空间逐层收窄 → 越排越准 (真理银行消费端 §14.1c):
```
候选集 (上千个) ──text_box 冲突排除──> (减几十) ──绿线冲突排除──> (减半)
  ──尺寸/方向冲突──> 收敛到真符号
```

**排除来源是可扩展的证据源 (pluggable exclusion)**: 排除阶段是**可选来源**
集合, 每个排除源 (text_box / 绿线 / 尺寸 / 方向 / 未来更多) 可独立开关、
独立参数化, **加新排除源不改主程序逻辑**:
- 主程序只留统一的 `_exclude(cx,cy)` 接口 + 排除源注册表
- 每个排除源: `{name, enabled, truth_score(可信度), 判定函数}`
- 新增来源 = 注册一条 (如 wire 对齐, 待评估后加入)
- 排除源也要遵循 schema §3.5b 可信度分层 (高可信硬排除, 低可信加权)

```
运行管线 (round N) → 对照 GT 量化 (hit<50px) → 定位弱点 (哪类错?)
  → 修正 (算法/参数/新增真理源) → 重跑验证 (round N+1)
```

**本轮实证轨迹** (电容识别, GT 14 个):
| 轮 | 修正 | 结果 (hit) |
|---|---|---|
| round029 | Hough pairs 单源 | 8/14 |
| 实测 | plates 优先 | 9/14 |
| v1 | 多源投票 + 强约束质量分 | 6/14 (过拟合退化) |
| 分析 | 发现 Hough 对短板线失效; proj 候选 14/14 存在但难选 | - |
| 洞察 | text_box (90) 硬约束排错 26 个误位 | 新真理源 §14.1b |
| 结论 | 用真理元素 (text_box/绿线) 分层约束选优 | 进行中 |

**规律**:
- 每次只改一处, 对照量化指标验证 —— 防止"调好但不知道为什么"
- 弱点定位看**错误模式** (哪类 refdes/位置/场景), 不只看数字
- 新增**真理源** (text_box/绿线) 往往比调阈值更有效 (§14.1c 真理银行)
- 记录每轮修正轨迹 (如 parameter_space.md), 可复盘、可回退

### 14.2 自我学习积累 (知识随确认增长)
| 知识 | 存储 | 机制 |
|---|---|---|
| **符号尺寸库** | `sch_symbol_sizes.json` (schema §3.6) | 确认 OK 的符号尺寸 **append 累积**; 中位=典型 |
| **IC 型号尺寸** | 按型号键 `ic:<model>` | 不同型号大小不同, 分别记录 |
| **合成符号掩膜** | 由典型尺寸生成 | 掩膜匹配确认新符号 |
| **纯黑图层** | 走线检测基础 | 去绿线干扰 |

### 14.3 进化闭环 (无监督)
```
识别 (sch_trace/label_ocr/flow_walk/symbol)
  → 校验 (reverse OCR / 边界 / 重叠 / label)
  → 确认 OK 的 → 尺寸/掩膜知识入库 (append)
  → 知识反哺 (典型尺寸校验 / 合成掩膜匹配 / 跨机型复用)
  → 越用越准
```
- 每个确认的符号都是学习样本, 无人工标注
- 校验失败自动纠正 (符号位置/关联), 纠正后再验证
- 知识库跨机型/跨图纸可复用同类型符号

### 14.4 关键教训
- 程序含宽容忍 → 需人工抽查 (round013 红点在符号内但仍有缺陷)
- 校验手段逐步叠加 (反向OCR → label框 → 边界 → 重叠 → 尺寸 → 掩膜),
  每层减少一类错误
- 识别(符号本体)与自我监督校验(位置/关联)分层: sch_symbol (对应 pcb_package) /
  sch_symbol_selfcheck (对应 pcb_verify)

### 14.5 多轮滚动迭代 (round 机制, 2026-09-17 沉淀)

**核心**: 识别不是一次性的, 而是**多轮滚动** (roundXXX)。第一轮往往只能
定位到**关键信息** (粗位置/粗略候选), 随管线**反复运行**, 数据逐步
**更精确、更丰富** —— 每一轮消费前一轮的产物 + 校验结果 + 累积知识, 反哺下一轮。

**滚动机制**:
```
round N 输出 (粗) ──校验──> 确认/纠正 ──> 知识入库 (append) ──> 反哺
                                                                    │
    round N+1 输入 (知识+前一轮数据) ◄────────────────────────────┘
```

**示例 (已实测)**:
- `sch_symbol_sizes.json` 尺寸知识库 append 累积: 一次 round028 运行
  cap 41→76 条 / circle 10→48 / ic 1→24 (确认 OK 的尺寸不断入库)
- `symbol_body` / `sym_boundary`: 随识别器迭代从"无"到"有", 并随模板/掩膜
  refine 位置精确化 (mask_loc / calib / real_loc 逐层矫正)

**待统计 (todo)**: 目前还没有系统统计"哪些数据是随轮次滚动的、各自滚动了
多少、收敛还是发散"。后续应:
1. 列出所有**滚动数据** (sizes db / symbol_body / sym_boundary / chain_order /
   components_index / waypoints 等) 及它们的生产者/消费者/累积方向
2. 记录轮次间的 delta (每轮新增/修正/删除), 评估是否收敛
3. 对发散 (越滚越乱) 的数据要加闸 (如尺寸偏离典型 ±60% 标 size_dev)
