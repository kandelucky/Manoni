"""Logo / sticker overlays — a transparent PNG laid over the photo.

The sibling of text.py: a picture watermark instead of a string. Like text, the
centre and the target WIDTH are kept in FULL-RES SOURCE px, so the logo stays
glued to the photo through zoom / pan and the small preview composites
identically to the full-res save — the only difference is `scale`, which
multiplies the position AND the size together. Pure Pillow, no Tk / state.

An overlay is a dict:
    path         absolute path to the source PNG (its own alpha is respected)
    cx, cy       centre, SOURCE px
    size         target WIDTH, SOURCE px (height follows the PNG's aspect ratio)
    opacity      0..1, multiplied onto the PNG's own alpha
    flip_h/v     mirror horizontally / vertically
    angle        rotation in degrees (positive = clockwise), 0 = upright
    tint         '#rrggbb' to recolour the whole logo to one flat colour
                 (the anti-aliased alpha is kept as a mask), or None for its
                 original colours — a black logo becomes white, etc.
"""

import math
import os

from PIL import Image


def _hex_to_rgb(value, default=(255, 255, 255)):
    "Parse '#rrggbb' (or '#rgb') to an (r, g, b) tuple; default on garbage."
    try:
        s = value.lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except (ValueError, AttributeError, TypeError, IndexError):
        return default


# path -> (mtime, RGBA image). Bounded so opening many logos can't grow it.
_logo_cache = {}


def load_logo(path):
    "The source PNG as an RGBA image (cached by path + mtime); None if unreadable."
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _logo_cache.get(path)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    try:
        im = Image.open(path).convert("RGBA")
    except Exception:
        return None
    if len(_logo_cache) > 24:        # a folder full of logos shouldn't pile up
        _logo_cache.clear()
    _logo_cache[path] = (mtime, im)
    return im


def logo_extent(overlay):
    "Width/height of the logo in SOURCE px (0,0 when unreadable). For the UI"
    " hit-box and corner snapping — the PNG's aspect ratio, grown to the rotated"
    " bounding box so the selection frame always encloses a turned logo."
    im = load_logo((overlay or {}).get("path"))
    w = max(1.0, float((overlay or {}).get("size", 0.0)))
    if im is None or im.width <= 0:
        return (0.0, 0.0)
    h = w * im.height / im.width
    angle = float((overlay or {}).get("angle", 0.0))
    if angle:
        c, s = abs(math.cos(math.radians(angle))), abs(math.sin(math.radians(angle)))
        return (w * c + h * s, w * s + h * c)
    return (w, h)


# Finished display tiles (flipped / tinted / resized / faded / rotated), keyed by
# every input EXCEPT position — so dragging a logo AROUND reuses the same tile
# instead of rebuilding + re-rotating it each frame (rotation is the costly bit).
_tile_cache = {}


def _logo_tile(overlay, scale):
    "The ready-to-paste RGBA tile for this overlay at this scale (cached), or None."
    im = load_logo(overlay.get("path"))
    if im is None or im.width <= 0:
        return None
    opacity = max(0.0, min(1.0, float(overlay.get("opacity", 1.0))))
    if opacity <= 0.0:
        return None
    dw = max(1, int(round(overlay.get("size", 100.0) * scale)))
    flip_h, flip_v = bool(overlay.get("flip_h")), bool(overlay.get("flip_v"))
    angle = float(overlay.get("angle", 0.0))
    tint = overlay.get("tint") or ""
    try:
        mtime = os.path.getmtime(overlay["path"])
    except (OSError, KeyError):
        mtime = 0
    key = (overlay.get("path"), mtime, dw, flip_h, flip_v,
           round(angle, 1), tint, round(opacity, 3))
    tile = _tile_cache.get(key)
    if tile is not None:
        return tile

    logo = im
    if flip_h:
        logo = logo.transpose(Image.FLIP_LEFT_RIGHT)
    if flip_v:
        logo = logo.transpose(Image.FLIP_TOP_BOTTOM)
    if tint:
        # Recolour to one flat colour, keeping the anti-aliased alpha as a mask
        # (the same trick the icon loader uses), so edges stay smooth.
        flat = Image.new("RGBA", logo.size, _hex_to_rgb(tint) + (0,))
        flat.putalpha(logo.split()[3])
        logo = flat
    # Target display size: width from `size` (source px) * scale, height from the
    # PNG's aspect ratio — so preview and full-res composite identically.
    dh = max(1, int(round(dw * logo.height / logo.width)))
    if (dw, dh) != logo.size:
        logo = logo.resize((dw, dh), Image.LANCZOS)
    if opacity < 1.0:
        logo = logo.copy()
        logo.putalpha(logo.split()[3].point(lambda v: int(v * opacity)))
    # Rotate last (positive = clockwise), expanding so no corner is clipped; the
    # new transparent border composites as a no-op. rotate keeps the image centred
    # on its own centre, so pasting the result centred on (cx, cy) glues the
    # logo's centre to its source-px point.
    if angle:
        logo = logo.rotate(-angle, resample=Image.BICUBIC, expand=True)

    if len(_tile_cache) > 32:            # a size / rotate drag spawns one per step
        _tile_cache.clear()
    _tile_cache[key] = logo
    return logo


def apply_logo_overlay(img, overlay, scale, src_box):
    "Draw the overlay's PNG centred on its source-px point, scaled to display px."
    logo = _logo_tile(overlay, scale)
    if logo is None:
        return img

    sx0, sy0, _sx1, _sy1 = src_box
    cx = (overlay["cx"] - sx0) * scale
    cy = (overlay["cy"] - sy0) * scale
    pw, ph = logo.size
    x, y = int(round(cx - pw / 2)), int(round(cy - ph / 2))

    # Composite ONLY the logo's bounding box, not the whole frame. Pasting onto a
    # copy of `img` with the logo's own alpha as the mask is byte-identical to a
    # full-frame alpha_composite on an opaque RGB base, but skips the two
    # whole-image RGBA<->RGB conversions — the cost that made dragging a small
    # logo over a big photo stutter. paste clips a partly-off-canvas box. Copy
    # first: `img` may be a cached pipeline stage we must not mutate in place.
    if img.mode == "RGB":
        out = img.copy()
        out.paste(logo, (x, y), logo)
        return out
    # Transparent (RGBA/other) base: full-layer composite (correct over a
    # see-through photo). Rare — the preview and save bases are RGB.
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    layer.paste(logo, (x, y))
    return Image.alpha_composite(img.convert("RGBA"), layer)
