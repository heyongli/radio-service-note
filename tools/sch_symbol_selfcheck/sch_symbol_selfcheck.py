#!/usr/bin/env python3
"""tools/sch_symbol_selfcheck/sch_symbol_selfcheck.py — 符号自我监督校验

purpose: 消费 sch_symbol (符号识别) 的 symbol_body + sch_components.json,
        内置自我监督算法自证识别是否准确:
          - circle/rect 本体须包含红点
          - cap/line 本体中心 = 符号位置 (修正 symbol_pos)
          - 红点不得落在 label 文字框内
          - 尺寸知识自学习 (验证 OK 尺寸 append 知识库, 中位=典型, 反哺校验)
        识别在 sch_symbol, 本程序自我校验 + 自我校准 + 自我学习
        (对应 PCB: sch_symbol=pcb_package, sch_symbol_selfcheck=pcb_verify).

用法:
  python3 sch_symbol_selfcheck.py --img sch.png --db sch_components.json
"""

import argparse
import json
import sys

import cv2
import numpy as np


def in_box(px, py, box, pad=4):
    if not box:
        return False
    xs = [p[0] for p in box]; ys = [p[1] for p in box]
    return (min(xs) - pad <= px <= max(xs) + pad and
            min(ys) - pad <= py <= max(ys) + pad)


def body_contains(px, py, body, pad=4):
    """红点是否在符号本体内."""
    if body is None:
        return None
    kind = body.get("kind")
    if kind == "circle":
        return (px - body["cx"]) ** 2 + (py - body["cy"]) ** 2 <= (body["r"] + pad) ** 2
    if kind == "rect":
        return (body["x"] - pad <= px <= body["x"] + body["w"] + pad and
                body["y"] - pad <= py <= body["y"] + body["h"] + pad)
    # cap/line: 本体中心即符号位置, 红点应在中心附近
    if kind in ("cap", "line"):
        return abs(px - body["cx"]) + abs(py - body["cy"]) <= 20
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--img", required=True)
    ap.add_argument("--db", required=True, help="sch_components.json (读写, 加 sym_verify)")
    ap.add_argument("--correct", action="store_true",
                    help="红点不在本体上时, 用本体中心修正 symbol_pos")
    ap.add_argument("--sizes-db", default=None,
                    help="符号尺寸知识库路径 (默认 projects/<机型>/nettable/sch_symbol_sizes.json)")
    ap.add_argument("--size-tol", type=float, default=0.6,
                    help="尺寸偏差容差 (典型尺寸 ±60%)")
    args = ap.parse_args()

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "sch_symbol"))
    from common import body_size, update_sizes_db, typical_size, check_size
    if args.sizes_db is None:
        # 默认写入项目 nettable (数据入 project)
        from pathlib import Path
        args.sizes_db = str(Path(args.db).parent / "sch_symbol_sizes.json")

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    db = json.load(open(args.db))

    n = n_ok = n_corrected = n_onlabel = n_sizedev = 0
    for c in db["components"]:
        if c.get("membership") != "flow_through" or not c.get("refdes"):
            continue
        sx, sy = c["symbol_pos"]
        tbox = c.get("text_box")
        body = c.get("symbol_body")
        sym = c.get("symbol_type", "cap")
        n += 1
        if in_box(sx, sy, tbox):
            c["sym_verify"] = "on_label"
            n_onlabel += 1
            continue
        inside = body_contains(sx, sy, body)
        if inside is True:
            c["sym_verify"] = "ok"
            n_ok += 1
            # 尺寸知识库: 记录已验证符号尺寸 (IC 按型号键, 不同型号大小不同)
            if args.sizes_db:
                sz = body_size(body)
                if sz:
                    sym_key = f"ic:{c.get('ic_model')}" if sym == "ic" and c.get("ic_model") else sym
                    update_sizes_db(args.sizes_db, sym_key, sz, c["refdes"])
                    typ = typical_size(args.sizes_db, sym_key)
                    r = check_size(sz, typ, args.size_tol) if typ else None
                    c["size_check"] = r
                    if r is True:
                        c["size_dev"] = None
                    elif r is not None:
                        c["size_dev"] = round(r, 2)
                        n_sizedev += 1
        elif inside is False and args.correct and body:
            c["symbol_pos"] = [body.get("cx", sx), body.get("cy", sy)]
            c["sym_verify"] = "corrected"
            n_corrected += 1
        else:
            c["sym_verify"] = "bad"
    tmp = args.db + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    import os
    os.replace(tmp, args.db)
    print(f"[sch_symbol_selfcheck] ok={n_ok}/{n} corrected={n_corrected} "
          f"on_label={n_onlabel} size_dev={n_sizedev}")


if __name__ == "__main__":
    main()