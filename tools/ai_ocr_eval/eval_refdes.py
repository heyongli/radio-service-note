#!/usr/bin/env python3
"""对比 OCR/AI 引擎在 PCB 位号识别上的表现 (vs nettable confirmed_anchors ground truth).

用法:
  python3 eval_refdes.py --engine v4 --img <300dpi.png> [--dpi 300] [--tile 1500] [--overlap 200]
  python3 eval_refdes.py --engine v6 --img <600dpi.png> --dpi 600 --tile 3000 --overlap 400

引擎: v4=PP-OCRv4 mobile (rapidocr-onnxruntime), v5=PP-OCRv5 (rapidocr), v6=PP-OCRv6 small (rapidocr)
输出: JSON 报告写到 --out (默认 /tmp/opencode/aiocr_eval_report.json), 并打印摘要.
"""
import argparse
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image

# 位号宽松正则 (与 agent.md 约定一致, 不加白名单)
REFDES_RE = re.compile(r"^[A-Z]{1,3}[0-9]{1,4}[A-Z]?$")

ANCHORS_DEFAULT = os.path.join(
    os.path.dirname(__file__),
    "../../projects/IC-2200H/nettable/top_pcb.json",
)


def norm_label(s):
    """J1_BNC -> J1"""
    return s.split("_")[0].upper()


def load_anchors(path):
    with open(path) as f:
        d = json.load(f)
    out = {}
    for name, info in d.get("confirmed_anchors_top", {}).items():
        px = info["label_px"] if isinstance(info, dict) else info
        out[norm_label(name)] = (float(px[0]), float(px[1]))
    return out  # 300dpi 坐标系


def make_engine(name, max_side_len=None):
    if name == "v4":
        from rapidocr_onnxruntime import RapidOCR as R4

        return ("rapidocr-onnxruntime/PP-OCRv4-mobile", R4())
    if name in ("v5", "v6"):
        from rapidocr import RapidOCR, OCRVersion, ModelType

        ver = OCRVersion.PPOCRV5 if name == "v5" else OCRVersion.PPOCRV6
        params = {
            "Det.ocr_version": ver,
            "Rec.ocr_version": ver,
            "Cls.ocr_version": OCRVersion.PPOCRV5,  # cls 无 v6 版本, 用 v5 行分类器
        }
        if name == "v5":  # 英文专用 rec 对字母数字位号更准
            params["Rec.model_type"] = ModelType.EN
        if max_side_len:
            params["Global.max_side_len"] = int(max_side_len)
        return (f"rapidocr/PP-OCR{name}-small", RapidOCR(params=params))
    raise SystemExit(f"unknown engine {name}")


def unrot(rx, ry, k, W, H):
    """旋转坐标系(k=1,2,3 CCW, np.rot90)下 hit 坐标 -> 原 tile 坐标 (连续近似)."""
    if k == 1:
        return W - 1 - ry, rx
    if k == 2:
        return W - 1 - rx, H - 1 - ry
    return ry, H - 1 - rx


