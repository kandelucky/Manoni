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
# View-only helpers (checkerboard + live histogram). All re-exported for the
# viewer; none are part of the edit pipeline.
from .display import has_alpha, checkerboard, histogram_image  # noqa: F401
# Destructive bakes: spot heal / clone stamp + perspective. All re-exported for
# the retouch / perspective tools; none are part of the slider pipeline.
from .retouch import (HEAL_FEATHER, heal_region, clone_region,  # noqa: F401
                      apply_perspective)
# Slider-effect passes + their tuning constants. edit_stages (below) runs these
# leaf ops; they live in effects.py.
from .effects import (apply_vignette, apply_grain, apply_denoise,  # noqa: F401
                      apply_split_tone, apply_dehaze, apply_focus_blur,
                      apply_clarity, apply_texture, apply_vibrance,
                      apply_temperature, apply_tint, apply_bw, apply_sepia,
                      apply_sharpen)


# The tuning constants + every slider-effect pass now live in effects.py; the
# effect functions the pipeline runs are imported at the top.


# The `Edits` value object now lives in edits.py (imported at the top).


# Histogram levels + the tone curve (stretch_lut / autocontrast_luts / tone_lut /
# apply_auto_luts) now live in levels.py; the ones the pipeline uses are imported
# at the top.


# The text / watermark overlay code now lives in text.py; TEXT_FONTS,
# resolve_font_family, text_extent and _apply_texts are imported at the top.


# The transparency checkerboard + live histogram now live in display.py, and
# the HSL colour mixer in colormix.py; both are imported at the top.


# --- The full edit pass ------------------------------------------------------
# The pass is expressed as an ordered list of STAGES (see `edit_stages`): each a
# (signature, fn) pair, fn mapping image -> image with the exact math the flat
# pass used. `apply_edits` just runs them all (output identical to before).
# `apply_edits_cached` reuses a per-view cache so an edit only recomputes the
# stages downstream of whatever actually changed — which is what stops a heavy
# effect (denoise / clarity / focus) jamming every later slider move.

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


# Spot healing / clone stamp and perspective correction now live in retouch.py;
# heal_region, clone_region and apply_perspective are imported at the top.
