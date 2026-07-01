"""Histogram levels + the ACR tone curve — the luminance/level maths.

Auto Levels / Auto Contrast build per-band stretch LUTs from an image's
histogram; the tone curve turns the highlights/shadows/whites/blacks sliders
into a single 256-entry LUT. All pure: LUTs and small maths, no Tk, no state.
The pipeline (see __init__) applies these; the window's auto-tone code calls
`autocontrast_luts` directly and feeds the result back in.
"""

import math

from PIL import Image


AUTO_CUTOFF = 0.5   # % of pixels clipped at each end before the histogram stretch

# Tone-curve push (0–255 units) at a full slider (amount = ±1) for each
# ACR tone control. Highlights/Shadows act on the BROAD bright/dark regions
# (a smooth hump that fades out at the extremes); Whites/Blacks act ONLY at
# the extreme top/bottom (the clipping points). This keeps all four visibly
# distinct, the way they behave in Photoshop.
TONE_HL = 70.0
TONE_SH = 70.0
TONE_WH = 55.0
TONE_BL = 55.0


# --- Auto levels / auto contrast --------------------------------------------

def stretch_lut(hist, cutoff):
    "256-entry LUT stretching [lo, hi] (after clipping `cutoff`% off each end) to 0–255."
    n = sum(hist)
    if n == 0:
        return list(range(256))
    clip = n * cutoff / 100.0
    cum, lo = 0, 0
    for i in range(256):
        cum += hist[i]
        if cum > clip:
            lo = i
            break
    cum, hi = 0, 255
    for i in range(255, -1, -1):
        cum += hist[i]
        if cum > clip:
            hi = i
            break
    if hi <= lo:
        return list(range(256))
    scale = 255.0 / (hi - lo)
    return [0 if i <= lo else 255 if i >= hi else int(round((i - lo) * scale))
            for i in range(256)]


def autocontrast_luts(img, per_channel, cutoff=AUTO_CUTOFF):
    "Per-band stretch LUTs. per_channel=True → Auto Levels (each RGB channel"
    " stretched alone, fixing a colour cast); False → Auto Contrast (one"
    " luminance stretch shared by all bands, so colour balance is kept)."
    img = img.convert("RGB")
    if per_channel:
        return [stretch_lut(b.histogram(), cutoff) for b in img.split()]
    lut = stretch_lut(img.convert("L").histogram(), cutoff)
    return [lut, lut, lut]


# --- Tone curve (highlights / shadows / whites / blacks) --------------------

def _bump(t, center, half):
    "Raised-cosine hump: 1.0 at center, fading to 0.0 at center ± half (and beyond)."
    d = abs(t - center)
    if d >= half:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * d / half))


def tone_lut(e):
    "One 256-entry LUT combining highlights/shadows/whites/blacks (None if neutral)."
    hl = e.highlights - 1.0
    sh = e.shadows - 1.0
    wh = e.whites - 1.0
    bl = e.blacks - 1.0
    if hl == 0.0 and sh == 0.0 and wh == 0.0 and bl == 0.0:
        return None
    lut = []
    for i in range(256):
        t = i / 255.0
        # Highlights/Shadows: broad humps over the bright / dark midtones that
        # taper before the very ends. Whites/Blacks: steep, only the top /
        # bottom ~28% (the clip points).
        w_hl = _bump(t, 0.62, 0.38)
        w_sh = _bump(t, 0.38, 0.38)
        w_wh = max(0.0, (t - 0.72) / 0.28) ** 2
        w_bl = max(0.0, (0.28 - t) / 0.28) ** 2
        v = (i
             + hl * TONE_HL * w_hl
             + sh * TONE_SH * w_sh
             + wh * TONE_WH * w_wh
             + bl * TONE_BL * w_bl)
        lut.append(max(0, min(255, int(round(v)))))
    return lut


def apply_auto_luts(img, luts):
    "Auto Levels / Auto Contrast: per-channel stretch through the prebuilt LUTs."
    r, g, b = img.convert("RGB").split()
    return Image.merge("RGB", (r.point(luts[0]), g.point(luts[1]), b.point(luts[2])))
