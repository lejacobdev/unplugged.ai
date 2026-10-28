"""Draws the unplugged.ai app icons (a row of waveform bars) into web/icons/."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "web/icons"
OUT.mkdir(exist_ok=True)
BARS = [0.30, 0.55, 0.85, 0.55, 0.30]
LIFT = 0.16  # the last bar floats free and is coloured: the "unplugged" mark
ACCENT = (240, 160, 110, 255)


def icon(size, maskable=False, rounded=True):
    s = size * 4  # draw large, then downsample for smooth edges
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if rounded:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=(20, 20, 22, 255))
    else:
        d.rectangle([0, 0, s, s], fill=(20, 20, 22, 255))  # full bleed (iOS rounds it itself)
    pad = 0.30 if maskable else 0.22
    area = s * (1 - 2 * pad)
    n = len(BARS)
    w = area / (n * 2 - 1)
    for i, h in enumerate(BARS):
        x0 = s * pad + i * 2 * w
        bh = area * h
        y0 = s / 2 - bh / 2
        last = i == n - 1
        if last:
            y0 -= area * LIFT
        d.rounded_rectangle([x0, y0, x0 + w, y0 + bh], radius=w / 2, fill=ACCENT if last else (236, 236, 236, 255))
    return im.resize((size, size), Image.LANCZOS)


icon(180, rounded=False).convert("RGB").save(OUT / "apple-touch-icon.png")
icon(192).save(OUT / "icon-192.png")
icon(512).save(OUT / "icon-512.png")
icon(512, maskable=True, rounded=False).save(OUT / "icon-maskable-512.png")
icon(64).save(OUT / "favicon.png")
print("icons written to", OUT)
