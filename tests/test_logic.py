"""Logic tests for the non-imaging (auto) items: filters, actions, resize, crop,
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
from manoni_app.ui.perspective import PerspectiveMixin  # noqa: E402


class FakeApp(FiltersMixin, ActionsMixin, ResizeMixin, CropMixin, SaveMixin):
    """The real mixins with just the plain state their PURE methods read. Nothing
    here touches Tk — the interactive methods are simply never called."""

    SLIDER_NEUTRAL = {"bw": 0.0, "sepia": 0.0, "grain": 0.0, "denoise": 0.0,
                      "focus": None, "auto_mode": None, "texts": []}

    def __init__(self):
        self.user_filters = []
        self.filter_groups = []
        self._builtin_collapsed = {}
        self._last_filter = None
        self.user_actions = []
        self.current_pil = None
        self.files = []
        self.index = 0
        self.folder = ""
        # resize state
        self._resize_mode = "dim"
        self._resize_lock = True
        self._resize_quality = "normal"
        self._resize_strength = {"soft": "medium", "sharp": "medium"}
        self._pct = None                      # what _resize_pct() returns
        self._wh = None                       # what _resize_wh() returns
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

    def _resize_pct(self):
        return self._pct

    def _resize_wh(self):
        return self._wh


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
def builtin_groups_standard_and_bw():
    a = app()
    # Both code-defined sets are always shown, in order, even with no user filters.
    ids = [g["id"] for g in a._strip_groups()]
    assert ids[:2] == [a.GROUP_STANDARD, a.GROUP_BW], "built-in sets missing / misordered"
    std, bw = a._strip_groups()[0], a._strip_groups()[1]
    assert len(std["items"]) == len(a.BUILTIN_FILTERS)
    assert len(bw["items"]) == len(a.BW_FILTERS) and bw["items"], "B&W set empty"
    # Every B&W look is a full desaturate — that is what makes it the B&W set.
    assert all(v.get("bw") == 1.0 for _, v in a.BW_FILTERS), "a B&W look is not mono"
    # _builtin_items resolves the tuples; a user group id resolves to None.
    assert a._builtin_items(a.GROUP_BW) is a.BW_FILTERS
    assert a._builtin_items("My filters") is None
    # The B&W group id is reserved, so a user can't shadow it.
    assert a._unique_group_name("Black & white") == "Black & white 2"


@check
def builtin_collapse_roundtrips_per_group():
    a = app()
    a._save_filters = lambda: None          # never touch the real store on disk
    a._set_group_collapsed(a.GROUP_BW, True)
    assert a._group_collapsed(a.GROUP_BW) and not a._group_collapsed(a.GROUP_STANDARD)
    # A legacy store with the old bool folds only Standard (migration path).
    a._builtin_collapsed = {a.GROUP_STANDARD: True}
    assert a._group_collapsed(a.GROUP_STANDARD) and not a._group_collapsed(a.GROUP_BW)


# ---- the "Last" filter (session-only slot) ---------------------------------

@check
def last_filter_captured_on_meaningful_save():
    a = app()
    a._state["brightness"] = 1.5              # a real slider adjustment
    a._capture_last_filter()
    assert a._last_filter is not None, "meaningful save did not fill the slot"
    assert a._last_filter["values"]["brightness"] == 1.5, "wrong values captured"


@check
def last_filter_kept_on_neutral_save():
    a = app()
    a._last_filter = {"values": {"brightness": 1.5}}   # an earlier meaningful save
    # A geometry-only save: every slider is neutral (_state is all-neutral here).
    a._capture_last_filter()
    assert a._last_filter["values"] == {"brightness": 1.5}, \
        "neutral save clobbered the previous slot"


@check
def last_filter_updates_on_next_meaningful_save():
    a = app()
    a._last_filter = {"values": {"brightness": 1.5}}
    a._state["contrast"] = 1.3                # a new, different adjustment
    a._capture_last_filter()
    assert a._last_filter["values"]["contrast"] == 1.3, "slot not updated"
    assert a._last_filter["values"]["brightness"] == 1.0, "stale value carried over"


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
def resize_target_batch_dim_and_percent():
    a = app()
    # percent → scale each image proportionally
    a._resize_mode = "pct"
    a._pct = 50
    assert a._resize_target_for(2000, 1000) == (1000, 500), "percent maths wrong"
    # dimensions, locked → fit INSIDE the W×H box, keeping aspect
    a._resize_mode = "dim"
    a._resize_lock = True
    a._wh = (1000, 1000)
    assert a._resize_target_for(2000, 1000) == (1000, 500), "locked fit-box maths wrong"
    # dimensions, unlocked → the exact box (may distort)
    a._resize_lock = False
    assert a._resize_target_for(2000, 1000) == (1000, 1000), "unlocked exact maths wrong"
    # blank value → None
    a._resize_mode = "pct"
    a._pct = None
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


@check
def resize_batch_gather_and_dest():
    import tempfile
    import shutil
    a = app()
    root = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(root, "sub", "deep"))
        os.makedirs(os.path.join(root, "_out"))
        os.makedirs(os.path.join(root, "sub", "resized"))
        for p in ("a.jpg", "b.PNG", "c.txt", "sub/d.jpeg",
                  "sub/deep/e.webp", "_out/old.jpg", "sub/resized/x.jpg"):
            open(os.path.join(root, *p.split("/")), "w").close()

        # Top level only skips subfolders and non-images.
        top = sorted(f for _, f in a._gather_batch_images(root, False))
        assert top == ["a.jpg", "b.PNG"], f"top-level gather wrong: {top}"

        # Recurse + skip the flat/mirror output dir → its copies aren't re-read
        # (other folders, e.g. sub/resized, are still ordinary images here).
        rec = sorted(f for _, f in a._gather_batch_images(
            root, True, skip_dir=os.path.join(root, "_out")))
        assert rec == ["a.jpg", "b.PNG", "d.jpeg", "e.webp", "x.jpg"], \
            f"skip_dir wrong: {rec}"

        # Recurse + skip the in-place sub-folder name → same, but _out kept.
        rn = sorted(f for _, f in a._gather_batch_images(
            root, True, skip_name="resized"))
        assert rn == ["a.jpg", "b.PNG", "d.jpeg", "e.webp", "old.jpg"], \
            f"skip_name wrong: {rn}"

        # Destination directory per output mode.
        sd = os.path.join(root, "sub", "deep")
        flat = {"out_mode": "flat", "out_dir": os.path.join(root, "o"),
                "src": root, "sub_name": "resized"}
        mirror = dict(flat, out_mode="mirror")
        inplace = dict(flat, out_mode="inplace")
        assert a._batch_dest_dir(flat, sd) == os.path.join(root, "o")
        assert a._batch_dest_dir(mirror, sd) == os.path.join(root, "o", "sub", "deep")
        assert a._batch_dest_dir(mirror, root) == os.path.join(root, "o")
        assert a._batch_dest_dir(inplace, sd) == os.path.join(sd, "resized")
    finally:
        shutil.rmtree(root, ignore_errors=True)


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


# ---- perspective: commit bakes pixels + resets dependent geometry ----------

class PerspApp(PerspectiveMixin):
    """The real perspective mixin with only the plain state apply_perspective_commit
    reads. Every Tk-touching collaborator it calls is stubbed to a no-op, so the
    genuine commit LOGIC (warp the pixels, reset crop / clone, zero the sliders,
    mark unsaved) runs without a Tk root."""

    def __init__(self, img):
        self.current_pil = img
        self._before_pil = img.copy()
        self._before_base_key = "k"
        self.persp_v = self.persp_h = 0.0
        self.clone_src = (1, 2)
        self.clone_offset = (3, 4)
        self.crop_rect = [5.0, 5.0, 9.0, 9.0]              # a non-full stale box
        self.crop_ratio = (16, 9)
        self._crop_btn_active = "16:9"
        self._edits_saved = True
        self.fit_mode = False
        self.pan_x = self.pan_y = 7.0
        self._view_key = "stale"
        self.files = ["Photo.jpg"]
        self.index = 0
        self.folder = ""
        self._toasts = []

    # Tk-touching collaborators → no-ops (never exercised headless).
    def toast(self, msg): self._toasts.append(msg)
    def _clear_focus_for_geometry(self): pass
    def _clear_text_for_geometry(self): pass
    def _clear_logo_for_geometry(self): pass
    def _restyle_crop_chips(self): pass
    def _render_preview(self): pass
    def _update_info(self, *a): pass
    def _refresh_filter_strip(self): pass
    # Geometry-undo hooks: the real commit records one undo entry via these
    # (NavMixin). The snapshot's contents don't affect the commit logic under
    # test, so both are stubbed out.
    def _geometry_snapshot(self): return {}
    def _record_geometry(self, before): pass


@check
def perspective_commit_noop_when_flat():
    src = Image.new("RGB", (40, 30), (120, 120, 120))
    a = PerspApp(src)
    a.apply_perspective_commit()                            # both sliders at 0
    assert a.current_pil is src, "commit warped the pixels with no keystone set"
    assert not getattr(a, "_perspd", False), "flat commit set the perspective flag"
    assert a._toasts and "slider" in a._toasts[-1].lower(), "no 'move a slider' hint"


@check
def perspective_commit_bakes_and_resets():
    from manoni_app import imaging
    src = _quad_image(60, 40)
    a = PerspApp(src)
    before = src.copy()
    a.persp_v, a.persp_h = 40.0, -20.0                      # sliders read −100..100
    a.apply_perspective_commit()
    # pixels are baked (warped) but the frame size is preserved.
    assert a.current_pil.size == (60, 40), "commit changed the image size"
    assert a.current_pil.tobytes() != before.tobytes(), "commit did not warp the pixels"
    # the committed pixels equal a direct warp at the /100 amounts.
    ref = imaging.apply_perspective(before, 0.40, -0.20)
    assert a.current_pil.tobytes() == ref.tobytes(), "commit != apply_perspective(v/100)"
    # the compare 'before' is warped in lockstep so the A/B stays aligned.
    assert a._before_pil.tobytes() != before.tobytes(), "before image not kept aligned"
    assert a._before_base_key is None, "before cache key not invalidated"
    # dependent geometry is reset: crop back to the full NEW frame, ratio cleared.
    assert a.crop_rect == [0.0, 0.0, 60.0, 40.0], f"crop not reset to full: {a.crop_rect}"
    assert a.crop_ratio is None and a._crop_btn_active is None, "crop ratio/active not cleared"
    assert a.clone_src is None and a.clone_offset is None, "clone anchor not cleared"
    # sliders zeroed (warp now baked in), and it is marked dirty + refit.
    assert a.persp_v == 0.0 and a.persp_h == 0.0, "sliders not zeroed after commit"
    assert a._perspd is True, "perspective flag not set"
    assert a._edits_saved is False, "commit left edits marked saved"
    assert a.fit_mode is True and a.pan_x == 0.0 and a.pan_y == 0.0, "view not refit"
    assert a._view_key is None, "cached view not dropped after pixels changed"


def _quad_image(w, h):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (200 if x < w // 2 else 60, 200 if y < h // 2 else 60, 120)
    return img


# ---- overwrite: in-place save (Ctrl+S) -------------------------------------

@check
def overwrite_fmt_maps_known_extensions():
    a = app()
    assert a._overwrite_fmt("Photo.JPG") == "JPEG", "jpg not mapped to JPEG"
    assert a._overwrite_fmt("a.jpeg") == "JPEG", "jpeg not mapped to JPEG"
    assert a._overwrite_fmt("a.PNG") == "PNG", "png not mapped to PNG"
    assert a._overwrite_fmt("a.webp") == "WEBP", "webp not mapped to WEBP"
    assert a._overwrite_fmt("a.tif") is None, "unhandled .tif not rejected"
    assert a._overwrite_fmt("noext") is None, "extensionless not rejected"


@check
def overwrite_writes_in_place_never_a_copy():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "photo.jpg")
        Image.new("RGB", (16, 16), (200, 100, 50)).save(target, "JPEG", quality=95)
        before = open(target, "rb").read()

        a = app()
        a.folder, a.files, a.index = d, ["photo.jpg"], 0
        a.current_pil = Image.open(target)
        a.current_pil.load()                       # closes the fp (exclusive) → replace ok
        # Collaborators that live on the Tk / viewer mixins → harmless stubs.
        a._apply_edits = lambda img: Image.new("RGB", img.size, (10, 20, 30))
        a._capture_last_filter = lambda: None
        a._refresh_saved_indicator = lambda: None

        assert a._write_overwrite(target) is True, "overwrite reported failure"
        # Wrote back onto the SAME file — no numbered copy beside it (unique_path
        # is deliberately skipped for an in-place save).
        assert os.listdir(d) == ["photo.jpg"], \
            f"overwrite left extra files: {os.listdir(d)}"
        assert open(target, "rb").read() != before, "overwrite did not change the file"
        assert Image.open(target).format == "JPEG", "overwrite changed the format"
        assert a._edits_saved is True, "overwrite left edits marked unsaved"


@check
def overwrite_refuses_unhandled_type():
    a = app()
    a.folder, a.files, a.index = ".", ["photo.tif"], 0
    a.current_pil = Image.new("RGB", (4, 4))
    # No handler for .tif → refuse before touching disk (returns False, no write).
    assert a._write_overwrite("photo.tif") is False, "tif overwrite not refused"


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
