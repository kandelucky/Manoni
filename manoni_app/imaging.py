"""Pure image-processing for Manoni — Pillow in, Pillow out.

No Tk and no Manoni state: every function takes its inputs explicitly (an `Edits`
value object for the slider settings, plus the source image and geometry). That
keeps the math readable, reusable and testable on its own, while the window code
stays about the UI. The Manoni methods are thin wrappers that build an `Edits`
from the live sliders and call in here.
"""

import math
from dataclasses import dataclass

from PIL import (Image, ImageEnhance, ImageFilter, ImageDraw, ImageStat,
                 ImageChops, ImageFont)


# --- Tuning constants (were class attributes on Manoni) ----------------------

AUTO_CUTOFF = 0.5   # % of pixels clipped at each end before the histogram stretch

# Blur radius (full-res source pixels) at the slider's max-blur end.
MAX_BLUR = 8.0

# Clarity: large-radius local contrast. Radius is in full-res pixels (scaled
# to display pixels in the preview, like blur). Vibrance: max saturation push.
CLARITY_RADIUS = 24.0   # full-res px; UnsharpMask radius at a full slider
CLARITY_PCT    = 120    # UnsharpMask percent at a full slider (amount = +1)
VIBRANCE_MAX   = 130.0  # max saturation add (0–255) for the most-muted pixels

# Texture: medium-frequency detail, sitting between sharpen (fine, ~1px) and
# clarity (broad, ~24px). Positive = crisper surface detail via a small-radius
# UnsharpMask with a threshold so flat areas / noise stay clean. Negative =
# gentle surface smoothing (a light blur blend; edge-aware only via the soft
# cap — PIL has no true bilateral filter, so this side is an approximation).
TEXTURE_RADIUS = 3.0    # full-res px; UnsharpMask radius at a full slider
TEXTURE_PCT    = 90     # UnsharpMask percent at a full slider (amount = +1)
TEXTURE_THRESH = 3      # skip diffs below this (leaves noise / flat tone alone)
TEXTURE_SMOOTH = 0.5    # max blur-blend fraction at a full negative slider

# Vignette: shade the corners (radial gradient × image). Bidirectional: the
# full slider drives corners to pure white / black, so no strength cap. AX =
# the bright-core semi-axis as a fraction of the image. Smaller = the shaded
# ring reaches further IN from the edges (stronger, more visible); ≈0.45 darkens
# the mid-edges too, not just the corners. BLUR_FRAC = falloff softness; the
# smooth mask is built at most MASK_MAX px then scaled up — cheap on a big save.
VIGNETTE_AX        = 0.45
VIGNETTE_BLUR_FRAC = 0.20
VIGNETTE_MASK_MAX  = 600

# Selective focus blur (Fotor-style depth of field). A circle stays sharp; the
# rest blurs. FOCUS_MAX_BLUR = Gaussian radius (full-res px) at a full strength
# slider — bigger than the global MAX_BLUR so the "background" can melt away.
# The soft mask is built at most MASK_MAX px then scaled up, like the vignette,
# so a full-res save doesn't pay for a huge-image mask blur.
FOCUS_MAX_BLUR  = 40.0
FOCUS_MASK_MAX  = 600

# Tone-curve push (0–255 units) at a full slider (amount = ±1) for each
# ACR tone control. Highlights/Shadows act on the BROAD bright/dark regions
# (a smooth hump that fades out at the extremes); Whites/Blacks act ONLY at
# the extreme top/bottom (the clipping points). This keeps all four visibly
# distinct, the way they behave in Photoshop.
TONE_HL = 70.0
TONE_SH = 70.0
TONE_WH = 55.0
TONE_BL = 55.0

# Sepia: a warm monochrome look. The grayscale luminance is mapped through a
# per-channel ramp (scale, offset) so shadows go warm-brown and highlights go
# cream — the classic darkroom tone. Roughly luminance-preserving at mid-gray.
# Strength 0..1 then blends this toned image over the original.
SEPIA_RAMP = ((0.843, 40), (0.765, 25), (0.588, 10))   # R, G, B: gray*scale + offset

# Film grain (analog look): monochrome Gaussian luminance noise laid over the
# finished image. GRAIN_MAX_SIGMA = the noise std-dev at a full slider (bigger =
# coarser, more visible specks). GRAIN_SIZE = the grain CELL in full-res source
# px; it is scaled to the preview's display px (like blur/clarity) so the grain
# the preview shows matches the saved full-res file rather than being finer.
GRAIN_MAX_SIGMA = 40.0
GRAIN_SIZE      = 1.5

# Noise reduction (high-ISO clean-up). The ugly part of digital noise is CHROMA
# — random colour specks; luminance noise reads as natural film-like grain. So
# we work in YCbCr and median-filter the chroma (Cb/Cr) HARD, where there is
# little real detail to lose, while touching luma (Y) only gently so edges and
# texture stay sharp. Median beats Gaussian on impulse/speckle noise. The window
# is in full-res px, scaled to the preview's display px (like blur/grain) so the
# preview tracks the saved file. LUMA_MAX caps how far luma is smoothed.
DENOISE_CHROMA_SIZE = 5.0   # full-res median window (px) for chroma at full slider
DENOISE_LUMA_SIZE   = 3.0   # gentler luma median window (px) at full slider
DENOISE_LUMA_MAX    = 0.6   # max luma blend fraction (keep detail) at a full slider

# Dehaze: approximate atmospheric-haze removal (Pillow has no true dark-channel
# prior, so this is a tasteful stand-in). Positive (+) CLEARS haze — pull the
# black point up to kill the milky veil, raise contrast, and re-saturate (haze
# washes colour out); negative (-) ADDS haze — lift the blacks, soften contrast
# and desaturate, for a soft atmospheric look. Global point/enhance ops, so it
# is scale-free (preview = save).
DEHAZE_BLACK    = 34    # black-point shift (0–255) at a full slider
DEHAZE_CONTRAST = 0.45  # contrast change at a full slider
DEHAZE_COLOR    = 0.45  # saturation change at a full slider

# Split-tone (colour grading): tint the SHADOWS and HIGHLIGHTS with independent
# warm↔cool shifts — the cinematic "teal & orange" look and its kin. Each amount
# is signed -1..+1: + warms (toward orange, R↑/B↓), - cools (toward teal/blue,
# R↓/B↑), exactly the temperature axis but applied through a luminance mask so
# the highlight tone touches only bright pixels and the shadow tone only dark
# ones — the midtones (skin) stay cleaner. SPLIT_MAX = the per-channel push.
SPLIT_MAX = 38.0   # max per-channel push (0–255) at a full slider


