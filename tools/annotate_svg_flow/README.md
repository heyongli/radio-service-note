# tools/annotate_svg_flow — 分层 SVG 标注

仿 `example/talkabout-bot.svg` 的分层原则, 把 waypoints JSON 渲染成
Inkscape 可编辑的分层 SVG(底图 base64 内嵌+锁定), 可导 PNG。
设计规范见根目录 `architecture.md` §4。

## 文件

| 脚本 | 作用 |
|---|---|
| `annotate_svg_flow.py` | 渲染器: wpts JSON → 分层 SVG(+cairosvg PNG) |
| `make_wpts_from_index.py` | 生成器: components_index + chain_order → wpts JSON(含 tx/ctrl 色块 zone) |

## annotate_svg_flow.py

```bash
python3 annotate_svg_flow.py --base projects/IC-2200H/render/rxtx300-1.png \
    --wpts projects/IC-2200H/nettable/wpts_rxtx_sch.json \
    --runs-dir projects/IC-2200H/annot/svg_runs \
    --out projects/IC-2200H/annot/rxtx_flow.svg \
    --png projects/IC-2200H/annot/rxtx_flow.png --tag rxtx-v3
```

### 分层原则(学自 example)
- 每个语义类一层: `rx`(绿) `tx`(红) `ctrl`(黄) `blocks`(蓝) `marks`(橙) `notes`(灰),
  层名即 Inkscape 图层名(如 "RX-Flow"), 层级默认样式可整体改;
- 底图单独一层 `Base`: **base64 内嵌**(单文件自包含, 拷走不丢底图,
  不用外链), `sodipodi:insensitive="true"` **锁定**(Inkscape 里点不中/
  拖不动, 防标注时误动底图);
- 实线=已确认, 虚线=推断(`dash: true`), not-located 进 notes 层不臆造。

### 参数用法(实测可靠值)
- `--base` + `--base-dpi`: 底图与 dpi; `--wpt-dpi`: waypoints px 所在 dpi
  (默认 300, 自动换算; **跨 dpi 必传对**, 否则整体偏移);
- `--wpts` 可多次: `path:layer` 指定该文件归属层; 文件内条目也可自带
  `"layer"` 字段(单文件多图层, 生成器产出的就是这种);
- waypoint 条目格式: `{label, px:[x,y], dot, dash, through:[[x,y]...],
  kind: dot|text|rect|line, to:[x,y](line用), w,h(rect用), layer, note}`;
  兼容旧 `nettable/wpts_top.json` 与 `top_pcb.json` 的 anchors 格式
  (label_px 自动识别);
- `--layer-style rx:color=#00c853,opacity=0.8`: 层色/透明度覆盖, 可多次;
- `--text-halo` 默认开: 白描边+paint-order, 密底图上可读性关键
  (crop-OCR 回读验证: L39/IC10/not-located 均可读);
- `--dot-r 7 --stroke-w 5 --font-size 34 --dash-array "10 8"`: 300dpi 页
  的实测合适量级; 底图换 dpi 时按比例调;
- `--runs-dir`: 每次渲染归档 `日期_标签_版本_脚本hash.svg` + 同名 `.json`
  元数据(参数快照); `--out`/`--png` 只是最新副本;
- `--png-dpi` 未用于缩放(PNG 按底图原始像素导出)。

### 已知边界
- 箭头 marker 按 6 层色各建一个(arrow-rx 等), 自定义层色时箭头
  仍是默认色——需改 `LAYER_DEFS`;
- rect 的 label 画在框左上角; 大框(>500px)标签会被图签淹没, 建议
  zone 类标签简短("TX z0")。

## make_wpts_from_index.py

```bash
python3 make_wpts_from_index.py --project projects/IC-2200H \
    --base-render projects/IC-2200H/render/rxtx300-1.png \
    --out projects/IC-2200H/nettable/wpts_rxtx_sch.json
```

- 输入: `nettable/components_index.json`(枢纽) + `top_pcb.json` 的
  chain_order_schematic + `rx_blocks_top.json`(功能块相对坐标);
- rx 链: 按链序连接有坐标的组件(箭头); 链元素跨多个 chain idx 的连线
  画虚线(中间有未定位元素); **无坐标的链元素全部进 notes 左边缘竖排
  (MIXOUT/FI1-FI2/QUAD/CDB450C24/AFOUT/VOLOUT/SP)**;
- 多位置元件(index 的 `alts`, 如 IC6×3 处): 链序路径启发式选点
  (prev→pick→next 总曼哈顿距离最小), 比取第一个位置准;
- tx/ctrl zone: 底图色块掩膜提取。**颜色掩膜必须先实测校准**——本页
  "红"实为深红 RGB≈[236,4,142](b 通道高), 掩膜用 6 值区间
  `--tx-color 150,255,0,110,0,200`; 黄色在本页几乎为零(10px);
- `--zone-max-frac 0.3`: zone bbox 超过页面 30% 的整页连通大块丢弃
  (TX 红路径遍布图面时区域级标注无意义, 改进 notes);
- 产出单一 JSON 条目带 layer 字段, 直接喂 annotate_svg_flow。

## 校验方法(改渲染参数后必做)
SVG 结构: lxml 检查每层 `<g>` 子元素数与文本样本;
渲染正确性: cairosvg 导 PNG 后, 在已知标签位置 crop±(90,60) + 4x
上采样 OCR 回读(marks 的 L39/IC10、blocks 的 BPF、notes 的 not-located
是基准回归点)。

## v0.1.2: 字号分级与标签方位 (2026-09-10)

- waypoint 条目新增 `fs`(字号覆盖)与 `lpos`(8方位: ul/ur/dl/dr/l/r/u/d,
  自动计算偏移+text-anchor)。按器件尺寸分级: 大IC/连接器 30-38, 晶体管/滤波器
  24-28, 小元件(R/C/D) 20-22, IC 引脚 18。
- 经验: 标签优先放连线行进方向的侧后方; 基图有丝印文字处(base PDF 文本层)
  避让; note 跟随主标签下方(0.62×fs)。

## v0.1.3: 分层渲染与布线 (2026-09-10)

- `--only-layers rx,notes`: 只渲染指定层 → RX/TX 流程图分离出图
  (TX 出图配 tx,ctrl; 共享段如 LPF/ANT-SW 在两边各画完整链)。
- polyline 加 `marker-mid`: 弯道处也有方向箭头(cairosvg 已验证支持)。
- 布线规范: 横平竖直优先; 交叉时绕行(如本例 TX 从上方进 D12、
  ctrl 线绕行西侧), 交汇于同一器件(如 ANT-SW)不算交叉。
