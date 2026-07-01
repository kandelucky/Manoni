"""Generate a diagnostic test chart for Manoni — one image whose zones each make
a specific tool's effect obvious.

The point isn't to be pretty; it's to be *diagnostic*. Every slider / tool has a
zone built to respond to it, so when you drag a control you know exactly which
patch should move (and by how much). Colour patches are built in PIL's HSV so
their hue lands exactly on the app's HSL band centres and gold/skin gates.

Run:  python tests/make_test_chart.py
Out:  test_chart.png  (in the repo root, next to this tests/ folder)

Zone map (see the printed labels on the image):
  A gradient        black->white ramp   light: brightness/contrast/highlights/
                                         shadows/whites/blacks, split-tone, dehaze,
                                         auto levels/contrast
  B hue bars        8 HSL bands + gold   HSL mixer, vibrance, saturation, temp/tint,
                    + skin (top vivid,   b&w, sepia
                    bottom muted)
  C grey wedge      neutral steps +      white balance: temperature / tint
                    flat neutral squares
  D detail          fine grating /       sharpen (fine), texture (mid), clarity
                    checker / star /     (broad), focus blur, denoise (chroma
                    noise / flat         speckle patch), grain (flat patch)
  E grid + spots    straight ruled grid  perspective warp; heal / clone (dust spots
                    + dust spots         on the smooth strip)
  F hazy scene      low-contrast, low-   dehaze (clear), auto levels / auto contrast
                    saturation panel
"""

import os
import random

from PIL import Image, ImageDraw, ImageFont

random.seed(7)          # reproducible noise / spots

W, H = 1600, 1200
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "test_chart.png")


def font(size, bold=True):
    for name in (("arialbd.ttf", "arial.ttf") if bold else ("arial.ttf",)):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_LBL = font(20)
F_SM = font(15, bold=False)


def hsv_patch(size, h, s, v):
    "Solid patch built in HSV so the hue lands exactly on an app band centre."
    return Image.new("HSV", size, (h, s, v)).convert("RGB")


def label(draw, x, y, text, fill=(255, 255, 255), bg=(0, 0, 0), f=F_LBL):
    "A small text tag with a dark plate so it stays readable over any patch."
    l, t, r, b = draw.textbbox((x, y), text, font=f)
    draw.rectangle((l - 4, t - 2, r + 4, b + 2), fill=bg)
    draw.text((x, y), text, font=f, fill=fill)