@dataclass
class Edits:
    """The live edit factors, all neutral by default.

    Each field is the slider's factor: 1.0 means "unchanged" (0.0 for the
    effects `bw`/`sepia`, which are 0..1 blends). Build one from the sliders and pass it to
    `apply_edits`. Plain data — no behaviour — so it is trivial to snapshot.
    """
    brightness:  float = 1.0
    contrast:    float = 1.0
    highlights:  float = 1.0
    shadows:     float = 1.0
    whites:      float = 1.0
    blacks:      float = 1.0
    clarity:     float = 1.0
    texture:     float = 1.0
    vibrance:    float = 1.0
    # Dehaze: 1.0 = neutral; amount = factor - 1.0 in [-1, 1] (+ clears haze, -
    # adds it). Approximate (Pillow has no dark-channel prior). See apply_dehaze.
    dehaze:      float = 1.0
    color:       float = 1.0
    temperature: float = 1.0
    tint:        float = 1.0
    # HSL colour mixer: per-hue saturation. Each factor 1.0 = unchanged, 0.0 =
    # that colour fully greyed, 2.0 = doubled. See apply_color_mixer / HSL_BANDS.
    sat_red:     float = 1.0
    sat_orange:  float = 1.0
    sat_yellow:  float = 1.0
    sat_green:   float = 1.0
    sat_aqua:    float = 1.0
    sat_blue:    float = 1.0
    sat_purple:  float = 1.0
    sat_magenta: float = 1.0
    # Gold and skin each get their own three-slider mini-HSL (the eight bands
    # only do saturation): hue shifts the tone, saturation deepens it, and the
    # third lifts its lightness. Both are HUE + SATURATION gated so they touch
    # only that material, not the pale things sharing its hue. All 1.0 = unchanged.
    gold_hue:    float = 1.0
    gold_sat:    float = 1.0
    gold_light:  float = 1.0
    skin_hue:    float = 1.0
    skin_sat:    float = 1.0
    skin_light:  float = 1.0
    # Noise reduction: 1.0 = off (kept at 1.0 so it shares the slider/factor
    # plumbing), down to 0.0 here it is OFF and 1.0 here would be full — see the
    # editpanel slider, which rests this at 0.0 (off → full). See apply_denoise.
    denoise:     float = 0.0
    bw:          float = 0.0
    sepia:       float = 0.0
    sharpen:     float = 1.0
    vignette:    float = 1.0
    # Film grain: 0.0 = off, up to 1.0 = full strength. See apply_grain.
    grain:       float = 0.0
    # Split-tone (colour grading): warm↔cool tint for highlights / shadows.
    # 1.0 = neutral; amount = factor - 1.0 in [-1, 1] (+ warm, - cool). See
    # apply_split_tone.
    split_hi:    float = 1.0
    split_sh:    float = 1.0
    # Selective "focus" blur (Fotor-style depth of field): a circle kept sharp
    # while everything outside it is Gaussian-blurred. None = off, else a dict
    # {cx, cy, r (source px), blur 0..1, feather 0..1}. See apply_focus_blur.
    focus:       object = None
    # Text / watermark overlay. None = off, else a dict with the string, its
    # centre + size in SOURCE px (so it stays glued to the photo through zoom /
    # pan and the preview matches the full-res save), colour, opacity, font key,
    # alignment and an optional drop shadow. See apply_text_overlay.
    text:        object = None


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


# --- Vignette ----------------------------------------------------------------

def apply_vignette(img, amount, scale, src_box, full_size, cache=None):
    """Shade the photo's CORNERS via a soft radial mask (the classic 'radial
    gradient × image'). `amount` is signed, -1..+1: negative LIGHTENS the
    corners (high-key), positive DARKENS them; the full slider (±1) drives the
    corners all the way to white / black. The bright ellipse is positioned in
    full-image coordinates and mapped into the visible region, so zoom/pan keep
    the vignette anchored to the photo centre, not the viewport edges. The mask
    depends only on geometry (not amount), so it is cached across drags via the
    optional `cache` dict (one geometry at a time, like the old single slot)."""
    w, h = img.size
    key = (w, h, src_box, full_size)
    mask = cache.get(key) if cache is not None else None
    if mask is None:
        fw, fh = full_size
        sx0, sy0, _sx1, _sy1 = src_box
        cx, cy = fw / 2.0, fh / 2.0
        ax, ay = fw * VIGNETTE_AX, fh * VIGNETTE_AX
        # bright-ellipse bbox mapped into this region's display pixels
        bbox = [(cx - ax - sx0) * scale, (cy - ay - sy0) * scale,
                (cx + ax - sx0) * scale, (cy + ay - sy0) * scale]
        blur = VIGNETTE_BLUR_FRAC * min(fw, fh) * scale
        # The mask is low-frequency: build it small, then scale up (cheap on
        # a big full-res save, where a full-size GaussianBlur would be slow).
        f = min(1.0, VIGNETTE_MASK_MAX / max(w, h))
        mw, mh = max(1, round(w * f)), max(1, round(h * f))
        mask = Image.new("L", (mw, mh), 0)
        ImageDraw.Draw(mask).ellipse([c * f for c in bbox], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(max(0.5, blur * f)))
        if (mw, mh) != (w, h):
            mask = mask.resize((w, h), Image.BILINEAR)
        if cache is not None:
            cache.clear()            # keep only the latest geometry (single slot)
            cache[key] = mask
    # Where the mask is dark (corners) the pixels become `edge`; at the centre
    # they stay as `img`. amount=+1 → black corners, amount=-1 → white corners.
    a = abs(amount)
    if amount > 0:
        edge = ImageEnhance.Brightness(img).enhance(1.0 - a)     # toward black
    else:
        white = Image.new("RGB", img.size, (255, 255, 255))
        edge = Image.blend(img, white, a)                       # toward white
    return Image.composite(img, edge, mask)


# --- Film grain --------------------------------------------------------------

