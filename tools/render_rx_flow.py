#!/usr/bin/env python3
"""
渲染 wpts_rx_top_v8.json 的 RX 信号流程线到 PCB 图片上
输出 SVG 和 PNG
"""

import json
import sys
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def load_font(size):
    for fp in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            pass
    return ImageFont.load_default()


def draw_arrow(draw, x1, y1, x2, y2, color, width=5, head_len=20, head_angle=30):
    draw.line([(x1, y1), (x2, y2)], fill=color, width=width, joint="curve")
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist < head_len * 2:
        return
    ux, uy = dx / dist, dy / dist
    a = math.radians(head_angle)
    ax1 = x2 - head_len * (ux * math.cos(a) - uy * math.sin(a))
    ay1 = y2 - head_len * (uy * math.cos(a) + ux * math.sin(a))
    ax2 = x2 - head_len * (ux * math.cos(-a) - uy * math.sin(-a))
    ay2 = y2 - head_len * (uy * math.cos(-a) + ux * math.sin(-a))
    draw.polygon([(x2, y2), (ax1, ay1), (ax2, ay2)], fill=color)


def draw_arrowed_line(draw, points, color, width=5, head_len=24, dash=False):
    if len(points) < 2:
        return
    if dash:
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=color, width=width, joint="curve")
    else:
        for i in range(len(points) - 1):
            if i == len(points) - 2:
                draw_arrow(draw, points[i][0], points[i][1],
                           points[i + 1][0], points[i + 1][1],
                           color, width)
            else:
                draw.line([points[i], points[i + 1]], fill=color, width=width, joint="curve")


