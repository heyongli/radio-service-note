#!/usr/bin/env python3
"""ai_refdes_ocr.py - PCB 位号 AI OCR 工具

purpose: PCB 图片 → AI 识别 → 元器件位号 + 坐标 (box/center/agree)
format: Python 3 + PIL/numpy/scipy + rapidocr/onnxruntime; 全参数 CLI (argparse)
version: 0.3.0 (2026-09-15 加入 --progress / --checkpoint / --jobs 多进程并行)
consumers: tools/render_rx_flow.py, make_wpts_from_index.py
applies_to: PCB top/bot/sch OCR (任何 view/任何 dpi)
parent_doc: ../../schema.md

核心流程:
  stage1 (全页 grid/contour) → raw_stage1 hits
  stage2 (字形聚类, 对 stage1 未覆盖的候选 crop+4x 上采样) → raw_stage2 hits
  合并 dedup_merge → 最终 hits (含 agree 标记)
"""

"""AI 位号 OCR 两阶段管线 (替代 tesseract 多阈值管线).

设计要点:
  * 工具是工具, 参数是参数: 所有阈值/尺寸/引擎全部 CLI 可传, 不再有魔法常数.
  * 多引擎协同: stage1(全页扫)/stage2(候补crop读) 可配不同引擎组合, 各做擅长的事
    (v4-mobile 全页小字检出强, v6 crop 读数稳, tess 可作第三方仲裁).
  * 每次运行的 JSON 永久落盘(runs-dir), 含 tool_version/日期/完整参数快照/脚本hash,
    用于不同参数间对比与数据校准; --out 只是指向最新运行的副本.

Stage 1  全页扫: 指定引擎 tile 网格扫描, 可选 tile 上采样与旋转 pass.
Stage 2  候补读: 灰度双极性掩码→连通域→尺寸过滤→cKDTree 聚类找 stage1 漏掉的
         小字候选区, crop+上采样+对比度增强后用指定引擎读.
后处理   同引擎同行碎片保守拼装 → 跨引擎同位去重合并(双引擎一致 agree=True).

用法示例:
  python3 ai_refdes_ocr.py --img600 /tmp/opencode/top600-1.png \
      --img300 projects/IC-2200H/render/top_hi-1.png \
      --runs-dir projects/IC-2200H/nettable/ai_ocr_runs \
      --sheet projects/IC-2200H/scan/ai_sign_sheet.png --tag baseline
  (每次运行自动写入 runs-dir/20260910_1530_baseline_v0.2.0_<shorthash>.json)
"""
import argparse
import datetime
import functools
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image, ImageDraw, ImageOps
from scipy import ndimage
from scipy.spatial import cKDTree

TOOL_VERSION = "0.3.0"
REFDES_RE = re.compile(r"^[A-Z]{1,3}[0-9]{1,4}[A-Z]?$")

_ABORT = False


def _sigint(sig, frame):
    global _ABORT
    _ABORT = True


class Progress:
    """每个任务块完成即报告进度 + 定期落盘中间结果 (可 --reuse-* 续跑)."""

    def __init__(self, phase, stage, total, cp_path, out_dpi, img_dpi, cp_every=120):
        self.phase = phase
        self.stage = stage
        self.total = total
        self.cp_path = cp_path
        self.out_dpi = out_dpi
        self.img_dpi = img_dpi
        self.cp_every = cp_every
        self.t0 = time.perf_counter()
        self.last_cp = self.t0
        self.last_line = self.t0
        self.n = 0
        self.hits = []
        self.done_tiles = []

    def _line(self, hits):
        el = time.perf_counter() - self.t0
        per = el / max(1, self.n)
        eta = per * max(0, self.total - self.n)
        pct = 100.0 * self.n / max(1, self.total)
        return (f"[{self.phase}] {self.n}/{self.total} ({pct:4.1f}%) "
                f"elapsed {el:5.0f}s ETA {eta:5.0f}s tile-avg {per:4.1f}s "
                f"hits={len(hits)}")

    def tick(self, hits, tile_idx=None):
        self.n += 1
        if tile_idx is not None:
            self.done_tiles.append(tile_idx)
        self.hits = hits
        line = self._line(hits)
        if sys.stderr.isatty():
            sys.stderr.write("\r" + line + "    ")
            sys.stderr.flush()
        elif time.perf_counter() - self.last_line > 5:
            self.last_line = time.perf_counter()
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
        now = time.perf_counter()
        if _ABORT:
            self.save_hits(hits)
            sys.stderr.write("\n[interrupted] checkpoint saved\n")
            sys.stderr.flush()
            sys.exit(130)
        if self.cp_path and (now - self.last_cp) >= self.cp_every:
            self.last_cp = now
            self.save_hits(hits)

    def save_hits(self, hits):
        if not self.cp_path:
            return
        key = f"raw_stage{self.stage}"
        cp = {"run_save": True, "phase": self.phase, "stage": self.stage,
              "created": datetime.datetime.now().isoformat(timespec="seconds"),
              "params": {"out_dpi": self.out_dpi, "img_dpi": self.img_dpi},
              key: hits,
              "_checkpoint_n": self.n, "_checkpoint_total": self.total,
              "_done_tiles": sorted(set(self.done_tiles))}
        os.makedirs(os.path.dirname(self.cp_path) or ".", exist_ok=True)
        tmp = self.cp_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cp, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.cp_path)
        sys.stderr.write(f"\n[checkpoint] stage{self.stage} n={len(hits)} "
                         f"{self.n}/{self.total} -> {self.cp_path}\n")
        sys.stderr.flush()

    def done(self, hits):
        self._line(hits)
        if sys.stderr.isatty():
            sys.stderr.write("\r" + self._line(hits) + "\n")
        else:
            sys.stderr.write(self._line(hits) + "\n")
        sys.stderr.flush()
        self.save_hits(hits)

    def every(self):
        return self.cp_every