def apply_grain(img, amount, scale):
    """Lay monochrome film grain over the finished image: Gaussian luminance
    noise added equally to R/G/B (so it reads as grain, not colour speckle).
    `amount` 0..1 = strength (the noise sigma). The grain CELL is GRAIN_SIZE
    full-res source px scaled to the preview's display px, so the preview's
    grain matches what the saved full-res file gets — like blur/clarity. Pure
    Pillow: the noise is split into a positive and a negative offset and
    added / subtracted per channel, no numpy."""
    img = img.convert("RGB")
    w, h = img.size
    if w < 1 or h < 1 or amount <= 0.0:
        return img
    sigma = amount * GRAIN_MAX_SIGMA
    cell = max(1, int(round(GRAIN_SIZE * scale)))    # grain clump in display px
    nw, nh = max(1, w // cell), max(1, h // cell)
    noise = Image.effect_noise((nw, nh), sigma)      # "L", Gaussian around 128
    if (nw, nh) != (w, h):
        noise = noise.resize((w, h), Image.BILINEAR)  # clump + smooth the specks
    hi = noise.point(lambda x: x - 128 if x > 128 else 0).convert("RGB")
    lo = noise.point(lambda x: 128 - x if x < 128 else 0).convert("RGB")
    return ImageChops.subtract(ImageChops.add(img, hi), lo)


# --- Noise reduction ---------------------------------------------------------

def _median_scaled(chan, size_px, scale):
    "MedianFilter at `size_px` full-res px, scaled to display px (odd int >= 3)."
    s = int(round(size_px * scale))
    if s % 2 == 0:
        s += 1
    s = max(3, s)
    return chan.filter(ImageFilter.MedianFilter(s))


def apply_denoise(img, amount, scale):
    """Reduce high-ISO noise. `amount` 0..1 = strength. Chroma noise (the random
    colour speckle) is removed aggressively with a median filter on Cb/Cr; luma
    is smoothed only lightly (capped by DENOISE_LUMA_MAX) so real detail / edges
    survive — luminance grain is far less objectionable than colour blotches.
    The median window is in full-res px, scaled to the preview's display px so
    the preview tracks the saved full-res file. Pure Pillow (YCbCr median)."""
    a = max(0.0, min(1.0, amount))
    if a <= 0.0:
        return img
    y, cb, cr = img.convert("YCbCr").split()
    # Chroma: lean on the median hard (chroma carries little detail), blend by `a`.
    cb = Image.blend(cb, _median_scaled(cb, DENOISE_CHROMA_SIZE, scale), a)
    cr = Image.blend(cr, _median_scaled(cr, DENOISE_CHROMA_SIZE, scale), a)
    # Luma: a gentle median, blended in only up to DENOISE_LUMA_MAX so texture
    # and edges stay crisp.
    y = Image.blend(y, _median_scaled(y, DENOISE_LUMA_SIZE, scale),
                    a * DENOISE_LUMA_MAX)
    return Image.merge("YCbCr", (y, cb, cr)).convert("RGB")


# --- Split-tone (colour grading) ---------------------------------------------

def apply_split_tone(img, hi_amt, sh_amt):
    """Warm/cool tint the highlights by `hi_amt` and shadows by `sh_amt`, each
    signed -1..+1 (+ warm / - cool). The tint is the temperature axis (R up & B
    down for warm) pushed through a luminance mask — squared so it concentrates
    at each tonal end and fades through the midtones — so the highlight tone
    only colours bright pixels and the shadow tone only dark ones. Pure Pillow;
    reuses `_shift_weighted` (the HSL mixer's weighted additive offset)."""
    if hi_amt == 0.0 and sh_amt == 0.0:
        return img
    img = img.convert("RGB")
    lum = img.convert("L")
    r, g, b = img.split()
    if hi_amt != 0.0:
        w = lum.point(lambda x: int(round((x / 255.0) ** 2 * 255)))   # bright end
        push = hi_amt * SPLIT_MAX
        r = _shift_weighted(r, w, +push)
        b = _shift_weighted(b, w, -push)
    if sh_amt != 0.0:
        w = lum.point(lambda x: int(round((1.0 - x / 255.0) ** 2 * 255)))  # dark end
        push = sh_amt * SPLIT_MAX
        r = _shift_weighted(r, w, +push)
        b = _shift_weighted(b, w, -push)
    return Image.merge("RGB", (r, g, b))


# --- Dehaze ------------------------------------------------------------------

def apply_dehaze(img, amount):
    """Clear (or add) atmospheric haze. `amount` signed -1..+1: + removes haze
    (deepen the black point, lift contrast, re-saturate), - adds it (lift the
    blacks, soften contrast, desaturate). A Pillow-only approximation of the
    dark-channel dehaze — global point + enhance ops, so it is scale-free."""
    a = max(-1.0, min(1.0, amount))
    if a == 0.0:
        return img
    img = img.convert("RGB")
    bp = abs(a) * DEHAZE_BLACK
    if a > 0:
        # Clear: clip the bottom `bp` levels to black, then rescale up — this
        # pulls down the milky veil that haze lays over the shadows.
        sc = 255.0 / (255.0 - bp)
        lut = [max(0, min(255, int(round((i - bp) * sc)))) for i in range(256)]
    else:
        # Haze: compress the whole range into [bp, 255] — lifts the blacks and
        # flattens contrast, the classic washed-out look.
        lut = [int(round(bp + i * (255.0 - bp) / 255.0)) for i in range(256)]
    img = img.point(lut * 3)
    img = ImageEnhance.Contrast(img).enhance(1.0 + a * DEHAZE_CONTRAST)
    img = ImageEnhance.Color(img).enhance(1.0 + a * DEHAZE_COLOR)
    return img


# --- Selective focus blur (depth of field) -----------------------------------

def apply_focus_blur(img, focus, scale, src_box, cache=None):
    """Keep a SHAPE sharp and Gaussian-blur everything outside it — the classic
    portrait / tilt-shift depth effect (Fotor's "blur" tool). Two shapes:

      • "circle" — a round in-focus area  {cx, cy, r}
      • "line"   — a straight in-focus band {cx, cy, angle, width}  (tilt-shift)

    All coordinates are FULL-RES SOURCE pixels (like the crop box), so the shape
    stays anchored to the photo through zoom and pan. They are mapped into this
    region's display pixels via `src_box` + `scale`, exactly like the vignette —
    so the small preview and the full-res save composite identically. `blur`
    (0..1) sets the blur radius; `feather` (0..1) softens the sharp→blurred
    transition. The mask depends only on the geometry, so it is cached across
    blur-slider drags via the optional `cache`."""
    blur_amt = float(focus.get("blur", 0.0))
    if blur_amt <= 0.0:
        return img
    radius = blur_amt * FOCUS_MAX_BLUR * scale          # display px
    if radius < 0.1:
        return img
    w, h = img.size
    sx0, sy0, _sx1, _sy1 = src_box
    cx = (focus["cx"] - sx0) * scale
    cy = (focus["cy"] - sy0) * scale
    feather = focus.get("feather", 0.4)
    shape = focus.get("shape", "circle")

    if shape == "line":
        hw = max(1.0, focus.get("width", 0.0) * 0.5 * scale)   # half-band, display px
        angle = focus.get("angle", 0.0)
        key = (w, h, round(cx, 1), round(cy, 1), round(hw, 1),
               round(angle, 4), round(feather, 3), "line")
    else:
        rx = max(1.0, focus["r"] * scale)
        key = (w, h, round(cx, 1), round(cy, 1), round(rx, 1),
               round(feather, 3), "circle")

    mask = cache.get(key) if cache is not None else None
    if mask is None:
        # Low-frequency mask: build it small, then scale up (cheap on a big save).
        f = min(1.0, FOCUS_MASK_MAX / max(w, h))
        mw, mh = max(1, round(w * f)), max(1, round(h * f))
        mask = Image.new("L", (mw, mh), 0)
        draw = ImageDraw.Draw(mask)
        if shape == "line":
            # The sharp band: a long quad centred on the line, ±half-width across
            # it. Drawn far past the image both ways along the line so it spans
            # the frame at any angle. 255 inside the band = stays sharp.
            ux, uy = math.cos(angle), math.sin(angle)       # along the line
            nx, ny = -uy, ux                                # across (perpendicular)
            L = (mw + mh) * 2 + 10
            ccx, ccy, hwf = cx * f, cy * f, hw * f
            draw.polygon([
                (ccx + ux * L + nx * hwf, ccy + uy * L + ny * hwf),
                (ccx - ux * L + nx * hwf, ccy - uy * L + ny * hwf),
                (ccx - ux * L - nx * hwf, ccy - uy * L - ny * hwf),
                (ccx + ux * L - nx * hwf, ccy + uy * L - ny * hwf),
            ], fill=255)
            soft = max(0.5, feather * hwf)
        else:
            bbox = [(cx - rx) * f, (cy - rx) * f, (cx + rx) * f, (cy + rx) * f]
            draw.ellipse(bbox, fill=255)                     # 255 inside = sharp
            soft = max(0.5, feather * rx * f)
        mask = mask.filter(ImageFilter.GaussianBlur(soft))
        if (mw, mh) != (w, h):
            mask = mask.resize((w, h), Image.BILINEAR)
        if cache is not None:
            cache.clear()            # keep only the latest geometry (single slot)
            cache[key] = mask
    blurred = img.filter(ImageFilter.GaussianBlur(radius))
    # Inside the shape (mask=255) keep the sharp img; outside, the blurred copy.
    return Image.composite(img, blurred, mask)


# --- Text / watermark overlay ------------------------------------------------
# A string laid over the photo, used for captions or a "© name" watermark. The
# centre and font height are kept in FULL-RES SOURCE px (like the focus shape),
# so the text stays glued to the photo through zoom/pan and the small preview
# composites identically to the full-res save: the only difference is `scale`,
# which multiplies the position AND the font size together.

# Friendly font name -> candidate Windows font files (first that loads wins).
# The default "Sans" (Arial) and "Georgian" (Sylfaen) both carry Georgian +
# Latin glyphs, so a Georgian watermark renders without picking a special font.
TEXT_FONT_FILES = {
    "Sans":       ["arial.ttf"],
    "Sans Bold":  ["arialbd.ttf"],
    "Serif":      ["times.ttf"],
    "Mono":       ["consola.ttf", "cour.ttf"],
    "Script":     ["segoesc.ttf", "BRADHITC.TTF", "comic.ttf"],
    "Georgian":   ["sylfaen.ttf"],
}
TEXT_FONTS = list(TEXT_FONT_FILES.keys())   # the order shown in the panel

_font_cache = {}   # (family, px) -> ImageFont; bounded so a size drag can't grow it


def _load_font(family, px):
    "An ImageFont for `family` at `px` height; falls back to Arial / the default."
    px = max(1, int(round(px)))
    key = (family, px)
    font = _font_cache.get(key)
    if font is None:
        for cand in TEXT_FONT_FILES.get(family, []) + ["arial.ttf"]:
            try:
                font = ImageFont.truetype(cand, px)
                break
            except OSError:
                continue
        if font is None:
            font = ImageFont.load_default()
        if len(_font_cache) > 64:     # a size drag spawns one entry per px — cap it
            _font_cache.clear()
        _font_cache[key] = font
    return font


def _hex_to_rgb(value, default=(255, 255, 255)):
    "Parse '#rrggbb' (or '#rgb') to an (r, g, b) tuple; default on garbage."
    try:
        s = value.lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except (ValueError, AttributeError, TypeError, IndexError):
        return default


def text_extent(overlay):
    "Width/height of the overlay text in SOURCE px (0,0 when empty). For the UI"
    " hit-box and corner snapping — measured at the un-scaled source font size."
    text = (overlay or {}).get("text") or ""
    if not text.strip():
        return (0.0, 0.0)
    font = _load_font(overlay.get("font", "Sans"),
                      max(1.0, overlay.get("size", 48.0)))
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = d.multiline_textbbox((0, 0), text, font=font,
                                align=overlay.get("align", "center"))
    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def apply_text_overlay(img, overlay, scale, src_box):
    "Draw the overlay's text centred on its source-px point, scaled to display px."
    text = (overlay.get("text") or "")
    if not text.strip():
        return img
    opacity = max(0.0, min(1.0, float(overlay.get("opacity", 1.0))))
    if opacity <= 0.0:
        return img
    px = max(1.0, overlay.get("size", 48.0) * scale)
    font = _load_font(overlay.get("font", "Sans"), px)
    sx0, sy0, _sx1, _sy1 = src_box
    cx = (overlay["cx"] - sx0) * scale
    cy = (overlay["cy"] - sy0) * scale
    align = overlay.get("align", "center")
    rgb = _hex_to_rgb(overlay.get("color", "#ffffff"))
    a = int(round(opacity * 255))

    # Paint onto a transparent layer the size of `img`, then alpha-composite —
    # so partial opacity blends with the photo instead of overwriting it.
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # Centre the text's INK box on (cx, cy) by drawing at the matching top-left.
    # (Manual centering, not anchor="mm" — multiline anchors vary across Pillow.)
    bbox = d.multiline_textbbox((0, 0), text, font=font, align=align)
    tlx = cx - (bbox[2] - bbox[0]) / 2 - bbox[0]
    tly = cy - (bbox[3] - bbox[1]) / 2 - bbox[1]
    if overlay.get("shadow"):
        # A soft dark drop-shadow lifts light text off a bright photo. Offset
        # scales with the font so it looks the same on preview and full-res.
        off = max(1, int(round(px * 0.07)))
        d.multiline_text((tlx + off, tly + off), text, font=font,
                         fill=(0, 0, 0, int(a * 0.6)), align=align)
    d.multiline_text((tlx, tly), text, font=font,
                     fill=(rgb[0], rgb[1], rgb[2], a), align=align)

    base = img.convert("RGBA")
    out = Image.alpha_composite(base, layer)
    return out.convert("RGB") if img.mode == "RGB" else out


# --- Transparency backdrop ---------------------------------------------------
# A PNG/WebP with an alpha channel is shown over a two-tone grey checkerboard so
# the see-through areas read as "transparent" rather than as a solid fill. The
# greys are tuned to sit calmly on Manoni's dark canvas (not Photoshop's bright
# white/grey, which would glare here). The square is a fixed SCREEN size, so the
# pattern stays the same on-screen at every zoom — exactly like a real editor.

CHECKER_LIGHT  = (94, 94, 94)
CHECKER_DARK   = (66, 66, 66)
CHECKER_SQUARE = 9   # checker square edge, in screen px


def has_alpha(img):
    "True if the image carries (channel or palette) transparency worth showing."
    if img is None:
        return False
    if img.mode in ("RGBA", "LA", "PA"):
        return True
    return img.mode == "P" and "transparency" in img.info


def checkerboard(w, h, square=CHECKER_SQUARE,
                 light=CHECKER_LIGHT, dark=CHECKER_DARK):
    """An opaque RGB checkerboard of size (w, h), anchored at its top-left.

    Built tile → row-strip → image so the cost is O(w/2sq + h/2sq) pastes rather
    than one per square — cheap enough to rebuild only when the viewport grows.
    """
    w = max(1, int(w))
    h = max(1, int(h))
    t = square * 2                       # one tile holds a 2×2 block of squares
    tile = Image.new("RGB", (t, t), light)
    cell = Image.new("RGB", (square, square), dark)
    tile.paste(cell, (square, 0))
    tile.paste(cell, (0, square))
    strip = Image.new("RGB", (w, t))     # one full-width band of tiles
    for x in range(0, w, t):
        strip.paste(tile, (x, 0))
    out = Image.new("RGB", (w, h))       # stack the band down the image
    for y in range(0, h, t):
        out.paste(strip, (0, y))
    return out


# --- Live histogram ----------------------------------------------------------
# A small RGB histogram drawn live in the edit panel. Each channel is a filled
# silhouette; the three are merged so overlaps brighten (R+G = yellow, all three
# = white) — the classic Photoshop additive look — then laid over a dark box.
# Built at 256-bin width then scaled, so it is cheap to redraw on every slider
# move. Reads whatever image it is handed (the edited preview viewport), so it
# tracks the live edit.

HIST_BG   = (22, 22, 22)   # the dark box the curves glow over
HIST_FILL = 200            # per-channel silhouette height (additive → white overlaps)


def histogram_image(src, w, h, bg=HIST_BG):
    "An additive RGB histogram of `src` as a (w, h) RGB image (None if too small)."
    if src is None or w < 2 or h < 2:
        return None
    hist = src.convert("RGB").histogram()          # 768: R[0..255], G[..], B[..]
    channels = (hist[0:256], hist[256:512], hist[512:768])
    # Normalise to the tallest bar, ignoring the pure-black/white spikes at 0 and
    # 255 that would otherwise flatten the rest — Photoshop clips them off too.
    peak = max((max(c[1:255]) for c in channels), default=0)
    if peak <= 0:
        peak = max((max(c) for c in channels), default=1) or 1
    bars = []
    for c in channels:
        col = Image.new("L", (256, h), 0)
        draw = ImageDraw.Draw(col)
        for i in range(256):
            bar = int(round(min(1.0, c[i] / peak) * (h - 1)))
            if bar > 0:
                draw.line([(i, h - 1), (i, h - 1 - bar)], fill=HIST_FILL)
        bars.append(col)
    merged = Image.merge("RGB", bars)
    if w != 256:
        merged = merged.resize((w, h), Image.BILINEAR)
    return ImageChops.add(merged, Image.new("RGB", (w, h), bg))


# --- HSL colour mixer (per-hue saturation) + gold shine ----------------------
# Strengthen or weaken ONE colour without touching the rest — Lightroom's HSL
# "Saturation" tab. Pure Pillow: a hue→gain table (256 entries) is built in
# Python (cheap), then applied to the Saturation channel with C-speed ImageChops
# so a full-res save stays fast. Hue is PIL's 0–255 scale (= degrees × 255/360).

# The eight named bands: (Edits attr, centre hue 0–255). The half-width below is
# wider than the spacing, so a colour sitting between two named hues is shared
# smoothly between them rather than snapping to one.
HSL_BANDS = (
    ("sat_red",     0),     #   0°
    ("sat_orange",  21),    #  30°
    ("sat_yellow",  43),    #  60°
    ("sat_green",   85),    # 120°
    ("sat_aqua",    128),   # 180°
    ("sat_blue",    170),   # 240°
    ("sat_purple",  191),   # 270°
    ("sat_magenta", 213),   # 300°
)
HSL_HALF = 32       # band half-width in 0–255 hue units (≈45°): neighbours overlap

# Gold: a warm amber (≈45°) handled on its own with three controls, a mini-HSL
# just for golden tones. Narrower than a normal band so only true golds move.
GOLD_CENTER     = 32    # ≈45° in 0–255
GOLD_HALF       = 22
GOLD_V_GAIN     = 0.60  # how much a full "shine" slider lifts the lightness
GOLD_HUE_SHIFT  = 18    # max hue shift (0–255 units, ≈25°) at a full hue slider
# Gold acts ONLY on genuinely golden pixels: a warm hue AND enough saturation.
# White / cream stonework shares gold's hue but is nearly grey (low saturation),
# so this gate fades the effect to zero below GOLD_SAT_LO and to full at
# GOLD_SAT_HI — keeping the shine off pale stone. (0–255 saturation units; raise
# the pair to be even stricter about what counts as "gold".)
GOLD_SAT_LO     = 60
GOLD_SAT_HI     = 120

# Skin: the same idea tuned for skin tones, which cluster tightly in hue (≈25°)
# across every complexion while their saturation ranges wide (pale → deep). The
# sat gate is low so even pale skin is included, but still drops near-grey walls.
SKIN_CENTER     = 18    # ≈25° in 0–255 (holds from light to deep skin)
SKIN_HALF       = 16
SKIN_V_GAIN     = 0.45  # gentler lightness lift than gold (skin blows out easily)
SKIN_HUE_SHIFT  = 14    # max hue shift (≈20°): nudge skin warmer / cooler
SKIN_SAT_LO     = 25    # include pale skin...
SKIN_SAT_HI     = 55    # ...at full strength, while near-grey pixels stay out

# (centre, half, sat_lo, sat_hi, v_gain, hue_shift, hue_attr, sat_attr, light_attr)
# One row per hue+saturation-gated mini-HSL. apply_color_mixer loops over these.
TARGETS = (
    (GOLD_CENTER, GOLD_HALF, GOLD_SAT_LO, GOLD_SAT_HI, GOLD_V_GAIN,
     GOLD_HUE_SHIFT, "gold_hue", "gold_sat", "gold_light"),
    (SKIN_CENTER, SKIN_HALF, SKIN_SAT_LO, SKIN_SAT_HI, SKIN_V_GAIN,
     SKIN_HUE_SHIFT, "skin_hue", "skin_sat", "skin_light"),
)


def _hue_weight(hue, center, half):
    "Raised-cosine weight 1→0 as `hue` moves `half` away from `center` (circular)."
    d = abs(hue - center)
    d = min(d, 256 - d)                     # hue is a circle
    if d >= half:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * d / half))


