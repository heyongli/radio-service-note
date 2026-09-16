#!/usr/bin/env python3
"""tools/render_rx_flow.py - RX flow 渲染

purpose: wpts + components_index → PNG/SVG 标注图 (PCB 顶视/底视, 信号流标注)
format: Python 3 + PIL + svgwrite
version: 0.5.0 (2026-09-15 全参数化, 颜色/字号/halo/箭头 都 CLI 可调)
consumers: 任何 RX flow 渲染, IC-2200H/类似 PCB 维修工程

原则 (agent.md §2, §10):
  - 全参数 CLI 化, 不硬编码任何视觉常数 (颜色/字号/halo 宽度/箭头长度等)
  - 默认值遵循"高对比度"原则: 深色文字 + 白色 halo, PCB 浅底可读
  - SVG 同步支持同样的参数化 (文本 halo 用 SVG filter 实现)

默认色板 (PCB 浅底优化, 深色 + halo):
  主流程线: 深绿 (0,140,0) / 虚线
  关键器件红点: 红 (200,0,0) + 黑心
  文字标签: 深蓝 (0,0,180) + 白色 halo (3px)
  确认框 (components_index): 深蓝 (0,0,180)
  旁路/控制框: 紫红 (160,0,160)
  notes 文字: 黑 + 白 halo
"""
import argparse
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


# === 默认色板 (全部 CLI 可覆盖) ===
DEFAULTS = {
    'color_green': '#008C00',
    'color_green_dash': '#007800',
    'color_red': '#C80000',
    'color_blue': '#0000B4',
    'color_purple': '#A000A0',
    'color_white': '#FFFFFF',
    'color_black': '#000000',
    'halo_color': '#FFFFFF',
    'halo_width': 3,
    'font_label': 44,
    'font_line_label': 36,
    'font_note': 28,
    'arrow_head_len': 36,
    'arrow_head_angle': 30,
    'line_width': 8,
    'line_dash_width': 6,
    'box_width': 4,
    'dash_pattern': '14,8',
}


def load_font(size, bold=False):
    font_paths = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
         else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
         else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ("/System/Library/Fonts/Helvetica.ttc", "C:/Windows/Fonts/arialbd.ttf" if bold
         else "C:/Windows/Fonts/arial.ttf"),
    ]
    for fp in font_paths:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            pass
    return ImageFont.load_default()


def hex_to_rgba(s, alpha=255):
    """'#008C00' -> (0,140,0,255)"""
    s = s.lstrip('#')
    if len(s) == 3:
        s = ''.join(c * 2 for c in s)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), alpha)


def draw_text_with_halo(draw, pos, text, fill, font, halo_color=(255, 255, 255, 255), halo_width=3):
    """带描边的文字, 在浅色 PCB 底图上保证可读"""
    x, y = pos
    for dx, dy in [(-halo_width, 0), (halo_width, 0), (0, -halo_width), (0, halo_width),
                    (-halo_width, -halo_width), (halo_width, -halo_width),
                    (-halo_width, halo_width), (halo_width, halo_width)]:
        draw.text((x + dx, y + dy), text, fill=halo_color, font=font)
    draw.text(pos, text, fill=fill, font=font)


def draw_dashed_line(draw, p1, p2, color, width=5, dash=14, gap=8, alpha=140):
    """Draw a dashed line between two points with transparency."""
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    # Apply reduced alpha for dashed lines
    if len(color) == 4:
        dash_color = (color[0], color[1], color[2], alpha)
    else:
        dash_color = color + (alpha,)
    pos = 0
    while pos < length:
        end = min(pos + dash, length)
        sx = x1 + ux * pos
        sy = y1 + uy * pos
        ex = x1 + ux * end
        ey = y1 + uy * end
        draw.line([(sx, sy), (ex, ey)], fill=dash_color, width=width)
        pos += dash + gap


def draw_arrow(draw, x1, y1, x2, y2, color, width=5, head_len=36, head_angle=30, dash=False):
    if dash:
        draw_dashed_line(draw, (x1, y1), (x2, y2), color, width)
    else:
        draw.line([(x1, y1), (x2, y2)], fill=color, width=width, joint="curve")
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist < head_len * 2:
        return
    ux, uy = dx / dist, dy / dist
    a = math.radians(head_angle)
    for sign in [1, -1]:
        ax = x2 - head_len * (ux * math.cos(sign * a) - uy * math.sin(sign * a))
        ay = y2 - head_len * (uy * math.cos(sign * a) + ux * math.sin(sign * a))
        if sign == 1:
            ax1, ay1 = ax, ay
        else:
            ax2, ay2 = ax, ay
    draw.polygon([(x2, y2), (ax1, ay1), (ax2, ay2)], fill=color)