def _versions():
    v = {"rapidocr": None, "rapidocr_onnxruntime": None, "tesseract": None}
    try:
        import rapidocr

        v["rapidocr"] = getattr(rapidocr, "__version__", None)
    except Exception:
        pass
    try:
        from importlib.metadata import version

        v["rapidocr_onnxruntime"] = version("rapidocr-onnxruntime")
    except Exception:
        pass
    try:
        v["tesseract"] = subprocess.run(["tesseract", "--version"], capture_output=True,
                                       text=True).stdout.splitlines()[0]
    except Exception:
        pass
    return {k: x for k, x in v.items() if x}


def _patch_dml():
    """Windows 原生运行: monkey-patch rapidocr 强制 DirectML (rapidocr use_dml bug)."""
    import sys
    if sys.platform != "win32":
        return False
    try:
        from dml_helper import enable_dml
    except ImportError:
        try:
            from ai_ocr_eval.dml_helper import enable_dml
        except ImportError:
            raise SystemExit("DirectML 需要 dml_helper.py; 请与 ai_refdes_ocr.py 同目录")
    return enable_dml()


def make_engine(name, max_side_len=None, use_dml=False):
    """引擎注册表: v4 / v5en / v6 / tess — 返回 (引擎对象, 描述).
    use_dml=True 时(Windows 原生运行) 强制 rapidocr v5/v6 走 DirectML.
    """
    if use_dml:
        _patch_dml()
    if name == "v4":
        from rapidocr_onnxruntime import RapidOCR as R4

        return R4(), "rapidocr-onnxruntime/PP-OCRv4-mobile"
    if name in ("v6", "v5en", "v5s"):
        from rapidocr import RapidOCR, OCRVersion, ModelType

        params = {"Cls.ocr_version": OCRVersion.PPOCRV5}
        if name == "v6":
            params.update({"Det.ocr_version": OCRVersion.PPOCRV6, "Rec.ocr_version": OCRVersion.PPOCRV6})
            desc = "rapidocr/PP-OCRv6-small"
        elif name == "v5en":
            params.update({"Det.ocr_version": OCRVersion.PPOCRV5, "Rec.ocr_version": OCRVersion.PPOCRV5,
                           "Rec.model_type": ModelType.EN})
            desc = "rapidocr/PP-OCRv5-en"
        else:
            params.update({"Det.ocr_version": OCRVersion.PPOCRV5,
                           "Det.model_type": ModelType.SERVER,
                           "Rec.ocr_version": OCRVersion.PPOCRV5,
                           "Rec.model_type": ModelType.SERVER})
            desc = "rapidocr/PP-OCRv5-server"
        if max_side_len:
            params["Global.max_side_len"] = int(max_side_len)
        return RapidOCR(params=params), desc
    if name == "tess":
        return ("tesseract", "tesseract")
    raise SystemExit(f"unknown engine: {name}")


def read_engine(eng, eng_name, arr):
    """统一返回 [(box(4x2) 或 [(x0,y0),(x1,y1)], text, conf)]."""
    if eng_name == "tess":
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            Image.fromarray(arr).save(f.name)
            tsv = subprocess.run(
                ["tesseract", f.name, "stdout", "--psm", "11", "tsv"],
                capture_output=True, text=True).stdout
        os.unlink(f.name)
        out = []
        for line in tsv.splitlines()[1:]:
            c = line.split("\t")
            if len(c) == 12 and c[0] == "5" and c[11].strip():
                l, t, w, h = int(c[6]), int(c[7]), int(c[8]), int(c[9])
                out.append((np.array([[l, t], [l + w, t], [l + w, t + h], [l, t + h]], float),
                            c[11], float(c[10]) / 100.0))
        return out
    r = eng(arr)
    if hasattr(r, "boxes"):  # rapidocr v3
        if r.boxes is None:
            return []
        return [(np.asarray(b), t, float(s)) for b, t, s in zip(r.boxes, r.txts, r.scores)]
    res, _ = eng(arr[:, :, ::-1])  # rapidocr-onnxruntime v4
    return [(np.asarray(b), t, float(s)) for b, t, s in res] if res else []