def _split_gain_maps(h, gains):
    "From a per-hue signed gain list, build the two 0–255 hue-indexed multiply"
    " maps (positive part, negative part) for the H band `h`."
    up   = [max(0, min(255, int(round( g * 255)))) for g in gains]
    down = [max(0, min(255, int(round(-g * 255)))) for g in gains]
    return h.point(up), h.point(down)


def _scale_channel(chan, up_map, down_map):
    "new = chan + chan*up - chan*down, all clamped 0..255 (C-speed ImageChops)."
    raised  = ImageChops.add(chan, ImageChops.multiply(chan, up_map))
    return ImageChops.subtract(raised, ImageChops.multiply(chan, down_map))


def _smoothstep_lut(lo, hi):
    "256-entry 0→255 ramp: 0 at/below `lo`, 255 at/above `hi`, smooth between."
    out = []
    for x in range(256):
        if x <= lo:
            f = 0.0
        elif x >= hi:
            f = 1.0
        else:
            f = (x - lo) / (hi - lo)
            f = f * f * (3.0 - 2.0 * f)     # smoothstep (eases both ends)
        out.append(int(round(f * 255)))
    return out


def _add_weighted(chan, weight, amount):
    "chan ± chan·|amount|·weight (multiplicative scale), clamped. `weight` is an"
    " L image (0–255 = 0..1); `amount` a scalar in [-1, 1] whose sign lightens"
    " (≥0) or darkens (<0) the channel only where `weight` is non-zero."
    a = max(-1.0, min(1.0, amount))
    scaled = weight.point(lambda x, k=abs(a): int(round(x * k)))   # |a|·weight
    delta = ImageChops.multiply(chan, scaled)                      # chan·|a|·weight
    return ImageChops.add(chan, delta) if a >= 0 else ImageChops.subtract(chan, delta)