def run_engine(engine_desc, engine, img_arr):
    """统一返回 [(cx, cy, text, score)] 坐标为输入图像像素."""
    if engine_desc.startswith("rapidocr-onnxruntime"):
        result, _ = engine(img_arr[:, :, ::-1])  # BGR
        out = []
        if result:
            for box, txt, sc in result:
                box = np.asarray(box)
                out.append((float(box[:, 0].mean()), float(box[:, 1].mean()), txt, float(sc)))
        return out
    r = engine(img_arr)
    out = []
    if r.boxes is not None:
        for box, txt, sc in zip(r.boxes, r.txts, r.scores):
            box = np.asarray(box)
            out.append((float(box[:, 0].mean()), float(box[:, 1].mean()), txt, float(sc)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=["v4", "v5", "v6"])
    ap.add_argument("--img", required=True)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--tile", type=int, default=0, help="tile 边长, 0=整页")
    ap.add_argument("--overlap", type=int, default=0)
    ap.add_argument("--anchors", default=ANCHORS_DEFAULT)
    ap.add_argument("--tol", type=float, default=60.0, help="匹配容差(px, 按300dpi)")
    ap.add_argument("--upscale", type=float, default=1.0, help="tile LANCZOS 上采样倍数")
    ap.add_argument("--rots", default="0", help="tile 旋转 pass, 逗号分隔如 0,90,270")
    ap.add_argument("--max-side-len", type=int, default=None, help="Global.max_side_len 覆盖")
    ap.add_argument("--preprocess", default="none", choices=["none", "gray", "graycontrast"])
    ap.add_argument("--out", default="/tmp/opencode/aiocr_eval_report.json")
    args = ap.parse_args()

    anchors = load_anchors(args.anchors)
    im = Image.open(args.img).convert("RGB")
    W, H = im.size
    scale = 300.0 / args.dpi  # 图像坐标(px@dpi) -> 300dpi 坐标
    arr = np.asarray(im)
    rots = [int(r) % 360 for r in args.rots.split(",") if r.strip()]
    rots_k = [({0: 0, 90: 1, 180: 2, 270: 3}[r]) for r in rots]

    desc, engine = make_engine(args.engine, args.max_side_len)
    t0 = time.perf_counter()
    hits = []  # (cx300, cy300, text, score)

    def ocr_tile(tile, ox, oy):
        """tile: np.array(HxWx3), ox/oy: tile 在原图的偏移(px@dpi)."""
        th_, tw_ = tile.shape[:2]
        up = args.upscale
        if up != 1.0:
            tile = np.asarray(
                Image.fromarray(tile).resize((int(tw_ * up), int(th_ * up)), Image.LANCZOS)
            )
        if args.preprocess == "gray":
            tile = np.asarray(Image.fromarray(tile).convert("L").convert("RGB"))
        elif args.preprocess == "graycontrast":
            from PIL import ImageOps

            tile = np.asarray(
                ImageOps.autocontrast(Image.fromarray(tile).convert("L")).convert("RGB")
            )
        for k in rots_k:
            t = np.rot90(tile, k) if k else tile
            for cx, cy, txt, sc in run_engine(desc, engine, t):
                if up != 1.0:
                    cx, cy = cx / up, cy / up
                if k:
                    cx, cy = unrot(cx, cy, k, tw_, th_)
                hits.append(((ox + cx) * scale, (oy + cy) * scale, txt, sc))

    if args.tile <= 0:
        ocr_tile(arr, 0, 0)
    else:
        step = args.tile - args.overlap
        for y in range(0, H, step):
            for x in range(0, W, step):
                x2, y2 = min(x + args.tile, W), min(y + args.tile, H)
                tile = arr[y:y2, x:x2]
                if tile.size == 0:
                    continue
                ocr_tile(tile, x, y)
    dt = time.perf_counter() - t0

    tol = args.tol
    matched, unmatched_hits = {}, []
    used = set()
    for cx, cy, txt, sc in hits:
        lab = txt.strip().upper().replace(" ", "")
        lab = lab.replace("1", "I").replace("0", "O")  # 简单混淆归一(只用于匹配尝试)
        best = None
        for name, (ax, ay) in anchors.items():
            if name in used:
                continue
            if abs(cx - ax) <= tol and abs(cy - ay) <= tol and (
                lab == name or txt.strip().upper() == name
            ):
                best = name
                break
        if best:
            used.add(best)
            matched[best] = {"text": txt, "conf": round(sc, 3), "px300": [round(cx), round(cy)]}
        else:
            unmatched_hits.append({"text": txt, "conf": round(sc, 3), "px300": [round(cx), round(cy)]})

    missed = [n for n in anchors if n not in used]
    report = {
        "engine": desc,
        "img": os.path.basename(args.img),
        "dpi": args.dpi,
        "tile": args.tile or "full",
        "upscale": args.upscale,
        "rots": rots,
        "preprocess": args.preprocess,
        "time_s": round(dt, 1),
        "n_hits": len(hits),
        "n_anchors": len(anchors),
        "n_matched": len(matched),
        "matched": matched,
        "missed": missed,
        "refdes_like_unmatched": sum(
            1 for h in unmatched_hits if REFDES_RE.match(h["text"].strip().upper())
        ),
        "hits_all": [
            {"text": t, "conf": round(sc, 3), "px300": [round(cx), round(cy)]}
            for cx, cy, t, sc in hits
        ],
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print(
        f"[{desc}] {report['img']} dpi={args.dpi} tile={report['tile']}: "
        f"{report['n_matched']}/{report['n_anchors']} anchors, {report['n_hits']} hits, "
        f"{report['time_s']}s  ->  {args.out}"
    )
    print("  matched:", " ".join(sorted(matched)))
    print("  MISSED :", " ".join(sorted(missed)))


if __name__ == "__main__":
    main()
