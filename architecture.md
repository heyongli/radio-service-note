# Architecture — 设计思路与原则

本文件沉淀项目的架构决策与工作思路(为什么这么设计)。操作规则见 `agent.md`,
实证配方见 `best_practices.md`, 后续路线见 `TODO.md`。

## 1. 数据流总架构

```
维修手册 PDF ──pdftoppm 600dpi──> render/(光栅底图)
                │
原理图文本层 ──pdftotext -bbox──> sch_components(位号+坐标)
                │                          │
PCB 渲染图 ──AI OCR 两阶段管线──> ai_ocr_runs/(每次运行 JSON 归档)
                │                          │
                └──────────┬───────────────┘
                           ▼
              nettable/components_index.json   ← 枢纽: 元器件索引
              (ref-des → 类型/名称/各视图坐标/来源/状态)
                           │
             ┌─────────────┼──────────────┐
             ▼             ▼              ▼
     top_pcb.json    wpts_*.json    chain_order    ← 网表(信号流/锚点/链序)
             └─────────────┼──────────────┘
                           ▼
              SVG 分层标注 (annotate_svg_flow) ──> annot/*.svg + .png
```

核心思想: **元器件索引是跨图映射的枢纽**。原理图读出的信号流
(哪个元件连哪个元件)只有通过"元器件索引"才能落到 PCB 的准确像素位置——
因为同一个 ref-des 在原理图/PCB top/PCB bot 三个视图各有坐标, 索引把它们
关联起来。没有索引, 信号流标注只能靠"空间先验猜", 错位就是必然(2026-09-10
审计旧网表 5 处锚点错误即教训)。

**索引即飞轮**: 任何工具只要能建立"器件→坐标"的识别, 就是净进展——不管
它来自 OCR、形状检测、封装匹配还是人工。索引完备度逐级解锁高级能力:

```
位号坐标(已有) → 组件本体绑定(todo: 形状检测) → 引脚级坐标(todo: 封装)
    → 焊盘连通关系(bot铜箔) → 网络/互联分析 → 原理分析(功能块级理解)
    → 反推原理图(netlist → 自动绘图, 即 PCB 逆向工程的终点)
```

因此新工具的验收标准不是"能不能读对某个字", 而是"能给索引贡献什么"。

## 2. 工具设计五原则

1. **工具是工具, 参数是参数**: 一切阈值/尺寸/引擎/图层选择走 CLI, 代码里
   不留魔法常数; 参数的"合理可靠用法"(实测调优值+踩坑记录)写进各自工具
   README, 而不是散在会话记忆里。
2. **多引擎协同, 各做擅长的事**: 引擎按阶段/按场景分工(stage1 全页扫用
   v4-mobile, stage2 crop 读数用 v4+v6 互证, tesseract 可作第三方仲裁);
   同位双引擎一致(agree)≈自动预确认, 分歧项才上升人工。
3. **每次运行都归档, 可比较、可校准**: 运行 JSON 强制落盘(runs-dir),
   含 tool_version/日期/全参数快照/脚本hash; 用 compare_runs.py 对比参数间
   增益回归, 校准数据回写 README/网表。只有确认完全乱套的运行才删除。
4. **快速模式→逐步细化**: 先 `--preset fast`(~20s)出全景初稿, 看清缺口
   再针对性细化(旋转 pass/上采样/换引擎), `--reuse-stage1` 复用上次中间
   结果, 绝不重复烧算力。
5. **中间结果是资产**: raw hits 常态化随运行保存(keep_raw 默认开);
   waypoints/components_index 等结构化 JSON 是"源", 渲染(SVG/PNG)只是
   派生视图, 改标注改 JSON, 不重跑识别。

## 3. 识别架构: 轮廓先行的两级漏斗 + 全板裁切索引

- **内容轮廓用传统工具, 识别用 AI**: 轮廓/内容检测是成熟问题
  (cv2 阈值+形态学+连通域, 毫秒级), 不需要 AI; AI 用在读字(dets 失灵的
  小字场景正是 AI rec 的强项)。分工明确, 各用最便宜够用的工具。
