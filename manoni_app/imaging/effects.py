"""The slider-effect passes — one leaf image op per creative / tonal slider.

Each function takes an image (and its slider amount + display scale, plus
geometry for the position-dependent ones) and returns a new image. They are the
building blocks the pipeline (see __init__.edit_stages) runs in order; none of
them know about each other or the Edits object. Pure Pillow, no Tk / state.

`apply_split_tone` reuses `_shift_weighted` from the colour mixer (a weighted
additive channel offset), the one op shared across effect modules.
"""

import math

from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageChops

from .colormix import _shift_weighted


# --- Tuning constants (were class attributes on Manoni) ----------------------

# Blur radius (full-res source pixels) at the slider's max-blur end.
MAX_BLUR = 8.0

# Clarity: large-radius local contrast. Radius is in full-res pixels (scaled
# to display pixels in the preview, like blur). Vibrance: max saturation push.
CLARITY_RADIUS = 24.0   # full-res px; UnsharpMask radius at a full slider
CLARITY_PCT    = 120    # UnsharpMask percent at a full slider (amount = +1)
VIBRANCE_GAIN  = 1.0    # max saturation multiplier boost for the most-muted pixels

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
# FOCUS_BLUR_EASE eases the slider (raises 0..1 to this power before scaling):
# >1 keeps low/mid slider values gentle and saves the full drama for near the
# top of the range, since a plain linear map made even a modest-looking slider
# position blur too hard.
#
# The shape's edge doesn't jump straight from sharp to FOCUS_MAX_BLUR: a short
# ring around it (FOCUS_TRANS_BASE at feather=1.0, source px) is rendered as a
# STACK of FOCUS_BLUR_LEVELS increasingly-blurred copies, radius climbing on
# its own eased curve (FOCUS_BLUR_LEVEL_EASE — small steps first). A plain
# alpha blend between the sharp image and one fully-blurred copy left a
# translucent "ghost" of sharp detail floating over the blur right at the
# edge; climbing the blur radius itself in short steps reads as a real lens
# defocusing instead. That stack is built on a crop around the shape (not the
# whole photo), and — like the mask trick above it used to use — that crop is
# itself downsampled to at most FOCUS_WORK_MAX px before the levels are blurred,
# so a big in-focus circle on a big save stays cheap (the crop's AREA grows
# with the shape's own size, unlike the vignette/heal boxes, so without this it
# would not be).
FOCUS_MAX_BLUR        = 40.0
FOCUS_BLUR_EASE       = 1.6
FOCUS_TRANS_BASE      = 80.0
FOCUS_BLUR_LEVELS     = 6
FOCUS_WORK_MAX        = 640
FOCUS_BLUR_LEVEL_EASE = 2.2

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
    (0..1) sets the blur radius; `feather` (0..1) sets how far outside the shape
    the blur takes to climb to full strength (see FOCUS_TRANS_BASE et al above).

    The ring masks (which pixels belong to which step of the ramp) depend only
    on the geometry, not the blur amount, so they — and the crop box they're
    built in — are cached across blur-slider drags via the optional `cache`."""
    blur_amt = float(focus.get("blur", 0.0))
    if blur_amt <= 0.0:
        return img
    radius = (blur_amt ** FOCUS_BLUR_EASE) * FOCUS_MAX_BLUR * scale   # display px
    if radius < 0.1:
        return img
    w, h = img.size
    sx0, sy0, _sx1, _sy1 = src_box
    cx = (focus["cx"] - sx0) * scale
    cy = (focus["cy"] - sy0) * scale
    feather = focus.get("feather", 0.4)
    shape = focus.get("shape", "circle")
    trans = max(1.0, feather * FOCUS_TRANS_BASE * scale)   # ramp width, display px
    # Crop margin: generous enough that a Gaussian blur of FOCUS_MAX_BLUR (the
    # largest `radius` can ever be) computed on just this crop still agrees with
    # one computed on the whole image, right up to the crop's edge. Independent
    # of the CURRENT blur amount, so the crop box (and the ring masks built in
    # it, below) don't need rebuilding on every blur-slider tick, only when the
    # shape itself moves/resizes or feather changes.
    pad = FOCUS_MAX_BLUR * scale * 3.0 + 8.0

    if shape == "line":
        hw = max(1.0, focus.get("width", 0.0) * 0.5 * scale)   # half-band, display px
        angle = focus.get("angle", 0.0)
        ux, uy = math.cos(angle), math.sin(angle)       # along the line
        nx, ny = -uy, ux                                # across (perpendicular)
        edge0 = hw
        half_w = hw + trans + pad
        L = (w + h) * 1.5 + 10.0        # long enough to cross the frame at any angle
        corners = [
            (cx + ux * L + nx * half_w, cy + uy * L + ny * half_w),
            (cx - ux * L + nx * half_w, cy - uy * L + ny * half_w),
            (cx - ux * L - nx * half_w, cy - uy * L - ny * half_w),
            (cx + ux * L - nx * half_w, cy + uy * L - ny * half_w),
        ]
        xs, ys = [p[0] for p in corners], [p[1] for p in corners]
        bx0, by0 = max(0, int(math.floor(min(xs)))), max(0, int(math.floor(min(ys))))
        bx1, by1 = min(w, int(math.ceil(max(xs)))), min(h, int(math.ceil(max(ys))))
        key = (w, h, round(cx, 1), round(cy, 1), round(hw, 1),
               round(angle, 4), round(feather, 3), "line")
    else:
        rx = max(1.0, focus["r"] * scale)               # shape radius, display px
        edge0 = rx
        half = rx + trans + pad
        bx0, by0 = max(0, int(math.floor(cx - half))), max(0, int(math.floor(cy - half)))
        bx1, by1 = min(w, int(math.ceil(cx + half))), min(h, int(math.ceil(cy + half)))
        key = (w, h, round(cx, 1), round(cy, 1), round(rx, 1),
               round(feather, 3), "circle")

    if bx1 - bx0 < 4 or by1 - by0 < 4:
        return img       # shape/frame combination leaves no room to ramp into
    crop_box = (bx0, by0, bx1, by1)

    cw, ch = bx1 - bx0, by1 - by0
    # The crop's own AREA grows with the shape's size (a big in-focus circle on
    # a big save has a big ring around it), so work at a downsampled copy of the
    # crop — same "build small, scale up" trick the old single mask used — and
    # only pay FOCUS_WORK_MAX² for the levels/masks regardless of shape size.
    wf = min(1.0, FOCUS_WORK_MAX / max(cw, ch))
    ww, wh = max(1, round(cw * wf)), max(1, round(ch * wf))

    cached = cache.get(key) if cache is not None else None
    if cached is not None and cached[0] == crop_box:
        ring_masks = cached[1]
    else:
        wlcx, wlcy = (cx - bx0) * wf, (cy - by0) * wf   # shape centre, working coords

        def ring_mask(R):
            "255 at/beyond radius R from the shape edge, 0 inside — a touch of"
            " blur only to antialias the ring, not to feather it (the ramp"
            " itself comes from stacking several of these, not this blur)."
            m = Image.new("L", (ww, wh), 255)
            draw = ImageDraw.Draw(m)
            Rw = R * wf
            if shape == "line":
                Lb = (ww + wh) * 1.5 + 10.0
                draw.polygon([
                    (wlcx + ux * Lb + nx * Rw, wlcy + uy * Lb + ny * Rw),
                    (wlcx - ux * Lb + nx * Rw, wlcy - uy * Lb + ny * Rw),
                    (wlcx - ux * Lb - nx * Rw, wlcy - uy * Lb - ny * Rw),
                    (wlcx + ux * Lb - nx * Rw, wlcy + uy * Lb - ny * Rw),
                ], fill=0)
            else:
                draw.ellipse([wlcx - Rw, wlcy - Rw, wlcx + Rw, wlcy + Rw], fill=0)
            return m.filter(ImageFilter.GaussianBlur(max(0.75, 1.5 * wf)))

        # Thresholds edge0, edge0 + trans/LEVELS, ... up to (but not including)
        # edge0 + trans — the last step's mask still reaches to infinity, so
        # everything beyond the ramp gets the final (full-radius) level.
        ring_masks = [ring_mask(edge0 + (k / FOCUS_BLUR_LEVELS) * trans)
                      for k in range(FOCUS_BLUR_LEVELS)]
        if cache is not None:
            cache.clear()            # keep only the latest geometry (single slot)
            cache[key] = (crop_box, ring_masks)

    # The ramp: start from the sharp crop, then repeatedly paste in a slightly
    # MORE blurred copy of it everywhere at/beyond the next ring threshold. The
    # per-level radius climbs on its own eased curve (small steps first, e.g.
    # ~1, 2, 5, 9, 14, 18px rather than jumping straight to the full amount) —
    # each step blends two RELATIVELY CLOSE blur amounts, so it reads as the
    # blur itself growing, not as sharp detail ghosting through a heavy blur.
    sub = img.crop(crop_box)
    sub_w = sub.resize((ww, wh), Image.BILINEAR) if (ww, wh) != (cw, ch) else sub
    result = sub_w
    for k in range(1, FOCUS_BLUR_LEVELS + 1):
        r_k = ((k / FOCUS_BLUR_LEVELS) ** FOCUS_BLUR_LEVEL_EASE) * radius * wf
        level = sub_w.filter(ImageFilter.GaussianBlur(r_k)) if r_k >= 0.1 else sub_w
        result = Image.composite(level, result, ring_masks[k - 1])
    if (ww, wh) != (cw, ch):
        result = result.resize((cw, ch), Image.BILINEAR)

    blurred_full = img.filter(ImageFilter.GaussianBlur(radius))
    blurred_full.paste(result, crop_box)
    return blurred_full


# --- The individual slider passes --------------------------------------------
# Pulled out of the flat pass so a stage can call one op and the caches can key
# on exactly its inputs. The math is byte-for-byte the old code.

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
    "Scale saturation, weighted by (1 - s/255) so muted colours move most and vivid"
    " ones barely. Multiplicative (s x factor), so neutral greys (s=0) stay grey"
    " instead of picking up the arbitrary hue=0 red cast an additive push gave them."
    gain = amt * VIBRANCE_GAIN
    h, s, v = img.convert("HSV").split()
    s = s.point(lambda x: max(0, min(255, int(x * (1.0 + gain * (1.0 - x / 255.0))))))
    return Image.merge("HSV", (h, s, v)).convert("RGB")


def apply_exposure_gamma(img, amt):
    "Brightness/Fill exposure: a gamma curve out = 255*(in/255)^gamma, gamma = 2^-amt."
    " Unlike the linear ImageEnhance.Brightness multiply, the endpoints are locked"
    " (0->0, 255->255), so it lifts/lowers the midtones without clipping highlights"
    " to white or crushing shadows to black."
    if amt == 0.0:
        return img
    gamma = 2.0 ** (-amt)
    lut = [max(0, min(255, int(round(255.0 * (i / 255.0) ** gamma)))) for i in range(256)]
    return img.point(lut * len(img.getbands()))


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