def unrot(rx, ry, k, W, H):
    """np.rot90(k=1,2,3) 坐标系下 hit -> 原 tile 坐标 (连续近似)."""
    if k == 1:
        return W - 1 - ry, rx
    if k == 2:
        return W - 1 - rx, H - 1 - ry
    return ry, H - 1 - rx


def _grid_tile_init(_arr, _eng, _up):
    """子进程初始化: 传递整图共享引用 + 引擎(仅 fork 时有效)."""
    global _T_ARR, _T_ENG, _T_UP
    _T_ARR, _T_ENG, _T_UP = _arr, _eng, _up


def _grid_tile_work(task):
    """单 tile 所有旋转/引擎扫描, 返回该 tile 的 hits (px 为 out-dpi 空间)."""
    global _T_ARR, _T_ENG, _T_UP
    y, x, tile, overlap, rots, scale = task
    H, W = _T_ARR.shape[:2]
    up = _T_UP
    arr = _T_ARR
    engs = _T_ENG
    hits = []
    sub = arr[y:y + tile, x:x + tile]
    th, tw = sub.shape[:2]
    if up != 1.0:
        sub = np.asarray(Image.fromarray(sub).resize(
            (int(tw * up), int(th * up)), Image.LANCZOS))
    for k in [({0: 0, 90: 1, 180: 2, 270: 3}[r]) for r in rots]:
        t = np.rot90(sub, k) if k else sub
        for ename, (eng, _) in engs.items():
            for box, txt, sc in read_engine(eng, ename, t):
                cx, cy = box[:, 0].mean(), box[:, 1].mean()
                if up != 1.0:
                    cx, cy = cx / up, cy / up
                if k:
                    cx, cy = unrot(cx, cy, k, tw, th)
                hits.append({
                    "text": txt, "conf": round(sc, 3), "engine": ename, "stage": 1,
                    "px": [round((x + cx) * scale), round((y + cy) * scale)],
                    "box": [[round((x + px / up) * scale), round((y + py / up) * scale)]
                            for px, py in box] if up != 1.0 else
                          [[round((x + px) * scale), round((y + py) * scale)] for px, py in box],
                })
    return hits


def stage1_grid(engs, arr, scale, P, report=None, resume_done=None):
    hits = []
    H, W = arr.shape[:2]
    up = P.stage1_upscale
    rots = [int(r) % 360 for r in P.stage1_rots.split(",") if r.strip() != ""]
    jobs = max(1, P.jobs)
    tiles = []
    for y in range(0, H, P.tile - P.overlap):
        for x in range(0, W, P.tile - P.overlap):
            tiles.append((y, x))
    resume_done = resume_done or set()
    todo_idx = [i for i in range(len(tiles)) if i not in resume_done]
    if jobs == 1:
        _grid_tile_init(arr, engs, up)  # 串行也初始化全局(供 _grid_tile_work 读)
        for i, ti in enumerate(todo_idx):
            y, x = tiles[ti]
            if report:
                report(i, len(tiles), hits, ti)
            hits += _grid_tile_work((y, x, P.tile, P.overlap, rots, scale))
        return hits
    init = functools.partial(_grid_tile_init, arr, engs, up)
    tasks = [(tiles[ti][0], tiles[ti][1], P.tile, P.overlap, rots, scale) for ti in todo_idx]
    with multiprocessing.Pool(jobs, initializer=init) as pool:
        for i, part in enumerate(pool.imap_unordered(_grid_tile_work, tasks)):
            if report:
                report(i, len(tiles), hits, todo_idx[i])
            hits += part
    return hits


def content_regions(arr, P):
    """内容轮廓检测(传统 cv2, 无 AI): 双极性掩码并集 → 闭运算成块 → 连通域 →
    过大区域沿长轴二分 → 子块内重取紧 bbox. 返回 [x0,y0,x1,y1] (img px)."""
    import cv2

    g = np.asarray(Image.fromarray(arr).convert("L"))
    mask = ((g < P.mask_dark) | (g > P.mask_light)).astype(np.uint8) if P.mask_light > 0 \
        else (g < P.mask_dark).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (P.close_kx, P.close_ky))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if area >= P.content_min_area:
            boxes.append([x, y, x + w, y + h])
    # 二分细分(过长/过宽的块沿长轴切半), 子块内重取紧 bbox
    out = []
    stack = boxes
    while stack:
        b = stack.pop()
        w, h = b[2] - b[0], b[3] - b[1]
        if w > P.region_max or h > P.region_max:
            if w >= h:
                mid = (b[0] + b[2]) // 2
                stack += [[b[0], b[1], mid, b[3]], [mid, b[1], b[2], b[3]]]
            else:
                mid = (b[1] + b[3]) // 2
                stack += [[b[0], b[1], b[2], mid], [b[0], mid, b[2], b[3]]]
        else:
            out.append(b)
    # 去重(二分可能在内容稀疏处产生空/重子块, 再按 mask 紧化)
    tight = []
    for x0, y0, x1, y1 in out:
        sub = mask[y0:y1, x0:x1]
        ys, xs = np.nonzero(sub)
        if len(xs) < P.content_min_area / 4:
            continue
        tight.append([x0 + xs.min(), y0 + ys.min(), x0 + xs.max() + 1, y0 + ys.max() + 1])
    return tight


