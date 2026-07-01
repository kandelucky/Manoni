"""Behavioural tests for manoni_app.imaging — the (მე) items of TESTING_TODO.md.

Unlike test_imaging_golden.py (which only locks the current pixels so a refactor
can be shown identical), this file asserts that each effect does the RIGHT thing:
the correct DIRECTION of change, a true no-op at neutral, hue/saturation gating,
and that the pipeline (cache / fast / neutral) is self-consistent. These are the
tests that can actually catch a tool that "doesn't work as expected".

Pure imaging only — Pillow in, Pillow out, no Tk, no state file. Run:

    python tests/test_behavior.py

Each check runs independently; a failure prints the case and the reason and the
script exits non-zero, but every other check still runs (so one break doesn't
hide the rest).
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageStat        # noqa: E402
from manoni_app import imaging          # noqa: E402
from manoni_app.imaging import Edits    # noqa: E402


# --- tiny image helpers ------------------------------------------------------

def solid(rgb, size=(40, 40)):
    return Image.new("RGB", size, rgb)


def hgrad(w=120, h=40, lo=0, hi=255):
    "Horizontal luminance gradient lo->hi, as RGB."
    img = Image.new("L", (w, h))
    px = img.load()
    for x in range(w):
        v = int(round(lo + (hi - lo) * x / (w - 1)))
        for y in range(h):
            px[x, y] = v
    return img.convert("RGB")


def stripes(w=120, h=120, period=24, a=96, b=160):
    "Vertical grey stripes (mid-frequency texture for clarity/texture/sharpen)."
    img = Image.new("RGB", (w, h))
    px = img.load()
    half = max(1, period // 2)
    for y in range(h):
        for x in range(w):
            c = a if (x // half) % 2 == 0 else b
            px[x, y] = (c, c, c)
    return img


def hsv_solid(h, s, v, size=(30, 30)):
    "A solid patch built in HSV (0-255 each) -> RGB."
    return Image.new("HSV", size, (h, s, v)).convert("RGB")


def means(img):
    return ImageStat.Stat(img.convert("RGB")).mean          # [R, G, B]


def stddev(img):
    return sum(ImageStat.Stat(img.convert("RGB")).stddev)


def sat_mean(img):
    "Mean of the HSV saturation channel."
    return ImageStat.Stat(img.convert("HSV").split()[1]).mean[0]


def spread(img):
    "Max-min of the channel means — how far from grey a solid patch is."
    m = means(img)
    return max(m) - min(m)


def same(a, b):
    return a.convert("RGB").tobytes() == b.convert("RGB").tobytes()


def ed(base, **kw):
    "apply_edits with an Edits built from kw."
    return imaging.apply_edits(base.copy(), Edits(**kw))


# --- the checks --------------------------------------------------------------
# Each is a no-arg function that raises AssertionError on failure.

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


# ---- pipeline ----

@check
def pipeline_neutral_is_noop():
    b = stripes()
    assert same(b, ed(b)), "neutral Edits changed the image"


@check
def pipeline_cache_equals_flat():
    b = stripes()
    combo = dict(brightness=1.1, contrast=1.2, vibrance=1.3, sat_green=1.5,
                 vignette=1.3, clarity=1.2, split_hi=1.3)
    flat = imaging.apply_edits(b.copy(), Edits(**combo))
    cache = {}
    c1 = imaging.apply_edits_cached(b.copy(), Edits(**combo), cache, base_key="k")
    c2 = imaging.apply_edits_cached(b.copy(), Edits(**combo), cache, base_key="k")
    assert same(flat, c1), "cached (first) != flat"
    assert same(flat, c2), "cached (reuse) != flat"


@check
def pipeline_fast_skips_heavy():
    b = stripes()
    # clarity is a heavy pass -> fast must skip it (output == input)...
    assert same(b, imaging.apply_edits(b.copy(), Edits(clarity=1.6), fast=True)), \
        "fast did not skip clarity"
    # ...but the same edit at full quality must change the image.
    assert not same(b, ed(b, clarity=1.6)), "clarity had no effect at full quality"


@check
def pipeline_fast_keeps_cheap():
    b = stripes()
    fast = imaging.apply_edits(b.copy(), Edits(brightness=1.4), fast=True)
    full = imaging.apply_edits(b.copy(), Edits(brightness=1.4), fast=False)
    assert same(fast, full), "fast changed a cheap pass (brightness)"


@check
def edits_defaults_all_neutral():
    e = Edits()
    for a in ("brightness", "contrast", "highlights", "shadows", "whites",
              "blacks", "clarity", "texture", "vibrance", "dehaze", "color",
              "temperature", "tint", "sharpen", "vignette", "split_hi", "split_sh"):
        assert getattr(e, a) == 1.0, f"{a} default != 1.0"
    for a in ("bw", "sepia", "grain", "denoise"):
        assert getattr(e, a) == 0.0, f"{a} default != 0.0"
    assert e.focus is None and e.texts is None, "focus/texts default not None"


# ---- basic tone / white balance ----

@check
def brightness_direction():
    g = solid((128, 128, 128))
    assert means(ed(g, brightness=1.5))[0] > 150, "brightness up did not brighten"
    assert means(ed(g, brightness=0.5))[0] < 100, "brightness down did not darken"
    assert same(g, ed(g, brightness=1.0)), "brightness 1.0 not a no-op"


@check
def contrast_direction():
    b = hgrad()
    assert stddev(ed(b, contrast=1.5)) > stddev(b), "contrast up did not widen spread"
    assert stddev(ed(b, contrast=0.5)) < stddev(b), "contrast down did not narrow spread"


@check
def temperature_warm_cool():
    g = solid((128, 128, 128))
    warm = means(ed(g, temperature=1.3))
    cool = means(ed(g, temperature=0.7))
    assert warm[0] > 128 > warm[2], "warm did not raise R / lower B"
    assert cool[0] < 128 < cool[2], "cool did not lower R / raise B"
    assert same(g, ed(g, temperature=1.0)), "temperature 1.0 not a no-op"


@check
def tint_green_magenta():
    g = solid((128, 128, 128))
    assert means(ed(g, tint=1.3))[1] < 128, "tint>1 did not cut green"
    assert means(ed(g, tint=0.7))[1] > 128, "tint<1 did not add green"


@check
def color_saturation_to_grey():
    red = solid((220, 40, 40))
    out = ed(red, color=0.0)
    r, gr, bl = means(out)
    assert max(r, gr, bl) - min(r, gr, bl) < 3, "color=0 did not desaturate to grey"
    assert spread(ed(red, color=1.6)) > spread(red), "color=1.6 did not boost saturation"


# ---- ACR tone curve (highlights/shadows/whites/blacks are distinct) ----

@check
def tone_highlights_lifts_bright_keeps_ends():
    lut = imaging.tone_lut(Edits(highlights=1.5))
    assert lut is not None
    assert lut[158] > 158, "highlights did not lift the bright midtones"
    assert lut[0] <= 1 and lut[255] >= 254, "highlights moved the extremes"


@check
def tone_shadows_lifts_dark_keeps_black():
    lut = imaging.tone_lut(Edits(shadows=1.5))
    assert lut[97] > 97, "shadows did not lift the dark midtones"
    assert lut[0] <= 1, "shadows moved pure black"


@check
def tone_whites_touch_only_top():
    lut = imaging.tone_lut(Edits(whites=1.4))
    assert lut[230] > 230, "whites did not lift the top"
    assert abs(lut[128] - 128) <= 1, "whites touched the midtones"


@check
def tone_blacks_touch_only_bottom():
    lut = imaging.tone_lut(Edits(blacks=0.7))
    assert lut[25] < 25, "blacks did not deepen the bottom"
    assert abs(lut[128] - 128) <= 1, "blacks touched the midtones"


@check
def tone_neutral_is_none():
    assert imaging.tone_lut(Edits()) is None, "neutral tone should build no LUT"


# ---- detail & colour ----

@check
def vibrance_weights_muted_more():
    low = hsv_solid(85, 60, 200)
    high = hsv_solid(85, 220, 200)
    d_low = imaging.apply_vibrance(low, 0.6)
    d_high = imaging.apply_vibrance(high, 0.6)
    gain_low = sat_mean(d_low) - sat_mean(low)
    gain_high = sat_mean(d_high) - sat_mean(high)
    assert gain_low > gain_high, "vibrance did not favour the muted colour"
    assert gain_low > 0, "vibrance did not raise the muted colour"


@check
def clarity_plus_more_local_contrast_than_minus():
    b = stripes(period=24)
    assert stddev(ed(b, clarity=1.6)) > stddev(ed(b, clarity=0.5)), \
        "clarity+ is not crisper than clarity-"


@check
def texture_plus_more_detail_than_minus():
    b = stripes(period=6)
    assert stddev(ed(b, texture=1.6)) > stddev(ed(b, texture=0.5)), \
        "texture+ is not crisper than texture-"


@check
def sharpen_blurs_left_of_neutral():
    # A hard black|white edge; a left-of-neutral 'sharpen' is a blur, so pixels
    # just inside the black side must bleed above 0.
    img = Image.new("RGB", (40, 20))
    px = img.load()
    for y in range(20):
        for x in range(40):
            px[x, y] = (0, 0, 0) if x < 20 else (255, 255, 255)
    blurred = ed(img, sharpen=0.3)
    assert blurred.getpixel((19, 10))[0] > 0, "blur did not bleed across the edge"
    # Sharpen>1 needs mid-tone edges with headroom (a hard 0/255 step is already
    # maximally sharp and clamps straight back), so test it on grey stripes.
    soft = stripes(period=8, a=96, b=160)
    assert not same(soft, ed(soft, sharpen=1.8)), "sharpen>1 changed nothing"


@check
def dehaze_plus_more_contrast_than_minus():
    b = hgrad(lo=70, hi=190)
    assert stddev(ed(b, dehaze=1.5)) > stddev(ed(b, dehaze=0.6)), \
        "dehaze+ did not add contrast vs dehaze-"


# ---- effects ----

@check
def bw_desaturates():
    red = solid((220, 40, 40))
    full = ed(red, bw=1.0)
    r, g, bl = means(full)
    assert max(r, g, bl) - min(r, g, bl) < 3, "bw=1.0 not fully grey"
    part = ed(red, bw=0.5)
    assert spread(part) < spread(red) and spread(part) > 2, "bw=0.5 not a partial blend"


@check
def sepia_is_warm_monochrome():
    g = solid((128, 128, 128))
    out = ed(g, sepia=1.0)
    r, gr, bl = means(out)
    assert r > gr > bl, "sepia is not warm (R>G>B)"
    assert same(g, ed(g, sepia=0.0)), "sepia=0 not a no-op"


@check
def split_tone_warms_highlights():
    bright = solid((220, 220, 220))
    out = imaging.apply_split_tone(bright, hi_amt=0.6, sh_amt=0.0)
    r, g, bl = means(out)
    assert r > 220 and bl < 220, "split highlights warm did not push R up / B down"


@check
def vignette_darkens_and_lightens_corners():
    g = solid((128, 128, 128), size=(200, 200))
    dark = ed(g, vignette=1.6)
    light = ed(g, vignette=0.6)
    assert dark.getpixel((2, 2))[0] < dark.getpixel((100, 100))[0], \
        "vignette+ did not darken the corners"
    assert light.getpixel((2, 2))[0] > light.getpixel((100, 100))[0], \
        "vignette- did not lighten the corners"


@check
def grain_adds_noise_keeps_size():
    g = solid((128, 128, 128))
    out = ed(g, grain=0.8)
    assert out.size == g.size and out.mode == "RGB", "grain broke size/mode"
    assert stddev(out) > stddev(g), "grain did not add noise"
    assert same(g, ed(g, grain=0.0)), "grain=0 not a no-op"


@check
def denoise_smooths_chroma():
    # A flat grey field with SPARSE, isolated colour speckles — the median filter
    # removes them (a checkerboard has no minority to remove, so median keeps it).
    b = solid((128, 128, 128), size=(40, 40))
    px = b.load()
    for y in range(0, 40, 5):
        for x in range(0, 40, 5):
            px[x, y] = (198, 58, 128)          # strong chroma speckle
    before = ImageStat.Stat(b.convert("YCbCr").split()[1]).stddev[0]
    out = ed(b, denoise=0.9)
    after = ImageStat.Stat(out.convert("YCbCr").split()[1]).stddev[0]
    assert before > 0, "test speckle produced no chroma variation"
    assert after < before * 0.5, "denoise did not smooth the chroma speckles"
    assert same(b, ed(b, denoise=0.0)), "denoise=0 not a no-op"


# ---- HSL colour mixer (hue / saturation gating) ----

@check
def mixer_band_hits_only_its_hue():
    red = solid((220, 30, 30))
    blue = solid((30, 30, 220))
    red_out = imaging.apply_color_mixer(red.copy(), Edits(sat_red=0.0))
    blue_out = imaging.apply_color_mixer(blue.copy(), Edits(sat_red=0.0))
    assert spread(red_out) < spread(red) * 0.5, "sat_red=0 did not desaturate red"
    assert abs(spread(blue_out) - spread(blue)) < 6, "sat_red touched blue"


@check
def gold_gate_skips_pale():
    gold = hsv_solid(32, 200, 180)     # true gold: warm hue, high saturation
    pale = hsv_solid(32, 30, 220)      # cream: same hue, low saturation
    g1 = imaging.apply_color_mixer(gold.copy(), Edits(gold_sat=1.6))
    p1 = imaging.apply_color_mixer(pale.copy(), Edits(gold_sat=1.6))
    gain_gold = sat_mean(g1) - sat_mean(gold)
    gain_pale = sat_mean(p1) - sat_mean(pale)
    assert gain_gold > gain_pale + 5, "gold_sat did not favour saturated gold"


@check
def skin_gate_skips_grey_wall():
    skin = hsv_solid(18, 120, 200)
    wall = hsv_solid(18, 10, 200)
    s1 = imaging.apply_color_mixer(skin.copy(), Edits(skin_sat=1.6))
    w1 = imaging.apply_color_mixer(wall.copy(), Edits(skin_sat=1.6))
    assert (sat_mean(s1) - sat_mean(skin)) > (sat_mean(w1) - sat_mean(wall)) + 3, \
        "skin_sat did not favour skin over the near-grey wall"


@check
def mixer_active_flag():
    assert not imaging.color_mixer_active(Edits()), "neutral mixer reported active"
    assert imaging.color_mixer_active(Edits(sat_blue=1.2)), "band not detected"
    assert imaging.color_mixer_active(Edits(gold_hue=1.1)), "gold not detected"
    assert imaging.color_mixer_active(Edits(skin_light=0.9)), "skin not detected"


# ---- focus blur ----

@check
def focus_circle_keeps_centre_blurs_outside():
    b = stripes(w=120, h=120, period=6)
    foc = {"shape": "circle", "cx": 60, "cy": 60, "r": 30,
           "blur": 0.9, "feather": 0.3}
    out = ed(b, focus=foc)
    centre_in = b.crop((55, 55, 65, 65))
    centre_out = out.crop((55, 55, 65, 65))
    assert same(centre_in, centre_out), "focus blurred the sharp centre"
    assert stddev(out.crop((0, 0, 12, 12))) < stddev(b.crop((0, 0, 12, 12))) * 0.6, \
        "focus did not blur the corner"


@check
def focus_zero_blur_is_noop():
    b = stripes()
    foc = {"shape": "circle", "cx": 60, "cy": 60, "r": 30,
           "blur": 0.0, "feather": 0.3}
    assert same(b, ed(b, focus=foc)), "focus blur=0 changed the image"


@check
def focus_line_runs_and_blurs():
    b = stripes(w=120, h=120, period=6)
    foc = {"shape": "line", "cx": 60, "cy": 60, "width": 40, "angle": 0.4,
           "blur": 0.7, "feather": 0.3}
    out = ed(b, focus=foc)
    assert out.size == b.size, "line focus broke size"
    assert not same(b, out), "line focus changed nothing"


# ---- text / watermark ----

@check
def text_extent_measures_only_real_text():
    w, h = imaging.text_extent({"text": "Hi", "size": 40, "font": "Sans",
                                "align": "center"})
    assert w > 0 and h > 0, "text_extent is zero for real text"
    assert imaging.text_extent({"text": "   "}) == (0.0, 0.0), \
        "blank text should measure (0,0)"


@check
def text_paints_and_respects_opacity():
    black = solid((0, 0, 0), size=(160, 80))
    ov = {"text": "MANONI", "cx": 80, "cy": 40, "size": 40, "color": "#ffffff",
          "opacity": 1.0, "font": "Sans", "align": "center", "shadow": False}
    box = (0, 0, 160, 80)
    painted = imaging.apply_text_overlay(black.copy(), ov, 1.0, box)
    assert means(painted)[0] > means(black)[0], "white text did not lighten the frame"
    empty = imaging.apply_text_overlay(black.copy(), {**ov, "text": "  "}, 1.0, box)
    assert same(black, empty), "empty text painted something"
    invisible = imaging.apply_text_overlay(black.copy(), {**ov, "opacity": 0.0},
                                           1.0, box)
    assert same(black, invisible), "opacity 0 still painted"


# ---- auto levels / contrast ----

@check
def autocontrast_stretches_low_contrast():
    b = hgrad(lo=80, hi=170)
    luts = imaging.autocontrast_luts(b, per_channel=False)
    out = imaging.apply_auto_luts(b, luts)
    assert stddev(out) > stddev(b) * 1.3, "auto contrast did not stretch the range"
    assert luts[0] == luts[1] == luts[2], "luminance mode should share one LUT"
    per = imaging.autocontrast_luts(b, per_channel=True)
    assert stddev(imaging.apply_auto_luts(b, per)) > stddev(b), \
        "auto levels did not stretch"


# ---- heal / clone (retouch) ----

@check
def heal_replaces_the_blemish():
    g = solid((128, 128, 128), size=(120, 120))
    from PIL import ImageDraw
    ImageDraw.Draw(g).ellipse([54, 54, 66, 66], fill=(255, 0, 0))
    patched, box = imaging.heal_region(g, 60, 60, 10)
    assert patched is not None and len(box) == 4, "heal returned nothing"
    lx, ly = 60 - box[0], 60 - box[1]
    r, gr, bl = patched.getpixel((int(lx), int(ly)))
    assert r < 200, "heal left the red blemish in place"


@check
def clone_copies_the_source():
    img = Image.new("RGB", (120, 60))
    px = img.load()
    for y in range(60):
        for x in range(120):
            px[x, y] = (200, 40, 40) if x < 60 else (40, 40, 200)  # red | blue
    patched, box = imaging.clone_region(img, dst_cx=90, dst_cy=30,
                                        src_cx=30, src_cy=30, radius=12)
    assert patched is not None, "clone returned nothing"
    lx, ly = 90 - box[0], 30 - box[1]
    r, g, b = patched.getpixel((int(lx), int(ly)))
    assert r > b, "clone did not copy the red source onto the blue side"
    # flip variant still produces a patch; a zero brush is refused.
    fp, _ = imaging.clone_region(img, 90, 30, 30, 30, 12, flip=True)
    assert fp is not None, "clone flip failed"
    assert imaging.clone_region(img, 90, 30, 30, 30, 0) == (None, None), \
        "clone accepted a zero-radius brush"


# ---- perspective ----

@check
def perspective_warps_and_noops():
    b = stripes(w=80, h=80, period=8)
    assert same(b, imaging.apply_perspective(b, 0.0, 0.0)), "perspective 0/0 not a no-op"
    out = imaging.apply_perspective(b, 0.3, -0.2)
    assert out.size == b.size, "perspective changed the size"
    assert not same(b, out), "perspective changed nothing"


# --- runner ------------------------------------------------------------------

def main():
    passed = failed = 0
    for fn in CHECKS:
        try:
            fn()
        except Exception as e:                       # noqa: BLE001
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
            if "-v" in sys.argv:
                traceback.print_exc()
        else:
            passed += 1
            print(f"pass  {fn.__name__}")
    print(f"\n{passed} passed, {failed} failed, of {len(CHECKS)} checks.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