def _shift_weighted(chan, weight, amount):
    "chan ± |amount|·weight (additive offset, for the hue band), clamped. `amount`"
    " is in 0–255 channel units; its sign chooses the shift direction."
    mag = weight.point(lambda x, k=abs(amount): int(round(x / 255.0 * k)))
    return ImageChops.add(chan, mag) if amount >= 0 else ImageChops.subtract(chan, mag)


def apply_color_mixer(img, e):
    """Apply the eight per-hue saturation bands plus the gold and skin mini-HSLs
    (each: hue / saturation / lightness) in one HSV pass. The eight bands key off
    HUE alone; gold and skin additionally key off SATURATION, so they touch only
    that material — not the pale things that merely share its hue. Returns `img`
    untouched (and pays nothing) when every control is neutral."""
    sat_gain = [0.0] * 256          # combined per-hue saturation gain (8 bands)
    bands_on = False
    for attr, center in HSL_BANDS:
        amt = getattr(e, attr, 1.0) - 1.0
        if amt == 0.0:
            continue
        bands_on = True
        for hue in range(256):
            sat_gain[hue] += amt * _hue_weight(hue, center, HSL_HALF)

    # Collect the active gated targets (gold, skin) as their three amounts.
    active = []
    for center, half, slo, shi, vgain, hshift, ha, sa, la in TARGETS:
        hue_amt, sat_amt, light_amt = (getattr(e, ha) - 1.0,
                                       getattr(e, sa) - 1.0,
                                       getattr(e, la) - 1.0)
        if hue_amt or sat_amt or light_amt:
            active.append((center, half, slo, shi, vgain, hshift,
                           hue_amt, sat_amt, light_amt))

    if not bands_on and not active:
        return img

    h, s, v = img.convert("HSV").split()
    h0, s0 = h, s                   # originals: every gate / weight reads these

    if bands_on:
        sat_gain = [max(-1.0, min(1.0, g)) for g in sat_gain]
        s = _scale_channel(s, *_split_gain_maps(h, sat_gain))

    # Each target's per-pixel membership = its HUE weight × a SATURATION gate.
    # The product is 0 for pale pixels, so grey/white material is left alone even
    # when it shares the hue. Weights read the ORIGINAL bands, so targets compose
    # independently of each other's edits. Saturation gates are cached by range.
    gate_cache = {}
    for center, half, slo, shi, vgain, hshift, hue_amt, sat_amt, light_amt in active:
        gw_lut = [int(round(_hue_weight(hue, center, half) * 255))
                  for hue in range(256)]
        gate = gate_cache.get((slo, shi))
        if gate is None:
            gate = s0.point(_smoothstep_lut(slo, shi))
            gate_cache[(slo, shi)] = gate
        weight = ImageChops.multiply(h0.point(gw_lut), gate)
        if sat_amt != 0.0:
            s = _add_weighted(s, weight, sat_amt)
        if light_amt != 0.0:
            v = _add_weighted(v, weight, light_amt * vgain)
        if hue_amt != 0.0:
            h = _shift_weighted(h, weight, hue_amt * hshift)

    return Image.merge("HSV", (h, s, v)).convert("RGB")