def stage1_contour(engs, arr, scale, P, report=None):
    hits = []
    H, W = arr.shape[:2]
    up = P.stage1_upscale
    rots = [int(r) % 360 for r in P.stage1_rots.split(",") if r.strip() != ""]
    regions = content_regions(arr, P)
    for i, (x0, y0, x1, y1) in enumerate(regions):
        if report:
            report(i, len(regions), hits)
        x0, y0 = max(0, x0 - P.region_grow), max(0, y0 - P.region_grow)
        x1, y1 = min(W, x1 + P.region_grow), min(H, y1 + P.region_grow)
        sub = arr[y0:y1, x0:x1]
        th, tw = sub.shape[:2]
        if up != 1.0:
            sub = np.asarray(Image.fromarray(sub).resize(
                (int(tw * up), int(th * up)), Image.LANCZOS))
        for k in [({0: 0, 90: 1, 180: 2, 270: 3}[r]) for r in rots]:
            t = np.rot90(sub, k) if k else sub
            for ename, (eng, _) in engs.items():
                for box, txt, sc in read_engine(eng, ename, t):
                    cx, cy = box[:, 0].mean(), box[:, 1].mean()
                    if up != 1.0:
                        cx, cy = cx / up, cy / up
                    if k:
                        cx, cy = unrot(cx, cy, k, tw, th)
                    hits.append({
                        "text": txt, "conf": round(sc, 3), "engine": ename, "stage": 1,
                        "px": [round((x0 + cx) * scale), round((y0 + cy) * scale)],
                        "box": [[round((x0 + px / up) * scale), round((y0 + py / up) * scale)]
                                for px, py in box] if up != 1.0 else
                              [[round((x0 + px) * scale), round((y0 + py) * scale)] for px, py in box],
                    })
    return hits, len(regions)


def stage2_candidates(img300, P):
    """字形聚类找文本候选框 (px 坐标同 img300), 返回 [[x0,y0,x1,y1], ...]."""
    g = np.asarray(img300.convert("L"))
    boxes = []
    for th in (P.mask_dark, P.mask_light):
        if th <= 0:
            continue
        mask = (g < th) if th < 128 else (g > th)
        lab, n = ndimage.label(mask)
        if n == 0:
            continue
        pts = []
        for sl in ndimage.find_objects(lab):
            if sl is None:
                continue
            h = sl[0].stop - sl[0].start
            w = sl[1].stop - sl[1].start
            if P.glyph_min_h <= h <= P.glyph_max_h and P.glyph_min_w <= w <= P.glyph_max_w \
                    and h * w >= P.glyph_min_area:
                pts.append(((sl[1].start + sl[1].stop) / 2, (sl[0].start + sl[0].stop) / 2))
        if len(pts) < 2:
            continue
        pts = np.array(pts)
        pairs = cKDTree(pts).query_pairs(P.cluster_r)
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
            if P.cand_min_w <= x1 - x0 <= P.cand_max_w and P.cand_min_h <= y1 - y0:
                boxes.append([int(x0), int(y0), int(x1), int(y1)])
    uniq = []
    for b in boxes:
        if not any(abs(b[0] - u[0]) < 8 and abs(b[1] - u[1]) < 8 for u in uniq):
            uniq.append(b)
    return uniq


