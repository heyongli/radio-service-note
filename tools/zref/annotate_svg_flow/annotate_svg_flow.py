#!/usr/bin/env python3
"""tools/annotate_svg_flow/annotate_svg_flow.py — 分层 SVG 标注
purpose: wpts JSON → 分层 SVG (底图 base64 内嵌 + 图层锁定)
format: Python 3 + lxml + cairosvg
version: 0.2.2 (2026-09-15)
consumers: 任何 PCB/sch 标注的 SVG 输出"""

"""分层 SVG 电路标注工具 (仿 example/talkabout-bot.svg 的分层原则).

分层原则(从 example 学到):
  * 底图单独一层: 光栅渲染图 base64 内嵌(不外链, 单文件自包含), 图层锁定
  * 每个语义类一层 (inkscape:groupmode=layer): rx / tx / ctrl / blocks / marks / notes
  * 层内元素: rect(区域) + polyline(信号流, 每个到达点画箭头) + text(标签) + 圆点/via
  * 实线=已确认, 虚线=推断/not-located (agent.md 防臆造约定)

v0.2.0 视觉规则 (2026-09-10 用户反馈驱动):
  * 线条/圆点 = 层色; 文字标签 = --label-color (默认深蓝 #0d47a1, 与线条区分)
  * via=true 条目 (信号从/到背面) = 土黄 #B8860B: 焊盘环+孔符号, 线条文字同色
  * 箭头 = 手绘三角 (每段终点+每个拐点), 不用 SVG marker (小图缩放后不可见)
  * fs 按元器件封装大小在 wpts 数据里逐条给定 (大IC 30-38 / 中件 24-28 / 小件-pin 18-22)
  * ldx/ldy = 在 lpos 方位基础上的**叠加**偏移 (v0.1.x bug: 直接覆盖)
  * note 与 label 独立渲染 (空 label 也出 note); u/ul/ur 方位 note 放 label 上方
  * rect 标签锚定矩形中心 ('d'=底边下方, 'u'=顶边上方)

用法:
  python3 annotate_svg_flow.py --base render.png --wpts nettable/wpts_top.json:rx \
      --runs-dir proj/annot/svg_runs --out proj/annot/flow.svg --png proj/annot/flow.png
"""
import argparse
import base64
import datetime
import hashlib
import json
import math
import os
import shutil

from lxml import etree

TOOL_VERSION = "0.2.2"
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


def draw_arrow(x, y, x0, y0, size, color):
    """在 (x,y) 画沿 (x0,y0)->(x,y) 方向的三角箭头."""
    dx, dy = x - x0, y - y0
    L = math.hypot(dx, dy)
    if L < 1e-6:
        return
    ux, uy = dx / L, dy / L
    bx, by = x - ux * size, y - uy * size
    wx, wy = -uy * size * 0.45, ux * size * 0.45
    sub("polygon", {"points": f"{x:.1f},{y:.1f} {bx + wx:.1f},{by + wy:.1f} "
                    f"{bx - wx:.1f},{by - wy:.1f}", "fill": color})


