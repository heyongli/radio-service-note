import json, argparse, math
from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument('--png', required=True)
ap.add_argument('--waypoints', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--scale', type=float, default=1.0)
ap.add_argument('--width', type=int, default=7, help='line width (at scale=1)')
ap.add_argument('--fontsize', type=int, default=18, help='label font size (at scale=1)')
ap.add_argument('--dotsize', type=int, default=14, help='dot radius (at scale=1)')
a = ap.parse_args()

im = Image.open(a.png).convert('RGB')
if a.scale != 1.0:
    im = im.resize((int(im.width*a.scale), int(im.height*a.scale)), Image.LANCZOS)
d = ImageDraw.Draw(im)
w = [dict(p) for p in json.load(open(a.waypoints))]
if a.scale != 1.0:
    for p in w:
        p['px'] = [p['px'][0]*a.scale, p['px'][1]*a.scale]
        if 'through' in p:
            p['through'] = [[q[0]*a.scale, q[1]*a.scale] for q in p['through']]
LW = max(1, round(a.width*a.scale))
DOT = max(2, round(a.dotsize*a.scale))
try:
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                              max(8, round(a.fontsize*a.scale)))
except OSError:
    font = ImageFont.load_default()

GREEN = (0, 230, 60)
def dashed_line(d, a1, b1, fill, width, dash=18, gap=12):
    x0, y0 = a1; x1, y1 = b1
    L = math.hypot(x1-x0, y1-y0)
    if L == 0: return
    n = max(1, int(L // (dash+gap)))
    for k in range(n+1):
        s0 = k*(dash+gap)/L; s1 = min(1.0, (k*(dash+gap)+dash)/L)
        if s0 >= 1: break
        d.line([x0+(x1-x0)*s0, y0+(y1-y0)*s0, x0+(x1-x0)*s1, y0+(y1-y0)*s1], fill=fill, width=width)
for i, p in enumerate(w):
    prev = w[i-1]['px'] if i else None
    if prev:
        if p.get('dash') or w[i-1].get('dash'):
            dashed_line(d, prev, p['px'], GREEN, LW)
        else:
            d.line([prev[0], prev[1], p['px'][0], p['px'][1]], fill=GREEN, width=LW)
    for q in p.get('through', []):
        d.line([q[0], q[1], p['px'][0], p['px'][1]], fill=GREEN, width=LW)
    if p.get('dot'):
        d.ellipse([p['px'][0]-DOT, p['px'][1]-DOT, p['px'][0]+DOT, p['px'][1]+DOT], outline=GREEN, width=max(2, LW//2+1))
    d.text((p['px'][0]+18, p['px'][1]-30), p['label'], fill=(255,255,120), font=font)
im.save(a.out)
print(a.out, im.size)
