"""Pure image-processing for Manoni — Pillow in, Pillow out.

No Tk and no Manoni state: every function takes its inputs explicitly (an `Edits`
value object for the slider settings, plus the source image and geometry). That
keeps the math readable, reusable and testable on its own, while the window code
stays about the UI. The Manoni methods are thin wrappers that build an `Edits`
from the live sliders and call in here.
"""

import math
from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageStat


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
    color:       float = 1.0
    temperature: float = 1.0
    tint:        float = 1.0
    bw:          float = 0.0
    sepia:       float = 0.0
    sharpen:     float = 1.0
    vignette:    float = 1.0
    # Selective "focus" blur (Fotor-style depth of field): a circle kept sharp
    # while everything outside it is Gaussian-blurred. None = off, else a dict
    # {cx, cy, r (source px), blur 0..1, feather 0..1}. See apply_focus_blur.
    focus:       object = None


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


# --- Selective focus blur (depth of field) -----------------------------------

def apply_focus_blur(img, focus, scale, src_box, cache=None):
    """Keep a circle sharp and Gaussian-blur everything outside it — the classic
    portrait / tilt-shift depth effect (Fotor's "blur" tool).

    `focus` = {cx, cy, r, blur, feather}. cx/cy/r are in FULL-RES SOURCE pixels
    (like the crop box), so the circle stays anchored to the photo through zoom
    and pan. They are mapped into this region's display pixels via `src_box` +
    `scale`, exactly like the vignette — so the small preview and the full-res
    save composite identically. `blur` (0..1) sets the blur radius; `feather`
    (0..1) softens the sharp→blurred transition. The mask depends only on the
    geometry, so it is cached across blur-slider drags via the optional `cache`."""
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
    rx = max(1.0, focus["r"] * scale)
    feather = focus.get("feather", 0.4)

    key = (w, h, round(cx, 1), round(cy, 1), round(rx, 1), round(feather, 3))
    mask = cache.get(key) if cache is not None else None
    if mask is None:
        # Low-frequency mask: build it small, then scale up (cheap on a big save).
        f = min(1.0, FOCUS_MASK_MAX / max(w, h))
        mw, mh = max(1, round(w * f)), max(1, round(h * f))
        mask = Image.new("L", (mw, mh), 0)
        bbox = [(cx - rx) * f, (cy - rx) * f, (cx + rx) * f, (cy + rx) * f]
        ImageDraw.Draw(mask).ellipse(bbox, fill=255)    # 255 inside = stays sharp
        soft = max(0.5, feather * rx * f)
        mask = mask.filter(ImageFilter.GaussianBlur(soft))
        if (mw, mh) != (w, h):
            mask = mask.resize((w, h), Image.BILINEAR)
        if cache is not None:
            cache.clear()            # keep only the latest geometry (single slot)
            cache[key] = mask
    blurred = img.filter(ImageFilter.GaussianBlur(radius))
    # Inside the circle (mask=255) keep the sharp img; outside, the blurred copy.
    return Image.composite(img, blurred, mask)


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