# --- The full edit pass ------------------------------------------------------

def apply_edits(img, e, auto_luts=None, scale=1.0, src_box=None, full_size=None,
                vig_cache=None, focus_cache=None):
    "Apply the live edit factors `e`. Cheap on the small preview, exact on full-res."
    # Geometry for position-dependent effects (vignette). Default: `img` IS the
    # whole photo (the full-res save path). The preview passes the visible box.
    if full_size is None:
        full_size = img.size
    if src_box is None:
        src_box = (0, 0, img.size[0], img.size[1])
    if auto_luts is not None:
        # Auto Levels / Auto Contrast first, as a tonal baseline the sliders
        # then fine-tune. The LUTs come from the full base image, so the
        # preview viewport and the saved full-res file map identically.
        r, g, b = img.convert("RGB").split()
        img = Image.merge("RGB", (r.point(auto_luts[0]),
                                  g.point(auto_luts[1]),
                                  b.point(auto_luts[2])))
    if e.brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(e.brightness)
    if e.contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(e.contrast)
    lut = tone_lut(e)
    if lut is not None:
        img = img.point(lut * len(img.getbands()))   # same table for each band
    if e.denoise > 0.0:
        # Clean noise BEFORE the detail pass, so clarity/texture/sharpen below
        # crisp the cleaned pixels rather than amplifying the speckle.
        img = apply_denoise(img, e.denoise, scale)
    if e.dehaze != 1.0:
        # Atmospheric-haze clear/add: a global tone+saturation move, before the
        # local-contrast (clarity/texture) and colour passes refine it.
        img = apply_dehaze(img, e.dehaze - 1.0)
    if e.clarity != 1.0:
        # Midtone local contrast. Like blur, the radius is in full-res pixels
        # and scaled to the preview's display pixels so on-screen matches save.
        amt = e.clarity - 1.0
        radius = CLARITY_RADIUS * scale
        if amt > 0:
            img = img.filter(ImageFilter.UnsharpMask(
                radius=radius, percent=int(amt * CLARITY_PCT), threshold=0))
        else:
            # Negative = soft glow: blend toward a large-radius blur.
            soft = img.filter(ImageFilter.GaussianBlur(radius))
            img = Image.blend(img, soft, min(0.7, -amt * 0.6))
    if e.texture != 1.0:
        # Medium-frequency detail. Small radius (scaled to display px like
        # clarity/blur, so preview matches save). Positive sharpens surface
        # detail but skips diffs below the threshold (noise / flat tone);
        # negative blends toward a light blur to soften the surface.
        amt = e.texture - 1.0
        radius = TEXTURE_RADIUS * scale
        if amt > 0:
            img = img.filter(ImageFilter.UnsharpMask(
                radius=radius, percent=int(amt * TEXTURE_PCT),
                threshold=TEXTURE_THRESH))
        else:
            soft = img.filter(ImageFilter.GaussianBlur(radius))
            img = Image.blend(img, soft, -amt * TEXTURE_SMOOTH)
    if e.vibrance != 1.0:
        # Saturation that protects already-saturated pixels: boost is weighted
        # by (1 - s/255), so muted colours move most, vivid ones barely.
        amt = e.vibrance - 1.0
        push = amt * VIBRANCE_MAX
        h, s, v = img.convert("HSV").split()
        s = s.point(lambda x: max(0, min(255, int(x + push * (1.0 - x / 255.0)))))
        img = Image.merge("HSV", (h, s, v)).convert("RGB")
    if e.color != 1.0:
        img = ImageEnhance.Color(img).enhance(e.color)
    # Per-hue saturation (HSL mixer) + gold shine. No-op when all are neutral.
    img = apply_color_mixer(img, e)
    if e.temperature != 1.0:
        # warm = boost red / cut blue; cool = the opposite
        k = (e.temperature - 1.0) * 0.3
        rs, bs = 1.0 + k, 1.0 - k
        r, g, b = img.split()
        r = r.point(lambda i: max(0, min(255, int(i * rs))))
        b = b.point(lambda i: max(0, min(255, int(i * bs))))
        img = Image.merge("RGB", (r, g, b))
    if e.tint != 1.0:
        # magenta (tint>1) cuts green; green (tint<1) boosts green
        gs = 1.0 - (e.tint - 1.0) * 0.3
        r, g, b = img.split()
        g = g.point(lambda i: max(0, min(255, int(i * gs))))
        img = Image.merge("RGB", (r, g, b))
    if e.bw > 0.0:
        # Black-and-white effect: blend toward a luminance grayscale. At full
        # strength any colour/temperature edit above is washed out → true B&W.
        gray = ImageEnhance.Color(img).enhance(0.0)   # desaturated, still RGB
        img = Image.blend(img, gray, e.bw)
    if e.sepia > 0.0:
        # Sepia: desaturate to luminance, then tone the grays warm via a
        # per-channel ramp (shadows → brown, highlights → cream). Blend by
        # strength, so the slider goes colour → fully toned.
        gray = img.convert("L")
        (rs, ro), (gs, go), (bs, bo) = SEPIA_RAMP
        toned = Image.merge("RGB", (
            gray.point(lambda x: max(0, min(255, int(x * rs + ro)))),
            gray.point(lambda x: max(0, min(255, int(x * gs + go)))),
            gray.point(lambda x: max(0, min(255, int(x * bs + bo)))),
        ))
        img = Image.blend(img, toned, e.sepia)
    if e.split_hi != 1.0 or e.split_sh != 1.0:
        # Colour grade: warm/cool tint the highlights and shadows separately
        # (sits with the toning effects, after any B&W / sepia conversion).
        img = apply_split_tone(img, e.split_hi - 1.0, e.split_sh - 1.0)
    if e.sharpen > 1.0:
        # Right of neutral = sharpen (1.0→2.0 maps to Sharpness 1.0→3.0).
        img = ImageEnhance.Sharpness(img).enhance(1.0 + (e.sharpen - 1.0) * 2.0)
    elif e.sharpen < 1.0:
        # Left of neutral = Gaussian blur. The radius is in full-res pixels;
        # scale it to the preview's display pixels so on-screen blur matches
        # what the saved full-res file will get.
        radius = (1.0 - e.sharpen) * MAX_BLUR * scale
        if radius > 0.1:
            img = img.filter(ImageFilter.GaussianBlur(radius))
    if e.focus:
        img = apply_focus_blur(img, e.focus, scale, src_box, focus_cache)
    if e.vignette != 1.0:
        img = apply_vignette(img, e.vignette - 1.0, scale, src_box, full_size,
                             vig_cache)
    if e.grain > 0.0:
        # Grain goes LAST of the looks — on top of the whole image (after focus
        # blur and vignette), the way real film grain sits over the photo.
        img = apply_grain(img, e.grain, scale)
    if e.text:
        # The text / watermark caps everything: an annotation laid crisply over
        # the finished photo (even on top of the grain), not part of the look.
        img = apply_text_overlay(img, e.text, scale, src_box)
    return img


