"""Golden characterization test for manoni_app.imaging.

Locks the current output of the pure image pipeline so the planned
`imaging.py` -> `imaging/` package split can be shown to be pixel-identical
(not eyeballed). Every public entry point is exercised on one deterministic
synthetic image and reduced to a short digest.

Run:  python tests/test_imaging_golden.py

  * First run (no baseline) writes tests/imaging_golden.json and reports
    "baseline created". Do this on the CURRENT code, before touching imaging.
  * Every later run compares against the baseline and exits non-zero on any
    difference, printing which case changed.
  * `--update` rewrites the baseline on purpose (after an intended change).

`imaging` is pure (only math + PIL, no Tk, no Manoni state, no state file),
so importing it here is safe — none of the headless-Manoni pitfalls apply.

Grain uses Image.effect_noise (an unseeded RNG), so it is checked structurally
(runs, right size/mode, actually changes the pixels) rather than by hash.
"""

import os
import sys
import json
import hashlib
import colorsys
from dataclasses import fields

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image                       # noqa: E402
from manoni_app import imaging              # noqa: E402
from manoni_app.imaging import Edits        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "imaging_golden.json")

W, H = 240, 160


def make_image():
    """A deterministic RGB field: hue sweeps left->right and value darkens
    top->bottom, so every hue band AND every tonal region carries material
    for the colour mixer, tone curve and effects to bite on. Pure stdlib."""
    img = Image.new("RGB", (W, H))
    data = []
    for y in range(H):
        v = 0.15 + 0.80 * (y / (H - 1))          # dark top -> bright bottom
        for x in range(W):
            r, g, b = colorsys.hsv_to_rgb(x / W, 0.85, v)
            data.append((int(r * 255), int(g * 255), int(b * 255)))
    img.putdata(data)
    return img


def digest_img(img):
    "Short stable hash of an image's mode, size and raw pixels."
    h = hashlib.sha256()
    h.update(("%s:%dx%d:" % (img.mode, img.size[0], img.size[1])).encode())
    h.update(img.tobytes())
    return h.hexdigest()[:16]