def draw_arrowed_line(draw, points, color, width=8, head_len=36, dash=False):
    if len(points) < 2:
        return
    for i in range(len(points) - 1):
        if i == len(points) - 2:
            draw_arrow(draw, points[i][0], points[i][1],
                       points[i + 1][0], points[i + 1][1],
                       color, width, head_len, dash=dash)
        else:
            if dash:
                draw_dashed_line(draw, points[i], points[i + 1], color, width)
            else:
                draw.line([points[i], points[i + 1]], fill=color, width=width, joint="curve")


# 全局色 (CLI 覆盖)
C = {}


def apply_colors(args):
    """从 CLI args 应用色板到全局 C"""
    global C, C_WHITE
    C['green'] = hex_to_rgba(args.color_green)
    C['green_dash'] = hex_to_rgba(args.color_green_dash)
    C['red'] = hex_to_rgba(args.color_red)
    C['blue'] = hex_to_rgba(args.color_blue)
    C['purple'] = hex_to_rgba(args.color_purple)
    C['black'] = hex_to_rgba(args.color_black)
    C['white'] = hex_to_rgba(args.color_white)
    C['halo'] = hex_to_rgba(args.halo_color)
    C_WHITE = C['white']


def render_png(wpts, base, comp_idx, args):
    C_WHITE = C['white']
    W, H = base.size
    draw = ImageDraw.Draw(base)

    # 确认框 (components_index) - 深蓝, 不画 box 内文字 (避免与 mark 重叠)
    if comp_idx and not args.skip_confirm_boxes:
        for ref, info in comp_idx.items():
            box = info.get("box") or []
            if len(box) != 4:
                continue
            pts = [(int(p[0]), int(p[1])) for p in box]
            draw.polygon(pts, outline=C['blue'], width=args.box_width)

    for item in wpts:
        kind = item.get("kind", "")
        if kind.startswith("_"):
            continue

        if kind == "line":
            px = item.get("px", [])
            through = item.get("through", [])
            dash = item.get("dash", False)
            label = item.get("label", "")
            lpos = item.get("lpos", "")
            fs = item.get("fs", args.font_line_label)

            points = []
            if px:
                points.append(tuple(px))
            points.extend([tuple(p) for p in through])

            if len(points) >= 2:
                color = C['green_dash'] if dash else C['green']
                draw_arrowed_line(draw, points, color,
                                  width=args.line_width if not dash else args.line_dash_width,
                                  head_len=args.arrow_head_len, dash=dash)
                if label:
                    mid = points[len(points) // 2]
                    lx, ly = mid
                    if lpos == "u":
                        ly -= 30
                    elif lpos == "d":
                        ly += 60
                    elif lpos == "l":
                        lx -= 200
                    elif lpos == "r":
                        lx += 30
                    font = load_font(fs, bold=True)
                    draw_text_with_halo(draw, (lx, ly), label,
                                        fill=C['green'], font=font,
                                        halo_color=C_WHITE, halo_width=args.halo_width)

        elif kind == "rect":
            label = item.get("label", "")
            if label in ("EP11", "EP12"):
                continue
            px = item.get("px", [])
            w = item.get("w", 200); h = item.get("h", 200)
            dash = item.get("dash", False)
            color = C['purple'] if dash else C['blue']
            if px:
                x, y = px
                box_coords = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                draw.polygon(box_coords, outline=color,
                             width=(6 if dash else 7))
                if label:
                    draw_text_with_halo(draw, (x + 5, y - args.font_label),
                                        label, fill=color,
                                        font=load_font(args.font_label))

        elif kind == "mark" or layer == "marks" if (layer := item.get("layer", "")) else kind == "mark":
            label = item.get("label", "")
            if label in ("EP11", "EP12"):
                continue
            px = item.get("px", [])
            dot = item.get("dot", False)
            fs = item.get("fs", args.font_label)
            lpos = item.get("lpos", "")
            note = item.get("note", "")
            inferred = label.endswith("?") or item.get("inferred", False)
            mark_type = item.get("mark_type", "")
            if px:
                x, y = px
                # IC outline: 轮廓标注, 另一面用虚线
                if item.get("outline"):
                    ocx = item.get("outline_cx", x)
                    ocy = item.get("outline_cy", y)
                    ow = item.get("outline_w", 220)
                    oh = item.get("outline_h", 160)
                    osw = item.get("outline_stroke", 3)
                    other_side = item.get("outline_view", "top") == "bot"
                    ocolor = C['purple'] if other_side else C['red']
                    rect = [ocx - ow/2, ocy - oh/2, ocx + ow/2, ocy + oh/2]
                    if other_side:
                        # dashed rectangle outline
                        pts = [(rect[0], rect[1]), (rect[2], rect[1]),
                               (rect[2], rect[3]), (rect[0], rect[3]), (rect[0], rect[1])]
                        for i in range(len(pts) - 1):
                            draw_dashed_line(draw, pts[i], pts[i+1], ocolor, width=max(3, osw))
                    else:
                        draw.rectangle(rect, outline=ocolor, width=osw)
                if mark_type == "via":
                    # Cross-side destination: red hollow circle (via), thick outline
                    r = 18
                    draw.ellipse([x - r, y - r, x + r, y + r],
                                 fill=C['white'], outline=C['red'], width=6)
                elif dot:
                    if inferred:
                        # Bot component: via icon (circle with cross)
                        r = 16
                        draw.ellipse([x - r, y - r, x + r, y + r],
                                     fill=C['white'], outline=C['purple'], width=4)
                        draw.line([(x - r, y), (x + r, y)], fill=C['purple'], width=3)
                        draw.line([(x, y - r), (x, y + r)], fill=C['purple'], width=3)
                    else:
                        # Top component: solid red dot with black center
                        r = 18
                        draw.ellipse([x - r, y - r, x + r, y + r],
                                     fill=C['red'], outline=C['red'], width=4)
                        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=C['black'])
                if label:
                    lx, ly = x, y
                    if lpos == "u": ly -= fs + 12
                    elif lpos == "d": ly += 22
                    elif lpos == "l": lx -= len(label) * fs * 0.65 + 12
                    elif lpos == "r": lx += 28
                    elif lpos == "ul":
                        lx -= len(label) * fs * 0.65 + 12
                        ly -= fs + 12
                    elif lpos == "ur": lx += 28; ly -= fs + 12
                    elif lpos == "dr": lx += 28; ly += 22
                    font = load_font(fs, bold=inferred or mark_type == "via")
                    fill = C['red'] if mark_type == "via" else (C['purple'] if inferred else C['red'])
                    draw_text_with_halo(draw, (lx, ly), label,
                                        fill=fill, font=font,
                                        halo_color=C_WHITE,
                                        halo_width=args.halo_width)
                if note:
                    draw_text_with_halo(draw, (lx, ly + fs + 8), note,
                                        fill=C['blue'],
                                        font=load_font(args.font_note),
                                        halo_color=C_WHITE,
                                        halo_width=args.halo_width - 1)

        elif kind == "text" or item.get("layer", "") in ("notes",):
            px = item.get("px", [])
            label = item.get("label", "")
            fs = item.get("fs", args.font_note + 8)
            if px and label:
                draw_text_with_halo(draw, tuple(px), label,
                                    fill=C['black'],
                                    font=load_font(fs, bold=True),
                                    halo_color=C_WHITE,
                                    halo_width=args.halo_width)


