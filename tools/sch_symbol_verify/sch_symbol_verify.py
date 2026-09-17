#!/usr/bin/env python3
"""tools/sch_symbol_verify/sch_symbol_verify.py — 符号验证 (纯验证)

purpose: 消费 sch_symbol (符号识别) 的 symbol_body + sch_components.json,
        验证红点 (symbol_pos) 是否在符号本体上:
          - circle/rect 本体须包含红点
          - cap/line 本体中心 = 符号位置 (修正 symbol_pos)
          - 红点不得落在 label 文字框内
        识别在 sch_symbol, 本程序只验证 (对应 PCB: sch_symbol=pcb_package,
        sch_symbol_verify=pcb_verify).

用法:
  python3 sch_symbol_verify.py --img sch.png --db sch_components.json
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
    args = ap.parse_args()

    img = cv2.imread(args.img)
    if img is None:
        sys.exit(f"cannot read {args.img}")
    db = json.load(open(args.db))

    n = n_ok = n_corrected = n_onlabel = 0
    for c in db["components"]:
        if c.get("membership") != "flow_through" or not c.get("refdes"):
            continue
        sx, sy = c["symbol_pos"]
        tbox = c.get("text_box")
        body = c.get("symbol_body")
        n += 1
        if in_box(sx, sy, tbox):
            c["sym_verify"] = "on_label"
            n_onlabel += 1
            continue
        inside = body_contains(sx, sy, body)
        if inside is True:
            c["sym_verify"] = "ok"
            n_ok += 1
        elif inside is False and args.correct and body:
            # 用本体中心修正红点
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
    print(f"[sch_symbol_verify] ok={n_ok}/{n} corrected={n_corrected} on_label={n_onlabel}")


if __name__ == "__main__":
    main()