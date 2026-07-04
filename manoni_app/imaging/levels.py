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


# --- Contrast (mid-gray S-curve) --------------------------------------------

# Contrast pivots at mid-gray (128), so the control behaves the SAME on every
# photo — unlike PIL's ImageEnhance.Contrast, which pivots on the image's own
# mean and therefore reads as "brightening" a dark shot / "darkening" a bright
# one. Positive amounts steepen a sigmoid with a soft rolloff at the ends (no
# hard clip to flat black / white); negative amounts fade the photo by
# compressing the range toward mid-gray. CONTRAST_K = the sigmoid steepness at
# a full (+1) slider (bigger = punchier).
CONTRAST_K = 5.0

# How far the negative (fade) side lifts the BLACK point at a full (-1) slider.
# The fade follows the dehaze "add haze" curve — it raises the black point but
# keeps the white point at 255, so the highlights stay bright. A plain range
# compression toward mid-gray instead pulled the whites down (dull, muddy top),
# which is exactly what this avoids.
CONTRAST_LIFT = 80.0


def contrast_lut(amount):
    "One 256-entry contrast LUT (None if neutral). `amount` signed -1..+1: + adds"
    " contrast through a mid-gray sigmoid (soft rolloff, no clipping), - fades by"
    " lifting the black point while keeping the white point at 255 (bright top)."
    if amount == 0.0:
        return None
    if amount > 0.0:
        k = amount * CONTRAST_K
        s0 = 1.0 / (1.0 + math.exp(k * 0.5))     # sigmoid at input 0
        span = 1.0 / (1.0 + math.exp(-k * 0.5)) - s0   # sigmoid(1) - sigmoid(0)
        lut = []
        for i in range(256):
            s = 1.0 / (1.0 + math.exp(-k * (i / 255.0 - 0.5)))
            lut.append(max(0, min(255, int(round(255.0 * (s - s0) / span)))))
        return lut
    # Negative: fade like the dehaze haze curve — map [0,255] -> [lift, 255], so
    # blacks rise but the white point (upper limit) stays at 255.
    lift = -amount * CONTRAST_LIFT
    return [max(0, min(255, int(round(lift + i * (255.0 - lift) / 255.0))))
            for i in range(256)]


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


# --- Auto tone (auto exposure + contrast normalisation) ---------------------

# Auto Tone normalises a flat / mis-exposed shot: it stretches the black & white
# points to restore contrast, then sets the midtone with a gamma so the photo
# lands at a balanced exposure. It is BIDIRECTIONAL — a washed-out bright shot is
# pulled DOWN, an under-exposed one lifted — unlike the range-only Auto Contrast /
# Auto Level. The trap a plain "median → mid-gray" would hit is graying a clean
# white background; so the DARKENING half of the gamma is faded out when the photo
# already owns a true white point (its 99th percentile is near 255). A genuine
# white-bg product shot therefore keeps its whites, while a dull, washed, no-true-
# white shot (the "overexposed" case) is brought down AND given contrast. One
# shared LUT keeps the colour balance.
AUTO_TONE_CLIP     = 0.4    # % clipped at each end for the black / white points
AUTO_TONE_MID      = 0.48   # target midtone (0..1) the median is pulled toward
AUTO_TONE_STRENGTH = 0.7    # how far toward AUTO_TONE_MID to pull the median
AUTO_TONE_GAMMA_LO = 0.45   # clamp the auto gamma so it never over-corrects
AUTO_TONE_GAMMA_HI = 2.6
AUTO_TONE_WHITE_LO = 240    # p99 below this → washed (darkening allowed, full pull)
AUTO_TONE_WHITE_HI = 253    # p99 at/above this → a true white point (no darkening)


def _percentile_level(hist, pct):
    "The lowest 0–255 level at/below which `pct`% of the pixels fall."
    n = sum(hist)
    if n == 0:
        return 128
    thresh = n * pct / 100.0
    cum = 0
    for i in range(256):
        cum += hist[i]
        if cum >= thresh:
            return i
    return 255


def auto_tone_luts(img):
    "Auto exposure + contrast (see the module notes): stretch the black/white"
    " points, then set the midtone with a gamma — pulling a washed bright shot"
    " DOWN and lifting a dark one, while a true white background is protected from"
    " graying. Colour balance kept (one shared LUT)."
    hist = img.convert("L").histogram()
    n = sum(hist)
    if n == 0:
        lut = list(range(256))
        return [lut, lut, lut]
    # Black / white points (restore contrast on a flat shot).
    clip = n * AUTO_TONE_CLIP / 100.0
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
        lo, hi = 0, 255
    # Midtone gamma toward the target. The DARKENING half is faded out when the
    # photo already owns a true white point (p99 near 255), so a clean white
    # background is not grayed; a washed shot with no real white is pulled down.
    m = min(max((_percentile_level(hist, 50) - lo) / (hi - lo), 0.01), 0.99)
    pull = AUTO_TONE_STRENGTH
    if AUTO_TONE_MID < m:                       # a bright photo → this would DARKEN
        white = min(1.0, max(0.0, (_percentile_level(hist, 99) - AUTO_TONE_WHITE_LO)
                                  / (AUTO_TONE_WHITE_HI - AUTO_TONE_WHITE_LO)))
        pull *= (1.0 - white)                   # protect a true white background
    target = min(max(m + pull * (AUTO_TONE_MID - m), 0.01), 0.99)
    gamma = min(max(math.log(target) / math.log(m),
                    AUTO_TONE_GAMMA_LO), AUTO_TONE_GAMMA_HI)
    scale = 255.0 / (hi - lo)
    lut = []
    for i in range(256):
        v = max(0.0, min(1.0, (i - lo) * scale / 255.0))
        lut.append(max(0, min(255, int(round(255.0 * v ** gamma)))))
    return [lut, lut, lut]


def build_auto_luts(img, mode):
    "Per-channel auto-correction LUTs for `mode`, or None if it is falsy / unknown."
    " 'levels' = per-channel stretch (removes a colour cast); 'contrast' = one"
    " luminance stretch (colour kept); 'tone' = luminance stretch + midtone gamma"
    " (colour kept, midtones re-exposed — see auto_tone_luts)."
    if mode == "tone":
        return auto_tone_luts(img)
    if mode in ("levels", "contrast"):
        return autocontrast_luts(img, mode == "levels")
    return None
