"""Text / watermark overlays — a string laid over the photo.

Used for captions or a "© name" watermark. The centre and font height are kept
in FULL-RES SOURCE px (like the focus shape), so the text stays glued to the
photo through zoom/pan and the small preview composites identically to the
full-res save: the only difference is `scale`, which multiplies the position
AND the font size together. Pure Pillow, no Tk / state.
"""

import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont


# Friendly font name -> real Windows font files per (bold, italic) style. Georgian
# coverage was dropped — those faces never actually rendered Georgian here, so this
# is a curated set of good-looking LATIN faces instead. Every family carries a full
# Regular / Bold / Italic / Bold-Italic set of true font files, so the Bold + Italic
# toggles always resolve to a genuine styled face — no synthetic slant or stroke.
TEXT_FONT_STYLES = {
    "Sans":    {(0, 0): ["segoeui.ttf"],  (1, 0): ["segoeuib.ttf"],
                (0, 1): ["segoeuii.ttf"], (1, 1): ["segoeuiz.ttf"]},   # Segoe UI
    "Serif":   {(0, 0): ["georgia.ttf"],  (1, 0): ["georgiab.ttf"],
                (0, 1): ["georgiai.ttf"], (1, 1): ["georgiaz.ttf"]},   # Georgia
    "Elegant": {(0, 0): ["pala.ttf"],     (1, 0): ["palab.ttf"],
                (0, 1): ["palai.ttf"],    (1, 1): ["palabi.ttf"]},     # Palatino Linotype
    "Soft":    {(0, 0): ["candara.ttf"],  (1, 0): ["candarab.ttf"],
                (0, 1): ["candarai.ttf"], (1, 1): ["candaraz.ttf"]},   # Candara
    "Casual":  {(0, 0): ["trebuc.ttf"],   (1, 0): ["trebucbd.ttf"],
                (0, 1): ["trebucit.ttf"], (1, 1): ["trebucbi.ttf"]},   # Trebuchet MS
    "Mono":    {(0, 0): ["consola.ttf"],  (1, 0): ["consolab.ttf"],
                (0, 1): ["consolai.ttf"], (1, 1): ["consolaz.ttf"]},   # Consolas
}
TEXT_FONTS = list(TEXT_FONT_STYLES.keys())   # the order shown in the panel

# Overlays saved with an older font set may name a dropped family; map those to the
# nearest survivor so old captions still render (and highlight a chip). The retired
# ‘Sans Bold’ becomes plain Sans — its weight now rides on the Bold toggle instead.
_FONT_ALIASES = {"Sans Bold": "Sans", "Light": "Sans", "Rounded": "Soft",
                 "Script": "Casual", "Georgian": "Serif", "Sans Light": "Sans"}


def resolve_font_family(family):
    "Normalise a stored font name to a current TEXT_FONTS key (handles old saves)."
    if family in TEXT_FONT_STYLES:
        return family
    return _FONT_ALIASES.get(family, TEXT_FONTS[0])


_FONTS_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_fonts_index = None


def _font_path(name):
    "Full path to a font file in the Windows fonts dir, matched CASE-INSENSITIVELY"
    " (e.g. on-disk 'Candara.ttf' vs our 'candara.ttf'). Falls back to the bare"
    " name so PIL can try its own lookup if the dir listing failed."
    global _fonts_index
    if _fonts_index is None:
        try:
            _fonts_index = {f.lower(): f for f in os.listdir(_FONTS_DIR)}
        except OSError:
            _fonts_index = {}
    real = _fonts_index.get(name.lower())
    return os.path.join(_FONTS_DIR, real) if real else name

_font_cache = {}   # (family, px, bold, italic) -> ImageFont; bounded (a size drag grows it)


