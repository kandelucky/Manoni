"""Pure image-processing for Manoni — Pillow in, Pillow out.

No Tk and no Manoni state: every function takes its inputs explicitly (an `Edits`
value object for the slider settings, plus the source image and geometry). That
keeps the math readable, reusable and testable on its own, while the window code
stays about the UI. The Manoni methods are thin wrappers that build an `Edits`
from the live sliders and call in here.
"""

import math

from PIL import (Image, ImageEnhance, ImageFilter, ImageDraw, ImageStat,
                 ImageChops, ImageFont)

from .edits import Edits   # noqa: F401 — the value object, re-exported here
# Histogram levels + tone curve. autocontrast_luts is re-exported (the window's
# auto-tone code calls it); apply_auto_luts / tone_lut are used by the pipeline.
from .levels import autocontrast_luts, apply_auto_luts, tone_lut  # noqa: F401
# HSL colour mixer. HSL_BANDS is re-exported (public); apply_color_mixer /
# color_mixer_active / _mixer_sig drive the pipeline; _shift_weighted is reused
# by the split-tone effect below.
from .colormix import (HSL_BANDS, apply_color_mixer, color_mixer_active,  # noqa: F401
                       _mixer_sig, _shift_weighted)
# Text / watermark overlays. TEXT_FONTS / resolve_font_family / text_extent are
# re-exported (the window uses them); _apply_texts is the pipeline's stage fn.
from .text import (TEXT_FONTS, resolve_font_family, text_extent,  # noqa: F401
                   _apply_texts)


# --- Tuning constants (were class attributes on Manoni) ----------------------

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


# The `Edits` value object now lives in edits.py (imported at the top).


# Histogram levels + the tone curve (stretch_lut / autocontrast_luts / tone_lut /
# apply_auto_luts) now live in levels.py; the ones the pipeline uses are imported
# at the top.


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
        # Feather only OUTWARD: a plain Gaussian on the hard shape spreads the
        # 255->0 edge both ways, so its inward half would soften the area just
        # inside the shape (blur leaking into the sharp region). Keep the hard
        # interior fully sharp by taking the per-pixel max of the hard mask and
        # the blurred one — inside stays 255, only the outside gets the falloff.
        hard = mask
        mask = ImageChops.lighter(hard, hard.filter(ImageFilter.GaussianBlur(soft)))
        if (mw, mh) != (w, h):
            mask = mask.resize((w, h), Image.BILINEAR)
        if cache is not None:
            cache.clear()            # keep only the latest geometry (single slot)
            cache[key] = mask
    blurred = img.filter(ImageFilter.GaussianBlur(radius))
    # Inside the shape (mask=255) keep the sharp img; outside, the blurred copy.
    return Image.composite(img, blurred, mask)


# The text / watermark overlay code now lives in text.py; TEXT_FONTS,
# resolve_font_family, text_extent and _apply_texts are imported at the top.


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


# The HSL colour mixer (bands + gold/skin mini-HSLs and their helpers) now lives
# in colormix.py; the symbols the pipeline uses are imported at the top.


# --- The full edit pass ------------------------------------------------------
# The pass is expressed as an ordered list of STAGES (see `edit_stages`): each a
# (signature, fn) pair, fn mapping image -> image with the exact math the flat
# pass used. `apply_edits` just runs them all (output identical to before).
# `apply_edits_cached` reuses a per-view cache so an edit only recomputes the
# stages downstream of whatever actually changed — which is what stops a heavy
# effect (denoise / clarity / focus) jamming every later slider move.

# The individual passes that used to live inline in apply_edits, pulled out so a
# stage can call one op and the caches can key on exactly its inputs. The math is
# byte-for-byte the old code — only the packaging changed.


def apply_clarity(img, amt, scale):
    "Midtone local contrast: + crisp (UnsharpMask), - soft glow (blur blend)."
    radius = CLARITY_RADIUS * scale
    if amt > 0:
        return img.filter(ImageFilter.UnsharpMask(
            radius=radius, percent=int(amt * CLARITY_PCT), threshold=0))
    soft = img.filter(ImageFilter.GaussianBlur(radius))
    return Image.blend(img, soft, min(0.7, -amt * 0.6))


def apply_texture(img, amt, scale):
    "Medium-frequency detail: + sharpen surface (thresholded), - light smooth."
    radius = TEXTURE_RADIUS * scale
    if amt > 0:
        return img.filter(ImageFilter.UnsharpMask(
            radius=radius, percent=int(amt * TEXTURE_PCT), threshold=TEXTURE_THRESH))
    soft = img.filter(ImageFilter.GaussianBlur(radius))
    return Image.blend(img, soft, -amt * TEXTURE_SMOOTH)


