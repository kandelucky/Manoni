"""Generate the two shared-file-type icons from the app icon.

Manoni's shareable files get their own Explorer icons: a filter export (.mnf)
and a language pack (.mnl). Each is the Manoni app icon with a small round
corner badge — a distinct accent colour plus a single bold letter — so the two
read apart at a glance yet still look like Manoni.

The badge colours are Manoni's own accents (see config.ACCENTS): Teal = filter,
Orange = language. Rendered at 4x then downscaled for clean edges, and saved as
multi-resolution .ico (256 down to 16) so they stay sharp at every Explorer view.

Run:    .venv\\Scripts\\python.exe tools\\make_filetype_icons.py
Output: mnf.ico, mnl.ico  (project root, beside manoni.ico)
"""

import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "manoni-icon.png")
FONT = r"C:\Windows\Fonts\segoeuib.ttf"   # Segoe UI Bold

SS = 4               # supersample factor for smooth edges
SIZE = 256           # master size (px)
ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]

# (extension, letter, badge fill, base-cut ring) — fills are Manoni accents.
TYPES = [
    ("mnf", "F", "#24b1a6"),   # Teal   — filter preset
    ("mnl", "L", "#ef8a53"),   # Orange — language pack
]

RING = "#1b1b1b"     # matches config.BG — a "cut-out" gap that lifts the badge
                     # off the app icon's own dark artwork


def _hx(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def build(letter, fill):
    base = Image.open(BASE).convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
    S = SIZE * SS
    img = base.resize((S, S), Image.LANCZOS)
    d = ImageDraw.Draw(img)

    # Badge geometry (in supersampled px): bottom-right, small margin.
    diam = int(S * 0.52)
    margin = int(S * 0.03)
    x1 = S - margin - diam
    y1 = S - margin - diam
    x2, y2 = x1 + diam, y1 + diam

    # Cut-out ring first (a fatter disc in the app-bg colour), then the fill.
    ring = int(S * 0.028)
    d.ellipse((x1 - ring, y1 - ring, x2 + ring, y2 + ring), fill=_hx(RING))
    d.ellipse((x1, y1, x2, y2), fill=_hx(fill))

    # Centred bold letter, white. Size the glyph to the badge, then nudge to the
    # true visual centre using its bbox (bold caps sit high with side bearings).
    font = ImageFont.truetype(FONT, int(diam * 0.62))
    l, t, r, b = d.textbbox((0, 0), letter, font=font)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    d.text((cx - (l + r) / 2, cy - (t + b) / 2), letter,
           font=font, fill=(255, 255, 255, 255))

    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    for ext, letter, fill in TYPES:
        icon = build(letter, fill)
        out = os.path.join(ROOT, ext + ".ico")
        icon.save(out, format="ICO", sizes=ICO_SIZES)
        print("wrote", out)


if __name__ == "__main__":
    main()