# --- Spot healing ------------------------------------------------------------

# A "spot heal" is a LOCAL pixel edit, unlike everything above (global filters).
# It clones the smoothest nearby same-size region over the blemish, colour-
# matched to the clean ring around it and feathered so the seam disappears.
# Pure Pillow — no OpenCV/inpainting — so it stays tiny on a weak laptop. The
# target box is padded a little beyond the brush so there is a clean border to
# (a) sample the colour from and (b) feather into.

HEAL_FEATHER = 0.5   # mask-edge blur as a fraction of the brush radius
HEAL_DIRS    = 8     # nearby source candidates probed around the spot


def _shift_channels(img, deltas):
    "Add a per-channel constant (signed), clamped to 0..255 — a cheap colour match."
    bands = []
    for band, d in zip(img.split(), deltas):
        di = int(round(d))
        if di == 0:
            bands.append(band)
        else:
            bands.append(band.point(lambda x, di=di: max(0, min(255, x + di))))
    return Image.merge("RGB", bands)


def heal_region(img, cx, cy, radius, feather=HEAL_FEATHER, opacity=1.0):
    """Spot-heal a round blemish centred at (cx, cy) in full-res pixels.

    `opacity` (0..1) is the blend strength: 1.0 fully replaces the spot with the
    clean clone, lower values keep some of the original showing through — a soft,
    partial heal (e.g. fading a wrinkle rather than erasing it).

    Returns (patched_region, box): the caller pastes `patched_region` at `box`
    into the working image, so only the touched area is rewritten — cheap on a
    big photo and trivial to snapshot for undo. Returns (None, None) when the
    brush is too small or off the image.
    """
    img = img.convert("RGB")
    iw, ih = img.size
    r = int(round(radius))
    if r < 1:
        return None, None
    # Pad the box beyond the brush: that margin is the clean border we colour-
    # match to and feather into. The disc itself stays radius `r`.
    margin = max(4, int(round(r * 0.6)))
    half = r + margin
    cxi, cyi = int(round(cx)), int(round(cy))
    x0 = max(0, cxi - half); y0 = max(0, cyi - half)
    x1 = min(iw, cxi + half); y1 = min(ih, cyi + half)
    bw, bh = x1 - x0, y1 - y0
    if bw < 3 or bh < 3:
        return None, None
    box = (x0, y0, x1, y1)
    target = img.crop(box)
    # Disc centre in the box's own coordinates (the spot is off-centre near edges).
    lx, ly = cx - x0, cy - y0

    # Hard disc (for stats) + a feathered copy (for the actual blend).
    hard = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(hard).ellipse([lx - r, ly - r, lx + r, ly + r], fill=255)
    mask = hard.filter(ImageFilter.GaussianBlur(max(0.5, feather * r)))
    if opacity < 1.0:
        a = max(0.0, min(1.0, opacity))         # scale the alpha → partial heal
        mask = mask.point(lambda v: int(round(v * a)))
    ring = hard.point(lambda x: 255 - x)        # the clean border outside the disc

    # Pick the source: a same-size region offset around the spot, kept only if it
    # fits fully inside the image; among those, the smoothest (lowest stddev) one,
    # so we clone flat skin/sky/wall rather than dragging an edge over the spot.
    d = max(bw, bh)
    best = None
    for k in range(HEAL_DIRS):
        ang = 2.0 * math.pi * k / HEAL_DIRS
        ox = int(round(cx + d * math.cos(ang) - lx))
        oy = int(round(cy + d * math.sin(ang) - ly))
        if ox < 0 or oy < 0 or ox + bw > iw or oy + bh > ih:
            continue
        cand = img.crop((ox, oy, ox + bw, oy + bh))
        score = sum(ImageStat.Stat(cand).stddev)
        if best is None or score < best[0]:
            best = (score, cand)
    if best is None:
        # Spot in a corner with a big brush: no neighbour fits. Blur the spot
        # itself — still hides a small blemish, just without borrowed texture.
        src = target.filter(ImageFilter.GaussianBlur(r))
    else:
        src = best[1]

    # Colour-match: shift the source so its mean under the disc equals the clean
    # ring's mean — the cloned centre then blends into the surrounding tone.
    tref = ImageStat.Stat(target, ring).mean
    sref = ImageStat.Stat(src, hard).mean
    src = _shift_channels(src, [t - s for t, s in zip(tref, sref)])

    return Image.composite(src, target, mask), box


