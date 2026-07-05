"""Text / watermark overlays — a string laid over the photo.

Used for captions or a "© name" watermark. The centre and font height are kept
in FULL-RES SOURCE px (like the focus shape), so the text stays glued to the
photo through zoom/pan and the small preview composites identically to the
full-res save: the only difference is `scale`, which multiplies the position
AND the font size together. Pure Pillow, no Tk / state.
"""

import math

from PIL import Image, ImageDraw, ImageFont


# Friendly font name -> candidate Windows font files (first that loads wins).
# EVERY file here carries BOTH Latin AND Georgian glyphs (verified on Win 10/11),
# so a Georgian caption renders in any chosen style instead of falling to empty
# ".notdef" boxes. The old Arial/Times/Consolas set looked fine in Latin but had
# no Georgian coverage, so Georgian text came out as boxes whatever you picked.
TEXT_FONT_FILES = {
    "Sans":       ["segoeui.ttf", "calibri.ttf", "micross.ttf"],   # Segoe UI
    "Sans Bold":  ["segoeuib.ttf", "calibrib.ttf", "micross.ttf"], # Segoe UI Bold
    "Light":      ["segoeuil.ttf", "calibril.ttf", "segoeui.ttf"], # Segoe UI Light
    "Serif":      ["sylfaen.ttf", "micross.ttf"],                  # Sylfaen
    "Rounded":    ["calibri.ttf", "segoeui.ttf"],                  # Calibri
    "Script":     ["Gabriola.ttf", "sylfaen.ttf"],                 # Gabriola
}
TEXT_FONTS = list(TEXT_FONT_FILES.keys())   # the order shown in the panel

# Overlays saved before this set existed may name a dropped family; map those to
# the nearest survivor so old captions still render (and highlight a chip).
_FONT_ALIASES = {"Mono": "Sans", "Georgian": "Serif", "Sans Light": "Light"}


def resolve_font_family(family):
    "Normalise a stored font name to a current TEXT_FONTS key (handles old saves)."
    if family in TEXT_FONT_FILES:
        return family
    return _FONT_ALIASES.get(family, TEXT_FONTS[0])

_font_cache = {}   # (family, px) -> ImageFont; bounded so a size drag can't grow it


def _load_font(family, px):
    "An ImageFont for `family` at `px`; falls back to a Georgian-capable face."
    px = max(1, int(round(px)))
    family = resolve_font_family(family)
    key = (family, px)
    font = _font_cache.get(key)
    if font is None:
        # Final fallbacks are Georgian-capable too, so a missing primary never
        # drops a Georgian caption back to boxes.
        for cand in TEXT_FONT_FILES.get(family, []) + ["segoeui.ttf", "micross.ttf"]:
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
    " hit-box and corner snapping — measured at the un-scaled source font size,"
    " grown to the rotated bounding box so the box encloses a turned caption."
    text = (overlay or {}).get("text") or ""
    if not text.strip():
        return (0.0, 0.0)
    font = _load_font(overlay.get("font", "Sans"),
                      max(1.0, overlay.get("size", 48.0)))
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = d.multiline_textbbox((0, 0), text, font=font,
                                align=overlay.get("align", "center"))
    w, h = (bbox[2] - bbox[0], bbox[3] - bbox[1])
    angle = float((overlay or {}).get("angle", 0.0))
    if angle:
        c, s = abs(math.cos(math.radians(angle))), abs(math.sin(math.radians(angle)))
        return (w * c + h * s, w * s + h * c)
    return (w, h)


# Finished caption tiles (glyphs drawn + rotated), keyed by every input EXCEPT
# position — so dragging a caption AROUND reuses the same tile instead of
# re-drawing the glyphs and re-rotating them each frame (rotation is the costly bit).
_tile_cache = {}


def _text_tile(overlay, scale):
    "The ready-to-paste RGBA tile for this caption at this scale (cached), or None."
    text = (overlay.get("text") or "")
    if not text.strip():
        return None
    opacity = max(0.0, min(1.0, float(overlay.get("opacity", 1.0))))
    if opacity <= 0.0:
        return None
    px = max(1.0, overlay.get("size", 48.0) * scale)
    family = overlay.get("font", "Sans")
    align = overlay.get("align", "center")
    color = overlay.get("color", "#ffffff")
    angle = float(overlay.get("angle", 0.0))
    shadow = bool(overlay.get("shadow"))
    a = int(round(opacity * 255))
    key = (text, family, round(px), align, color, a, shadow, round(angle, 1))
    tile = _tile_cache.get(key)
    if tile is not None:
        return tile

    font = _load_font(family, px)
    rgb = _hex_to_rgb(color)
    # Draw onto a TIGHT tile with the text's INK box centred in it, so the tile
    # can be rotated about that centre. (Manual centering, not anchor="mm" —
    # multiline anchors vary across Pillow.)
    scratch = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = scratch.multiline_textbbox((0, 0), text, font=font, align=align)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if tw <= 0 or th <= 0:
        return None
    # A soft dark drop-shadow lifts light text off a bright photo; its offset
    # scales with the font so it reads the same on preview and full-res.
    off = max(1, int(round(px * 0.07))) if shadow else 0
    m = off + 2                              # margin so the shadow + AA edges never clip
    tile = Image.new("RGBA", (int(tw + 2 * m), int(th + 2 * m)), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    ox, oy = m - bbox[0], m - bbox[1]        # ink box lands at (m, m) → centred in the tile
    if off:
        d.multiline_text((ox + off, oy + off), text, font=font,
                         fill=(0, 0, 0, int(a * 0.6)), align=align)
    d.multiline_text((ox, oy), text, font=font,
                     fill=(rgb[0], rgb[1], rgb[2], a), align=align)

    # Rotate about the tile centre (positive = clockwise), expanding so no glyph
    # is clipped; the ink centre stays at the rotated tile's centre.
    if angle:
        tile = tile.rotate(-angle, resample=Image.BICUBIC, expand=True)

    if len(_tile_cache) > 48:                # a size / rotate drag spawns one per step
        _tile_cache.clear()
    _tile_cache[key] = tile
    return tile


def apply_text_overlay(img, overlay, scale, src_box):
    "Draw the overlay's text centred on its source-px point, scaled to display px."
    tile = _text_tile(overlay, scale)
    if tile is None:
        return img

    sx0, sy0, _sx1, _sy1 = src_box
    cx = (overlay["cx"] - sx0) * scale
    cy = (overlay["cy"] - sy0) * scale
    pw, ph = tile.size
    x, y = int(round(cx - pw / 2)), int(round(cy - ph / 2))

    # Composite ONLY the caption's bounding box, not the whole frame. Pasting onto
    # a copy of `img` with the tile's own alpha as the mask is byte-identical to a
    # full-frame alpha_composite on an opaque RGB base, but skips the two
    # whole-image RGBA<->RGB conversions — the cost that made dragging / rotating a
    # caption over a big photo stutter. paste clips a partly-off-canvas box. Copy
    # first: `img` may be a cached pipeline stage we must not mutate in place.
    if img.mode == "RGB":
        out = img.copy()
        out.paste(tile, (x, y), tile)
        return out
    # Transparent (RGBA/other) base: full-layer composite. Rare — the preview and
    # save bases are RGB.
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    layer.paste(tile, (x, y))
    return Image.alpha_composite(img.convert("RGBA"), layer)


def _apply_texts(img, texts, scale, src_box):
    "Draw every text / watermark overlay in list order (later over earlier)."
    for ov in texts:
        img = apply_text_overlay(img, ov, scale, src_box)
    return img
