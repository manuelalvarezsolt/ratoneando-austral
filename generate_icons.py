"""Genera los íconos PNG de la PWA. Ejecutar una sola vez: python generate_icons.py"""
import os, sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    os.system(f'"{sys.executable}" -m pip install Pillow')
    from PIL import Image, ImageDraw, ImageFont

BG   = (26, 74, 122)     # #1A4A7A
TEXT = (230, 237, 243)   # #E6EDF3

FONT_CANDIDATES = [
    'C:/Windows/Fonts/arialbd.ttf',
    'C:/Windows/Fonts/calibrib.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
]

def load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def make_icon(px):
    img  = Image.new('RGBA', (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, px, px], radius=int(px * 0.22), fill=BG)

    font = load_font(int(px * 0.56))
    text = 'R'
    bb   = draw.textbbox((0, 0), text, font=font)
    x    = (px - (bb[2] - bb[0])) / 2 - bb[0]
    y    = (px - (bb[3] - bb[1])) / 2 - bb[1] - px * 0.02
    draw.text((x, y), text, fill=TEXT, font=font)
    return img

out = os.path.join(os.path.dirname(__file__), 'app', 'static', 'icons')
os.makedirs(out, exist_ok=True)

for size in [180, 192, 512]:
    p = os.path.join(out, f'icon-{size}.png')
    make_icon(size).save(p, 'PNG')
    print(f'Creado: {p}')

print('Listo.')