def clone_region(img, dst_cx, dst_cy, src_cx, src_cy, radius,
                 feather=HEAL_FEATHER, opacity=1.0, flip=False):
    """Clone-stamp: copy a feathered disc from (src_cx, src_cy) straight onto
    (dst_cx, dst_cy) in full-res pixels.

    Unlike heal_region this is an EXACT copy — no smoothest-neighbour search and
    no colour match — exactly Photoshop's Clone Stamp: the user picks the source,
    so the tool just duplicates it. `feather` / `opacity` behave as in heal. With
    `flip` the source texture is mirrored left↔right about the source point (handy
    for symmetric retouching), while the source point itself stays anchored.

    Returns (patched_region, box) for the destination, or (None, None) if the
    brush is too small, off the image, or the source disc falls outside it.
    """
    img = img.convert("RGB")
    iw, ih = img.size
    r = int(round(radius))
    if r < 1:
        return None, None
    margin = max(4, int(round(r * 0.6)))
    half = r + margin
    dxi, dyi = int(round(dst_cx)), int(round(dst_cy))
    x0 = max(0, dxi - half); y0 = max(0, dyi - half)
    x1 = min(iw, dxi + half); y1 = min(ih, dyi + half)
    bw, bh = x1 - x0, y1 - y0
    if bw < 3 or bh < 3:
        return None, None
    box = (x0, y0, x1, y1)
    target = img.crop(box)
    lx, ly = dst_cx - x0, dst_cy - y0
    # The source crop lines the source point up with the dest disc centre (lx, ly).
    # For flip, take the window whose centre column maps onto lx after a left↔right
    # flip, so the source point stays put and only the texture mirrors — no wrap.
    sy0 = y0 + int(round(src_cy - dst_cy))
    if flip:
        sx0 = int(round(src_cx - (bw - 1 - lx)))
    else:
        sx0 = x0 + int(round(src_cx - dst_cx))
    if sx0 < 0 or sy0 < 0 or sx0 + bw > iw or sy0 + bh > ih:
        return None, None
    src = img.crop((sx0, sy0, sx0 + bw, sy0 + bh))
    if flip:
        src = src.transpose(Image.FLIP_LEFT_RIGHT)

    hard = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(hard).ellipse([lx - r, ly - r, lx + r, ly + r], fill=255)
    mask = hard.filter(ImageFilter.GaussianBlur(max(0.5, feather * r)))
    if opacity < 1.0:
        a = max(0.0, min(1.0, opacity))
        mask = mask.point(lambda v: int(round(v * a)))
    return Image.composite(src, target, mask), box


# --- Perspective / keystone correction ---------------------------------------
# Fix converging verticals (a building shot from below) or horizontals. The
# corrected image is a PROJECTIVE warp: the output rectangle samples a trapezoid
# of the source. Because that trapezoid stays INSIDE the source, the output is
# always fully filled — no empty corners to crop or fill. KEYSTONE_MAX caps how
# far an edge is pinched (a fraction of that dimension) at a full ±slider. The
# warp is defined in image-fraction terms, so it is scale-free: applying it to
# the small fitted preview and to the full-res photo gives the identical result.

KEYSTONE_MAX = 0.30   # max edge inset as a fraction of W/H, at a full ±1 slider


def _solve_linear(A, b):
    "Solve the n×n system A·x = b by Gauss-Jordan with partial pivoting (no numpy)."
    n = len(A)
    m = [list(row) + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None                       # singular (degenerate quad)
        m[col], m[piv] = m[piv], m[col]
        pv = m[col][col]
        for c in range(col, n + 1):
            m[col][c] /= pv
        for r in range(n):
            if r != col and m[r][col] != 0.0:
                f = m[r][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] for i in range(n)]


def perspective_coeffs(out_pts, in_pts):
    """The 8 PERSPECTIVE coefficients for Image.transform: for each OUTPUT corner
    in `out_pts` give the INPUT point in `in_pts` it should sample from. Returns
    (a,b,c,d,e,f,g,h) such that output (X,Y) maps to input
    ((aX+bY+c)/(gX+hY+1), (dX+eY+f)/(gX+hY+1)); None if the quad is degenerate."""
    A, bvec = [], []
    for (X, Y), (x, y) in zip(out_pts, in_pts):
        A.append([X, Y, 1, 0, 0, 0, -x * X, -x * Y]); bvec.append(x)
        A.append([0, 0, 0, X, Y, 1, -y * X, -y * Y]); bvec.append(y)
    return _solve_linear(A, bvec)


def apply_perspective(img, v, h):
    """Keystone-correct `img`: `v` vertical, `h` horizontal, each signed -1..+1.
    v>0 widens the top (fixes verticals that converge upward), v<0 widens the
    bottom; h>0 widens the left, h<0 the right. The output is the same size and
    fully filled (the sampled trapezoid lies inside the source). Scale-free, so
    the fitted-preview warp matches the full-res commit. Pure Pillow."""
    if v == 0.0 and h == 0.0:
        return img
    if img.mode in ("P", "1"):
        img = img.convert("RGB")
    w, hh = img.size
    kx = KEYSTONE_MAX * w
    ky = KEYSTONE_MAX * hh
    vt = kx * v if v > 0 else 0.0     # inset each TOP corner in x (v>0)
    vb = -kx * v if v < 0 else 0.0    # inset each BOTTOM corner in x (v<0)
    hl = ky * h if h > 0 else 0.0     # inset each LEFT corner in y (h>0)
    hr = -ky * h if h < 0 else 0.0    # inset each RIGHT corner in y (h<0)
    # Input trapezoid (TL, TR, BR, BL) sampled across the full output rectangle.
    in_pts = [(vt, hl), (w - vt, hr), (w - vb, hh - hr), (vb, hh - hl)]
    out_pts = [(0, 0), (w, 0), (w, hh), (0, hh)]
    coeffs = perspective_coeffs(out_pts, in_pts)
    if coeffs is None:
        return img
    return img.transform((w, hh), Image.PERSPECTIVE, coeffs,
                         resample=Image.BICUBIC)