def _load_font(family, px, bold=False, italic=False):
    "A real ImageFont for `family` at `px` in the given style; regular as a fallback."
    px = max(1, int(round(px)))
    family = resolve_font_family(family)
    b, i = int(bool(bold)), int(bool(italic))
    key = (family, px, b, i)
    font = _font_cache.get(key)
    if font is None:
        styles = TEXT_FONT_STYLES[family]
        # Prefer the exact style; relax italic, then bold, then plain if a face is
        # somehow missing. Segoe UI is the final safety net.
        files = (styles.get((b, i)) or styles.get((b, 0)) or
                 styles.get((0, i)) or styles[(0, 0)])
        for cand in files + ["segoeui.ttf"]:
            try:
                font = ImageFont.truetype(_font_path(cand), px)
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
                      max(1.0, overlay.get("size", 48.0)),
                      overlay.get("bold", False), overlay.get("italic", False))
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
    bold = bool(overlay.get("bold"))
    italic = bool(overlay.get("italic"))
    align = overlay.get("align", "center")
    color = overlay.get("color", "#ffffff")
    angle = float(overlay.get("angle", 0.0))
    shadow = bool(overlay.get("shadow"))
    # Shadow parameters — distance and blur are % of the font size, so the
    # shadow scales with the text and the preview matches the full-res save.
    # The .get defaults reproduce the old fixed look (crisp, down-right, 60%
    # black), so overlays saved before these knobs existed render unchanged.
    sh_dist = float(overlay.get("shadow_dist", 10.0))
    sh_angle = float(overlay.get("shadow_angle", 45.0))
    sh_blur = float(overlay.get("shadow_blur", 0.0))
    sh_op = max(0.0, min(1.0, float(overlay.get("shadow_opacity", 0.6))))
    sh_color = overlay.get("shadow_color", "#000000")
    a = int(round(opacity * 255))
    key = (text, family, round(px), bold, italic, align, color, a,
           angle and round(angle, 1),
           shadow and (round(sh_dist, 1), round(sh_angle), round(sh_blur, 1),
                       round(sh_op, 2), sh_color))
    tile = _tile_cache.get(key)
    if tile is not None:
        return tile

    font = _load_font(family, px, bold, italic)
    rgb = _hex_to_rgb(color)
    # Draw onto a TIGHT tile with the text's INK box centred in it, so the tile
    # can be rotated about that centre. (Manual centering, not anchor="mm" —
    # multiline anchors vary across Pillow.)
    scratch = ImageDraw.Draw(Image.new("L", (1, 1)))
    bbox = scratch.multiline_textbbox((0, 0), text, font=font, align=align)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if tw <= 0 or th <= 0:
        return None
    # A drop-shadow lifts light text off a bright photo. Its offset comes from
    # the distance + angle knobs (0° = right, 90° = down, matching the y-down
    # image axes) and everything scales with the font so it reads the same on
    # preview and full-res.
    sh_a = int(round(a * sh_op)) if shadow else 0
    dx = dy = 0.0
    blur_r = 0.0
    if sh_a:
        d_px = px * sh_dist / 100.0
        dx = d_px * math.cos(math.radians(sh_angle))
        dy = d_px * math.sin(math.radians(sh_angle))
        blur_r = px * sh_blur / 200.0        # 100 → half the font height: very soft
    # Margin so the shadow (offset + ~3σ of blur spread) + AA edges never clip.
    m = int(math.ceil(max(abs(dx), abs(dy)) + 3.0 * blur_r)) + 2
    size = (int(tw + 2 * m), int(th + 2 * m))
    tile = Image.new("RGBA", size, (0, 0, 0, 0))
    ox, oy = m - bbox[0], m - bbox[1]        # ink box lands at (m, m) → centred in the tile
    if sh_a:
        sh_rgb = _hex_to_rgb(sh_color, (0, 0, 0))
        ImageDraw.Draw(tile).multiline_text(
            (ox + dx, oy + dy), text, font=font,
            fill=(sh_rgb[0], sh_rgb[1], sh_rgb[2], sh_a), align=align)
        if blur_r > 0.1:
            tile = tile.filter(ImageFilter.GaussianBlur(blur_r))
    d = ImageDraw.Draw(tile)
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


