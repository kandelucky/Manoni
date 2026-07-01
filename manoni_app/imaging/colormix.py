"""The HSL colour mixer — per-hue saturation bands plus the gold & skin mini-HSLs.

Strengthen or weaken ONE colour without touching the rest (Lightroom's HSL
"Saturation" tab), with two extra hue+saturation-gated targets (gold, skin) that
each get their own hue / saturation / lightness so they move only that material.
Pure Pillow: a hue→gain table is built in Python (cheap), then applied with
C-speed ImageChops so a full-res save stays fast. Hue is PIL's 0–255 scale.

`_shift_weighted` (a weighted additive channel offset) is also reused by the
split-tone effect in the pipeline module.
"""

import math

from PIL import Image, ImageChops


# The eight named bands: (Edits attr, centre hue 0–255). The half-width below is
# wider than the spacing, so a colour sitting between two named hues is shared
# smoothly between them rather than snapping to one.
HSL_BANDS = (
    ("sat_red",     0),     #   0°
    ("sat_orange",  21),    #  30°
    ("sat_yellow",  43),    #  60°
    ("sat_green",   85),    # 120°
    ("sat_aqua",    128),   # 180°
    ("sat_blue",    170),   # 240°
    ("sat_purple",  191),   # 270°
    ("sat_magenta", 213),   # 300°
)
HSL_HALF = 32       # band half-width in 0–255 hue units (≈45°): neighbours overlap

# Gold: a warm amber (≈45°) handled on its own with three controls, a mini-HSL
# just for golden tones. Narrower than a normal band so only true golds move.
GOLD_CENTER     = 32    # ≈45° in 0–255
GOLD_HALF       = 22
GOLD_V_GAIN     = 0.60  # how much a full "shine" slider lifts the lightness
GOLD_HUE_SHIFT  = 18    # max hue shift (0–255 units, ≈25°) at a full hue slider
# Gold acts ONLY on genuinely golden pixels: a warm hue AND enough saturation.
# White / cream stonework shares gold's hue but is nearly grey (low saturation),
# so this gate fades the effect to zero below GOLD_SAT_LO and to full at
# GOLD_SAT_HI — keeping the shine off pale stone. (0–255 saturation units; raise
# the pair to be even stricter about what counts as "gold".)
GOLD_SAT_LO     = 60
GOLD_SAT_HI     = 120

# Skin: the same idea tuned for skin tones, which cluster tightly in hue (≈25°)
# across every complexion while their saturation ranges wide (pale → deep). The
# sat gate is low so even pale skin is included, but still drops near-grey walls.
SKIN_CENTER     = 18    # ≈25° in 0–255 (holds from light to deep skin)
SKIN_HALF       = 16
SKIN_V_GAIN     = 0.45  # gentler lightness lift than gold (skin blows out easily)
SKIN_HUE_SHIFT  = 14    # max hue shift (≈20°): nudge skin warmer / cooler
SKIN_SAT_LO     = 25    # include pale skin...
SKIN_SAT_HI     = 55    # ...at full strength, while near-grey pixels stay out

# (centre, half, sat_lo, sat_hi, v_gain, hue_shift, hue_attr, sat_attr, light_attr)
# One row per hue+saturation-gated mini-HSL. apply_color_mixer loops over these.
TARGETS = (
    (GOLD_CENTER, GOLD_HALF, GOLD_SAT_LO, GOLD_SAT_HI, GOLD_V_GAIN,
     GOLD_HUE_SHIFT, "gold_hue", "gold_sat", "gold_light"),
    (SKIN_CENTER, SKIN_HALF, SKIN_SAT_LO, SKIN_SAT_HI, SKIN_V_GAIN,
     SKIN_HUE_SHIFT, "skin_hue", "skin_sat", "skin_light"),
)


def _hue_weight(hue, center, half):
    "Raised-cosine weight 1→0 as `hue` moves `half` away from `center` (circular)."
    d = abs(hue - center)
    d = min(d, 256 - d)                     # hue is a circle
    if d >= half:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * d / half))


def _split_gain_maps(h, gains):
    "From a per-hue signed gain list, build the two 0–255 hue-indexed multiply"
    " maps (positive part, negative part) for the H band `h`."
    up   = [max(0, min(255, int(round( g * 255)))) for g in gains]
    down = [max(0, min(255, int(round(-g * 255)))) for g in gains]
    return h.point(up), h.point(down)


def _scale_channel(chan, up_map, down_map):
    "new = chan + chan*up - chan*down, all clamped 0..255 (C-speed ImageChops)."
    raised  = ImageChops.add(chan, ImageChops.multiply(chan, up_map))
    return ImageChops.subtract(raised, ImageChops.multiply(chan, down_map))