def digest_obj(obj):
    "Short stable hash of any JSON-able value (LUTs, boxes, ...)."
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def collect():
    "Run every entry point and reduce each to a comparable value."
    base = make_image()
    out = {}

    def edited(name, **kw):
        out[name] = digest_img(imaging.apply_edits(base.copy(), Edits(**kw)))

    # --- basic tone / colour --------------------------------------------------
    edited("neutral")
    edited("brightness", brightness=1.4)
    edited("contrast", contrast=1.3)
    edited("color", color=1.5)
    edited("temperature", temperature=1.3)
    edited("tint", tint=0.8)

    # --- ACR tone curve -------------------------------------------------------
    edited("highlights", highlights=1.5)
    edited("shadows", shadows=1.5)
    edited("whites", whites=1.4)
    edited("blacks", blacks=0.7)
    edited("clarity", clarity=1.6)
    edited("texture", texture=1.5)
    edited("vibrance", vibrance=1.6)
    edited("exposure_gamma", exposure_g=1.6)
    edited("dehaze_plus", dehaze=1.5)
    edited("dehaze_minus", dehaze=0.6)

    # --- HSL colour mixer -----------------------------------------------------
    edited("sat_red_zero", sat_red=0.0)
    edited("sat_blue_double", sat_blue=2.0)
    edited("sat_green", sat_green=1.6)
    edited("gold", gold_hue=1.3, gold_sat=1.4, gold_light=1.3)
    edited("skin", skin_hue=1.2, skin_sat=1.3, skin_light=1.2)

    # --- effects --------------------------------------------------------------
    edited("denoise", denoise=0.8)
    edited("bw", bw=1.0)
    edited("sepia", sepia=1.0)
    edited("vignette_dark", vignette=1.6)
    edited("vignette_light", vignette=0.6)
    edited("sharpen", sharpen=1.8)
    edited("blur", sharpen=0.4)
    edited("split_tone", split_hi=1.4, split_sh=0.7)
    edited("focus_circle", focus={"shape": "circle", "cx": 120, "cy": 80,
                                  "r": 40, "blur": 0.7, "feather": 0.4})
    edited("focus_line", focus={"shape": "line", "cx": 120, "cy": 80,
                                "width": 50, "angle": 0.3, "blur": 0.6,
                                "feather": 0.4})
    edited("text", texts=[{"text": "Manoni", "cx": 120, "cy": 80, "size": 36,
                           "color": "#ffcc00", "opacity": 0.9, "font": "Sans",
                           "align": "center", "shadow": True}])

    # --- combinations + the two render paths ----------------------------------
    combo = dict(brightness=1.1, contrast=1.2, vibrance=1.3, sat_green=1.5,
                 vignette=1.3, clarity=1.2, split_hi=1.3)
    edited("combo", **combo)
    out["combo_fast"] = digest_img(
        imaging.apply_edits(base.copy(), Edits(**combo), fast=True))

    # Preview path: a downscaled view with matching scale + geometry, so the
    # position-dependent effects (vignette/focus) map like the real viewport.
    half = base.resize((W // 2, H // 2))
    out["preview_scaled"] = digest_img(imaging.apply_edits(
        half, Edits(vignette=1.4, clarity=1.2,
                    focus={"shape": "circle", "cx": 120, "cy": 80,
                           "r": 40, "blur": 0.6, "feather": 0.4}),
        scale=0.5, src_box=(0, 0, W, H), full_size=(W, H)))

    # apply_edits_cached must equal apply_edits for the same config.
    cache = {}
    out["cached_first"] = digest_img(imaging.apply_edits_cached(
        base.copy(), Edits(**combo), cache, base_key="t"))
    out["cached_reuse"] = digest_img(imaging.apply_edits_cached(
        base.copy(), Edits(**combo), cache, base_key="t"))

    # --- standalone entry points ---------------------------------------------
    out["autolut_per_channel"] = digest_obj(
        imaging.autocontrast_luts(base, per_channel=True))
    out["autolut_luminance"] = digest_obj(
        imaging.autocontrast_luts(base, per_channel=False))
    out["autolut_tone"] = digest_obj(imaging.auto_tone_luts(base))
    out["color_mixer"] = digest_img(
        imaging.apply_color_mixer(base.copy(), Edits(sat_red=0.4, gold_sat=1.5)))
    out["histogram"] = digest_img(imaging.histogram_image(base, 200, 80))
    out["checkerboard"] = digest_img(imaging.checkerboard(64, 48))
    out["has_alpha_rgb"] = imaging.has_alpha(base)
    rgba = base.convert("RGBA")
    rgba.putalpha(128)                       # make it genuinely see-through
    out["has_alpha_rgba"] = imaging.has_alpha(rgba)
    out["text_extent"] = list(imaging.text_extent(
        {"text": "Manoni", "size": 48, "font": "Sans", "align": "center"}))

    heal_img, heal_box = imaging.heal_region(base.copy(), 120, 80, 20)
    out["heal"] = digest_img(heal_img)
    out["heal_box"] = list(heal_box)
    clone_img, clone_box = imaging.clone_region(base.copy(), 120, 80, 60, 40, 20)
    out["clone"] = digest_img(clone_img)
    out["clone_box"] = list(clone_box)

    out["perspective"] = digest_img(imaging.apply_perspective(base.copy(), 30, -20))

    # --- Edits dataclass defaults (a moved dataclass must keep them) ----------
    out["edits_defaults"] = {f.name: f.default for f in fields(Edits)}

    return out, base


def check_grain(base):
    "Grain is random; assert it runs and changes the pixels, don't hash it."
    g = imaging.apply_edits(base.copy(), Edits(grain=0.8))
    assert g.size == base.size and g.mode == "RGB", "grain broke size/mode"
    assert digest_img(g) != digest_img(base), "grain did not change the image"


def main():
    update = "--update" in sys.argv
    results, base = collect()
    check_grain(base)

    if not os.path.exists(GOLDEN) or update:
        with open(GOLDEN, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, sort_keys=True)
        print("baseline %s: %d cases -> %s"
              % ("updated" if update else "created", len(results), GOLDEN))
        return 0

    with open(GOLDEN, encoding="utf-8") as f:
        golden = json.load(f)

    diffs = []
    for name in sorted(set(results) | set(golden)):
        want = golden.get(name, "<missing in baseline>")
        got = results.get(name, "<missing in run>")
        if want != got:
            diffs.append((name, want, got))

    if diffs:
        print("FAIL: %d of %d cases differ from the baseline:\n" % (len(diffs), len(results)))
        for name, want, got in diffs:
            print("  %-22s baseline=%r  now=%r" % (name, want, got))
        print("\nIf this change was intentional, rebaseline with --update.")
        return 1

    print("PASS: all %d imaging cases match the baseline." % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