def stage2_read(engs, arr_ref, cands_imgpx, covered, P, scale, report=None):
    """cands_imgpx: 主底图坐标系下的候选框; scale: 主底图px -> out px;
    候选框来自低分辨率图的会先乘 f_low 转到主底图坐标系."""
    hits = []
    up = P.stage2_upscale
    for i, (x0, y0, x1, y1) in enumerate(cands_imgpx):
        if report:
            report(i, len(cands_imgpx), hits)
        if covered and any(x0 < c[2] and x1 > c[0] and y0 < c[3] and y1 > c[1] for c in covered):
            continue
        x0, y0, x1, y1 = x0 - P.crop_pad, y0 - P.crop_pad, x1 + P.crop_pad, y1 + P.crop_pad
        if x1 - x0 < P.min_crop_w:
            m = (x0 + x1) / 2
            x0, x1 = m - P.min_crop_w / 2, m + P.min_crop_w / 2
        if y1 - y0 < P.min_crop_h:
            m = (y0 + y1) / 2
            y0, y1 = m - P.min_crop_h / 2, m + P.min_crop_h / 2
        px0, py0, px1, py1 = int(max(0, x0)), int(max(0, y0)), int(x1), int(y1)
        crop = arr_ref[py0:py1, px0:px1]
        if crop.size == 0:
            continue
        im = Image.fromarray(crop)
        im = im.resize((im.width * up, im.height * up), Image.LANCZOS)
        if P.stage2_preprocess == "gray":
            im = im.convert("L").convert("RGB")
        elif P.stage2_preprocess == "graycontrast":
            im = ImageOps.autocontrast(im.convert("L")).convert("RGB")
        elif P.stage2_preprocess == "invert":
            im = ImageOps.invert(ImageOps.autocontrast(im.convert("L"))).convert("RGB")
        a = np.asarray(im)
        for ename, (eng, _) in engs.items():
            for box, txt, sc in read_engine(eng, ename, a):
                ibx = px0 + box[:, 0].mean() / up  # 主底图 px
                iby = py0 + box[:, 1].mean() / up
                hits.append({
                    "text": txt, "conf": round(sc, 3), "engine": ename, "stage": 2,
                    "px": [round(ibx * scale), round(iby * scale)],
                    "box": [[round((px0 + px / up) * scale), round((py0 + py / up) * scale)]
                            for px, py in box],
                })
    return hits


def _bbox(b):
    return [min(p[0] for p in b), min(p[1] for p in b), max(p[0] for p in b), max(p[1] for p in b)]


def assemble_lines(hits, P):
    """同引擎同行碎片保守拼装 (参数: asm_gap/asm_dh/asm_maxfrag)."""
    def alnum(s):
        return re.sub(r"[^A-Z0-9]", "", s.upper())

    used = [False] * len(hits)
    out = []
    for i, h in enumerate(hits):
        if used[i]:
            continue
        if len(alnum(h["text"])) > P.asm_maxfrag:
            out.append(h)
            used[i] = True
            continue
        cx0, cy0, cx1, cy1 = _bbox(h["box"])
        group, used[i] = [h], True
        changed = True
        while changed:
            changed = False
            for j, g in enumerate(hits):
                if used[j] or len(alnum(g["text"])) > P.asm_maxfrag:
                    continue
                gx0, gy0, gx1, gy1 = _bbox(g["box"])
                near_x = (0 <= gx0 - cx1 <= P.asm_gap) or (0 <= cx0 - gx1 <= P.asm_gap)
                if near_x and abs((gy0 + gy1) / 2 - (cy0 + cy1) / 2) <= P.asm_dh:
                    group.append(g)
                    used[j] = True
                    cx0, cx1 = min(cx0, gx0), max(cx1, gx1)
                    cy0, cy1 = min(cy0, gy0), max(cy1, gy1)
                    changed = True
        if len(group) == 1:
            out.append(h)
            continue
        group.sort(key=lambda z: min(p[0] for p in z["box"]))
        text = "".join(g["text"] for g in group).upper()
        text = re.sub(r"(?<=[A-Z0-9])\s+(?=[A-Z0-9])", "", text)
        out.append({
            "text": text, "conf": round(sum(g["conf"] for g in group) / len(group), 3),
            "engine": group[0]["engine"], "stage": 2 if any(g["stage"] == 2 for g in group) else 1,
            "px": [round(sum(g["px"][0] for g in group) / len(group)),
                   round(sum(g["px"][1] for g in group) / len(group))],
            "box": [[min(min(p[0] for p in g["box"]) for g in group),
                     min(min(p[1] for p in g["box"]) for g in group)],
                    [max(max(p[0] for p in g["box"]) for g in group),
                     max(max(p[1] for p in g["box"]) for g in group)]],
        })
    return out


def dedup_merge(hits, dist):
    out = []
    for h in sorted(hits, key=lambda z: -z["conf"]):
        norm = re.sub(r"[^A-Z0-9]", "", h["text"].upper())
        same = [o for o in out if o["norm"] == norm
                and abs(o["px"][0] - h["px"][0]) <= dist
                and abs(o["px"][1] - h["px"][1]) <= dist]
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


