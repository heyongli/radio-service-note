#!/usr/bin/env python3
"""probe_anchor.py - 锚点/位置探测工具

purpose: 在 PCB 图上探测指定 refdes 的位置, 验证索引坐标
format: Python 3 + PIL + onnxruntime
version: 0.2.0 (2026-09-15)
consumers: 标注校对, 索引验证
applies_to: 用 rapidocr 单独扫一个坐标找 refdes, 与 components_index 比对
parent_doc: ../../schema.md
"""

"""逐锚点探针: crop ±pad(px@300dpi), 多变体(原图/灰度/自动对比度, 2x/4x上采样)逐个跑多引擎,
报告每个锚点附近读到的 text+conf, 用于诊断 det/rec 失败模式与调参.

用法:
  python3 probe_anchor.py --anchor IC10 [--anchor X2 ... | --all-missed <report.json>]
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageOps


def get_engines(which):
    out = {}
    if "v4" in which:
        from rapidocr_onnxruntime import RapidOCR as R4

        out["v4"] = R4()
    if "v6" in which:
        from rapidocr import RapidOCR, OCRVersion

        out["v6"] = RapidOCR(
            params={"Det.ocr_version": OCRVersion.PPOCRV6, "Rec.ocr_version": OCRVersion.PPOCRV6,
                    "Cls.ocr_version": OCRVersion.PPOCRV5}
        )
    if "v5en" in which:
        from rapidocr import RapidOCR, OCRVersion, ModelType

        out["v5en"] = RapidOCR(
            params={"Det.ocr_version": OCRVersion.PPOCRV5, "Rec.ocr_version": OCRVersion.PPOCRV5,
                    "Rec.model_type": ModelType.EN, "Cls.ocr_version": OCRVersion.PPOCRV5}
        )
    return out


def run(eng, arr):
    r = eng(arr)
    if hasattr(r, "boxes"):  # rapidocr v3
        if r.boxes is None:
            return []
        return [(t, float(s)) for t, s in zip(r.txts, r.scores)]
    res, _ = eng(arr[:, :, ::-1])  # v4
    return [(t, float(s)) for _, t, s in res] if res else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchor", action="append", default=[], help="锚点名, 可多次")
    ap.add_argument("--all-missed", help="eval 报告 JSON, 对其 missed 全部探测")
    ap.add_argument("--engines", default="v4,v6")
    ap.add_argument("--img", default="/tmp/opencode/top600-1.png")
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--pad", type=float, default=80, help="crop 半径 px@300dpi")
    ap.add_argument("--anchors", default=os.path.join(os.path.dirname(__file__),
                 "../../projects/IC-2200H/nettable/top_pcb.json"))
    args = ap.parse_args()

    raw = json.load(open(args.anchors))["confirmed_anchors_top"]
    anchors = {k.split("_")[0]: v for k, v in raw.items()}  # J1_BNC -> J1
    names = args.anchor
    if args.all_missed:
        names += json.load(open(args.all_missed))["missed"]

    im = Image.open(args.img).convert("RGB")
    f = args.dpi / 300.0
    engs = get_engines(args.engines.split(","))

    for name in names:
        px = anchors[name]["label_px"] if isinstance(anchors[name], dict) else anchors[name]
        want = name.split("_")[0]
        cx, cy = px[0] * f, px[1] * f
        box = (int(cx - args.pad * f), int(cy - args.pad * f),
               int(cx + args.pad * f), int(cy + args.pad * f))
        crop = im.crop(box)
        variants = {
            "orig4x": crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS),
            "gray4x": ImageOps.autocontrast(crop.convert("L")).resize(
                (crop.width * 4, crop.height * 4), Image.LANCZOS
            ),
        }
        print(f"\n== {name} @300dpi{px} want='{want}'")
        for vname, vimg in variants.items():
            varr = np.asarray(vimg.convert("RGB"))
            for ename, eng in engs.items():
                try:
                    reads = run(eng, varr)
                except Exception as e:
                    print(f"  {vname}/{ename}: ERR {e}")
                    continue
                if reads:
                    print(f"  {vname}/{ename}: {reads}")
                else:
                    print(f"  {vname}/{ename}: (no text)")


if __name__ == "__main__":
    main()
