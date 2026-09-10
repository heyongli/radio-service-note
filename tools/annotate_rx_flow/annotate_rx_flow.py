#!/usr/bin/env python3
"""Draw a block-level RX (or TX) signal-flow annotation over a rendered PCB view.

Reads a waypoint config (JSON) and renders a thick green polyline with:
  - numbered circle markers at each waypoint
  - block labels (functional block from the schematic)
  - arrows along the path
  - a legend block with disclaimer

Why block-level: the IC-2200H top/bottom views (9-2/9-4) are artwork views
without part designators (verified via pdftotext), so part-level routing is not
possible from these pages. Anchor points use text-verified connector callouts;
block positions are approximate (board-fraction coordinates).

Usage:
  python3 annotate_rx_flow.py --png extract/top_hi-1.png \
      --board 742,579,2781,2015 --out extract/top_rx_annot.png
"""
import argparse
import json

from PIL import Image, ImageDraw, ImageFont

FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def get_font(size):
    import os
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


DEFAULT_BLOCKS = [
    # (fraction x, fraction y, label)  fractions of the board rect
    # order = RX signal order; verified chain from rxtxflow schematic page
    (0.955, 0.06, "ANT (J1)"),
    (0.880, 0.28, "LPF"),
    (0.800, 0.24, "20dB ATT"),
    (0.715, 0.30, "BPF\n136-174"),
    (0.640, 0.36, "1st MIX"),
    (0.560, 0.44, "F1\n1st IF"),
    (0.470, 0.52, "FM IF IC\n(2nd MIX/DET)"),
    (0.400, 0.62, "F1/F2\n455kHz"),
    (0.360, 0.72, "DET/AF"),
    (0.470, 0.82, "AF AMP\nVOL"),
    (0.700, 0.88, "AF OUT"),
    (0.955, 0.06, "SP"),   # placeholder, replaced below
]


def draw_flow(png, board, out, blocks, width=9, disclaimer=None):
    im = Image.open(png).convert("RGB")
    d = ImageDraw.Draw(im)
    L, T, R, B = board
    pts = [(L + fx * (R - L), T + fy * (B - T)) for fx, fy, _ in blocks]
    font = get_font(34)
    small = get_font(26)

    # thick green path
    d.line(pts, fill=(0, 200, 0), width=width, joint="curve")
    for (x, y), (nx, ny) in zip(pts, pts[1:]):
        # arrowhead mid-segment
        mx, my = (x + nx) / 2, (y + ny) / 2
        import math
        ang = math.atan2(ny - y, nx - x)
        for da in (2.6, -2.6):
            d.line([(mx, my), (mx + 22 * math.cos(ang + da),
                               my + 22 * math.sin(ang + da))],
                   fill=(0, 160, 0), width=width - 2)

    for i, ((x, y), (_, _, label)) in enumerate(zip(pts, blocks)):
        r = 22
        d.ellipse([x - r, y - r, x + r, y + r], fill=(0, 200, 0),
                  outline=(0, 90, 0), width=3)
        d.text((x, y), str(i + 1), fill=(255, 255, 255), font=small,
               anchor="mm")
        d.text((x + r + 8, y - r), label, fill=(0, 120, 0), font=font,
               stroke_width=3, stroke_fill=(255, 255, 255))

    if disclaimer:
        tw = d.textlength(disclaimer, font=small)
        d.rectangle([12, 12, 24 + tw, 52], fill=(255, 255, 240),
                    outline=(0, 160, 0), width=2)
        d.text((24, 20), disclaimer, fill=(0, 110, 0), font=small)
    im.save(out)
    print(f"saved {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", required=True)
    ap.add_argument("--board", required=True, help="L,T,R,B px of board rect")
    ap.add_argument("--out", required=True)
    ap.add_argument("--blocks", default=None,
                    help="JSON file with [[fx,fy,label], ...]; "
                    "default = IC-2200H RX chain")
    ap.add_argument("--width", type=int, default=9)
    ap.add_argument("--disclaimer",
                    default="RX flow (block-level, approximate)")
    args = ap.parse_args()

    board = tuple(int(v) for v in args.board.split(","))
    blocks = DEFAULT_BLOCKS[:-1] + [(0.955, 0.06, "SP")]
    if args.blocks:
        blocks = [tuple(b) for b in json.load(open(args.blocks))]
    draw_flow(args.png, board, args.out, blocks, width=args.width,
              disclaimer=args.disclaimer)


if __name__ == "__main__":
    main()
