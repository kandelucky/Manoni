"""Pure image-processing for Manoni — Pillow in, Pillow out.

No Tk and no Manoni state: every function takes its inputs explicitly (an `Edits`
value object for the slider settings, plus the source image and geometry). That
keeps the math readable, reusable and testable on its own, while the window code
stays about the UI. The Manoni methods are thin wrappers that build an `Edits`
from the live sliders and call in here.

This package used to be one big `imaging.py`; it is split by topic now, and this
`__init__` just re-exports the public surface so callers keep writing
`imaging.apply_edits(...)`, `imaging.Edits`, etc. unchanged. The modules:

    edits.py     the `Edits` value object (plain data)
    levels.py    auto levels / contrast + the ACR tone curve
    colormix.py  the HSL colour mixer (per-hue bands + gold/skin mini-HSLs)
    effects.py   the slider-effect passes (vignette, grain, denoise, clarity, …)
    text.py      text / watermark overlays + font handling
    display.py   view-only helpers (transparency checkerboard, live histogram)
    retouch.py   destructive bakes: spot heal / clone stamp + perspective
    pipeline.py  composes the effects in order into `apply_edits`
"""

from .edits import Edits                                             # noqa: F401
from .levels import autocontrast_luts, tone_lut, apply_auto_luts     # noqa: F401
from .colormix import (HSL_BANDS, apply_color_mixer,                 # noqa: F401
                       color_mixer_active)
from .text import (TEXT_FONTS, resolve_font_family, text_extent,     # noqa: F401
                   apply_text_overlay)
from .display import has_alpha, checkerboard, histogram_image        # noqa: F401
from .retouch import (HEAL_FEATHER, heal_region, clone_region,       # noqa: F401
                      perspective_coeffs, apply_perspective)
from .effects import (apply_vignette, apply_grain, apply_denoise,    # noqa: F401
                      apply_split_tone, apply_dehaze, apply_focus_blur,
                      apply_clarity, apply_texture, apply_vibrance,
                      apply_temperature, apply_tint, apply_bw, apply_sepia,
                      apply_sharpen)
from .pipeline import edit_stages, apply_edits, apply_edits_cached    # noqa: F401
