
* 开始任务前先 load best_practices.md, 按其中的已验证结论操作, 避免重复踩坑
* git 提交纪律 : 不要自动 commit; 等用户明确要求 commit 执行。
* git 提交纪律 : 永远不要 `git add -f`, 尊重 .gitignore 规则, projects/ 等目录不进 git。
* 未确认的坐标要记录并在渲染时忽略 不得臆造坐标
* 修改任何工具/程序前, 必须先完整阅读其 `readme.md`; 改动不得破坏 readme 中固化的原则并保持重要算法


## 项目介绍
* 通过pdf或者图片的电路图, 信号流程图, 在实物pcb照片或者维修pcb的点位图上标注信号流程
* 注意合理利用各种现有工具

* **本项目的最终交付物**: 在 PCB **top/bot 实拍或点位图**上, 复现原理图
   中标注的 RX 信号流 —— 信号从 ANT 进, 依次穿过各种器件到达speaker

* **文档位置约定**:
  - **仓库根**放通用规范: agent/architecture/best_practices/cluster/
    radio-knowledge/schema/todo
  - **projects/<机型>/** 仅放工程特定文档 (如 radio-design.md, **不放**通用规范)
  - **projects/<机型>/nettable/** 仅放结构化 JSON + 项目特定的 schema.md (可选)
  - 每个设备/机型(如 IC-2200H)建立项目目录 projects/<机型>/: 源PDF放项目根, 中间文件按类型分目录(禁混放, 详见 architecture.md 第 0 章): render/(PDF渲染底图) crops/(切片/裁切+索引) nettable/(网表+元器件索引+waypoints JSON, 字段规范见仓库根 schema.md) annot/(仅最终 SVG+PNG, 严禁子目录) svg_runs/(渲染中间归档+参数快照) 
  - ocr_runs/(OCR 运行归档, 严禁 annot/crops/svg_runs 子目录); 临时中间件放 /tmp/opencode/ 并在网表JSON记录路径

 - `projects/<机型>/` 下**严禁**放通用规范文件 (如 schema.md 的通用部分,
   或重复 best_practices.md/architecture.md 内容)
 - 项目特定的设计/分析文档**可以放**, 如 `radio-design.md`
 
 - 规范全部在仓库根: `agent.md`, `architecture.md`, `best_practices.md`,
     `cluster.md`, `radio-knowledge.md`, `schema.md`, `todo.md`



* 文档分工: agent.md=操作规则 | best_practices.md=实证配方(任务前必读) |
  architecture.md=设计思路与原则 | schema.md=JSON 字段规范(toplevel, 含五要素) |
  radio-knowledge.md=通用无线电知识 | todo.md=后续路线 |
  tools/README.md=工具索引与研发进度

## 基本工具用法说明
* 用到脚本放入 tools/目录; 工具需要参数化
* **OCR 工具默认尝试 DirectML GPU**: 所有调用 RapidOCR 的工具, 启动时先 `from dml_helper import enable_dml; enable_dml()`, 失败再 fallback CPU。详见 `best_practices.md` §12 + `tools/ai_ocr_eval/dml_helper.py`。




## 文件元数据管理

### toplevel schema.md (仓库根 `schema.md`)

- 仓库**只有一份** toplevel schema.md, 路径 `./schema.md`
- 包含: 所有项目共用的字段约束、溯源约定、转换公式、JSON 格式示例
- 任何项目读这个 schema.md 就知道 JSON 字段规范

### 保持schema对数据的规范管理

1. **修改任何 nettable/ JSON 前**: 先读 toplevel `schema.md`
2. **修改任何 nettable/ JSON 后**: 更新  `schema.md`
3. **加载任何 nettable/ JSON 时**: 按 schema.md 的校验规则检查字段


#### schema 必备信息

| 要素 | 内容 |
|---|---|
| §1 文件清单 | 该目录下每个 JSON/MD 文件 + 一句话用途 |
| §2 目录结构 | ASCII 树状图 + 每层职责 |
| §3 元数据格式 | 每个 JSON 的字段表格 + 必填/可选 + 完整示例 |
| §4 用法 | 消费者/生产者/校验/错误处理 |
| §5 目的 | 该目录在项目中的核心目的 + 与其他模块的关系 + 演进方向 |


### schema.md 使用与编写规范 

* **所有 JSON 字段定义必须配套 schema.md, schema.md 是 toplevel 文件格式定义**

* **任何新生成的设计文档/中间文档/数据库/JSON/程序** 必须在合适位置
  记录 **功能(format)、格式、版本、用途** 四字段(详见 architecture.md §10)。

* 文件头注释 / JSON `_meta` / Markdown frontmatter 都可, 形式不限但必须可读。

* 通用 vs 工程特定 区分(详见 architecture.md §9):
  - **radio-knowledge.md** (仓库根): 通用无线电知识, 所有项目可复用
  - **projects/<机型>/radio-design.md**: 工程特定 RX/TX/Control/Power 链 + 关键器件功能 + 调试点

* **关键器件索引** (`projects/<机型>/nettable/components_index.json`) 每条
  必须含 refdes/box/center/view + **role (功能) + flow_note (在链序中的具体作用)**。

* **矩形裁切索引** (`projects/<机型>/nettable/rectangle_crops_index.json`) 每条
  必须含 bbox/center/wh/area/aspect/rectangularity/category/crop_file/view, 字段规范见 schema.md §2.6。



## 重大发现归档原则

任务过程中产生的任何"重大发现/踩坑/经验/方法", 立刻按"使用范围"归档到对应位置:
- 跨项目通用 → 仓库根 `.md`
- 硬件/集群 → `cluster.md`
- 工具踩坑/参数实测 → `best_practices.md`
- 项目特定工程 → `projects/<机型>/radio-design.md`
- 工具特定 → `tools/<tool>/readme.md`
- 一次性临时 → 不归档 (不留 shell 历史/会话记忆)

任何任务开始前, 先查相关文件是否已有记录, 避免重复劳动。


## 元器件标号识别与标注要求

见 `architecture.md` §16 (元器件标号识别与标注要求)。

核心规则:
- 元器件标号识别首选矩形裁切+OCR 或 AI-OCR 管线
- 标注根据元器件索引, 不捏造坐标
- 分层 SVG, 实线=确认/虚线=推断/not-located 不臆造
- 防幻觉

