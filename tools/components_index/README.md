# tools/components_index — 元器件索引

`nettable/components_index.json` 是跨图映射的枢纽(架构见 architecture.md §1):
ref-des → 类型/名称/各视图坐标/来源/状态/链序。原理图读出的信号流靠它落到
PCB 像素坐标; 未来封装/引脚字段也挂在这里。

## 生成

```bash
python3 build_index.py --project projects/IC-2200H --ai-run <某次 ai_refdes_ocr 运行JSON>
```

- 数据源: `sch_components_raw.json`(原理图位号坐标, pdftotext -bbox) +
  `top_pcb.json`(已审计的确认锚点, 权威) + AI-OCR 运行命中(补非锚点位号) +
  `part_names.json`(位号→名称/值, 人工维护的小字典);
- 同一位号在多源出现时: 网表锚点优先(status=confirmed), AI 命中其次
  (ocr_hit), 只原理图有坐标的 schematic_only;
- 多位置元件(原理图多处出现, 如 IC6): `px` 取第一处, 全部存 `alts`,
  下游(make_wpts_from_index)用链序路径启发式选点;
- `--ai-run` 建议传最新 refine 运行; 路径例:
  `projects/IC-2200H/nettable/ai_ocr_runs/20260910_162730_refine-*.json`。

## 输出 schema(随文件内嵌, 此处为权威说明)

```json
{
 "spec_version": "0.1",
 "schema": { "space": "各视图 px 均为该视图 300dpi 渲染坐标",
             "status": "confirmed|ocr_hit|schematic_only|unverified",
             "upgrade": "0.2 计划加 package(封装)/pins(引脚)" },
 "components": {
   "IC10": {
     "type": "IC",              // 前缀推断: R/C/L/D/Q/IC/X/FI/J/EP...
     "name": "S-AV36 (ATT)",    // part_names.json
     "views": {
       "schematic": {"px": [2172,406], "alts": [], "src": "sch_components_raw"},
       "pcb_top":  {"px": [1311,895], "src": "nettable/confirmed_anchors_top",
                     "evidence": "...conf0.99+v6 0.97..."},
       "pcb_bot":  null },
     "status": "confirmed",
     "chain_elems": [{"idx": 3, "elem": "IC10 ATT"}],   // 信号链引用
     "note": "" } }
}
```

### status 语义
- `confirmed`: 网表双确认锚点(2026-09-10 已审计纠错 5 处);
- `ocr_hit`: 仅 AI-OCR 命中, 待图签(--sheet)人工确认后升级;
- `schematic_only`: 只有原理图坐标;
- `unverified`: 曾标 confirmed 但被审计降级(如 IC12), 待复核。

### 升级约定
- 0.1→0.2(计划): +`package`(封装类型, 依赖形状检测工具见 todo) +
  `pins`(引脚相对坐标数组, 依赖封装尺寸+图纸比例);
- schema 字段与实际不符时以文件内 `schema` 为准; 转换脚本按
  `spec_version` 分支, 不做隐式迁移。