def render_png_legacy(*args, **kwargs):
    """兼容旧调用 (不带 layer marker)"""
    pass  # above replaces this


def generate_svg(wpts, out_svg, width, height, pcb_img_path, comp_idx, args):
    """生成 SVG, halo 通过 SVG <filter> 实现 (feMorphology 描边)
    svgwrite 不直接支持 feMorphology, 我们 save 后用 raw XML 注入
    """
    import svgwrite
    import base64

    dwg = svgwrite.Drawing(out_svg, size=(width, height), profile="full")

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

    SC = {k: args.__dict__[f"color_{k}"] for k in
          ['green', 'green_dash', 'red', 'blue', 'purple', 'black', 'white']}

    SC = {k: args.__dict__[f"color_{k}"] for k in
          ['green', 'green_dash', 'red', 'blue', 'purple', 'black', 'white']}

    if comp_idx and not args.skip_confirm_boxes:
        for ref, info in comp_idx.items():
            box = info.get("box") or []
            if len(box) != 4:
                continue
            pts = [(int(p[0]), int(p[1])) for p in box]
            safe_id = "".join(c if c.isalnum() else "-" for c in ref)[:24]
            g = dwg.g(id=f"comp-{safe_id}", stroke=SC['blue'],
                      fill="none", stroke_width=args.box_width)
            g.add(dwg.polygon(points=pts))
            dwg.add(g)

    for item in wpts:
        kind = item.get("kind", "")
        layer = item.get("layer", "")
        if kind.startswith("_"):
            continue

        if kind == "line":
            px = item.get("px", [])
            through = item.get("through", [])
            dash = item.get("dash", False)
            label = item.get("label", "")
            lpos = item.get("lpos", "")
            fs = item.get("fs", args.font_line_label)
            color = SC['green_dash'] if dash else SC['green']
            anchor = {"u": "middle", "d": "middle", "l": "end", "r": "start",
                      "ul": "end", "ur": "start"}.get(lpos, "start")
            pts = list(map(tuple, ([px] if px else []) + through))
            if len(pts) >= 2:
                safe_id = "".join(c if c.isalnum() else "-" for c in label)[:24]
                g = dwg.g(id=f"line-{safe_id}", stroke=color, fill=color,
                          filter="url(#halo)")
                if dash:
                    for i in range(len(pts) - 1):
                        g.add(dwg.line(start=pts[i], end=pts[i + 1],
                                       stroke_width=args.line_dash_width,
                                       stroke_dasharray=args.dash_pattern))
                else:
                    for i in range(len(pts) - 1):
                        g.add(dwg.line(start=pts[i], end=pts[i + 1],
                                       stroke_width=args.line_width))
                    x1, y1 = pts[-2]; x2, y2 = pts[-1]
                    dx, dy = x2 - x1, y2 - y1; d = math.hypot(dx, dy) or 1
                    ux, uy = dx / d, dy / d
                    a = math.radians(args.arrow_head_angle)
                    head = args.arrow_head_len
                    ax1 = x2 - head * (ux * math.cos(a) - uy * math.sin(a))
                    ay1 = y2 - head * (uy * math.cos(a) + ux * math.sin(a))
                    ax2 = x2 - head * (ux * math.cos(-a) - uy * math.sin(-a))
                    ay2 = y2 - head * (uy * math.cos(-a) + ux * math.sin(-a))
                    g.add(dwg.polygon(points=[(x2, y2), (ax1, ay1), (ax2, ay2)],
                                       fill=color, stroke=color))
                if label:
                    mid = pts[len(pts) // 2]
                    lx, ly = mid
                    if lpos == "u": ly -= 40
                    elif lpos == "d": ly += 60
                    elif lpos == "l": lx -= 200
                    elif lpos == "r": lx += 30
                    g.add(dwg.text(label, insert=(lx, ly), fill=color,
                                   font_size=fs, text_anchor=anchor,
                                   font_weight="bold"))
                dwg.add(g)

        elif kind == "rect":
            label = item.get("label", "")
            if label in ("EP11", "EP12"):
                continue
            px = item.get("px", [])
            w = item.get("w", 200); h = item.get("h", 200)
            dash = item.get("dash", False)
            color = SC['purple'] if dash else SC['blue']
            if px:
                x, y = px
                safe_id = "".join(c if c.isalnum() else "-" for c in label)[:24]
                g = dwg.g(id=f"rect-{safe_id}", stroke=color, fill="none",
                          stroke_width=(6 if dash else 7),
                          stroke_dasharray="8,5" if dash else None,
                          filter="url(#halo)")
                g.add(dwg.rect(insert=(x, y), size=(w, h)))
                if label:
                    g.add(dwg.text(label, insert=(x + 8, y - 30),
                                   fill=color, font_size=args.font_label,
                                   font_weight="bold"))
                dwg.add(g)

        elif kind == "mark" or layer == "marks":
            label = item.get("label", "")
            if label in ("EP11", "EP12"):
                continue
            px = item.get("px", [])
            dot = item.get("dot", False)
            fs = item.get("fs", args.font_label)
            lpos = item.get("lpos", "")
            note = item.get("note", "")
            inferred = label.endswith("?") or item.get("inferred", False)
            mark_type = item.get("mark_type", "")
            anchor = {"u": "middle", "d": "middle", "l": "end", "r": "start",
                      "ul": "end", "ur": "start", "dr": "start"}.get(lpos, "start")
            if px:
                x, y = px
                safe_id = "".join(c if c.isalnum() else "-" for c in ref)[:24] if False else "".join(
                    c if c.isalnum() else "-" for c in label)[:24]
                g = dwg.g(id=f"mark-{safe_id}", filter="url(#halo)")
                # IC outline: 另一面用虚线
                if item.get("outline"):
                    ocx = item.get("outline_cx", x)
                    ocy = item.get("outline_cy", y)
                    ow = item.get("outline_w", 220)
                    oh = item.get("outline_h", 160)
                    osw = item.get("outline_stroke", 3)
                    other_side = item.get("outline_view", "top") == "bot"
                    ocolor = SC['purple'] if other_side else SC['red']
                    x1, y1, x2, y2 = ocx - ow/2, ocy - oh/2, ocx + ow/2, ocy + oh/2
                    if other_side:
                        d = ("M%d,%d H%d V%d H%d Z" % (x1, y1, x2, y2, x1))
                        g.add(dwg.path(d=d, fill="none", stroke=ocolor,
                                       stroke_width=osw, stroke_dasharray="14,8"))
                    else:
                        g.add(dwg.rect(insert=(x1, y1), size=(ow, oh), fill="none",
                                       stroke=ocolor, stroke_width=osw))
                if mark_type == "via":
                    # Cross-side destination: red hollow circle (via)
                    r = 18
                    g.add(dwg.circle(center=(x, y), r=r,
                                     fill=SC['white'], stroke=SC['red'], stroke_width=6))
                elif dot:
                    if inferred:
                        # Bot component: via icon (circle with cross)
                        r = 16
                        g.add(dwg.circle(center=(x, y), r=r,
                                         fill=SC['white'], stroke=SC['purple'], stroke_width=4))
                        g.add(dwg.line(start=(x - r, y), end=(x + r, y),
                                       stroke=SC['purple'], stroke_width=3))
                        g.add(dwg.line(start=(x, y - r), end=(x, y + r),
                                       stroke=SC['purple'], stroke_width=3))
                    else:
                        # Top component: solid red dot with black center
                        r = 18
                        g.add(dwg.circle(center=(x, y), r=r,
                                         fill=SC['red'], stroke=SC['red'], stroke_width=4))
                        g.add(dwg.circle(center=(x, y), r=5, fill=SC['black']))
                if label:
                    lx, ly = x, y
                    if lpos == "u": ly -= fs + 12
                    elif lpos == "d": ly += 22
                    elif lpos == "l": lx -= len(label) * fs * 0.65 + 12
                    elif lpos == "r": lx += 28
                    elif lpos == "ul":
                        lx -= len(label) * fs * 0.65 + 12
                        ly -= fs + 12
                    elif lpos == "ur": lx += 28; ly -= fs + 12
                    elif lpos == "dr": lx += 28; ly += 22
                    color = SC['purple'] if inferred else SC['red']
                    g.add(dwg.text(label, insert=(lx, ly), fill=color,
                                   font_size=fs, text_anchor=anchor,
                                   font_weight="bold"))
                if note:
                    g.add(dwg.text(note, insert=(lx, ly + fs + 8),
                                   fill=SC['blue'], font_size=args.font_note))
                dwg.add(g)

        elif kind == "text" or layer in ("notes",):
            px = item.get("px", [])
            label = item.get("label", "")
            fs = item.get("fs", args.font_note + 8)
            if px and label:
                dwg.add(dwg.text(label, insert=tuple(px),
                                 fill=SC['black'],
                                 font_size=fs, font_weight="bold",
                                 filter="url(#halo)"))

    dwg.save()

    # 注入 halo SVG filter (svgwrite 不直接支持 feMorphology, 用 raw XML 后处理)
    halo_filter = (
        f'<filter id="halo" x="-50%" y="-50%" width="200%" height="200%">'
        f'<feMorphology operator="dilate" radius="{args.halo_width}" '
        f'in="SourceGraphic" result="dilated"/>'
        f'<feFlood flood-color="{args.halo_color}" flood-opacity="1"/>'
        f'<feComposite in2="dilated" operator="in"/>'
        f'<feComposite in="SourceGraphic"/>'
        f'</filter>'
    )
    svg_text = Path(out_svg).read_text()
    # 注入 halo filter (兼容 <defs /> 自闭合和 <defs></defs>)
    if "<defs />" in svg_text:
        svg_text = svg_text.replace(
            "<defs />",
            f"<defs>{halo_filter}</defs>",
        )
    elif "<defs" in svg_text and "</defs>" in svg_text:
        idx = svg_text.find("</defs>")
        svg_text = svg_text[:idx] + halo_filter + svg_text[idx:]
    Path(out_svg).write_text(svg_text)


def render_rx_flow(pcb_img_path, wpts_path, out_svg, out_png, components_path, args):
    if Path(pcb_img_path).exists():
        base = Image.open(pcb_img_path).convert("RGBA")
    else:
        base = Image.new("RGBA", (5100, 6600), (255, 255, 255, 255))
        print(f"警告: 底图不存在 {pcb_img_path}, 使用白色占位图")
    W, H = base.size

    with open(wpts_path) as f:
        wpts = json.load(f)
    comp_idx = {}
    if components_path and Path(components_path).exists():
        with open(components_path) as f:
            comp_idx = json.load(f)

    apply_colors(args)
    render_png(wpts, base, comp_idx, args)
    base.save(out_png)
    print(f"PNG saved: {out_png}")

    generate_svg(wpts, out_svg, W, H, pcb_img_path, comp_idx, args)
    print(f"SVG saved: {out_svg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", required=True)
    ap.add_argument("--wpts", required=True)
    ap.add_argument("--components")
    ap.add_argument("--out-png", default="rx_flow_top.png")
    ap.add_argument("--out-svg", default=None,
                    help="SVG 输出路径; 省略则与 --out-png 同目录同名 (.svg)")
    # === 颜色 (全部 CLI) ===
    ap.add_argument("--color-green", default=DEFAULTS['color_green'])
    ap.add_argument("--color-green-dash", default=DEFAULTS['color_green_dash'])
    ap.add_argument("--color-red", default=DEFAULTS['color_red'])
    ap.add_argument("--color-blue", default=DEFAULTS['color_blue'])
    ap.add_argument("--color-purple", default=DEFAULTS['color_purple'])
    ap.add_argument("--color-white", default=DEFAULTS['color_white'])
    ap.add_argument("--color-black", default=DEFAULTS['color_black'])
    # === halo (文字描边) ===
    ap.add_argument("--halo-color", default=DEFAULTS['halo_color'])
    ap.add_argument("--halo-width", type=int, default=DEFAULTS['halo_width'])
    # === 字号 ===
    ap.add_argument("--font-label", type=int, default=DEFAULTS['font_label'])
    ap.add_argument("--font-line-label", type=int, default=DEFAULTS['font_line_label'])
    ap.add_argument("--font-note", type=int, default=DEFAULTS['font_note'])
    # === 箭头 ===
    ap.add_argument("--arrow-head-len", type=int, default=DEFAULTS['arrow_head_len'])
    ap.add_argument("--arrow-head-angle", type=int, default=DEFAULTS['arrow_head_angle'])
    # === 线宽 ===
    ap.add_argument("--line-width", type=int, default=DEFAULTS['line_width'])
    ap.add_argument("--line-dash-width", type=int, default=DEFAULTS['line_dash_width'])
    ap.add_argument("--box-width", type=int, default=DEFAULTS['box_width'])
    ap.add_argument("--dash-pattern", default=DEFAULTS['dash_pattern'])
    # === 开关 ===
    ap.add_argument("--skip-confirm-boxes", action="store_true",
                    help="跳过 components_index 的青色确认框 (避免视觉噪音)")
    args = ap.parse_args()
    if args.out_svg is None:
        args.out_svg = str(Path(args.out_png).with_suffix(".svg"))
    render_rx_flow(args.pcb, args.wpts, args.out_svg, args.out_png, args.components, args)


if __name__ == "__main__":
    main()