def sign_sheet(merged, img, out_png, P):
    im = Image.open(img)
    sf = P.img_dpi / P.out_dpi  # out px -> img px
    n = len(merged)
    cols = max(1, min(8, n))
    rows = (n + cols - 1) // cols
    cell = P.sheet_cell
    sheet = Image.new("RGB", (cols * cell, rows * cell), (255, 255, 255))
    dr = ImageDraw.Draw(sheet)
    for i, h in enumerate(merged):
        cx, cy = h["px"][0] * sf, h["px"][1] * sf
        c = im.crop((max(0, cx - P.sheet_pad), max(0, cy - P.sheet_pad),
                     cx + P.sheet_pad, cy + P.sheet_pad))
        c = c.resize((cell, cell), Image.LANCZOS)
        x, y = (i % cols) * cell, (i // cols) * cell
        sheet.paste(c, (x, y))
        dr.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(200, 200, 200))
        dr.text((x + 4, y + 4), f"{h['norm']} {h['conf']:.2f}", fill=(255, 180, 0))
        dr.text((x + 4, y + cell - 14), f"#{i} {','.join(h['engines'])} s{h['stage']}",
                fill=(0, 120, 0))
    sheet.save(out_png)


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--img", required=True, help="主底图(通常 600dpi 渲染)")
    ap.add_argument("--img-dpi", type=int, default=600, help="主底图 dpi")
    ap.add_argument("--out-dpi", type=int, default=300,
                    help="输出坐标所在 dpi (px 值 = out-dpi 空间)")
    ap.add_argument("--img-low", help="低分辨率底图(字形聚类用, 缺省自动缩半)")
    ap.add_argument("--preset", choices=["fast", "full"], default=None,
                    help="fast=仅stage1+v4(~20s 出全景初稿); full=两阶段双引擎(默认各参数生效基础)")
    ap.add_argument("--stages", default=None, help="执行的 stage, 逗号分隔 (缺省按 preset/默认 1,2)")
    ap.add_argument("--reuse-stage1", help="复用某次运行 JSON 的 stage1 命中(跳过 stage1 计算); "
                   "优先读其 raw_stage1, 缺省读 stage==1 的 hits; 保存算力的逐步细化关键参数")
    ap.add_argument("--resume-stage1", action="store_true",
                   help="跳过 --checkpoint 中已记录完成(_done_tiles)的 stage1 tile, 只补扫剩余")
    ap.add_argument("--reuse-stage2", help="复用某次运行 JSON 的 stage2 命中(跳过 stage2 计算)")
    # --- stage 1 ---
    ap.add_argument("--stage1-mode", default="grid", choices=["grid", "contour"],
                    help="grid=盲tile网格; contour=内容轮廓检测+二分细分(跳过空白区)")
    ap.add_argument("--jobs", type=int, default=1,
                    help="stage1 tile 并行进程数(默认1=串行; 多核大图建议设核数-1)")
    ap.add_argument("--stage1-engines", default="v4", help="全页扫引擎: v4,v5en,v6,tess")
    ap.add_argument("--tile", type=int, default=3000, help="stage1 tile 边长(px@img-dpi)")
    ap.add_argument("--overlap", type=int, default=400)
    ap.add_argument("--stage1-upscale", type=float, default=1.0, help="tile/region 上采样倍数")
    ap.add_argument("--stage1-rots", default="0", help="tile 旋转 pass: 0,90,180,270")
    ap.add_argument("--max-side-len", type=int, default=0,
                    help="rapidocr Global.max_side_len 覆盖(0=库默认)")
    ap.add_argument("--content-min-area", type=int, default=300,
                    help="contour模式: 内容连通域最小面积px(去噪点)")
    ap.add_argument("--close-kx", type=int, default=25, help="contour模式: 闭运算核宽px")
    ap.add_argument("--close-ky", type=int, default=9, help="contour模式: 闭运算核高px")
    ap.add_argument("--region-max", type=int, default=2000,
                    help="contour模式: 区域超过此边长沿长轴二分")
    ap.add_argument("--region-grow", type=int, default=60,
                    help="contour模式: 区域外扩px(给det留上下文)")
    # --- stage 2 ---
    ap.add_argument("--stage2-engines", default="v4,v6", help="候补 crop 引擎")
    ap.add_argument("--dml", action="store_true",
                    help="Windows 原生运行时启用 DirectML (rapidocr use_dml=True)")
    ap.add_argument("--glyph-min-h", type=int, default=5, help="单字形高范围(低分辨率图px)")
    ap.add_argument("--glyph-max-h", type=int, default=28)
    ap.add_argument("--glyph-min-w", type=int, default=2)
    ap.add_argument("--glyph-max-w", type=int, default=24)
    ap.add_argument("--glyph-min-area", type=int, default=12)
    ap.add_argument("--cluster-r", type=float, default=20, help="字形聚类近邻半径px")
    ap.add_argument("--cand-min-w", type=int, default=8)
    ap.add_argument("--cand-max-w", type=int, default=120)
    ap.add_argument("--cand-min-h", type=int, default=6)
    ap.add_argument("--mask-dark", type=int, default=110, help="深字阈值(0=关)")
    ap.add_argument("--mask-light", type=int, default=200, help="浅字阈值(0=关)")
    ap.add_argument("--crop-pad", type=int, default=14, help="候选框外扩px")
    ap.add_argument("--min-crop-w", type=int, default=48)
    ap.add_argument("--min-crop-h", type=int, default=32)
    ap.add_argument("--stage2-upscale", type=int, default=4, help="crop 上采样倍数")
    ap.add_argument("--stage2-preprocess", default="graycontrast",
                    choices=["none", "gray", "graycontrast", "invert"])
    # --- 后处理 ---
    ap.add_argument("--asm-gap", type=int, default=12, help="碎片拼装水平间隙px")
    ap.add_argument("--asm-dh", type=int, default=6, help="碎片拼装 baseline 容差px")
    ap.add_argument("--asm-maxfrag", type=int, default=6, help="可参与拼装的片段最大字符数")
    ap.add_argument("--dedup-dist", type=int, default=25, help="跨引擎同位去重半径px")
    # --- 输出 ---
    ap.add_argument("--runs-dir", default=None,
                    help="运行 JSON 归档目录(默认 <img 同目录>/ai_ocr_runs); 每次必存")
    ap.add_argument("--progress", action="store_true",
                    help="汇报中间进度: stderr 打印已完成块/总数/耗时/ETA/命中数")
    ap.add_argument("--checkpoint", metavar="PATH",
                    help="每 --checkpoint-every 秒把当前 raw_stage1/raw_stage2 中间结果落盘(可用 --reuse-* 续跑; 中断自动保存)")
    ap.add_argument("--checkpoint-every", type=int, default=120,
                    help="checkpoint 落盘间隔秒数(默认 120, 仅 --checkpoint 有效)")
    ap.add_argument("--out", help="指向最新运行的副本路径(可选)")
    ap.add_argument("--sheet", help="视觉签收拼图 PNG(可选)")
    ap.add_argument("--sheet-pad", type=int, default=100, help="签收图 crop 半径(px@img-dpi)")
    ap.add_argument("--sheet-cell", type=int, default=260)
    ap.add_argument("--tag", default="", help="运行标签(进文件名)")
    ap.add_argument("--note", default="", help="备注(进 JSON)")
    ap.add_argument("--only-refdes", action="store_true", help="hits 只保留位号样式")
    ap.add_argument("--keep-raw", action="store_true", help="JSON 附 stage1/stage2 原始 hits")
    return ap