def apply_vibrance(img, amt):
    "Saturation weighted by (1 - s/255): muted colours move most, vivid ones barely."
    push = amt * VIBRANCE_MAX
    h, s, v = img.convert("HSV").split()
    s = s.point(lambda x: max(0, min(255, int(x + push * (1.0 - x / 255.0)))))
    return Image.merge("HSV", (h, s, v)).convert("RGB")


def apply_temperature(img, temperature):
    "Warm (>1) boosts red / cuts blue; cool (<1) the opposite."
    k = (temperature - 1.0) * 0.3
    rs, bs = 1.0 + k, 1.0 - k
    r, g, b = img.split()
    r = r.point(lambda i: max(0, min(255, int(i * rs))))
    b = b.point(lambda i: max(0, min(255, int(i * bs))))
    return Image.merge("RGB", (r, g, b))


def apply_tint(img, tint):
    "Magenta (>1) cuts green; green (<1) boosts green."
    gs = 1.0 - (tint - 1.0) * 0.3
    r, g, b = img.split()
    g = g.point(lambda i: max(0, min(255, int(i * gs))))
    return Image.merge("RGB", (r, g, b))


def apply_bw(img, amt):
    "Blend toward a desaturated (still-RGB) grayscale; full strength = true B&W."
    gray = ImageEnhance.Color(img).enhance(0.0)   # desaturated, still RGB
    return Image.blend(img, gray, amt)


def apply_sepia(img, amt):
    "Desaturate to luminance, tone the grays warm (shadows brown, highlights cream)."
    gray = img.convert("L")
    (rs, ro), (gs, go), (bs, bo) = SEPIA_RAMP
    toned = Image.merge("RGB", (
        gray.point(lambda x: max(0, min(255, int(x * rs + ro)))),
        gray.point(lambda x: max(0, min(255, int(x * gs + go)))),
        gray.point(lambda x: max(0, min(255, int(x * bs + bo)))),
    ))
    return Image.blend(img, toned, amt)


def apply_sharpen(img, sharpen, scale):
    "Right of neutral sharpens; left blurs (radius full-res px, scaled to display)."
    if sharpen > 1.0:
        return ImageEnhance.Sharpness(img).enhance(1.0 + (sharpen - 1.0) * 2.0)
    if sharpen < 1.0:
        radius = (1.0 - sharpen) * MAX_BLUR * scale
        if radius > 0.1:
            return img.filter(ImageFilter.GaussianBlur(radius))
    return img


def edit_stages(e, auto_luts, scale, src_box, full_size, fast,
                vig_cache=None, focus_cache=None):
    """The edit pass as an ordered list of (signature, fn) stages.

    Same ops, same order, same guards as the flat pass — running every stage in
    turn reproduces `apply_edits` exactly. Each `signature` captures precisely the
    inputs that stage's `fn` reads (its slider values, plus geometry for the
    position-dependent ones), so the live cache can tell which stages an edit left
    untouched and reuse their cached output. `fast` simply omits the heavy stages.
    """
    stages = []
    add = stages.append
    if auto_luts is not None:
        add((("auto", id(auto_luts)), lambda img: apply_auto_luts(img, auto_luts)))
    if e.brightness != 1.0:
        add((("brightness", e.brightness),
             lambda img, f=e.brightness: ImageEnhance.Brightness(img).enhance(f)))
    if e.contrast != 1.0:
        add((("contrast", e.contrast),
             lambda img, f=e.contrast: ImageEnhance.Contrast(img).enhance(f)))
    lut = tone_lut(e)
    if lut is not None:
        add((("tone", e.highlights, e.shadows, e.whites, e.blacks),
             lambda img, l=lut: img.point(l * len(img.getbands()))))
    if e.denoise > 0.0 and not fast:
        add((("denoise", e.denoise, scale),
             lambda img, a=e.denoise, s=scale: apply_denoise(img, a, s)))
    if e.dehaze != 1.0 and not fast:
        add((("dehaze", e.dehaze),
             lambda img, a=e.dehaze - 1.0: apply_dehaze(img, a)))
    if e.clarity != 1.0 and not fast:
        add((("clarity", e.clarity, scale),
             lambda img, a=e.clarity - 1.0, s=scale: apply_clarity(img, a, s)))
    if e.texture != 1.0 and not fast:
        add((("texture", e.texture, scale),
             lambda img, a=e.texture - 1.0, s=scale: apply_texture(img, a, s)))
    if e.vibrance != 1.0:
        add((("vibrance", e.vibrance),
             lambda img, a=e.vibrance - 1.0: apply_vibrance(img, a)))
    if e.color != 1.0:
        add((("color", e.color),
             lambda img, f=e.color: ImageEnhance.Color(img).enhance(f)))
    if color_mixer_active(e):
        add((("mixer",) + _mixer_sig(e), lambda img, ee=e: apply_color_mixer(img, ee)))
    if e.temperature != 1.0:
        add((("temperature", e.temperature),
             lambda img, f=e.temperature: apply_temperature(img, f)))
    if e.tint != 1.0:
        add((("tint", e.tint), lambda img, f=e.tint: apply_tint(img, f)))
    if e.bw > 0.0:
        add((("bw", e.bw), lambda img, a=e.bw: apply_bw(img, a)))
    if e.sepia > 0.0:
        add((("sepia", e.sepia), lambda img, a=e.sepia: apply_sepia(img, a)))
    if e.split_hi != 1.0 or e.split_sh != 1.0:
        add((("split", e.split_hi, e.split_sh),
             lambda img, hi=e.split_hi - 1.0, sh=e.split_sh - 1.0:
                 apply_split_tone(img, hi, sh)))
    if e.sharpen != 1.0 and not fast:
        add((("sharpen", e.sharpen, scale),
             lambda img, f=e.sharpen, s=scale: apply_sharpen(img, f, s)))
    if e.focus and not fast:
        add((("focus", tuple(sorted(e.focus.items())), scale, src_box),
             lambda img, fo=e.focus, s=scale, sb=src_box:
                 apply_focus_blur(img, fo, s, sb, focus_cache)))
    if e.vignette != 1.0:
        add((("vignette", e.vignette, scale, src_box, full_size),
             lambda img, a=e.vignette - 1.0, s=scale, sb=src_box, fs=full_size:
                 apply_vignette(img, a, s, sb, fs, vig_cache)))
    if e.grain > 0.0 and not fast:
        add((("grain", e.grain, scale),
             lambda img, a=e.grain, s=scale: apply_grain(img, a, s)))
    if e.texts:
        sig_texts = tuple(tuple(sorted(ov.items())) for ov in e.texts)
        add((("texts", scale, src_box, sig_texts),
             lambda img, ts=e.texts, s=scale, sb=src_box: _apply_texts(img, ts, s, sb)))
    return stages


