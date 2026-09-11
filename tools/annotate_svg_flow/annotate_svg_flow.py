#!/usr/bin/env python3
"""分层 SVG 电路标注工具 (仿 example/talkabout-bot.svg 的分层原则).

分层原则(从 example 学到):
  * 底图单独一层: 光栅渲染图 base64 内嵌(不外链, 单文件自包含), 图层锁定
    (sodipodi:insensitive="true", Inkscape 里点不中/拖不动, 防误操作)
  * 每个语义类一层 (inkscape:groupmode=layer + inkscape:label):
    rx / tx / ctrl-power / blocks / marks / notes, 层级默认色, 可整体开关/隐藏
  * 层内元素: rect(区域) + polyline+箭头(信号流) + text(标签) + 圆点(锚点)
  * 实线=已确认, 虚线=推断/not-located (agent.md 防臆造约定)
  * base 之上按 rx → tx → ctrl → blocks → marks → notes 叠放

工具规范(与 ai_refdes_ocr.py 一致): 全参数 CLI; 每次渲染归档 runs-dir
(含 tool_version/date/params/script_sha1); --out 只是指向最新运行的副本.

用法:
  python3 annotate_svg_flow.py --base render.png --wpts nettable/wpts_top.json:rx \
      --runs-dir proj/annot/svg_runs --out proj/annot/flow.svg --png proj/annot/flow.png
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import shutil

from lxml import etree

TOOL_VERSION = "0.1.0"
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
INK_NS = "http://www.inkscape.org/namespaces/inkscape"
SOD_NS = "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
NSMAP = {None: SVG_NS, "xlink": XLINK_NS, "inkscape": INK_NS, "sodipodi": SOD_NS}

# 层定义: 顺序=叠放次序(底→顶), 默认色, inkscape:label
LAYER_DEFS = [
    ("rx", "#00c853", "RX-Flow"),
    ("tx", "#ff2a2a", "TX-Flow"),
    ("ctrl", "#ffcc00", "Ctrl-Power"),
    ("blocks", "#75a9ff", "Function-Blocks"),
    ("marks", "#ff6f00", "Marks"),
    ("notes", "#9e9e9e", "Notes"),
]


def _el(tag, attrs, text=None):
    e = etree.SubElement(_CUR[0], f"{{{SVG_NS}}}{tag}")
    for k, v in attrs.items():
        e.set(k, str(v))
    if text is not None:
        e.text = text
    return e


_CUR = [None]


def sub(tag, attrs, text=None):
    return _el(tag, attrs, text)


def parse_wpts_spec(spec):
    """'path[:layer[:label]]' 或 'path:layer=label' → (path, layer, label_override)."""
    label = None
    if "=" in spec:
        spec, label = spec.split("=", 1)
    parts = spec.split(":")
    path = parts[0]
    layer = parts[1] if len(parts) > 1 else None
    return path, layer, label


def load_wpts(path):
    with open(path) as f:
        d = json.load(f)
    if isinstance(d, dict):  # 兼容 nettable confirmed_anchors 格式
        out = []
        for name, info in d.items():
            e = {"label": name.split("_")[0], "px": info["label_px"]}
            if isinstance(info, dict) and info.get("note"):
                e["note"] = info["note"]
            out.append(e)
        return out
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="底图 PNG")
    ap.add_argument("--base-dpi", type=int, default=300)
    ap.add_argument("--wpt-dpi", type=int, default=300,
                    help="waypoints px 所在 dpi (自动换算到底图空间)")
    ap.add_argument("--wpts", action="append", default=[],
                    help="waypoint JSON, 可多次; 'path[:layer]' 或 'path:layer=Inkscape标签'")
    ap.add_argument("--only-layers", default=None,
                    help="只渲染这些层(逗号分隔, 如 rx 或 rx,ctrl); 缺省全部")
    ap.add_argument("--layer-style", action="append", default=[],
                    help="层样式覆盖: 'rx:color=#xxxxxx,opacity=0.8'")
    ap.add_argument("--dot-r", type=float, default=7)
    ap.add_argument("--stroke-w", type=float, default=5)
    ap.add_argument("--font-size", type=float, default=34)
    ap.add_argument("--dash-array", default="10 8")
    ap.add_argument("--arrow-len", type=float, default=18)
    ap.add_argument("--text-halo", action="store_true", default=True,
                    help="文字白描边提高可读性")
    ap.add_argument("--no-text-halo", dest="text_halo", action="store_false")
    ap.add_argument("--runs-dir", default=None,
                    help="运行归档目录(默认 <base 同目录>/svg_runs); 每次必存")
    ap.add_argument("--out", help="最新运行副本路径(可选)")
    ap.add_argument("--png", help="cairosvg 导出 PNG(可选)")
    ap.add_argument("--png-dpi", type=int, default=96)
    ap.add_argument("--tag", default="")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    from PIL import Image
    W, H = Image.open(args.base).size
    s = args.base_dpi / args.wpt_dpi  # wpt px -> base px

    root = etree.Element(f"{{{SVG_NS}}}svg", nsmap=NSMAP)
    root.set("width", str(W))
    root.set("height", str(H))
    root.set("viewBox", f"0 0 {W} {H}")
    root.set("version", "1.1")
    now = datetime.datetime.now().isoformat(timespec="seconds")
    root.addprevious(etree.Comment(
        f" annotate_svg_flow v{TOOL_VERSION} {now} base={os.path.basename(args.base)} "))

    _CUR[0] = root
    # defs: 箭头 marker (每色一个)
    defs = sub("defs", {"id": "defs"})
    _CUR[0] = defs
    for key, color, _lab in LAYER_DEFS:
        mk = sub("marker", {"id": f"arrow-{key}", "viewBox": "0 0 10 10", "refX": "8",
                            "refY": "5", "markerWidth": "5", "markerHeight": "5",
                            "orient": "auto-start-reverse"})
        sub("path", {"d": "M 0 0 L 10 5 L 0 10 z", "fill": color})
    _CUR[0] = root

    # base 层: base64 内嵌 + 锁定
    with open(args.base, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    g = sub("g", {"id": "layer-base", f"{{{INK_NS}}}groupmode": "layer",
                  f"{{{INK_NS}}}label": "Base",
                  f"{{{SOD_NS}}}insensitive": "true"})
    _CUR[0] = g
    img = sub("image", {"x": "0", "y": "0", "width": str(W), "height": str(H),
                        "preserveAspectRatio": "none",
                        f"{{{XLINK_NS}}}href": f"data:image/png;base64,{b64}",
                        "href": f"data:image/png;base64,{b64}"})
    _CUR[0] = root

    styles = {}
    for spec in args.layer_style:
        kvs = spec.split(":", 1)
        if len(kvs) != 2:
            continue
        d = {}
        for kv in kvs[1].split(","):
            if "=" in kv:
                d[kv.split("=")[0].strip()] = kv.split("=")[1].strip()
        styles[kvs[0].strip()] = d

    # 收集 waypoints: 每条输入的条目可自带 layer 字段, 否则用 spec 的 hint
    only = set(args.only_layers.split(",")) if args.only_layers else None
    buckets = {key: [] for key, _, _ in LAYER_DEFS}
    for spec in args.wpts:
        path, layer_hint, label_ov = parse_wpts_spec(spec)
        for e in load_wpts(path):
            layer = e.get("layer") or layer_hint or "notes"
            if layer not in buckets:
                continue
            if only and layer not in only:
                continue
            if label_ov:
                e = dict(e, label=e.get("label", ""))
            buckets[layer].append(e)

    counts = {}
    for key, color, label in LAYER_DEFS:
        entries = buckets[key]
        if not entries:
            continue
        st = styles.get(key, {})
        col = st.get("color", color)
        op = st.get("opacity", "0.95")
        layer_label = st.get("label", label)
        _CUR[0] = root
        g = sub("g", {"id": f"layer-{key}", f"{{{INK_NS}}}groupmode": "layer",
                      f"{{{INK_NS}}}label": layer_label,
                      "style": f"display:inline;opacity:{op};stroke:{col};fill:{col}"})
        _CUR[0] = g
        n = 0
        for e in entries:
            n += 1
            px = [e["px"][0] * s, e["px"][1] * s]
            lab = e.get("label", "")
            dash = e.get("dash", False)
            common = {"stroke": col, "fill": "none"}
            if dash:
                common["stroke-dasharray"] = args.dash_array
            kind = e.get("kind")
            if e.get("through"):
                pts = [px] + [[p[0] * s, p[1] * s] for p in e["through"]]
                pl = sub("polyline", {
                    "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in pts),
                    "stroke-width": args.stroke_w, **common,
                    "marker-end": f"url(#arrow-{key})",
                    "marker-mid": f"url(#arrow-{key})"})
            elif kind == "rect":
                sub("rect", {"x": str(px[0]), "y": str(px[1]),
                             "width": str(e.get("w", 200) * s), "height": str(e.get("h", 120) * s),
                             "stroke-width": args.stroke_w, "fill": col, "fill-opacity": "0.12",
                             **({"stroke-dasharray": args.dash_array} if dash else {})})
            elif kind == "line" and e.get("to"):
                sub("line", {"x1": str(px[0]), "y1": str(px[1]),
                             "x2": str(e["to"][0] * s), "y2": str(e["to"][1] * s),
                             "stroke-width": args.stroke_w,
                             "marker-end": f"url(#arrow-{key})", **common})
            # 点锚 + 标签(除纯 rect/line 外都画点; dot=False 只出文字)
            if e.get("dot", True) and kind not in ("rect", "line", "text"):
                sub("circle", {"cx": str(px[0]), "cy": str(px[1]), "r": str(args.dot_r),
                               "fill": col if not dash else "none", "stroke": col,
                               "stroke-width": "2"})
            if lab:
                fs = e.get("fs", args.font_size)
                lpos = e.get("lpos")  # ul/ur/dl/dr/l/r/u/d 方位简写
                ldx, ldy = e.get("ldx", 0), e.get("ldy", 0)
                anch = "start"
                rr = args.dot_r + 4
                if lpos == "ul":
                    anch, ldx, ldy = "end", -rr, -rr
                elif lpos == "ur":
                    anch, ldx, ldy = "start", rr, -rr
                elif lpos == "dl":
                    anch, ldx, ldy = "end", -rr, rr + fs * 0.25
                elif lpos == "dr":
                    anch, ldx, ldy = "start", rr, rr + fs * 0.25
                elif lpos == "l":
                    anch, ldx, ldy = "end", -rr, fs * 0.30
                elif lpos == "r":
                    anch, ldx, ldy = "start", rr, fs * 0.30
                elif lpos == "u":
                    anch, ldx, ldy = "middle", 0, -rr - fs * 0.25
                elif lpos == "d":
                    anch, ldx, ldy = "middle", 0, rr + fs * 0.85
                tx = px[0] + rr + ldx
                ty = px[1] - rr + ldy
                t = sub("text", {"x": str(tx), "y": str(ty), "font-size": str(fs),
                                 "font-family": "sans-serif", "font-weight": "bold",
                                 "text-anchor": anch,
                                 "stroke-width": str(fs * 0.12),
                                 "stroke": "#ffffff" if args.text_halo else "none",
                                 "paint-order": "stroke", "fill": col}, lab)
                if e.get("note"):
                    sub("text", {"x": str(tx), "y": str(ty + fs * 0.8),
                                 "font-size": str(fs * 0.62),
                                 "font-family": "sans-serif", "fill": col,
                                 "opacity": "0.9", "text-anchor": anch}, e["note"])
        counts[key] = n

    tree = etree.ElementTree(root)
    now2 = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    script_sha = hashlib.sha1(open(os.path.abspath(__file__), "rb").read()).hexdigest()[:12]
    run_file = f"{now2}{('_' + args.tag) if args.tag else ''}_v{TOOL_VERSION}_{script_sha}.svg"
    runs_dir = args.runs_dir or os.path.join(os.path.dirname(os.path.abspath(args.base)),
                                             "svg_runs")
    os.makedirs(runs_dir, exist_ok=True)
    svg_path = os.path.join(runs_dir, run_file)
    tree.write(svg_path, xml_declaration=True, encoding="UTF-8")
    meta = {"tool_version": TOOL_VERSION, "date": now, "script_sha1": script_sha,
            "params": vars(args), "layer_counts": counts,
            "base_size": [W, H], "note": args.note}
    with open(svg_path.replace(".svg", ".json"), "w") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        shutil.copyfile(svg_path, args.out)
    if args.png:
        import cairosvg

        os.makedirs(os.path.dirname(args.png) or ".", exist_ok=True)
        cairosvg.svg2png(url=svg_path, write_to=args.png,
                         output_width=W, output_height=H)
    print(f"SVG run: {svg_path}")
    print(f"layers: {counts}")
    if args.out:
        print(f"-> out: {args.out}")
    if args.png:
        print(f"-> png: {args.png}")


if __name__ == "__main__":
    main()