def draw_via(x, y, r, color, hole_stroke):
    """PCB via 符号: 焊盘环 + 孔."""
    sub("circle", {"cx": f"{x:.1f}", "cy": f"{y:.1f}", "r": f"{r * 1.6:.1f}",
                   "fill": color, "stroke": "none"})
    sub("circle", {"cx": f"{x:.1f}", "cy": f"{y:.1f}", "r": f"{r * 0.55:.1f}",
                   "fill": "#ffffff", "stroke": color, "stroke-width": str(hole_stroke)})


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
    ap.add_argument("--label-color", default="#0d47a1",
                    help="文字标签颜色(与层色区分, 醒目); via 条目固定土黄")
    ap.add_argument("--dot-r", type=float, default=7)
    ap.add_argument("--stroke-w", type=float, default=6)
    ap.add_argument("--font-size", type=float, default=24,
                    help="默认字号; 各条目用 fs 字段按封装大小覆盖")
    ap.add_argument("--dash-array", default="10 8")
    ap.add_argument("--arrow-len", type=float, default=24)
    ap.add_argument("--via-color", default="#b8860b",
                    help="via/背面段土黄色")
    ap.add_argument("--dot-stroke", type=float, default=2,
                    help="锚点圆点描边宽")
    ap.add_argument("--via-stroke", type=float, default=1.5,
                    help="via 孔环描边宽")
    ap.add_argument("--note-scale", type=float, default=0.62,
                    help="note 字号 = fs × 此比例")
    ap.add_argument("--halo-scale", type=float, default=0.14,
                    help="文字白描边宽 = fs × 此比例")
    ap.add_argument("--rect-fill-opacity", type=float, default=0.12,
                    help="区域矩形填充不透明度")
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
    # base 层: base64 内嵌 + 锁定
    with open(args.base, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    g = sub("g", {"id": "layer-base", f"{{{INK_NS}}}groupmode": "layer",
                  f"{{{INK_NS}}}label": "Base",
                  f"{{{SOD_NS}}}insensitive": "true"})
    _CUR[0] = g
    sub("image", {"x": "0", "y": "0", "width": str(W), "height": str(H),
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

    # 收集 waypoints
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
            kind = e.get("kind")
            via = e.get("via", False)
            # via=背面过孔(符号+土黄); tan=仅土黄(背面段, 不画符号); 其余=层色
            tan_only = e.get("tan", False)
            ecol = args.via_color if (via or tan_only) else col
            tcol = args.via_color if (via or tan_only) else args.label_color
            common = {"stroke": ecol, "fill": "none"}
            if dash:
                common["stroke-dasharray"] = args.dash_array
            if e.get("through"):
                pts = [px] + [[p[0] * s, p[1] * s] for p in e["through"]]
                sub("polyline", {
                    "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in pts),
                    "stroke-width": args.stroke_w, **common})
                # 每个到达点(拐点+终点)画箭头; 短段跳过(终点必画)
                for i in range(1, len(pts)):
                    seg = math.hypot(pts[i][0] - pts[i - 1][0],
                                     pts[i][1] - pts[i - 1][1])
                    if seg >= args.arrow_len * 0.8 or i == len(pts) - 1:
                        draw_arrow(pts[i][0], pts[i][1], pts[i - 1][0],
                                   pts[i - 1][1], args.arrow_len, ecol)
            elif kind == "rect":
                rw, rh = e.get("w", 200) * s, e.get("h", 120) * s
                sub("rect", {"x": f"{px[0]:.1f}", "y": f"{px[1]:.1f}",
                             "width": f"{rw:.1f}", "height": f"{rh:.1f}",
                             "stroke-width": args.stroke_w, "fill": ecol,
                             "fill-opacity": str(args.rect_fill_opacity),
                             **({"stroke-dasharray": args.dash_array} if dash else {})})
                if via:  # 矩形中心画 via 符号 (整个区域在背面)
                    draw_via(px[0] + rw / 2, px[1] + rh / 2, args.dot_r * 0.8,
                             args.via_color, args.via_stroke)
            elif kind == "line" and e.get("to"):
                tx2, ty2 = e["to"][0] * s, e["to"][1] * s
                sub("line", {"x1": f"{px[0]:.1f}", "y1": f"{px[1]:.1f}",
                             "x2": f"{tx2:.1f}", "y2": f"{ty2:.1f}",
                             "stroke-width": args.stroke_w, **common})
                draw_arrow(tx2, ty2, px[0], px[1], args.arrow_len, ecol)
            # 锚点符号: via 条目=via 焊盘环; 普通条目=圆点 (dot=False 只出文字)
            if via:
                vx, vy = px
                if e.get("via_at") == "end" and e.get("through"):
                    vx, vy = e["through"][-1][0] * s, e["through"][-1][1] * s
                    if not e.get("dot"):
                        pass
                    else:  # px 处仍是本面真实器件: 保留普通圆点
                        sub("circle", {"cx": f"{px[0]:.1f}", "cy": f"{px[1]:.1f}",
                                       "r": str(args.dot_r),
                                       "fill": col if not dash else "none",
                                       "stroke": col, "stroke-width": str(args.dot_stroke)})
                draw_via(vx, vy, args.dot_r, args.via_color, args.via_stroke)
            elif e.get("dot", True) and kind not in ("rect", "line", "text"):
                sub("circle", {"cx": f"{px[0]:.1f}", "cy": f"{px[1]:.1f}",
                               "r": str(args.dot_r),
                               "fill": ecol if not dash else "none",
                               "stroke": ecol, "stroke-width": str(args.dot_stroke)})
            # 文字: label + note 独立渲染 (note 不依赖 label)
            if lab or e.get("note"):
                fs = e.get("fs", args.font_size)
                lpos = e.get("lpos")
                base_ldx, base_ldy = e.get("ldx", 0), e.get("ldy", 0)
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
                else:
                    ldx, ldy = 0, 0
                ldx += base_ldx
                ldy += base_ldy
                # rect 标签锚定矩形中心; 其余锚定 px
                if kind == "rect":
                    cx = px[0] + e.get("w", 200) * s / 2
                    if anch == "middle":
                        tx = cx + ldx
                    elif anch == "end":
                        tx = cx - e.get("w", 200) * s / 2 - rr + ldx
                    else:
                        tx = cx + e.get("w", 200) * s / 2 + rr + ldx
                    ty = (px[1] - rr + ldy) if lpos == "u" else \
                         (px[1] + e.get("h", 120) * s + rr + fs * 0.6 + ldy)
                else:
                    tx = px[0] + rr + ldx
                    ty = px[1] - rr + ldy
                if lab:
                    # 两遍绘制: 白垫底层 + 彩色顶层 (cairosvg 不支持 paint-order,
                    # 单遍 stroke 会盖掉 fill → PNG 里字被白描边啃成残影)
                    attrs = {"x": f"{tx:.1f}", "y": f"{ty:.1f}",
                             "font-size": str(fs),
                             "font-family": "sans-serif", "font-weight": "bold",
                             "text-anchor": anch}
                    if args.text_halo:
                        sub("text", {**attrs,
                                     "fill": "#ffffff", "stroke": "#ffffff",
                                     "stroke-width": str(fs * args.halo_scale * 2)}, lab)
                    sub("text", {**attrs, "fill": tcol}, lab)
                if e.get("note"):
                    nfs = fs * args.note_scale
                    if not lab:  # 无 label: note 就在本位
                        ny = ty
                    elif lpos in ("u", "ul", "ur"):
                        ny = ty - fs * 0.95
                    else:
                        ny = ty + fs * 1.02
                    sub("text", {"x": f"{tx:.1f}", "y": f"{ny:.1f}",
                                 "font-size": f"{nfs:.1f}",
                                 "font-family": "sans-serif",
                                 "fill": tcol, "opacity": "0.95",
                                 "text-anchor": anch}, e["note"])
        counts[key] = n

    tree = etree.ElementTree(root)
    now2 = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    script_sha = hashlib.sha1(open(os.path.abspath(__file__), "rb").read()).hexdigest()[:12]
    run_file = f"{now2}{('_' + args.tag) if args.tag else ''}_v{TOOL_VERSION}_{script_sha}.svg"
    runs_dir = args.runs_dir
    if not runs_dir:
        base_dir = os.path.dirname(os.path.abspath(args.base))
        # 如果 base 在 <project>/render/, 默认 svg_runs 放 <project>/svg_runs
        # 如果 base 在 <project>/annot/, 默认 svg_runs 放 <project>/svg_runs
        # 否则回退到 base 同目录的 svg_runs
        if base_dir.endswith("/render") or base_dir.endswith("/annot"):
            runs_dir = os.path.join(os.path.dirname(base_dir), "svg_runs")
        else:
            runs_dir = os.path.join(base_dir, "svg_runs")
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
