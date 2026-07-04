"""Logic tests for the non-imaging (მე) items: filters, actions, resize, crop,
save — the JSON safety, unique naming, group bookkeeping, resolution-independent
action replay, resize math and the save-metadata rules.

These are window mixin methods, but the ones tested here are PURE (they only read
plain state / PIL images, never Tk), so a tiny stub object that mixes the real
mixins in and supplies that state exercises the genuine code — no Tk root, no
state file. Run:

    python tests/test_logic.py
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image                                   # noqa: E402
from manoni_app.ui.filters import FiltersMixin          # noqa: E402
from manoni_app.ui.actions import ActionsMixin          # noqa: E402
from manoni_app.ui.resize import ResizeMixin            # noqa: E402
from manoni_app.ui.crop import CropMixin                # noqa: E402
from manoni_app.ui.saving import SaveMixin              # noqa: E402


class FakeApp(FiltersMixin, ActionsMixin, ResizeMixin, CropMixin, SaveMixin):
    """The real mixins with just the plain state their PURE methods read. Nothing
    here touches Tk — the interactive methods are simply never called."""

    SLIDER_NEUTRAL = {"bw": 0.0, "sepia": 0.0, "grain": 0.0, "denoise": 0.0,
                      "focus": None, "auto_mode": None, "texts": []}

    def __init__(self):
        self.user_filters = []
        self.filter_groups = []
        self.user_actions = []
        self.current_pil = None
        self.files = []
        self.index = 0
        self.folder = ""
        # resize state
        self._resize_mode = "px"
        self._resize_quality = "normal"
        self._resize_strength = {"soft": "medium", "sharp": "medium"}
        self._rv = None                       # what _resize_value() returns
        # crop state
        self.crop_ratio = None
        self.crop_rect = None
        # a live-edit state _filter_active compares against
        self._state = {k: self._slider_neutral(k) for k in self.FILTER_KEYS}
        self._state["auto_mode"] = None

    # --- stubs the pure methods lean on ---
    def toast(self, *a, **k):
        pass

    def _slider_neutral(self, attr):
        return self.SLIDER_NEUTRAL.get(attr, 1.0)

    def _edit_state(self):
        return dict(self._state)

    def _resize_value(self):
        return self._rv


CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def app():
    return FakeApp()


# ---- filters: JSON safety + naming + groups --------------------------------

@check
def filter_sanitize_keeps_known_drops_junk():
    a = app()
    vals = a._sanitize_filter_values(
        {"brightness": "1.5", "zzz": 9, "contrast": "oops", "auto_mode": "levels"})
    assert vals["brightness"] == 1.5, "known numeric key not coerced to float"
    assert "zzz" not in vals, "unknown key survived"
    assert "contrast" not in vals, "unparseable value survived"
    assert vals["auto_mode"] == "levels", "valid auto_mode dropped"
    bad = a._sanitize_filter_values({"auto_mode": "bogus"})
    assert bad["auto_mode"] is None, "invalid auto_mode not nulled"


@check
def filter_coerce_accepts_the_three_shapes():
    a = app()
    one = a._coerce_filter_list({"manoni_filter": 1, "name": "X", "group": "G",
                                 "values": {"brightness": 1.2}})
    assert len(one) == 1 and one[0]["name"] == "X" and one[0]["group"] == "G"
    bundle = a._coerce_filter_list({"filters": [{"name": "A", "values": {"contrast": 1.1}},
                                                {"name": "", "values": {}}]})
    assert [f["name"] for f in bundle] == ["A"], "bundle / junk filtering wrong"
    bare = a._coerce_filter_list([{"name": "B", "values": {"color": 1.3}}])
    assert len(bare) == 1 and bare[0]["group"] is None, "bare list not accepted"


@check
def filter_unique_names():
    a = app()
    a.user_filters = [{"name": "Look", "group": "My filters", "values": {}}]
    assert a._unique_filter_name("Look") == "Look 2", "clash not numbered"
    assert a._unique_filter_name("Fresh") == "Fresh", "free name changed"


@check
def group_unique_names_avoid_reserved():
    a = app()
    assert a._unique_group_name("Standard") == "Standard 2", "reserved name not bumped"
    assert a._unique_group_name("Mine") == "Mine", "free group name changed"


@check
def group_normalize_order_and_others():
    a = app()
    a.user_filters = [{"name": "a", "group": "My filters", "values": {}},
                      {"name": "b", "group": "Others", "values": {}}]
    a._normalize_groups()
    names = [g["name"] for g in a.filter_groups]
    assert names[0] == "My filters", "My filters is not first"
    assert names[-1] == "Others", "Others is not last"
    # Drop the Others member -> the automatic Others group disappears.
    a.user_filters = [{"name": "a", "group": "My filters", "values": {}}]
    a._normalize_groups()
    assert "Others" not in [g["name"] for g in a.filter_groups], "empty Others kept"


@check
def filter_active_matches_live_state():
    a = app()
    assert a._filter_active({}), "an all-neutral filter should read as active on neutral edits"
    assert not a._filter_active({"brightness": 1.5}), "differing filter read as active"
    a._state["brightness"] = 1.5
    assert a._filter_active({"brightness": 1.5}), "matching filter not read as active"


# ---- actions: JSON safety + resolution-independent replay ------------------

@check
def action_coerce_and_sanitize_steps():
    a = app()
    lst = a._coerce_action_list({"actions": [
        {"name": "A", "steps": [{"op": "crop", "box": [0, 0, 1, 1]}]},
        {"name": "", "steps": []},
    ]})
    assert [x["name"] for x in lst] == ["A"], "action bundle / junk filtering wrong"
    steps = a._sanitize_steps([
        {"op": "crop", "box": [0.0, 0.0, 0.5, 1.0]},
        {"op": "crop", "box": [1, 2]},                 # malformed -> dropped
        {"op": "edit", "state": {"brightness": 1.2}},
        {"op": "bogus"},                               # unknown -> dropped
    ])
    ops = [s["op"] for s in steps]
    assert ops == ["crop", "edit"], f"bad step filtering: {ops}"


@check
def action_rel_focus_validation():
    a = app()
    assert a._sanitize_rel_focus({"shape": "circle", "cx": 0.5, "cy": 0.5,
                                  "r": 0.3}) is not None
    assert a._sanitize_rel_focus({"shape": "square", "cx": 0.5, "cy": 0.5}) is None
    assert a._sanitize_rel_focus({"shape": "circle"}) is None, "missing coords accepted"


@check
def action_focus_roundtrip_same_size():
    a = app()
    a.current_pil = Image.new("RGB", (200, 120))
    foc = {"shape": "circle", "cx": 80.0, "cy": 60.0, "r": 30.0,
           "blur": 0.6, "feather": 0.4}
    back = a._focus_from_rel(a._focus_to_rel(foc))
    for k in ("cx", "cy", "r"):
        assert abs(back[k] - foc[k]) < 1e-6, f"focus round-trip drifted on {k}"


@check
def action_focus_is_resolution_independent():
    a = app()
    a.current_pil = Image.new("RGB", (100, 100))
    rel = a._focus_to_rel({"shape": "circle", "cx": 50.0, "cy": 50.0, "r": 30.0,
                           "blur": 0.6, "feather": 0.4})
    big = a._focus_from_rel_size(rel, 200, 200)
    assert abs(big["cx"] - 100.0) < 1e-6 and abs(big["r"] - 60.0) < 1e-6, \
        "focus did not scale with the image size"


@check
def action_resolve_keeps_last_edit_and_clears_focus():
    a = app()
    action = {"steps": [
        {"op": "edit", "state": {"brightness": 1.1,
                                 "focus": {"shape": "circle", "cx": 0.5, "cy": 0.5,
                                           "r": 0.3}}},
        {"op": "crop", "box": [0, 0, 0.5, 1.0]},
        {"op": "edit", "state": {"brightness": 1.4, "focus": None}},
    ]}
    crops, live = a._resolve_action(action)
    assert crops == [[0, 0, 0.5, 1.0]], "crop not collected"
    assert live["brightness"] == 1.4, "last edit did not win"
    # a crop AFTER the final edit would clear its focus; here the last edit's
    # own focus is None already, so just confirm resolve returns it intact.
    action2 = {"steps": [
        {"op": "edit", "state": {"brightness": 1.2,
                                 "focus": {"shape": "circle", "cx": 0.5, "cy": 0.5,
                                           "r": 0.3}}},
        {"op": "crop", "box": [0, 0, 0.5, 1.0]},
    ]}
    _, live2 = a._resolve_action(action2)
    assert live2["focus"] is None, "crop after an edit did not clear its focus"


@check
def action_replay_is_resolution_independent():
    a = app()
    crops = [[0.0, 0.0, 0.5, 1.0]]                      # left half
    live = {"brightness": 1.4}
    for (w, h) in ((100, 100), (40, 40)):
        src = Image.new("RGB", (w, h), (100, 100, 100))
        out = a._apply_action_to_image(src, crops, live)
        assert out.size == (w // 2, h), f"crop not scaled for {w}x{h}: {out.size}"
        from PIL import ImageStat
        # brightness 1.4 lifts the gray-100 crop; the linear Exposure runs at half
        # strength (factor 1.2 → ~120), so assert a clear lift over the original 100.
        assert ImageStat.Stat(out).mean[0] > 110, "replayed brightness missing"
    # plain crop (no edit) leaves the pixels alone but still crops.
    plain = a._apply_action_to_image(Image.new("RGB", (100, 100), (100, 100, 100)),
                                     crops, {})
    assert plain.size == (50, 100), "crop-only replay wrong size"


@check
def action_unique_names():
    a = app()
    a.user_actions = [{"name": "Macro", "steps": []}]
    assert a._unique_action_name("Macro") == "Macro 2"
    assert a._unique_action_name("Other") == "Other"


# ---- resize: target maths + quality passes ---------------------------------

@check
def resize_target_px_and_percent():
    a = app()
    a._resize_mode = "px"
    a._rv = 1000                                       # long side -> 1000
    assert a._resize_target_for(2000, 1000) == (1000, 500), "px long-side maths wrong"
    a._resize_mode = "pct"
    a._rv = 50
    assert a._resize_target_for(2000, 1000) == (1000, 500), "percent maths wrong"
    a._rv = None
    assert a._resize_target_for(2000, 1000) is None, "blank value not None"


@check
def resize_pixels_size_and_quality():
    a = app()
    # Vertical stripes: real edges survive the downscale, so the sharp/soft
    # passes actually bite (a smooth ramp has no local contrast to sharpen).
    src = Image.new("RGB", (100, 50))
    px = src.load()
    for x in range(100):
        c = 80 if (x // 4) % 2 == 0 else 176
        for y in range(50):
            px[x, y] = (c, c, c)
    a._resize_quality = "normal"
    normal = a._resize_pixels(src, (50, 25))
    a._resize_quality = "sharp"
    sharp = a._resize_pixels(src, (50, 25))
    a._resize_quality = "soft"
    soft = a._resize_pixels(src, (50, 25))
    assert normal.size == sharp.size == soft.size == (50, 25), "resize target size wrong"
    assert normal.tobytes() != sharp.tobytes(), "sharp pass identical to normal"
    assert normal.tobytes() != soft.tobytes(), "soft pass identical to normal"


# ---- crop: pure geometry / formatting helpers ------------------------------

@check
def crop_rotate_keeps_size():
    src = Image.new("RGB", (60, 40), (10, 20, 30))
    assert FakeApp._rotate_keep_size(src, 0).size == (60, 40), "rotate 0 changed size"
    assert FakeApp._rotate_keep_size(src, 12).size == (60, 40), "rotate kept-size broke"


@check
def crop_ratio_text_and_num():
    a = app()
    assert a._ratio_text(4, 2) == "2:1", "ratio not reduced"
    assert a._ratio_text(1920, 1080) == "16:9", "16:9 not detected"
    assert a._num(3.0) == "3", "whole number kept a decimal"


# ---- save: metadata rules + naming -----------------------------------------

@check
def save_export_meta_forces_orientation_and_keeps_icc():
    a = app()
    im = Image.new("RGB", (8, 8))
    ex = im.getexif()
    ex[0x0112] = 6                                     # a rotated orientation tag
    im.info["icc_profile"] = b"ICCPROFILEBYTES"
    a.current_pil = im
    extra = a._export_meta()
    assert extra["icc_profile"] == b"ICCPROFILEBYTES", "ICC profile not carried"
    parsed = Image.Exif()
    parsed.load(extra["exif"])
    assert parsed[0x0112] == 1, "orientation not forced to 1 (double-rotate risk)"


@check
def save_basename_appends_edited():
    a = app()
    a.files = ["Photo.JPG"]
    a.index = 0
    assert a._save_basename() == "Photo_edited", "save basename rule wrong"


def main():
    passed = failed = 0
    for fn in CHECKS:
        try:
            fn()
        except Exception as e:                          # noqa: BLE001
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
