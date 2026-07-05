"""The `Edits` value object — the live slider settings as plain data.

Kept in its own module so the whole imaging package (and the window code that
builds one from the sliders) can import it without pulling in the pipeline. No
behaviour, so it is trivial to snapshot for undo / actions.
"""

from dataclasses import dataclass


@dataclass
class Edits:
    """The live edit factors, all neutral by default.

    Each field is the slider's factor: 1.0 means "unchanged" (0.0 for the
    effects `bw`/`sepia`, which are 0..1 blends). Build one from the sliders and pass it to
    `apply_edits`. Plain data — no behaviour — so it is trivial to snapshot.
    """
    brightness:  float = 1.0
    exposure_g:  float = 1.0   # gamma exposure (Brightness/Fill), beside the linear one
    contrast:    float = 1.0
    highlights:  float = 1.0
    shadows:     float = 1.0
    whites:      float = 1.0
    blacks:      float = 1.0
    clarity:     float = 1.0
    texture:     float = 1.0
    vibrance:    float = 1.0
    # Dehaze: 1.0 = neutral; amount = factor - 1.0 in [-1, 1] (+ clears haze, -
    # adds it). Approximate (Pillow has no dark-channel prior). See apply_dehaze.
    dehaze:      float = 1.0
    color:       float = 1.0
    temperature: float = 1.0
    tint:        float = 1.0
    # HSL colour mixer: per-hue saturation. Each factor 1.0 = unchanged, 0.0 =
    # that colour fully greyed, 2.0 = doubled. See apply_color_mixer / HSL_BANDS.
    sat_red:     float = 1.0
    sat_orange:  float = 1.0
    sat_yellow:  float = 1.0
    sat_green:   float = 1.0
    sat_aqua:    float = 1.0
    sat_blue:    float = 1.0
    sat_purple:  float = 1.0
    sat_magenta: float = 1.0
    # Gold and skin each get their own three-slider mini-HSL (the eight bands
    # only do saturation): hue shifts the tone, saturation deepens it, and the
    # third lifts its lightness. Both are HUE + SATURATION gated so they touch
    # only that material, not the pale things sharing its hue. All 1.0 = unchanged.
    gold_hue:    float = 1.0
    gold_sat:    float = 1.0
    gold_light:  float = 1.0
    skin_hue:    float = 1.0
    skin_sat:    float = 1.0
    skin_light:  float = 1.0
    # Noise reduction: 1.0 = off (kept at 1.0 so it shares the slider/factor
    # plumbing), down to 0.0 here it is OFF and 1.0 here would be full — see the
    # editpanel slider, which rests this at 0.0 (off → full). See apply_denoise.
    denoise:     float = 0.0
    bw:          float = 0.0
    sepia:       float = 0.0
    sharpen:     float = 1.0
    vignette:    float = 1.0
    # Film grain: 0.0 = off, up to 1.0 = full strength. See apply_grain.
    grain:       float = 0.0
    # Split-tone (colour grading): warm↔cool tint for highlights / shadows.
    # 1.0 = neutral; amount = factor - 1.0 in [-1, 1] (+ warm, - cool). See
    # apply_split_tone.
    split_hi:    float = 1.0
    split_sh:    float = 1.0
    # Selective "focus" blur (Fotor-style depth of field): a circle kept sharp
    # while everything outside it is Gaussian-blurred. None = off, else a dict
    # {cx, cy, r (source px), blur 0..1, feather 0..1}. See apply_focus_blur.
    focus:       object = None
    # Text / watermark overlays. None or [] = off, else a LIST of dicts, each a
    # string with its centre + size in SOURCE px (so it stays glued to the photo
    # through zoom / pan and the preview matches the full-res save), colour,
    # opacity, font key, alignment and an optional drop shadow. Drawn in list
    # order (later = on top). See apply_text_overlay.
    texts:       object = None
    # Logo / sticker overlays. None or [] = off, else a LIST of dicts, each a PNG
    # path with its centre + width in SOURCE px, opacity, flip flags and an
    # optional flat-colour tint. Drawn after the texts (on top). See apply_logo_overlay.
    logos:       object = None