def _smoothstep_lut(lo, hi):
    "256-entry 0→255 ramp: 0 at/below `lo`, 255 at/above `hi`, smooth between."
    out = []
    for x in range(256):
        if x <= lo:
            f = 0.0
        elif x >= hi:
            f = 1.0
        else:
            f = (x - lo) / (hi - lo)
            f = f * f * (3.0 - 2.0 * f)     # smoothstep (eases both ends)
        out.append(int(round(f * 255)))
    return out


def _add_weighted(chan, weight, amount):
    "chan ± chan·|amount|·weight (multiplicative scale), clamped. `weight` is an"
    " L image (0–255 = 0..1); `amount` a scalar in [-1, 1] whose sign lightens"
    " (≥0) or darkens (<0) the channel only where `weight` is non-zero."
    a = max(-1.0, min(1.0, amount))
    scaled = weight.point(lambda x, k=abs(a): int(round(x * k)))   # |a|·weight
    delta = ImageChops.multiply(chan, scaled)                      # chan·|a|·weight
    return ImageChops.add(chan, delta) if a >= 0 else ImageChops.subtract(chan, delta)


def _shift_weighted(chan, weight, amount):
    "chan ± |amount|·weight (additive offset, for the hue band), clamped. `amount`"
    " is in 0–255 channel units; its sign chooses the shift direction."
    mag = weight.point(lambda x, k=abs(amount): int(round(x / 255.0 * k)))
    return ImageChops.add(chan, mag) if amount >= 0 else ImageChops.subtract(chan, mag)


def apply_color_mixer(img, e):
    """Apply the eight per-hue saturation bands plus the gold and skin mini-HSLs
    (each: hue / saturation / lightness) in one HSV pass. The eight bands key off
    HUE alone; gold and skin additionally key off SATURATION, so they touch only
    that material — not the pale things that merely share its hue. Returns `img`
    untouched (and pays nothing) when every control is neutral."""
    sat_gain = [0.0] * 256          # combined per-hue saturation gain (8 bands)
    bands_on = False
    for attr, center in HSL_BANDS:
        amt = getattr(e, attr, 1.0) - 1.0
        if amt == 0.0:
            continue
        bands_on = True
        for hue in range(256):
            sat_gain[hue] += amt * _hue_weight(hue, center, HSL_HALF)

    # Collect the active gated targets (gold, skin) as their three amounts.
    active = []
    for center, half, slo, shi, vgain, hshift, ha, sa, la in TARGETS:
        hue_amt, sat_amt, light_amt = (getattr(e, ha) - 1.0,
                                       getattr(e, sa) - 1.0,
                                       getattr(e, la) - 1.0)
        if hue_amt or sat_amt or light_amt:
            active.append((center, half, slo, shi, vgain, hshift,
                           hue_amt, sat_amt, light_amt))

    if not bands_on and not active:
        return img

    h, s, v = img.convert("HSV").split()
    h0, s0 = h, s                   # originals: every gate / weight reads these

    if bands_on:
        sat_gain = [max(-1.0, min(1.0, g)) for g in sat_gain]
        s = _scale_channel(s, *_split_gain_maps(h, sat_gain))

    # Each target's per-pixel membership = its HUE weight × a SATURATION gate.
    # The product is 0 for pale pixels, so grey/white material is left alone even
    # when it shares the hue. Weights read the ORIGINAL bands, so targets compose
    # independently of each other's edits. Saturation gates are cached by range.
    gate_cache = {}
    for center, half, slo, shi, vgain, hshift, hue_amt, sat_amt, light_amt in active:
        gw_lut = [int(round(_hue_weight(hue, center, half) * 255))
                  for hue in range(256)]
        gate = gate_cache.get((slo, shi))
        if gate is None:
            gate = s0.point(_smoothstep_lut(slo, shi))
            gate_cache[(slo, shi)] = gate
        weight = ImageChops.multiply(h0.point(gw_lut), gate)
        if sat_amt != 0.0:
            s = _add_weighted(s, weight, sat_amt)
        if light_amt != 0.0:
            v = _add_weighted(v, weight, light_amt * vgain)
        if hue_amt != 0.0:
            h = _shift_weighted(h, weight, hue_amt * hshift)

    return Image.merge("HSV", (h, s, v)).convert("RGB")


def color_mixer_active(e):
    "True if any HSL band or the gold / skin mini-HSLs is off-neutral (else a no-op)."
    for attr, _ in HSL_BANDS:
        if getattr(e, attr, 1.0) != 1.0:
            return True
    for row in TARGETS:
        if any(getattr(e, a) != 1.0 for a in row[6:9]):   # hue / sat / light attrs
            return True
    return False


def _mixer_sig(e):
    "Hashable snapshot of every colour-mixer field, for a stage cache signature."
    return (tuple(getattr(e, a) for a, _ in HSL_BANDS)
            + tuple(getattr(e, a) for row in TARGETS for a in row[6:9]))