def main():
    img = Image.new("RGB", (W, H), (30, 30, 30))
    d = ImageDraw.Draw(img)

    # -- A: black -> white gradient (full tonal range) ------------------------
    ay0, ay1 = 30, 150
    for x in range(W):
        g = round(255 * x / (W - 1))
        d.line((x, ay0, x, ay1), fill=(g, g, g))
    label(d, 12, ay0 + 6, "A  TONE / SPLIT-TONE / DEHAZE / LEVELS")

    # -- B: hue bars (8 bands + gold + skin), vivid top / muted bottom --------
    by0, by1 = 170, 380
    mid = (by0 + by1) // 2
    bars = [
        ("red", 0, 255, "band"),      ("orange", 21, 255, "band"),
        ("yellow", 43, 255, "band"),  ("green", 85, 255, "band"),
        ("aqua", 128, 255, "band"),   ("blue", 170, 255, "band"),
        ("purple", 191, 255, "band"), ("magenta", 213, 255, "band"),
        ("gold", 32, 100, "gold"),    ("skin", 18, 40, "skin"),
    ]
    bw = W // len(bars)
    for i, (name, hue, sat, kind) in enumerate(bars):
        x0 = i * bw
        x1 = W if i == len(bars) - 1 else x0 + bw
        w = x1 - x0
        # vivid (top): the band / gate sits here
        img.paste(hsv_patch((w, mid - by0), hue, sat, 225), (x0, by0))
        # muted (bottom): low saturation -> vibrance lifts this most
        muted_s = 90 if kind == "band" else max(28, sat - 55)
        img.paste(hsv_patch((w, by1 - mid), hue, muted_s, 210), (x0, mid))
        label(d, x0 + 4, by0 + 4, name, f=F_SM)
    label(d, 12, by1 + 4, "B  HSL BANDS + GOLD/SKIN  (top vivid / bottom muted)"
                          "  — vibrance, saturation, b&w, sepia", f=F_SM)

    # -- C: neutral grey step wedge + big neutral squares (white balance) -----
    cy0, cy1 = 410, 500
    steps = 16
    sw = W // steps
    for i in range(steps):
        g = round(255 * i / (steps - 1))
        x0 = i * sw
        x1 = W if i == steps - 1 else x0 + sw
        d.rectangle((x0, cy0, x1, cy1), fill=(g, g, g))
    label(d, 12, cy0 + 6, "C  NEUTRAL GREYS — TEMPERATURE / TINT")

    # -- D: detail zone (sharpen / texture / clarity / focus / denoise / grain)
    dy0, dy1 = 530, 770
    dh = dy1 - dy0
    col = W // 5

    # D1 fine 1px grating -> sharpen / focus
    x0 = 0
    for x in range(x0, x0 + col, 2):
        d.line((x, dy0, x, dy1), fill=(230, 230, 230))
        d.line((x + 1, dy0, x + 1, dy1), fill=(25, 25, 25))
    label(d, x0 + 4, dy0 + 4, "fine 1px → sharpen", f=F_SM)

    # D2 medium checker -> texture
    x0 = col
    cs = 6
    for yy in range(dy0, dy1, cs):
        for xx in range(x0, x0 + col, cs):
            on = ((xx // cs) + (yy // cs)) % 2 == 0
            c = (210, 210, 210) if on else (40, 40, 40)
            d.rectangle((xx, yy, xx + cs - 1, yy + cs - 1), fill=c)
    label(d, x0 + 4, dy0 + 4, "6px checker → texture", f=F_SM)

    # D3 radial star -> clarity (broad) / focus blur
    x0 = 2 * col
    cx, cy = x0 + col // 2, (dy0 + dy1) // 2
    R = min(col, dh) // 2 - 6
    spokes = 36
    import math
    for k in range(spokes):
        a0 = 2 * math.pi * k / spokes
        a1 = 2 * math.pi * (k + 0.5) / spokes
        c = (235, 235, 235) if k % 2 == 0 else (30, 30, 30)
        d.polygon([(cx, cy),
                   (cx + R * math.cos(a0), cy + R * math.sin(a0)),
                   (cx + R * math.cos(a1), cy + R * math.sin(a1))], fill=c)
    label(d, x0 + 4, dy0 + 4, "star → clarity/focus", f=F_SM)

    # D4 chroma-noise patch -> denoise (colour speckle on flat grey)
    x0 = 3 * col
    npatch = Image.new("RGB", (col, dh))
    px = npatch.load()
    for yy in range(dh):
        for xx in range(col):
            px[xx, yy] = (max(0, min(255, 130 + random.randint(-45, 45))),
                          max(0, min(255, 130 + random.randint(-45, 45))),
                          max(0, min(255, 130 + random.randint(-45, 45))))
    img.paste(npatch, (x0, dy0))
    label(d, x0 + 4, dy0 + 4, "colour noise → denoise", f=F_SM)

    # D5 flat clean grey -> grain shows here
    x0 = 4 * col
    d.rectangle((x0, dy0, W, dy1), fill=(128, 128, 128))
    label(d, x0 + 4, dy0 + 4, "flat grey → grain", f=F_SM)

    label(d, 12, dy1 + 4, "D  DETAIL — sharpen / texture / clarity / focus "
                          "/ denoise / grain", f=F_SM)

    # -- E: ruled grid (perspective) + dust spots (heal/clone) ----------------
    ey0, ey1 = 800, 1010
    egrid_x1 = W * 3 // 5
    d.rectangle((0, ey0, egrid_x1, ey1), fill=(245, 245, 245))
    gstep = 40
    for x in range(0, egrid_x1, gstep):
        d.line((x, ey0, x, ey1), fill=(20, 20, 20), width=2)
    for y in range(ey0, ey1, gstep):
        d.line((0, y, egrid_x1, y), fill=(20, 20, 20), width=2)
    label(d, 12, ey0 + 6, "E  RULED GRID → perspective (lines must stay straight)",
          f=F_SM)

    # smooth strip with dust spots -> heal / clone
    sx0 = egrid_x1
    for x in range(sx0, W):
        f = (x - sx0) / (W - sx0)
        g = round(70 + 120 * f)
        d.line((x, ey0, x, ey1), fill=(g, g - 6, g - 12))
    for _ in range(9):
        rx = random.randint(sx0 + 20, W - 20)
        ry = random.randint(ey0 + 20, ey1 - 20)
        rr = random.randint(4, 9)
        d.ellipse((rx - rr, ry - rr, rx + rr, ry + rr), fill=(35, 25, 20))
    label(d, sx0 + 8, ey0 + 6, "dust spots → heal / clone", f=F_SM)

    # -- F: hazy low-contrast panel -> dehaze / auto levels -------------------
    fy0, fy1 = 1040, 1180
    # colourful content, but compressed into a narrow bright midtone band and
    # de-saturated: auto-levels should stretch it, dehaze should clear it.
    scene = Image.new("HSV", (W, fy1 - fy0))
    sp = scene.load()
    ww = W
    for xx in range(ww):
        hue = int(255 * xx / ww)
        for yy in range(fy1 - fy0):
            # low saturation + squeezed value range 150..205 = milky / hazy
            v = 150 + int(55 * yy / (fy1 - fy0))
            sp[xx, yy] = (hue, 60, v)
    img.paste(scene.convert("RGB"), (0, fy0))
    label(d, 12, fy0 + 6, "F  HAZY / LOW-CONTRAST → dehaze, auto levels/contrast",
          f=F_SM)

    img.save(OUT)
    print("wrote", OUT, img.size)


if __name__ == "__main__":
    main()
