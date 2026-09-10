#!/usr/bin/env python3
"""AI 位号 OCR 两阶段管线 (替代 tesseract 多阈值管线).

Stage 1  全页扫: RapidOCR(PP-OCRv4/v5/v6) tile 3000/400 @600dpi — 抓中大字号文本.
Stage 2  候补读: 灰度掩码→连通域→尺寸过滤→cKDTree 聚类的文本候选区(Stage1 漏的),
         对每候选 crop 4x LANCZOS 上采样后双引擎(v4+v6)读 — 抓小/低对比位号.
输出: JSON(hits_all + provenance) + 视觉签收拼图 PNG (黄字标 bbox, 供人工双确认).

用法:
  python3 ai_refdes_ocr.py --img600 /tmp/opencode/top600-1.png --img300 projects/IC-2200H/render/top_hi-1.png \
      --out projects/IC-2200H/nettable/ai_ocr_top.json --sheet projects/IC-2200H/scan/ai_sign_sheet.png
"""
import argparse
import json
import os
import re
import time

import numpy as np
from PIL import Image, ImageDraw, ImageOps
from scipy import ndimage
from scipy.spatial import cKDTree

REFDES_RE = re.compile(r"^[A-Z]{1,3}[0-9]{1,4}[A-Z]?$")


def make_engines(which):
    engs = {}
    if "v4" in which:
        from rapidocr_onnxruntime import RapidOCR as R4

        engs["v4"] = R4()
    if "v6" in which:
        from rapidocr import RapidOCR, OCRVersion

        engs["v6"] = RapidOCR(
            params={"Det.ocr_version": OCRVersion.PPOCRV6, "Rec.ocr_version": OCRVersion.PPOCRV6,
                    "Cls.ocr_version": OCRVersion.PPOCRV5}
        )
    if "v5en" in which:
        from rapidocr import RapidOCR, OCRVersion, ModelType

        engs["v5en"] = RapidOCR(
            params={"Det.ocr_version": OCRVersion.PPOCRV5, "Rec.ocr_version": OCRVersion.PPOCRV5,
                    "Rec.model_type": ModelType.EN, "Cls.ocr_version": OCRVersion.PPOCRV5}
        )
    return engs


def read_engine(eng, arr):
    r = eng(arr)
    if hasattr(r, "boxes"):  # rapidocr v3
        if r.boxes is None:
            return []
        return [(np.asarray(b), t, float(s)) for b, t, s in zip(r.boxes, r.txts, r.scores)]
    res, _ = eng(arr[:, :, ::-1])  # rapidocr-onnxruntime v4
    return [(np.asarray(b), t, float(s)) for b, t, s in res] if res else []


def stage1_fullpage(engs, arr600, f2scale=0.5, tile=3000, overlap=400):
    hits = []
    H, W = arr600.shape[:2]
    step = tile - overlap
    for y in range(0, H, step):
        for x in range(0, W, step):
            sub = arr600[y:y + tile, x:x + tile]
            for ename, eng in engs.items():
                for box, txt, sc in read_engine(eng, sub):
                    hits.append({
                        "text": txt, "conf": round(sc, 3), "engine": ename, "stage": 1,
                        "px300": [round((x + box[:, 0].mean()) * f2scale),
                                  round((y + box[:, 1].mean()) * f2scale)],
                        "box300": [[round((x + px) * f2scale), round((y + py) * f2scale)]
                                   for px, py in box],
                    })
    return hits


