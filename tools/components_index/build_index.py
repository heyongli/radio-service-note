#!/usr/bin/env python3
"""元器件索引构建 — 原理图↔PCB 跨图映射的枢纽.

把 原理图位号坐标 / PCB锚点(网表) / AI-OCR运行命中 三方数据按 ref-des
合并成单一索引: 位号 → 类型/名称/各视图坐标/来源/状态。信号流标注(原理图
链序→PCB落点)一律通过本索引解析坐标。

数据自描述: 输出 JSON 带 spec_version + schema 字段, 便于格式转换/升级。

用法(IC-2200H, 默认路径已内置):
  python3 build_index.py --project projects/IC-2200H
"""
import argparse
import datetime
import json
import os
import re

TOOL_VERSION = "0.1.0"
SPEC_VERSION = "0.1"

TYPE_MAP = [
    (re.compile(r"^IC"), "IC"), (re.compile(r"^Q"), "transistor"),
    (re.compile(r"^R"), "resistor"), (re.compile(r"^C"), "capacitor"),
    (re.compile(r"^L"), "inductor"), (re.compile(r"^D"), "diode"),
    (re.compile(r"^X"), "xtal"), (re.compile(r"^FI?"), "filter"),
    (re.compile(r"^J"), "connector"), (re.compile(r"^EP"), "pad"),
    (re.compile(r"^[VF]L"), "filter"), (re.compile(r"^W"), "jumper"),
    (re.compile(r"^B"), "ferrite"), (re.compile(r"^T"), "transformer"),
    (re.compile(r"^V"), "varactor"),
]


def comp_type(refdes):
    for rx, t in TYPE_MAP:
        if rx.match(refdes):
            return t
    return "other"


def norm_key(k):
    return k.split("_")[0].upper()