- **二分细分**: 过大内容块沿长轴二分到 region-max 以下, 子块内重取紧
  bbox——"先轮廓定哪里有东西, 再逐块识别"。
- **两阶段漏斗**: stage1 全页网格扫抓中大字(快); stage2 字形聚类补漏,
  只对 stage1 没覆盖的候选 crop+4x 上采样读(准)。实测(600dpi PCB top):
  grid 3000/400 全页 17s 出 68 个位号, contour 模式对密集板面无优势
  (29s/58 个), 但稀疏页面(标题页/元件表)预期收益大——参数怎么选写进
  工具 README, 结论来自 compare_runs 校准。
- **全板裁切索引**(2026-09-11 新增): 对 PCB 渲染图按 200×200 px 网格
  (40px 重叠)切割, 建立 `crops/board_tiles/tiles_index.json`。每个 tile
  独立送 AI OCR, 结果按 tile 坐标回写到 `ocr_runs/`。好处:
  1. 避免全页 OCR 漏检小字(分块后字相对更大)
  2. 裁切图可复用于后续 AI 多模态识别(不用重跑切割)
  3. 结果可增量更新(只重跑变化区域)
- **快精结合两阶段识别**(2026-09-11 新增):
  1. **快速扫描**: `--preset fast` 全板跑一遍, ~10s 建立初步索引
     (可能漏检小字/低对比字)
  2. **精细探测**: 对快速扫描未覆盖的区域, 用 `--preset full` 或
     多引擎交叉验证, 逐 tile 精读
  3. 结果合并去重, 写入 `components_index.json`
  原则: 先出粗稿看清全局缺口, 再针对性补盲, 避免一开始就全量精算。
- **引擎选择要实测**(2026-09-14 新增, CPU 机对比):
  - v4 = rapidocr_onnxruntime 的 PP-OCRv4 **server** 模型(已装, 精度高
    但保守); v6 = rapidocr 的 PP-OCRv6 **small/mobile**(快但杂, 易幻觉
    出 IC169/IR78 这类假位号); v5en 依赖英文模型(未下载=0 命中)。
  - 实测同批 bot 图块: v4 17 命中(IC6/Q26/R184/C250 全中), v6 25 命中
    但混入假位号且漏真实件, v5 server(80MB, modelscope 可自动下载)最
    灵敏——补出 v4 漏的 R177~R185 连续串/R109/C288~C297, 但漏 IC6。
  - **结论**: CPU 机默认 stage1=v4 server 合理; 要覆盖全面需
    `--stage1-engines v4,v5s` 双引擎(403s/全板 87 个 vs 单 v4 17 个;
    双引擎同位一致 agree=True 才算预确认)。工具已注册 `v5s` 引擎名。
  - 全页小 tile(3000px) 内丝印字太小, 全页扫基本无效(仅 1-5 个);
    必须按 `crops/board_tiles*` 切块(200px)小块扫才出效果。
- **PCB 背面扫描**(2026-09-14 新增): bot 视图同样按 200×200 tile 切块
  (crops/board_tiles_bot), 由 `pcb-bot.pdf` @300dpi 渲染。背面往往有
  顶面无标的小器件(Q16/IC6/Q26 等丝印在背面), 是补充 RX 链坐标的关键
  —但 bot 坐标只属 bot 视图, 不得直接用于顶图标注(§5A 每视图独立坐标系)。
