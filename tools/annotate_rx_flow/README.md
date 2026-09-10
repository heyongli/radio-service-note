# annotate_rx_flow — 信号流程标注工具(2 个)

## annotate_rx_flow.py — 块级路径(旧,原理图序号节点)
以 PCB 视图渲染图为底,按板矩形内 0-1 分数坐标画块级绿线路径。
`--png <渲染图> --board x0,y0,x1,y1 --blocks <blocks.json> --out <成品>`
blocks.json: `[[fx, fy, "标签"], ...]`。
视图方向:top 前缘在页底,bot 是垂直镜像(fy'=1-fy)。
**已过时**:本批 PCB 图光栅内有位号(见 ../pcb_designator_ocr),优先位号级方案。

## add_photo_wpts.py — 位号级 waypoint 线(照片/PCB图通用,当前主力)
```bash
python3 add_photo_wpts.py --png <底图> --waypoints <wpts.json> --out <成品.png> \
    [--scale 0.5] [--width 9] [--fontsize 22] [--dotsize 14]
```
waypoints JSON: `{"px":[x,y], "label":"...", "dot":true, "dash":true,
"through":[[x,y]]}`(px 为底图原生像素坐标;--scale 用于 600dpi 底图+300dpi 坐标)。
- 实线=已确认链路段, 虚线(dash)=推断段(未定位元件), 端点圆圈=确认锚点
- through: 并行支路再连线(如 FI1↔FI2)
- 未确认坐标不得入线, 用虚线+label "not located" 注明
- 出全尺寸成品 + --scale 0.5 半尺寸 view 校验图各一张
- 示例: projects/IC-2200H/annot/top_pcb_rx.png (top view RX 链, 2026-09)

## 网表配套
waypoints JSON 与坐标依据存 `projects/<机型>/nettable/`(top_pcb.json:
confirmed_anchors/not_located/chain_order/artifacts)。
