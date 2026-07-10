"""Measure what every slider costs, and what it taxes the rest of the edit.

Produces the table that `manoni_app/cost.py` hardcodes. Re-run it after the
pipeline changes (a new stage, a reordered one, a faster effect) and update
SLIDER_TAX if the tiers moved:

    python tools/bench_slider_cost.py

`own ms` is the stage measured alone on a preview-sized image. `up` counts the
sliders that sit upstream of it — every one of them, when moved, forces this
stage to recompute. `tax` combines them: the cost this slider imposes on an
average later edit, once it is switched on.
"""

import os
import sys
import time
import dataclasses

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manoni_app import imaging                            # noqa: E402
from manoni_app.imaging.pipeline import edit_stages       # noqa: E402
from manoni_app.cost import TAX_HEAVY, TAX_MEDIUM         # noqa: E402

PREVIEW = (1400, 933)      # a typical maximised-window viewport
FULL = (6000, 4000)        # the source it was scaled down from (24 MP)
REPEATS = 5

# Every slider the panel offers, with a "switched well on" probe value. The
# probe only has to leave the rest value — the stage cost barely moves with it.
SLIDERS = {
    "brightness": 1.4, "exposure_g": 1.4, "contrast": 1.4, "highlights": 0.6,
    "shadows": 1.4, "whites": 1.3, "blacks": 0.7,
    "denoise": 0.5, "dehaze": 1.5, "clarity": 1.5, "texture": 1.5,
    "vibrance": 1.5, "color": 1.5,
    "sat_red": 1.5, "sat_orange": 1.5, "sat_yellow": 1.5, "sat_green": 1.5,
    "sat_aqua": 1.5, "sat_blue": 1.5, "sat_purple": 1.5, "sat_magenta": 1.5,
    "gold_hue": 1.2, "gold_sat": 1.5, "gold_light": 1.2,
    "skin_hue": 1.2, "skin_sat": 1.5, "skin_light": 1.2,
    "temperature": 1.3, "tint": 1.3, "bw": 1.0, "sepia": 1.0,
    "split_hi": 1.3, "split_sh": 1.3,
    "sharpen": 1.6, "vignette": 1.5, "grain": 0.5,
}


def _sample_image(path):
    "A real photo at preview size — flat colour would flatter the convolutions."
    src = Image.open(path).convert("RGB")
    return src.resize(PREVIEW, Image.LANCZOS)


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base = _sample_image(os.path.join(here, "Filter_Show.jpg"))
    default = imaging.Edits()
    src_box = (0, 0) + PREVIEW

    def stages(edits):
        return edit_stages(edits, None, 1.0, src_box, FULL, False)

    # The pipeline ORDER comes from the code, never from a hand-kept list.
    order = [sig[0] for sig, _ in stages(dataclasses.replace(default, **SLIDERS))]
    pos = {name: i for i, name in enumerate(order)}

    stage_of, own = {}, {}
    for attr, val in SLIDERS.items():
        one = stages(dataclasses.replace(default, **{attr: val}))
        sig, fn = one[-1]          # the stage this slider alone switched on
        stage_of[attr] = sig[0]
        best = float("inf")
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            fn(base)
            best = min(best, (time.perf_counter() - t0) * 1000)
        own[attr] = best

    rows = []
    for attr in SLIDERS:
        upstream = sum(1 for other in SLIDERS
                       if pos[stage_of[other]] < pos[stage_of[attr]])
        rows.append((own[attr] * upstream / len(SLIDERS), attr, own[attr], upstream))

    print("pipeline order: %s\n" % " -> ".join(order))
    print("%-14s %8s %5s %9s  %s" % ("slider", "own ms", "up", "tax", "dot"))
    for tax, attr, ms, upstream in sorted(rows, reverse=True):
        tier = ("red" if tax >= TAX_HEAVY else
                "amber" if tax >= TAX_MEDIUM else "-")
        print("%-14s %8.1f %5d %9.1f  %s" % (attr, ms, upstream, tax, tier))


if __name__ == "__main__":
    main()