- **双机协同 OCR**(2026-09-14 新增):
  - 资源拓扑: 本地 8 核/27G(render 宿主) + 远程 10.0.0.121 14 核/100G
    (root/plus1234, venv 于 /opt/ocrvenv)。远程已装 same 工具
    (ai_refdes_ocr.py 已 rsync), 依赖 rapidocr/rapidocr_onnxruntime/
    opencv-python-headless/scipy + libgl1。
  - 分工原则: 远程跑重负载(600dpi 全板多朝向多引擎, 1 核 60min 级);
    本地跑实时(300dpi quick 扫描、SVG 渲染、索引合并、结果汇合)。
    分配脚本 `ocr_runs/slave_remote.sh`(top600|bot600|check)。
  - **2026-09-14 更新 - 直接在 Proxmox 宿主 yvr(10.0.0.100) 跑任务**:
    宿主 14 核 E5-2697v3/125G, 与 llm 同桥 vmbr0 直连, 本机只需连通宿主
    一个点即可天然访问 llm(10.0.0.121)。宿主 Python 3.13.5, venv 于
    `/opt/ocr_venv`(rapidocr 3.9.2, rapidocr-onnxruntime 1.2.3,
    opencv-headless 5.0.0.93, scipy 1.18.1, pillow 12.3.0; 需系统包
    libgl1 libglib2.0 已装)。工具与底图: `/opt/pcbocr/{tools/ai_ocr_eval,
    render,runs}`。llm(LXC 静态 IP 10.0.0.121) 网络不稳定, **不再依赖**,
    重任务优先跑在宿主 yvr 上。
  - **进度/中间结果 (2026-09-14, v0.3.0)**: 工具新增 `--progress`
    (每完成一块任务 stderr 输出 n/total、%、elapsed、ETA、hits) 与
    `--checkpoint PATH [--checkpoint-every N]`(周期性把 raw_stage1/
    raw_stage2 中间结果落盘, 可 `--reuse-stage1/2` 续跑; Ctrl-C 中断
    自动保存 checkpoint)。宿主验证通过: 12 tiles 8s 全程进度行 +
    多次 checkpoint 落盘 + 复用续跑成功。
  - 结果汇合: 各自 out-dpi 固定, 按视图(300dpi 空间)落 components_index,
    跨机同位合并同去重逻辑(agree = 多引擎同位一致)。
  - 注意: 远程容器需显式同步 render + 工具(`scp`), 模型首次自动从
    modelscope 下载(v5 server 88MB+84MB)。SSH 用 sshpass 密码认证。
  - **实测教训**: 600dpi 全图 + 3 朝向 + 1.5x 上采样 + 双引擎太重(本地
    38min+ 未完成) → 默认用 300dpi 200px tile 快扫, 高精度任务定向
    crop 关键区域即可, 勿全板 600dpi。

## 4. 标注架构: SVG 分层(仿 example/talkabout-bot.svg)

- **底图自包含**: base64 内嵌(不外链), 单文件拷走不失底; 底图层锁定
  (sodipodi:insensitive), Inkscape 里点不中拖不动, 防误操作。
- **语义分层**: rx / tx / ctrl-power / blocks / marks / notes 每类一层,
  Inkscape 命名图层, 层级默认色, 可独立开关——不同读者各取所需层。
- **诚实标注**: 实线=本面确认走线, 虚线=背面走线(信号从/到PCB另一面),
  "not located"不得臆造坐标(agent.md 防臆造约定在 SVG 上同样生效)。
- **渲染即派生**: SVG 由 waypoints JSON 生成; PNG 由 cairosvg 导出。
  两者都在 svg_runs/ 归档且带参数快照。

### 4A. 连线布线规范

- **横平竖直**: 信号流连线优先水平/垂直走向, 避免斜线; 拐点用
  `through` 字段定义中间点, 每段独立画箭头。
- **避免自交叉**: 不同信号路径不得相交; 若必须跨越, 用绕行(如
  TX 从上方进 D12、ctrl 线绕行西侧), 交汇于同一器件不算交叉。
- **连接器标注**: 连接器(J/ANT等)使用特殊图标(焊盘环+孔符号),
  用较小字体(fs=20)标注连接目标模块(如 "→ ANT Jack" 或
  "→ Main Unit J3")。

### 4B. 视觉编码规则

- **实线绿**: 本面确认走线(PCB同层可见)
- **虚线绿**: 背面走线(信号从/到PCB另一层)
- **黄色高亮区**: 未确认路径(坐标未经OCR验证, 待复核)
- **箭头**: 每段连线终点必须有箭头, 指示信号方向
- **连接器**: 焊盘环+孔符号, 小字标注连接目标

### 4B. 坐标校验规则