def main():
    P = build_parser().parse_args()
    # preset 应用: 用户显式给的参数优先(两段解析)
    import sys as _sys

    explicit = {a.split("=")[0].lstrip("-").replace("-", "_") for a in _sys.argv[1:] if a.startswith("-")}
    if P.stages is None:
        P.stages = "1" if P.preset == "fast" else "1,2"
    if "stage1_engines" not in explicit and P.preset == "fast":
        P.stage1_engines = "v4"
    # 中间结果常态化保存: reuse/细化流程依赖 raw hits
    P.keep_raw = True
    t0 = time.perf_counter()
    img = Image.open(P.img).convert("RGB")
    arr = np.asarray(img)
    scale = P.out_dpi / P.img_dpi  # img px -> out px
    f_low = 2.0
    if P.img_low:
        img_low = Image.open(P.img_low).convert("RGB")
        f_low = img.width / img_low.width  # 低分辨率图 -> 主底图倍数
    else:
        img_low = img.resize((img.width // 2, img.height // 2), Image.LANCZOS)

    stages = {int(s) for s in P.stages.split(",") if s.strip()}
    use_dml = getattr(P, "dml", False)
    engs1 = {n: make_engine(n, P.max_side_len or None, use_dml) for n in
             [x.strip() for x in P.stage1_engines.split(",") if x.strip()]}
    engs2 = {n: make_engine(n, P.max_side_len or None, use_dml) for n in
             [x.strip() for x in P.stage2_engines.split(",") if x.strip()]}

    def load_reused(path, stage):
        src = json.load(open(path))
        key = f"raw_stage{stage}"
        hits = src.get(key) or [dict(h) for h in src.get("hits", []) if h.get("stage") == stage]
        if not hits:
            raise SystemExit(f"{path} 无可复用的 stage{stage} 命中(源运行需 --keep-raw)")
        sp = src.get("params", {})
        if sp.get("out_dpi") not in (None, P.out_dpi) or sp.get("img_dpi") not in (None, P.img_dpi):
            raise SystemExit(f"{path} 坐标系(dpi)与本次不一致, 拒绝复用")
        return hits

    hits1, hits2, n_regions = [], [], 0
    cp1 = cp2 = None
    if P.checkpoint:
        cp1 = os.path.join(P.checkpoint, "cp_stage1.json")
        cp2 = os.path.join(P.checkpoint, "cp_stage2.json")
        os.makedirs(P.checkpoint, exist_ok=True)
    resume_done = None
    if P.reuse_stage1:
        hits1 = load_reused(P.reuse_stage1, 1)
    elif 1 in stages:
        if P.resume_stage1 and os.path.exists(cp1):
            rcp = json.load(open(cp1))
            resume_done = set(rcp.get("_done_tiles") or [])
            if resume_done:
                hits1 = list(rcp.get("raw_stage1") or [])
                sys.stderr.write(f"[resume] stage1 复用已扫完 tile x{len(resume_done)} "
                                 f"(hits={len(hits1)}), 只补剩余…\n")
                sys.stderr.flush()
        prog1 = Progress("stage1", 1, -1, cp1, P.out_dpi, P.img_dpi, P.checkpoint_every) if P.progress or P.checkpoint else None
        if prog1:
            signal.signal(signal.SIGINT, _sigint)
            prog1.done_tiles = sorted(resume_done) if resume_done else []
            if P.stage1_mode == "grid":
                H, W = arr.shape[:2]
                prog1.total = ((H + P.tile - P.overlap - 1) // (P.tile - P.overlap)) * \
                              ((W + P.tile - P.overlap - 1) // (P.tile - P.overlap))
        def rep1(n, total, hits, tile_idx=None):
            if prog1:
                prog1.total = total if prog1.total in (-1, None) else prog1.total
                prog1.tick(hits, tile_idx)
        if P.stage1_mode == "contour":
            hits1b, n_regions = stage1_contour(engs1, arr, scale, P, report=rep1)
            hits1 = hits1 + hits1b
        else:
            hits1b = stage1_grid(engs1, arr, scale, P, report=rep1, resume_done=resume_done)
            hits1 = hits1 + hits1b
        if prog1:
            prog1.done(hits1)
    if P.reuse_stage2:
        hits2 = load_reused(P.reuse_stage2, 2)
    elif 2 in stages:
        covered = [_bbox(h["box"]) for h in hits1]
        cands = stage2_candidates(img_low, P)
        cands_imgpx = [(c[0] * f_low, c[1] * f_low, c[2] * f_low, c[3] * f_low) for c in cands]
        prog2 = Progress("stage2", 2, len(cands_imgpx), cp2, P.out_dpi, P.img_dpi, P.checkpoint_every) if P.progress or P.checkpoint else None
        if prog2:
            signal.signal(signal.SIGINT, _sigint)
        def rep2(n, total, hits):
            if prog2:
                prog2.tick(hits)
        hits2 = stage2_read(engs2, arr, cands_imgpx, covered, P, scale, report=rep2)
        if prog2:
            prog2.done(hits2)

    per_engine = {}
    for h in hits1 + hits2:
        per_engine.setdefault(h["engine"], []).append(h)
    assembled = []
    for eng, lst in per_engine.items():
        assembled += assemble_lines(lst, P)
    merged = dedup_merge(assembled, P.dedup_dist)
    if P.only_refdes:
        merged = [m for m in merged if m["refdes_like"]]
    dt = time.perf_counter() - t0

    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    script_hash = hashlib.sha1(open(os.path.abspath(__file__), "rb").read()).hexdigest()[:12]
    run_file = f"{now}{('_' + P.tag) if P.tag else ''}_v{TOOL_VERSION}_{script_hash}.json"
    runs_dir = P.runs_dir or os.path.join(os.path.dirname(os.path.abspath(P.img)),
                                          "ai_ocr_runs")
    report = {
        "run_id": run_file,
        "tool_version": TOOL_VERSION,
        "tool_script_sha1": script_hash,
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "params": {k: v for k, v in vars(P).items()},
        "engine_versions": _versions(),
        "engines": {"stage1": {n: d for n, (_, d) in engs1.items()},
                    "stage2": {n: d for n, (_, d) in engs2.items()}},
        "img": os.path.abspath(P.img),
        "note": P.note,
        "time_s": round(dt, 1),
        "n_stage1": len(hits1), "n_stage2": len(hits2), "n_merged": len(merged),
        "n_regions": n_regions,
        "n_refdes": sum(1 for m in merged if m["refdes_like"]),
        "n_agree": sum(1 for m in merged if m["agree"]),
        "hits": [{k: m[k] for k in ("text", "norm", "conf", "engine", "engines", "agree",
                                    "stage", "px", "refdes_like")} for m in merged],
    }
    if P.keep_raw:
        report["raw_stage1"] = hits1
        report["raw_stage2"] = hits2
    os.makedirs(runs_dir, exist_ok=True)
    path = os.path.join(runs_dir, run_file)
    with open(path, "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    if P.out:
        os.makedirs(os.path.dirname(P.out) or ".", exist_ok=True)
        shutil.copyfile(path, P.out)
    if P.sheet:
        os.makedirs(os.path.dirname(P.sheet) or ".", exist_ok=True)
        sign_sheet([m for m in merged if m["refdes_like"]] or merged, P.img, P.sheet, P)
    print(f"stage1={len(hits1)} stage2={len(hits2)} merged={len(merged)} "
          f"refdes={report['n_refdes']} agree={report['n_agree']} {report['time_s']}s")
    print(f"-> run: {path}")
    if P.out:
        print(f"-> out: {P.out}")


if __name__ == "__main__":
    main()
