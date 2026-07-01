"""View-only helpers: the transparency checkerboard and the live histogram.

These are not edits — they are things the viewer paints around the photo. Pure
Pillow, so they sit here with the rest of the image maths rather than in the Tk
window code. The window calls them directly.
"""

from PIL import Image, ImageDraw, ImageChops


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