- **坐标必须在板框内**: 300dpi 下 IC-2200H 页面 2550×3300 px
  (8.5"×11" letter), 板框约占页面中间区域; 超出合理范围的坐标视为错误,
  必须回溯 components_index.json 验证。
- **IC/晶体管定位优先级**: pin-silk(引脚丝印) > body(暗矩形) >
  contour(轮廓); 不可仅凭 schematic 坐标估算 pcb_top 位置。
- **多位置元件(alts)**: 链序路径启发式选点(prev→pick→next 总
  曼哈顿距离最小), 不取第一个位置。

## 5. 坐标系核心假设 + 数据溯源规范

### 5A. 每图独立, 比例可共享

**坐标不能跨视图共享**。原理图/PCB top/PCB bot 是三张不同的图片,
各有独立的像素坐标系、缩放比例和原点。同一 ref-des 在三个视图的 px
值描述的是不同图像上的位置, 不能直接互换。

**可共享的只有比例关系**: 如果我们知道某器件在原理图上位于 A 和 B 之间
(比例位置 ~0.4), 那在 PCB top 上它大概率也在对应 A' 和 B' 之间——但
具体的 px 值必须来自该视图自身的识别(OCR/形状检测等), 不能从原理图
坐标推算。

### 5B. 数据溯源: 每条结果必须携带的元数据

**任何识别结果(JSON)必须包含以下溯源字段**, 否则不可跨运行共享:

```json
{
  "src_file": "projects/icom2200h/render/pcb-top-300-1.png",
  "src_dpi": 300,
  "src_crop": {"x0": 250, "y0": 100, "x1": 450, "y1": 300},
  "tool": "ai_refdes_ocr",
  "tool_version": "0.2.0",
  "preset": "fast",
  "engine": "v4",
  "run_id": "20260911_154353"
}
```

- `src_file`: 哪个源文件
- `src_dpi`: 源文件 DPI
- `src_crop`: 裁切区域(如果是 tile); 全页识别则为 null
- `tool` + `tool_version`: 哪个工具哪个版本生成
- `preset` + `engine`: 用了什么参数
- `run_id`: 哪次运行(可追溯到 `runs/` 目录的具体 JSON)

**后果**: 没有溯源的坐标视为不可信。多次运行间共享数据时,
靠 `src_file + src_crop + tool_version` 三元组去重。

## 6. 坐标校验规则

- **坐标必须在板框内**: 300dpi 下 IC-2200H 页面 2550×3300 px
  (8.5"×11" letter), 板框约占页面中间区域; 超出合理范围的坐标视为错误,
  必须回溯 components_index.json 验证。
- **IC/晶体管定位优先级**: pin-silk(引脚丝印) > body(暗矩形) >
  contour(轮廓); 不可仅凭 schematic 坐标估算 pcb_top 位置。
- **多位置元件(alts)**: 链序路径启发式选点(prev→pick→next 总
  曼哈顿距离最小), 不取第一个位置。

- **单一坐标系**: 所有 px 统一 300dpi 渲染空间(带 view 字段区分
  schematic/pcb_top/pcb_bot); 600dpi 中间量必须换算后再入网表——
  2026-09-10 审计发现旧锚点 5 处错误, 根因就是 600dpi 原始坐标混入。
- **每个坐标必有来源**(provenance): 哪次运行/哪个引擎/什么置信度/是否
  视觉确认。无来源的"confirmed"视同存疑。
- **状态三态**: confirmed(双证) / inferred(虚线) / not_located(不臆造)。
  规范全文见 projects/<机型>/nettable/SCHEMA.md。

## 7. 防幻觉三道闸

1. **AI 双引擎同位一致**(v4+v6 同文本同坐标)才算预确认;
2. **坐标空间校验**: 命中必须落在图内且与空间先验(如"FI2 旁找 FI1")
   相容, 否则降级待查;
3. **视觉签收兜底**: 高倍 crop 拼图签(--sheet)人工过一遍——AI 时代
   这道闸不是流程残留, 是 2026-09-10 纠出 5 处旧错误的直接功臣(反向:
   AI 也纠了人工确认的错, 双向不信任才是信任)。