def parse_chain_refs(chain, universe):
    """chain 元素 → 出现过的已知位号 (只在 universe 内认, 防把型号/网络名当位号)."""
    out = []
    for i, elem in enumerate(chain):
        refs = []
        for tok in re.findall(r"[A-Z]{1,3}[0-9]{1,4}[A-Z]?", elem):
            if tok in universe:
                refs.append(tok)
        out.append((i, elem, refs))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--sch", default=None, help="sch_components_raw.json 路径")
    ap.add_argument("--nettable", default=None, help="top_pcb.json 路径")
    ap.add_argument("--ai-run", default=None, help="ai_refdes_ocr 运行 JSON(缺省=用 nettable 锚点)")
    ap.add_argument("--names", default=None, help="part_names.json (位号→名称/值)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    nt_dir = os.path.join(args.project, "nettable")
    sch_p = args.sch or os.path.join(nt_dir, "sch_components_raw.json")
    nt_p = args.nettable or os.path.join(nt_dir, "top_pcb.json")
    out_p = args.out or os.path.join(nt_dir, "components_index.json")
    names_p = args.names or os.path.join(nt_dir, "part_names.json")
    names = {}
    if os.path.exists(names_p):
        names = json.load(open(names_p))

    sch = json.load(open(sch_p))
    nt = json.load(open(nt_p))

    comps = {}

    def ensure(ref):
        if ref not in comps:
            comps[ref] = {"type": comp_type(ref), "name": names.get(ref, ""),
                          "views": {}, "status": "schematic_only",
                          "chain_elems": [], "note": ""}
        return comps[ref]

    # 1) 原理图坐标(多位号多处出现的存 alts, 供链序选点)
    for k, pts in sch.items():
        ref = norm_key(k)
        c = ensure(ref)
        c["views"]["schematic"] = {"px": pts[0], "alts": pts if len(pts) > 1 else [],
                                   "src": "sch_components_raw(pdftotext -bbox, 300dpi)"}

    # 2) 网表确认锚点(已审计纠错) — 权威来源, 覆盖 status
    for view_key, view in (("confirmed_anchors_top", "pcb_top"),
                           ("confirmed_anchors_bot", "pcb_bot")):
        for k, info in nt.get(view_key, {}).items():
            ref = norm_key(k)
            c = ensure(ref)
            c["views"][view] = {"px": info["label_px"],
                                "src": f"nettable/{view_key}",
                                "evidence": info.get("note", "")}
            c["status"] = "confirmed"
    # not_located → 待复核
    for s in nt.get("not_located", []):
        m = re.match(r"^([A-Z]{1,3}[0-9]{1,4}[A-Z]?)\b", s)
        if m:
            c = ensure(m.group(1))
            if c["status"] == "schematic_only":
                c["status"] = "unverified"
            c["note"] = s

    # 3) AI-OCR 运行命中 (非锚点位号的补充位置; 已确认坐标不被覆盖)
    n_ai = 0
    if args.ai_run:
        run = json.load(open(args.ai_run))
        best = {}
        for h in run.get("hits", []):
            if not h.get("refdes_like"):
                continue
            key = h["norm"]
            pri = (h["agree"], h["conf"])
            if key not in best or pri > best[key][0]:
                best[key] = (pri, h)
        for key, (pri, h) in best.items():
            c = ensure(key)
            if "pcb_top" not in c["views"]:
                c["views"]["pcb_top"] = {
                    "px": h["px"], "src": f"ai_ocr_run:{os.path.basename(args.ai_run)}",
                    "conf": h["conf"], "engines": h["engines"]}
                if c["status"] == "schematic_only":
                    c["status"] = "ocr_hit"
                n_ai += 1

    # 4) 信号链序
    universe = set(comps)
    for i, elem, refs in parse_chain_refs(nt.get("chain_order_schematic", []), universe):
        for r in refs:
            comps[r]["chain_elems"].append({"idx": i, "elem": elem})

    linked = [r for r, c in comps.items()
              if "schematic" in c["views"] and ("pcb_top" in c["views"] or "pcb_bot" in c["views"])]
    out = {
        "spec_version": SPEC_VERSION,
        "tool_version": TOOL_VERSION,
        "schema": {
            "space": "各视图 px 均为该视图 300dpi 渲染坐标(px): schematic=rxtxflow页, "
                     "pcb_top=top视图, pcb_bot=bot视图",
            "components.{ref}": "type=前缀推断的器件类别; name=名称/参数值(part_names); "
                                "views.{view}.px=[x,y]; views.{view}.src=来源文件/运行; "
                                "chain_elems=信号链序引用[{idx,elem}];",
            "status": "confirmed=网表双确认锚点 | ocr_hit=仅AI-OCR命中(待图签) | "
                      "schematic_only=仅原理图坐标 | unverified=旧锚点被降级待复核",
            "upgrade": "0.1: 首版; 未来加 package(封装)/pins(引脚相对坐标) 字段时升 0.2",
        },
        "device": os.path.basename(args.project.rstrip("/")),
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "schematic": os.path.basename(sch_p),
            "nettable": os.path.basename(nt_p),
            "ai_run": os.path.basename(args.ai_run) if args.ai_run else None,
            "part_names": os.path.basename(names_p) if names else None,
        },
        "stats": {"n_components": len(comps), "n_confirmed": sum(
            1 for c in comps.values() if c["status"] == "confirmed"),
            "n_ocr_hit": sum(1 for c in comps.values() if c["status"] == "ocr_hit"),
            "n_linked_sch_pcb": len(linked), "linked": sorted(linked)},
        "components": dict(sorted(comps.items())),
    }
    os.makedirs(os.path.dirname(out_p), exist_ok=True)
    with open(out_p, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"components={out['stats']['n_components']} "
          f"confirmed={out['stats']['n_confirmed']} ocr_hit={out['stats']['n_ocr_hit']} "
          f"sch<->pcb linked={out['stats']['n_linked_sch_pcb']}")
    print(f"-> {out_p}")


if __name__ == "__main__":
    main()
