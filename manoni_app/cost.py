"""How much each slider, once switched on, taxes the rest of the editing.

The edit pipeline is staged and cached (`imaging.apply_edits_cached`): moving a
slider recomputes its own stage and every stage AFTER it. So an effect that is
left switched on costs nothing by itself — it costs on every later slider move
that sits upstream of it. Two things decide how much it hurts:

  * how expensive that stage is, and
  * how late it sits in the pipeline (a late stage is downstream of almost
    every slider, so almost every edit pays for it).

    tax = own_cost_ms * (sliders upstream of it / all sliders)

Measured on a 1400x933 preview (`tools/bench_slider_cost.py` reproduces it):

    slider        own ms    up    tax
    denoise        399.7     7   77.7   <- expensive, and 7 sliders precede it
    grain           45.4    35   44.1   <- cheap-ish, but dead last: everything pays
    sharpen         31.8    33   29.2
    sat_* / gold_* / skin_*  ~70    13   ~25   (one `mixer` stage, per-band cost)
    vignette        25.2    34   23.8
    vibrance        61.7    11   18.9
    split_hi/sh     15.5    31   13.4
    texture         47.3    10   13.1
    clarity         47.9     9   12.0
    dehaze          35.5     8    7.9
    everything else               < 8

The measurements leave two clean gaps — 44.1 -> 29.2 and 18.9 -> 13.5 — so the
thresholds sit in the gaps rather than being picked out of the air.

Only the marked sliders get a dot: a badge on all 36 would grade nothing. The
advice a dot carries is "switch this one on LAST", not "avoid it".
"""

# Fixed hex, not theme tokens — like TitledSlider's `chip`, the grade means the
# same thing in dark and light mode, so the restyle pass must leave it alone.
# Saturated on purpose. The dot is 5 px wide and tintkit rims it with a shade of
# its own fill, so more than half of it is rim: the eye averages the two, and a
# muted pair (the brick #C0574E / ochre #C8932F this replaces) came out only
# ~29 dE apart once averaged — near enough to be read as one badge. Saturating
# buys back the ~10 dE the rim costs, without growing the dot.
DOT_HEAVY = "#D9342B"    # red   — tax >= 40 ms
DOT_MEDIUM = "#E9A21C"   # amber — tax >= 15 ms

TAX_HEAVY = 40.0
TAX_MEDIUM = 15.0

# slider attr -> measured tax, in ms (see the table above). Sliders whose tax is
# below TAX_MEDIUM are simply absent: no entry, no dot.
SLIDER_TAX = {
    "denoise": 77.7,
    "grain": 44.1,
    "sharpen": 29.2,
    "sat_red": 25.9, "sat_orange": 26.4, "sat_yellow": 25.1, "sat_green": 25.6,
    "sat_aqua": 26.1, "sat_blue": 26.6, "sat_purple": 28.2, "sat_magenta": 26.3,
    "gold_hue": 24.5, "gold_sat": 24.5, "gold_light": 24.2,
    "skin_hue": 23.5, "skin_sat": 24.3, "skin_light": 24.0,
    "vignette": 23.8,
    "vibrance": 18.9,
}


def dot_color(attr):
    "The dot colour for one slider attribute, or None when it costs too little."
    tax = SLIDER_TAX.get(attr, 0.0)
    if tax >= TAX_HEAVY:
        return DOT_HEAVY
    if tax >= TAX_MEDIUM:
        return DOT_MEDIUM
    return None


def preset_dot(values, neutral_of):
    """The dot colour for a filter — a saved set of slider values.

    A filter costs whatever its heaviest switched-on slider costs, so it wears
    that slider's badge. `neutral_of(attr)` gives the slider's rest value; a
    slider parked there adds no stage to the pipeline, so it is ignored — that
    is what lets a filter listing every key score the same as one listing only
    the keys it actually moves.

    Only DOT_HEAVY is ever returned. A filter is one click, not a slider you
    keep nudging, so the medium grade earns nothing here — and it would fire on
    almost every look, since a mere `vibrance` or `vignette` is enough to reach
    it (six of the eight built-ins). A badge worn by six rows out of eight
    grades nothing. Red still marks the two that genuinely hurt: grain, denoise.
    """
    worst = 0.0
    for attr, val in (values or {}).items():
        tax = SLIDER_TAX.get(attr, 0.0)
        if tax <= worst:
            continue                       # cheap, or no better than what we have
        if abs(float(val) - neutral_of(attr)) < 1e-6:
            continue                       # parked at rest -> no stage, no cost
        worst = tax
    return DOT_HEAVY if worst >= TAX_HEAVY else None