def apply_edits_cached(img, e, cache, base_key, auto_luts=None, scale=1.0,
                       src_box=None, full_size=None, vig_cache=None,
                       focus_cache=None, fast=False):
    """Like `apply_edits`, but reuse `cache` to skip the stages an edit left alone.

    `cache` is a plain dict the caller keeps for one view; `base_key` is a token
    identifying the base image's PIXELS (not just its object identity), so the
    caller can retire the cache when it patches the base in place. We compare this
    render's stage signatures to the previous render's: the longest leading run
    that matches produces byte-identical images, so their cached outputs are
    reused and only the stages from the first change onward are recomputed. The
    result equals `apply_edits`; it just does less work. When `base_key` differs
    from the cached one the whole cache is dropped (new photo / zoom / pan / heal).
    """
    if full_size is None:
        full_size = img.size
    if src_box is None:
        src_box = (0, 0, img.size[0], img.size[1])
    stages = edit_stages(e, auto_luts, scale, src_box, full_size, fast,
                         vig_cache, focus_cache)
    prev = cache.get("stages") or []
    if cache.get("base_key") != base_key:   # base pixels changed → nothing reusable
        prev = []
    out = img
    new = []
    i = 0
    while i < len(stages) and i < len(prev) and stages[i][0] == prev[i][0]:
        out = prev[i][1]                    # identical inputs+params → identical output
        new.append(prev[i])
        i += 1
    for j in range(i, len(stages)):
        out = stages[j][1](out)
        new.append((stages[j][0], out))
    cache["base_key"] = base_key
    cache["stages"] = new
    return out


def apply_edits(img, e, auto_luts=None, scale=1.0, src_box=None, full_size=None,
                vig_cache=None, focus_cache=None, fast=False):
    """Apply the live edit factors `e`. Cheap on the small preview, exact on full-res.

    `fast` skips the heavy convolution passes (denoise, dehaze, clarity, texture,
    sharpen/blur, focus blur, grain) so a slider drag stays fluid; the cheap tone
    and colour passes still track live. The next non-fast render restores them.
    """
    # Geometry for position-dependent effects (vignette). Default: `img` IS the
    # whole photo (the full-res save path). The preview passes the visible box.
    if full_size is None:
        full_size = img.size
    if src_box is None:
        src_box = (0, 0, img.size[0], img.size[1])
    for _sig, fn in edit_stages(e, auto_luts, scale, src_box, full_size, fast,
                                vig_cache, focus_cache):
        img = fn(img)
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