def stage2_candidates(img300, min_h=5, max_h=28, max_w=120, cluster_r=20):
    """字形聚类找文本候选框 (300dpi 坐标), 返回 [(x0,y0,x1,y1), ...]."""
    g = np.asarray(img300.convert("L"))
    boxes = []
    for mask_fn in (lambda v: v < 110, lambda v: v > 200):  # 深字/浅字两极性
        lab, n = ndimage.label(mask_fn(g))
        if n == 0:
            continue
        objs = ndimage.find_objects(lab)
        pts = []
        for i, sl in enumerate(objs):
            if sl is None:
                continue
            h = sl[0].stop - sl[0].start
            w = sl[1].stop - sl[1].start
            if min_h <= h <= max_h and 2 <= w <= 24 and h * w > 12:
                pts.append(((sl[1].start + sl[1].stop) / 2, (sl[0].start + sl[0].stop) / 2))
        if len(pts) < 2:
            continue
        # cKDTree 近邻并查集聚类
        pts = np.array(pts)
        tree = cKDTree(pts)
        pairs = tree.query_pairs(cluster_r)
        parent = list(range(len(pts)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for a, b in pairs:
            parent[find(a)] = find(b)
        groups = {}
        for i in range(len(pts)):
            groups.setdefault(find(i), []).append(i)
        for idx in groups.values():
            xs, ys = pts[idx, 0], pts[idx, 1]
            x0, x1 = xs.min() - 6, xs.max() + 6
            y0, y1 = ys.min() - 6, ys.max() + 6
            w, h = x1 - x0, y1 - y0
            if 8 <= w <= max_w and 6 <= h <= max_h + 8 and len(idx) >= 1:
                boxes.append([int(x0), int(y0), int(x1), int(y1)])
    # 去重(两极性重复)
    uniq = []
    for b in boxes:
        if not any(abs(b[0] - u[0]) < 8 and abs(b[1] - u[1]) < 8 for u in uniq):
            uniq.append(b)
    return uniq


def stage2_read(engs, arr600, cands300, covered, upscale=4, pad300=14):
    hits = []
    f2 = 2.0  # 300 -> 600dpi
    for x0, y0, x1, y1 in cands300:
        if any(x0 < c[2] and x1 > c[0] and y0 < c[3] and y1 > c[1] for c in covered):
            continue  # stage1 已覆盖
        # 加 pad 保留上下文, 保证最小 crop 尺寸
        x0, y0, x1, y1 = x0 - pad300, y0 - pad300, x1 + pad300, y1 + pad300
        if x1 - x0 < 48:
            cxm = (x0 + x1) / 2
            x0, x1 = int(cxm - 24), int(cxm + 24)
        if y1 - y0 < 32:
            cym = (y0 + y1) / 2
            y0, y1 = int(cym - 16), int(cym + 16)
        px0, py0, px1, py1 = int(x0 * f2), int(y0 * f2), int(x1 * f2), int(y1 * f2)
        crop = arr600[py0:py1, px0:px1]
        if crop.size == 0:
            continue
        im = Image.fromarray(crop)
        im = im.resize((im.width * upscale, im.height * upscale), Image.LANCZOS)
        im = ImageOps.autocontrast(im.convert("L")).convert("RGB")
        a = np.asarray(im)
        for ename, eng in engs.items():
            for box, txt, sc in read_engine(eng, a):
                hits.append({
                    "text": txt, "conf": round(sc, 3), "engine": ename, "stage": 2,
                    "px300": [round(px0 / f2 + box[:, 0].mean() / (f2 * upscale)),
                              round(py0 / f2 + box[:, 1].mean() / (f2 * upscale))],
                    "box300": [[round(px0 / f2 + px / (f2 * upscale)), round(py0 / f2 + py / (f2 * upscale))]
                               for px, py in box],
                })
    return hits


def assemble_lines(hits, gap=22, dh=10):
    """同行碎片拼装: 同一 baseline 邻近 box 的文本按 x 序拼接 (解决 'C'+'22'+'5' 碎片)."""
    used = [False] * len(hits)
    out = []
    for i, h in enumerate(hits):
        if used[i]:
            continue
        bx = h["box300"]
        cx0, cy0 = min(p[0] for p in bx), min(p[1] for p in bx)
        cx1, cy1 = max(p[0] for p in bx), max(p[1] for p in bx)
        group = [h]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, g in enumerate(hits):
                if used[j]:
                    continue
                gx0 = min(p[0] for p in g["box300"])
                gx1 = max(p[0] for p in g["box300"])
                gy0 = min(p[1] for p in g["box300"])
                gy1 = max(p[1] for p in g["box300"])
                gyc = (gy0 + gy1) / 2
                cyc = (cy0 + cy1) / 2
                near_x = (gx0 - cx1 <= gap and gx0 >= cx0 - gap) or (cx0 - gx1 <= gap and cx0 >= gx0 - gap)
                if near_x and abs(gyc - cyc) <= dh and (
                    gx0 < cx1 + gap and gx1 > cx0 - gap
                ):
                    group.append(g)
                    used[j] = True
                    cx0, cx1 = min(cx0, gx0), max(cx1, gx1)
                    cy0, cy1 = min(cy0, gy0), max(cy1, gy1)
                    changed = True
        if len(group) == 1:
            out.append(h)
            continue
        group.sort(key=lambda z: min(p[0] for p in z["box300"]))
        text = "".join(g["text"] for g in group).upper()
        text = re.sub(r"(?<=[A-Z0-9])\s+(?=[A-Z0-9])", "", text)
        conf = round(sum(g["conf"] for g in group) / len(group), 3)
        px300 = [round(sum(g["px300"][0] for g in group) / len(group)),
                 round(sum(g["px300"][1] for g in group) / len(group))]
        out.append({
            "text": text, "conf": conf, "engine": "+".join(sorted({g["engine"] for g in group})),
            "stage": 2 if any(g["stage"] == 2 for g in group) else 1,
            "px300": px300,
            "box300": [[min(min(p[0] for p in g["box300"]) for g in group),
                        min(min(p[1] for p in g["box300"]) for g in group)],
                       [max(max(p[0] for p in g["box300"]) for g in group),
                        max(max(p[1] for p in g["box300"]) for g in group)]],
        })
    return out


def dedup_merge(hits, dist=25):
    """按 (归一文本, 坐标近邻) 去重; 双引擎同位一致 -> agree=True."""
    out = []
    for h in sorted(hits, key=lambda z: -z["conf"]):
        norm = re.sub(r"[^A-Z0-9]", "", h["text"].upper())
        same = [o for o in out if o["norm"] == norm
                and abs(o["px300"][0] - h["px300"][0]) <= dist
                and abs(o["px300"][1] - h["px300"][1]) <= dist]
        if same:
            same[0]["engines"].add(h["engine"])
            continue
        o = dict(h)
        o["norm"] = norm
        o["engines"] = {h["engine"]}
        out.append(o)
    for o in out:
        o["refdes_like"] = bool(REFDES_RE.match(o["norm"]))
        o["agree"] = len(o["engines"]) >= 2
        o["engines"] = sorted(o["engines"])
    return out


def sign_sheet(merged, img600, out_png, pad=50, cell=260):
    """命中坐标±pad crop 拼图, 黄字标注, 供人工视觉双确认."""
    f2 = 2.0
    im = Image.open(img600)
    n = len(merged)
    cols = max(1, min(8, n))
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (255, 255, 255))
    dr = ImageDraw.Draw(sheet)
    for i, h in enumerate(merged):
        cx, cy = h["px300"][0] * f2, h["px300"][1] * f2
        c = im.crop((max(0, cx - pad), max(0, cy - pad), cx + pad, cy + pad))
        c = c.resize((cell, cell), Image.LANCZOS)
        x, y = (i % cols) * cell, (i // cols) * cell
        sheet.paste(c, (x, y))
        dr.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(200, 200, 200))
        dr.text((x + 4, y + 4), f"{h['norm'] if h.get('norm') else h['text']} {h['conf']:.2f}",
                fill=(255, 180, 0))
        dr.text((x + 4, y + cell - 14), f"#{i} {','.join(h.get('engines', []))} s{h['stage']}",
                fill=(0, 120, 0))
    sheet.save(out_png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img600", required=True)
    ap.add_argument("--img300", help="300dpi 底图(用于字形聚类); 缺省用600dpi缩半")
    ap.add_argument("--engines", default="v4,v6")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sheet", help="视觉签收拼图输出")
    ap.add_argument("--only-refdes", action="store_true", help="输出只保留位号样式文本")
    args = ap.parse_args()

    t0 = time.perf_counter()
    arr600 = np.asarray(Image.open(args.img600).convert("RGB"))
    img300 = Image.open(args.img300) if args.img300 else Image.open(args.img600).resize(
        (arr600.shape[1] // 2, arr600.shape[0] // 2), Image.LANCZOS)
    engs = make_engines(args.engines.split(","))

    hits1 = stage1_fullpage(engs, arr600)
    covered = [h["box300"] for h in hits1]
    covered = [[min(p[0] for p in b), min(p[1] for p in b), max(p[0] for p in b), max(p[1] for p in b)]
               for b in covered]
    cands = stage2_candidates(img300)
    hits2 = stage2_read(engs, arr600, cands, covered)

    merged = dedup_merge(assemble_lines(hits1 + hits2))
    if args.only_refdes:
        merged = [m for m in merged if m["refdes_like"]]
    dt = time.perf_counter() - t0
    report = {
        "img600": os.path.abspath(args.img600),
        "img300": os.path.abspath(args.img300) if args.img300 else "(derived)",
        "engines": args.engines,
        "time_s": round(dt, 1),
        "n_stage1": len(hits1), "n_stage2": len(hits2), "n_merged": len(merged),
        "n_refdes": sum(1 for m in merged if m["refdes_like"]),
        "n_agree": sum(1 for m in merged if m["agree"]),
        "hits": [{k: m[k] for k in ("text", "norm", "conf", "engine", "engines", "agree",
                                     "stage", "px300", "refdes_like")} for m in merged],
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    if args.sheet:
        os.makedirs(os.path.dirname(args.sheet), exist_ok=True)
        sign_sheet([m for m in merged if m["refdes_like"]] or merged, args.img600, args.sheet)
    print(f"stage1={len(hits1)} stage2={len(hits2)} merged={len(merged)} "
          f"refdes={report['n_refdes']} agree={report['n_agree']} {report['time_s']}s")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
