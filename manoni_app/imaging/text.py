"""Text / watermark overlays — a string laid over the photo.

Used for captions or a "© name" watermark. The centre and font height are kept
in FULL-RES SOURCE px (like the focus shape), so the text stays glued to the
photo through zoom/pan and the small preview composites identically to the
full-res save: the only difference is `scale`, which multiplies the position
AND the font size together. Pure Pillow, no Tk / state.
"""

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


def _apply_texts(img, texts, scale, src_box):
    "Draw every text / watermark overlay in list order (later over earlier)."
    for ov in texts:
        img = apply_text_overlay(img, ov, scale, src_box)
    return img