def render_png(wpts, base, comp_idx):
    W, H = base.size
    draw = ImageDraw.Draw(base)
    font_small = load_font(14)
    font_med = load_font(18)
    font_large = load_font(24)

    # 颜色
    CYAN = (0, 255, 255, 255)
    GREEN = (0, 200, 0, 255)
    GREEN_DASH = (0, 180, 0, 200)
    RED = (255, 0, 0, 255)
    YELLOW = (255, 200, 0, 255)
    WHITE = (255, 255, 255, 255)

    # components_index 确认框 (青色)
    if comp_idx:
        for ref, info in comp_idx.items():
            box = info.get("box", [])
            if len(box) == 4:
                pts = [(int(p[0]), int(p[1])) for p in box]
                draw.polygon(pts, outline=CYAN, width=3)
                cx, cy = info.get("center", [0, 0])
                draw.text((int(cx) + 30, int(cy) - 15), ref, fill=CYAN, font=font_small)

    # 画 wpts
    for item in wpts:
        layer = item.get("layer", "")
        kind = item.get("kind", "")

        if kind == "line":
            px = item.get("px", [])
            through = item.get("through", [])
            dash = item.get("dash", False)
            label = item.get("label", "")
            lpos = item.get("lpos", "")
            fs = item.get("fs", 18)
            color = GREEN_DASH if dash else GREEN
            font = load_font(fs)

            points = []
            if px:
                points.append(tuple(px))
            points.extend([tuple(p) for p in through])

            if len(points) >= 2:
                draw_arrowed_line(draw, points, color,
                                  width=5 if not dash else 4,
                                  head_len=24, dash=dash)
                if label:
                    mid = points[len(points) // 2]
                    lx, ly = mid
                    if lpos == "u":
                        ly -= 25
                    elif lpos == "d":
                        ly += 25
                    elif lpos == "l":
                        lx -= 120
                    elif lpos == "r":
                        lx += 20
                    draw.text((lx, ly), label, fill=color, font=font)

        elif kind == "rect":
            label = item.get("label", "")
            if label in ("EP11", "EP12"):
                continue  # 跳过非关键器件
            px = item.get("px", [])
            w = item.get("w", 200)
            h = item.get("h", 200)
            dash = item.get("dash", False)
            color = YELLOW if dash else CYAN
            if px:
                x, y = px
                box_coords = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                draw.polygon(box_coords, outline=color, width=3 if dash else 4)
                if label:
                    draw.text((x + 5, y - 20), label, fill=color, font=load_font(16))

        elif kind == "mark" or layer == "marks":
            label = item.get("label", "")
            if label in ("EP11", "EP12"):
                continue  # 跳过非关键器件
            px = item.get("px", [])
            dot = item.get("dot", False)
            fs = item.get("fs", 22)
            lpos = item.get("lpos", "")
            note = item.get("note", "")
            if px:
                x, y = px
                if dot:
                    draw.ellipse([x - 8, y - 8, x + 8, y + 8],
                                 fill=RED, outline=WHITE, width=2)
                if label:
                    lx, ly = x, y
                    if lpos == "u":
                        ly -= fs + 5
                    elif lpos == "d":
                        ly += 10
                    elif lpos == "l":
                        lx -= len(label) * fs * 0.6
                    elif lpos == "r":
                        lx += 10
                    elif lpos == "ul":
                        lx -= len(label) * fs * 0.6
                        ly -= fs + 5
                    elif lpos == "ur":
                        lx += 10
                        ly -= fs + 5
                    elif lpos == "dr":
                        lx += 10
                        ly += 10
                    draw.text((lx, ly), label, fill=RED, font=load_font(fs))
                if note:
                    draw.text((lx, ly + fs + 2), note, fill=YELLOW, font=load_font(14))

        elif kind == "text" or layer in ("notes",):
            px = item.get("px", [])
            label = item.get("label", "")
            fs = item.get("fs", 18)
            if px and label:
                draw.text(tuple(px), label, fill=WHITE, font=load_font(fs))


def generate_svg(wpts, out_svg, width, height, pcb_img_path, comp_idx):
    """生成 SVG 矢量图"""
    import svgwrite
    import base64

    dwg = svgwrite.Drawing(out_svg, size=(width, height), profile="full")

    # 嵌入 PCB 底图 (base64)
    if pcb_img_path and Path(pcb_img_path).exists():
        ext = Path(pcb_img_path).suffix.lstrip(".").lower() or "png"
        mime = {"png": "image/png", "jpg": "image/jpeg",
                "jpeg": "image/jpeg"}.get(ext, "image/png")
        with open(pcb_img_path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        dwg.add(svgwrite.image.Image(
            href=f"data:{mime};base64,{data}",
            insert=(0, 0), size=(width, height),
        ))

    C_GREEN = "#00C800"
    C_GREEN_DASH = "#00B400"
    C_RED = "#FF0000"
    C_YELLOW = "#FFC800"
    C_WHITE = "#FFFFFF"
    C_CYAN = "#00FFFF"

    # components_index 确认框
    if comp_idx:
        for ref, info in comp_idx.items():
            box = info.get("box", [])
            if len(box) == 4:
                pts = [(int(p[0]), int(p[1])) for p in box]
                cx, cy = info.get("center", [0, 0])
                g = dwg.g(id=f"comp-{ref}", stroke=C_CYAN,
                          fill="none", stroke_width=3)
                g.add(dwg.polygon(points=pts))
                g.add(dwg.text(ref, insert=(int(cx) + 30, int(cy) - 15),
                               fill=C_CYAN, font_size=14))
                dwg.add(g)

    # 画 wpts
    for item in wpts:
        layer = item.get("layer", "")
        kind = item.get("kind", "")

        if kind == "line":
            px = item.get("px", [])
            through = item.get("through", [])
            dash = item.get("dash", False)
            label = item.get("label", "")
            lpos = item.get("lpos", "")
            fs = item.get("fs", 18)
            color = C_GREEN_DASH if dash else C_GREEN
            anchor = {"u": "middle", "d": "middle", "l": "end", "r": "start",
                      "ul": "end", "ur": "start"}.get(lpos, "start")

            pts = list(map(tuple, ([px] if px else []) + through))
            if len(pts) >= 2:
                safe_id = "".join(c if c.isalnum() else "-" for c in label)[:24]
                g = dwg.g(id=f"line-{safe_id}", stroke=color, fill=color)
                if dash:
                    for i in range(len(pts) - 1):
                        g.add(dwg.line(start=pts[i], end=pts[i + 1],
                                       stroke_width=4,
                                       stroke_dasharray="10,6"))
                else:
                    for i in range(len(pts) - 1):
                        g.add(dwg.line(start=pts[i], end=pts[i + 1],
                                       stroke_width=5))
                    # 箭头
                    x1, y1 = pts[-2]
                    x2, y2 = pts[-1]
                    dx, dy = x2 - x1, y2 - y1
                    d = math.hypot(dx, dy) or 1
                    ux, uy = dx / d, dy / d
                    head = 24
                    a = math.radians(30)
                    ax1 = x2 - head * (ux * math.cos(a) - uy * math.sin(a))
                    ay1 = y2 - head * (uy * math.cos(a) + ux * math.sin(a))
                    ax2 = x2 - head * (ux * math.cos(-a) - uy * math.sin(-a))
                    ay2 = y2 - head * (uy * math.cos(-a) + ux * math.sin(-a))
                    g.add(dwg.polygon(points=[(x2, y2), (ax1, ay1), (ax2, ay2)],
                                      fill=color, stroke=color))
                if label:
                    mid = pts[len(pts) // 2]
                    lx, ly = mid
                    if lpos == "u":
                        ly -= 25
                    elif lpos == "d":
                        ly += 25
                    elif lpos == "l":
                        lx -= 120
                    elif lpos == "r":
                        lx += 20
                    g.add(dwg.text(label, insert=(lx, ly), fill=color,
                                   font_size=fs, text_anchor=anchor))
                dwg.add(g)

        elif kind == "rect":
            label = item.get("label", "")
            if label in ("EP11", "EP12"):
                continue
            px = item.get("px", [])
            w = item.get("w", 200)
            h = item.get("h", 200)
            dash = item.get("dash", False)
            color = C_YELLOW if dash else C_CYAN
            if px:
                x, y = px
                g = dwg.g(id=f"rect-{label}", stroke=color, fill="none",
                          stroke_width=3 if dash else 4,
                          stroke_dasharray="6,4" if dash else None)
                g.add(dwg.rect(insert=(x, y), size=(w, h)))
                if label:
                    g.add(dwg.text(label, insert=(x + 5, y - 20),
                                   fill=color, font_size=16))
                dwg.add(g)

        elif kind == "mark" or layer == "marks":
            label = item.get("label", "")
            if label in ("EP11", "EP12"):
                continue
            px = item.get("px", [])
            dot = item.get("dot", False)
            fs = item.get("fs", 22)
            lpos = item.get("lpos", "")
            note = item.get("note", "")
            anchor = {"u": "middle", "d": "middle", "l": "end", "r": "start",
                      "ul": "end", "ur": "start", "dr": "start"}.get(lpos, "start")
            if px:
                x, y = px
                g = dwg.g(id=f"mark-{label}")
                if dot:
                    g.add(dwg.circle(center=(x, y), r=8, fill=C_RED,
                                     stroke=C_WHITE, stroke_width=2))
                if label:
                    lx, ly = x, y
                    if lpos == "u":
                        ly -= fs + 5
                    elif lpos == "d":
                        ly += 10
                    elif lpos == "l":
                        lx -= len(label) * fs * 0.6
                    elif lpos == "r":
                        lx += 10
                    elif lpos == "ul":
                        lx -= len(label) * fs * 0.6
                        ly -= fs + 5
                    elif lpos == "ur":
                        lx += 10
                        ly -= fs + 5
                    elif lpos == "dr":
                        lx += 10
                        ly += 10
                    g.add(dwg.text(label, insert=(lx, ly), fill=C_RED,
                                   font_size=fs, text_anchor=anchor))
                if note:
                    g.add(dwg.text(note, insert=(lx, ly + fs + 2),
                                   fill=C_YELLOW, font_size=14))
                dwg.add(g)

        elif kind == "text" or layer in ("notes",):
            px = item.get("px", [])
            label = item.get("label", "")
            fs = item.get("fs", 18)
            if px and label:
                dwg.add(dwg.text(label, insert=tuple(px),
                                 fill=C_WHITE, font_size=fs))

    dwg.save()


def render_rx_flow(pcb_img_path, wpts_path, out_svg, out_png, components_path=None):
    # 加载 PCB 底图
    if Path(pcb_img_path).exists():
        base = Image.open(pcb_img_path).convert("RGBA")
    else:
        base = Image.new("RGBA", (5100, 6600), (255, 255, 255, 255))
        print(f"警告: 底图不存在 {pcb_img_path}, 使用白色占位图")
    W, H = base.size

    # 加载 wpts / components_index
    with open(wpts_path) as f:
        wpts = json.load(f)
    comp_idx = {}
    if components_path and Path(components_path).exists():
        with open(components_path) as f:
            comp_idx = json.load(f)

    # PNG
    render_png(wpts, base, comp_idx)
    base.save(out_png)
    print(f"PNG saved: {out_png}")

    # SVG
    generate_svg(wpts, out_svg, W, H, pcb_img_path, comp_idx)
    print(f"SVG saved: {out_svg}")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", required=True)
    ap.add_argument("--wpts", required=True)
    ap.add_argument("--out-png", default="rx_flow_top_v8.png")
    ap.add_argument("--out-svg", default="rx_flow_top_v8.svg")
    ap.add_argument("--components", help="components_index.json 路径")
    args = ap.parse_args()
    render_rx_flow(args.pcb, args.wpts, args.out_svg, args.out_png, args.components)


if __name__ == "__main__":
    main()
