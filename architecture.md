
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

## 13. 全流程工具链

将探索阶段验证过的方法和原则固化为可复用工具, 确保流程一致、可追溯。

### 13.1 OCR 识别
| 工具 | 路径 | 用途 |
|---|---|---|
| `rectangle_locator.py` | `tools/rectangle_locator/` | 矩形轮廓检测, 定位 refdes 标号 |
| `circle_locator.py` | `tools/circle_locator/` | 圆形轮廓检测, 补充识别 |
| `ic_ocr_scan_dml.py` | `tools/ic_ocr_scan/` | Windows DirectML GPU 加速 OCR |
| `detect_ic.py` | `tools/ic_package_detect/` | IC 封装定位: 矩形+圆形裁切+旋转OCR+refdes 匹配 → 本体框 |

**detect_ic.py crop-ocr (IC 本体定位首选)**: 配合 rectangle/circle_locator 的裁切,
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
曾导致 components_index 345 处 rot≠0 坐标偏移 (如 IC12 从错误的 (3555,2719)
校正到正确的 (3429,2768))。任何"变换后再识别"的中间结果, box 必须逆变换回源空间。

### 13.2 信号流渲染
| 工具 | 路径 | 用途 |
|---|---|---|
| `signal_flow_route.py` | `tools/signal_flow_route/` | 信号流自动路由, 生成 waypoints |
| `render_rx_flow.py` | `tools/render_rx_flow/` | 渲染 RX/TX 信号流标注图 |

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

**render_rx_flow.py** (固化渲染规则):
- 实线/虚线: 虚线用 semi-transparent 绘制, 避免遮挡 PCB 底图
- via 标记: 红色空心圆 (width=12, r=18)
- 箭头: 每段连线终点, 跟随信号流方向

**输入**: JSON config (components 坐标/view/lpos + connections 列表)
**输出**: wpts JSON, 与 `render_rx_flow.py` 兼容
