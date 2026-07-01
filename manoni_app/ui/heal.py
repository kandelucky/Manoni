"""Retouch tool for Manoni — two modes that share one brush, paint loop and
undo:

  • Auto heal (heal)  — paint over a blemish and it is cloned away from a
    clean neighbour, colour-matched (imaging.heal_region).
  • Clone (clone stamp)  — Alt+click a source, then paint an exact copy of it
    with a locked offset (imaging.clone_region), like Photoshop.

Unlike the sliders — global, non-destructive, rebuilt every render — a retouch
is a LOCAL pixel edit baked straight into current_pil, the same way crop bakes
its result. Each stroke is one undo step.

Mixin on the Manoni window — every method uses the shared `self`, so behaviour
is identical to when it lived directly on the class.
"""

import tkinter as tk

import tintkit

from ..config import BAR, ACCENT, FG_DIM, EDIT_PANEL_W, EDIT_PAD
from .. import imaging
from ..i18n import t


class HealMixin:
    # --- Retouch (col 3 panel + paint-on-preview) ---------------------------

    HEAL_MIN        = 4      # smallest brush radius, in source px
    HEAL_MAX        = 160    # largest brush radius, in source px
    HEAL_WHEEL_STEP = 4      # px per wheel notch / [ ] keypress
    CLONE_SRC       = "#ffcc44"   # colour of the clone source-ring overlay
    HEAL_DEF_RADIUS   = 24   # brush size a per-slider reset returns to
    HEAL_DEF_STRENGTH = 100  # strength (%) a per-slider reset returns to
    HEAL_DEF_FEATHER  = 50   # edge softness (%) a per-slider reset returns to

    def _build_heal_section(self, parent):
        "Retouch panel: heal/clone mode, a hint, brush sliders, and the footer."
        f = tk.Frame(parent, bg=BAR)

        # Mode toggle: auto heal vs manual clone stamp — a segmented control
        # (the two modes are exclusive), matching the focus-tool shape toggle.
        self._heal_modes = ["auto", "clone"]
        self._heal_mode_tabs = tintkit.SegmentedTabs(
            f, self.theme, [t("Auto heal"), t("Clone")], selected=0, bg="bar",
            command=lambda i, _l: self._set_heal_mode(self._heal_modes[i]))
        self._heal_mode_tabs.pack(padx=EDIT_PAD, pady=(10, 2))

        self._heal_hint = tk.Label(f, text="", bg=BAR, fg=FG_DIM, anchor="w",
                                   font=("Segoe UI", 8), justify="left",
                                   wraplength=self._edit_dpi_w(
                                       EDIT_PANEL_W - 2 * EDIT_PAD))
        self._heal_hint.pack(fill="x", padx=EDIT_PAD, pady=(8, 6))

        # Clone-only options (aligned + mirror) — independent on/off toggles, so
        # checkboxes, not the exclusive segmented control. Shown only in clone
        # mode (packed / unpacked by _refresh_heal_mode).
        self._clone_opts = tk.Frame(f, bg=BAR)
        self._chk_aligned = tintkit.Checkbox(
            self._clone_opts, self.theme, t("Aligned"),
            state="on" if self.clone_aligned else "off", bg="bar",
            command=lambda st: self._set_clone_opt("aligned", st == "on"))
        self._chk_aligned.pack(anchor="w", padx=EDIT_PAD, pady=(2, 0))
        self._chk_flip = tintkit.Checkbox(
            self._clone_opts, self.theme, t("Mirror"),
            state="on" if self.clone_flip else "off", bg="bar",
            command=lambda st: self._set_clone_opt("flip", st == "on"))
        self._chk_flip.pack(anchor="w", padx=EDIT_PAD, pady=(2, 0))

        # Brush sliders. Each carries its title on its own strip (label + value
        # + reset icon) above a full-width track, so the label never sits on the
        # track. They are absolute magnitudes (neutral = the low end), so the
        # readout reads as a gauge. Changing a brush setting is not an image
        # edit, so unlike the tone sliders these carry no undo gesture.
        self.s_heal_size = self._heal_slider(
            f, t("Brush size"), self._set_heal_radius, "size",
            self.HEAL_MIN, self.HEAL_MAX, self.HEAL_MIN, self.heal_radius)
        self.s_heal_size.pack(fill="x", padx=EDIT_PAD, pady=(2, 6))
        self.s_heal_strength = self._heal_slider(
            f, t("Strength"), self._set_heal_strength, "strength",
            0, 100, 0, round(self.heal_opacity * 100))
        self.s_heal_strength.pack(fill="x", padx=EDIT_PAD, pady=(2, 6))
        self.s_heal_feather = self._heal_slider(
            f, t("Edge softness"), self._set_heal_feather, "feather",
            0, 100, 0, round(self.heal_feather * 100))
        self.s_heal_feather.pack(fill="x", padx=EDIT_PAD, pady=(2, 6))

        tk.Label(f, text=t("Ctrl+Z — undo the last action"), bg=BAR, fg=FG_DIM,
                 anchor="w", font=("Segoe UI", 8)).pack(fill="x", padx=EDIT_PAD,
                                                        pady=(12, 4))

        # Footer: Done closes the tool (the strokes are already baked into the
        # photo); Remove all lifts every retouch on this photo in one undo step.
        done = tintkit.Button(
            f, self.theme, t("Done"), role="primary", variant="filled",
            stretch=True, bg="bar", command=lambda: self.set_section("basic"))
        done.pack(fill="x", padx=EDIT_PAD, pady=(6, 0))
        remove = tintkit.Button(
            f, self.theme, t("Remove all"), role="neutral", variant="outline",
            icon="x", stretch=True, bg="bar", command=self._remove_all_heal)
        remove.pack(fill="x", padx=EDIT_PAD, pady=(8, 10))
        tintkit.HoverTip(remove.canvas, self.theme,
                         t("Remove every retouch on this photo"))

        self._refresh_heal_mode()
        return f

    def _heal_slider(self, parent, label, setter, which, lo, hi, neutral, value):
        "A brush TitledSlider (title strip + reset icon over a full-width track)."
        # Gauge sliders (grow from the low end): show the raw value, not the
        # signed delta — "24" reads clearer than "+20" for a brush size.
        return tintkit.TitledSlider(
            parent, self.theme, label, value=value, lo=lo, hi=hi, neutral=neutral,
            command=setter, bg="bar", reset_tip=t("Reset this slider"),
            value_fmt=lambda v, n: str(v),
            on_reset=lambda: self._reset_heal_slider(which))

    def _reset_heal_slider(self, which):
        "Return one brush slider to its default. Not an image edit, so no undo."
        if which == "size":
            self._set_heal_radius(self.HEAL_DEF_RADIUS)
            self.s_heal_size.set(self.HEAL_DEF_RADIUS)
        elif which == "strength":
            self._set_heal_strength(self.HEAL_DEF_STRENGTH)
            self.s_heal_strength.set(self.HEAL_DEF_STRENGTH)
        else:
            self._set_heal_feather(self.HEAL_DEF_FEATHER)
            self.s_heal_feather.set(self.HEAL_DEF_FEATHER)

    # --- Mode (heal vs clone) -----------------------------------------------

    def _set_clone_opt(self, key, on):
        "Set an aligned / mirror clone option from its checkbox, then repaint."
        if key == "aligned":
            self.clone_aligned = on
            if not on:
                self.clone_offset = None    # next stroke re-anchors to the source
        else:
            self.clone_flip = on
        self._render_preview()

    def _sync_clone_opts(self):
        "Sync the aligned / mirror checkboxes to the current bool state."
        if not hasattr(self, "_chk_aligned"):
            return
        self._chk_aligned.state = "on" if self.clone_aligned else "off"
        self._chk_aligned.repaint()
        self._chk_flip.state = "on" if self.clone_flip else "off"
        self._chk_flip.repaint()

    def _set_heal_mode(self, mode):
        "Switch retouch mode; clear any clone source so the next one is deliberate."
        self.heal_mode = mode
        self.clone_src = None
        self.clone_offset = None
        self._refresh_heal_mode()
        self._render_preview()

    def _refresh_heal_mode(self):
        "Sync the mode toggle, swap the hint, and show clone options in clone mode."
        if hasattr(self, "_heal_mode_tabs"):
            idx = (self._heal_modes.index(self.heal_mode)
                   if self.heal_mode in self._heal_modes else 0)
            if self._heal_mode_tabs.selected != idx:
                self._heal_mode_tabs.selected = idx
                self._heal_mode_tabs.repaint()
        if self.heal_mode == "clone":
            self._heal_hint.configure(
                text=t("Alt+click — pick a source; then paint an exact copy. The wheel or [ ] changes the brush size."))
            self._clone_opts.pack(fill="x", pady=(0, 6),
                                  before=self.s_heal_size.frame)
            self._sync_clone_opts()
        else:
            self._heal_hint.configure(
                text=t("Click or drag over a blemish — I erase it with a copy of nearby clean background. The wheel or [ ] changes the brush size."))
            self._clone_opts.pack_forget()

    def _enter_heal(self):
        "Open the retouch tool: show the brush cursor and repaint with its ring."
        if self.current_pil is None:
            self._render_preview()
            return
        self.preview.configure(cursor="crosshair")
        self._render_preview()

    def _heal_active(self):
        "True when the retouch tool is open with a photo loaded (drives the clicks)."
        return (self.panel_open and self.active_section == "heal"
                and self.current_pil is not None)

    # --- Brush sliders ------------------------------------------------------

    def _set_heal_radius(self, v):
        "Slider / wheel / key set the brush radius (source px); refresh the ring."
        self.heal_radius = max(self.HEAL_MIN, min(self.HEAL_MAX, int(v)))
        self._draw_heal_cursor()

    def _set_heal_strength(self, v):
        "Slider: blend strength (100 = solid clone, 0 = very weak / barely there)."
        self.heal_opacity = max(0.05, min(1.0, int(v) / 100.0))

    def _set_heal_feather(self, v):
        "Slider: how soft the patch edge is (0 = crisp, higher = more blurred)."
        self.heal_feather = max(0.0, min(1.0, int(v) / 100.0))

    def _heal_brush_key(self, direction):
        "[ and ] shrink / grow the brush while the retouch tool is open."
        if not self._heal_active():
            return
        self._set_heal_radius(self.heal_radius + direction * self.HEAL_WHEEL_STEP)
        self.s_heal_size.set(self.heal_radius)

    def _heal_wheel(self, event):
        "Wheel over the photo while retouching: resize the brush instead of zooming."
        step = self.HEAL_WHEEL_STEP if event.delta > 0 else -self.HEAL_WHEEL_STEP
        self._set_heal_radius(self.heal_radius + step)
        self.s_heal_size.set(self.heal_radius)
        self._heal_cursor = (event.x, event.y)
        self._draw_heal_cursor()
        return "break"

    # --- Clone source (Alt+click) -------------------------------------------

    def _clone_set_source(self, event):
        "Alt+click in clone mode: anchor the source the next stroke copies from."
        if not self._heal_active():
            return
        sx, sy = self._scr_to_src(event.x, event.y)
        iw, ih = self.current_pil.size
        if not (0 <= sx <= iw and 0 <= sy <= ih):
            return "break"
        self.clone_src = (sx, sy)
        self.clone_offset = None          # re-align on the next paint dab
        self._heal_cursor = (event.x, event.y)
        self._render_preview()
        self.toast(t("Source picked — now paint the copy"))
        return "break"

    # --- Painting -----------------------------------------------------------

    def _heal_press(self, event):
        "Begin a stroke: snapshot the image so the whole stroke is one undo step."
        if not self._heal_active():
            return
        if self.heal_mode == "clone":
            if self.clone_src is None:
                self.toast(t("First Alt+click a source"))
                return "break"
            if self.clone_offset is None or not self.clone_aligned:
                # Aligned: lock the offset once and keep it across strokes.
                # Non-aligned: re-anchor to the source at the start of each stroke.
                psx, psy = self._scr_to_src(event.x, event.y)
                self.clone_offset = (psx - self.clone_src[0],
                                     psy - self.clone_src[1])
        self._heal_before_img = self.current_pil.convert("RGB")  # always an RGB copy
        self._heal_dirty = None
        self._heal_last = None
        # Rebuild the view base fresh at the stroke's first dab, so a still-running
        # async render from before the stroke isn't reading the very buffer the
        # in-place dab patches are about to mutate.
        self._view_key = None
        self._heal_dab(event.x, event.y)
        return "break"

    def _heal_move(self, event):
        "Drag: lay down dabs spaced along the path so a swipe paints continuously."
        if not self._heal_active() or self._heal_before_img is None:
            return
        sx, sy = self._scr_to_src(event.x, event.y)
        if self._heal_last is not None:
            lx, ly = self._heal_last
            spacing = max(2.0, self.heal_radius * 0.5)
            if (sx - lx) ** 2 + (sy - ly) ** 2 < spacing * spacing:
                self._heal_cursor = (event.x, event.y)   # too close: just move ring
                self._draw_heal_cursor()
                return "break"
        self._heal_dab(event.x, event.y)
        return "break"

    def _heal_release(self, event):
        "End the stroke: record one undo entry covering everything it touched."
        if self._heal_before_img is None:
            return
        if self._heal_dirty is not None and self.files:
            box = tuple(self._heal_dirty)
            self._push_undo({"kind": "heal", "folder": self.folder,
                             "file": self.files[self.index], "box": box,
                             "before": self._heal_before_img.crop(box),
                             "after": self.current_pil.crop(box)})
        self._heal_before_img = None
        self._heal_dirty = None
        self._heal_last = None
        if self.heal_mode == "clone" and not self.clone_aligned:
            self.clone_offset = None      # non-aligned: each stroke restarts at source
        self._view_key = None             # one clean full-res rescale to settle seams
        self._render_preview()
        return "break"

    def _heal_dab(self, scrx, scry):
        "Apply one dab under screen (scrx, scry); grow the stroke's dirty box."
        sx, sy = self._scr_to_src(scrx, scry)
        iw, ih = self.current_pil.size
        if not (0 <= sx <= iw and 0 <= sy <= ih):
            return
        if self.current_pil.mode != "RGB":      # retouch works in RGB; bake mode once
            self.current_pil = self.current_pil.convert("RGB")
        if self.heal_mode == "clone":
            if self.clone_offset is None:
                return
            patched, box = imaging.clone_region(
                self.current_pil, sx, sy,
                sx - self.clone_offset[0], sy - self.clone_offset[1],
                self.heal_radius, feather=self.heal_feather,
                opacity=self.heal_opacity, flip=self.clone_flip)
        else:
            patched, box = imaging.heal_region(
                self.current_pil, sx, sy, self.heal_radius,
                feather=self.heal_feather, opacity=self.heal_opacity)
        if patched is None:
            return
        # Snapshot the un-healed pixels the first time a stroke touches this photo,
        # so the before/after compare can show the blemish in "before" (იყო).
        if self._before_pil is None:
            self._before_pil = self.current_pil.copy()
            self._before_base_key = None
        self.current_pil.paste(patched, box)
        self._healed = True
        self._edits_saved = False
        self._grow_dirty(box)
        self._heal_last = (sx, sy)
        self._heal_cursor = (scrx, scry)
        # Patch only the dabbed box into the cached scaled view; fall back to a
        # full re-render only if the cache can't be reused. This keeps a stroke
        # smooth on a big photo (the old full-viewport rescale per dab froze it).
        if not self._patch_view_base(box):
            self._view_key = None
        self._render_preview(inline=True)   # in-place patch → keep it off the worker

    def _grow_dirty(self, box):
        "Union `box` into the current stroke's dirty rectangle (for one undo crop)."
        if self._heal_dirty is None:
            self._heal_dirty = list(box)
        else:
            d = self._heal_dirty
            d[0] = min(d[0], box[0]); d[1] = min(d[1], box[1])
            d[2] = max(d[2], box[2]); d[3] = max(d[3], box[3])

    # --- Brush-ring cursor --------------------------------------------------

    def _heal_hover(self, event):
        "Move the brush ring with the mouse (no re-render — just the ring)."
        if not self._heal_active():
            return
        self.preview.configure(cursor="crosshair")
        self._heal_cursor = (event.x, event.y)
        self._draw_heal_cursor()

    def _draw_heal_cursor(self):
        "Draw the brush ring at the cursor (+ the clone source ring in clone mode)."
        c = self.preview
        c.delete("healcur")
        if not self._heal_active() or self._heal_cursor is None:
            return
        scale = self._disp[0] or 1.0
        x, y = self._heal_cursor
        r = self.heal_radius * scale
        c.create_oval(x - r, y - r, x + r, y + r, outline=ACCENT, width=1,
                      tags="healcur")
        c.create_line(x - 4, y, x + 4, y, fill=ACCENT, tags="healcur")
        c.create_line(x, y - 4, x, y + 4, fill=ACCENT, tags="healcur")
        # Clone mode: show where pixels are being sampled from.
        if self.heal_mode == "clone" and self.clone_src is not None:
            if self.clone_offset is not None:    # source tracks the cursor offset
                ssx, ssy = self._scr_to_src(x, y)
                px, py = self._src_to_scr(ssx - self.clone_offset[0],
                                          ssy - self.clone_offset[1])
            else:                                # not painting yet: the fixed anchor
                px, py = self._src_to_scr(*self.clone_src)
            c.create_oval(px - r, py - r, px + r, py + r, outline=self.CLONE_SRC,
                          width=1, dash=(3, 2), tags="healcur")
            c.create_line(px - 5, py, px + 5, py, fill=self.CLONE_SRC, tags="healcur")
            c.create_line(px, py - 5, px, py + 5, fill=self.CLONE_SRC, tags="healcur")

    # --- Undo / redo of a stroke --------------------------------------------

    def _remove_all_heal(self):
        "Lift every retouch on this photo in one undo step (restore the pre-heal pixels)."
        if not self._healed or self._before_pil is None or not self.files:
            self.toast(t("No retouches to remove"))
            return
        iw, ih = self.current_pil.size
        box = (0, 0, iw, ih)
        # before = the healed pixels a redo brings back; after = the un-healed
        # snapshot _before_pil has kept aligned through every crop / rotate.
        # Restoring it drops the retouches but keeps all other edits.
        before = self.current_pil.convert("RGB").crop(box)
        after = self._before_pil.convert("RGB").crop(box)
        self._push_undo({"kind": "heal", "folder": self.folder,
                         "file": self.files[self.index], "box": box,
                         "before": before, "after": after})
        self.current_pil = self._before_pil.copy()
        self._before_pil = None
        self._before_base_key = None
        self._healed = False
        self._edits_saved = False
        self._view_key = None
        self._render_preview()
        self.toast(t("Retouches removed"))

    def _apply_heal_patch(self, cmd, patch):
        "Paste a stored before/after crop back at its box. Same-image only."
        if cmd["folder"] != self.folder or not self.files \
                or self.files[self.index] != cmd["file"]:
            self.toast(t("Can't undo — a different image is open"))
            return False
        if self.current_pil.mode != "RGB":
            self.current_pil = self.current_pil.convert("RGB")
        self.current_pil.paste(patch, cmd["box"])
        self._healed = True
        self._edits_saved = False
        self._view_key = None
        self._render_preview()
        return True
