"""The edit pipeline — turn an `Edits` value object into a finished image.

The pass is expressed as an ordered list of STAGES (see `edit_stages`): each a
(signature, fn) pair, fn mapping image -> image. `apply_edits` just runs them
all; `apply_edits_cached` reuses a per-view cache so an edit only recomputes the
stages downstream of whatever actually changed — which is what stops a heavy
effect (denoise / clarity / focus) jamming every later slider move.

This module is the one place that knows the order the effects compose in; the
effect functions themselves (imported below) know nothing about each other.
"""

from PIL import ImageEnhance

from .levels import apply_auto_luts, tone_lut
from .colormix import apply_color_mixer, color_mixer_active, _mixer_sig
from .text import _apply_texts
from .effects import (apply_vignette, apply_grain, apply_denoise, apply_split_tone,
                      apply_dehaze, apply_focus_blur, apply_clarity, apply_texture,
                      apply_vibrance, apply_temperature, apply_tint, apply_bw,
                      apply_sepia, apply_sharpen, apply_exposure_gamma)


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
        # TEST: linear exposure at half strength (deviation from 1.0 halved) so it
        # can be compared fairly against the gentler gamma exposure beside it.
        add((("brightness", e.brightness),
             lambda img, f=1.0 + (e.brightness - 1.0) * 0.5:
                 ImageEnhance.Brightness(img).enhance(f)))
    if e.exposure_g != 1.0:
        add((("exposure_g", e.exposure_g),
             lambda img, a=e.exposure_g - 1.0: apply_exposure_gamma(img, a)))
    if e.contrast != 1.0:
        # Contrast dialled back to 50% strength (deviation from 1.0 x0.5) — the raw
        # ImageEnhance.Contrast was too aggressive at the slider extremes.
        add((("contrast", e.contrast),
             lambda img, f=1.0 + (e.contrast - 1.0) * 0.5:
                 ImageEnhance.Contrast(img).enhance(f)))
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
