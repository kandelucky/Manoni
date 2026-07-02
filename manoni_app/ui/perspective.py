"""Perspective / keystone-correction tool for Manoni.

A geometry tool, like Crop / Resize / Straighten: two sliders (vertical and
horizontal keystone) warp the photo to straighten converging verticals or
horizontals. The preview is LIVE on the fitted view — the warp is applied to the
already-scaled view image, which matches the full-res commit because
`imaging.apply_perspective` is scale-free. Committing bakes the warp into
`current_pil` in memory (the original on disk is never touched; Save writes the
copy). Mixin on the Manoni window — every method uses the shared `self`.
"""

import os
import tkinter as tk

import tintkit

from ..config import EDIT_PAD
from ..i18n import t


class PerspectiveMixin:
    # --- Panel --------------------------------------------------------------

    def _build_perspective_section(self, parent):
        "Perspective panel: vertical + horizontal keystone sliders, then Apply."
        f = self._tw(tk.Frame(parent), bg="bar")

        intro = self._tw(tk.Label(
            f, text=t("Straighten converging verticals or horizontals "
                      "(buildings shot from below / to the side)."),
            font=("Segoe UI", 8), justify="left", anchor="w",
            wraplength=self._edit_dpi_w(190)), bg="bar", fg="fg_dim")
        intro.pack(fill="x", padx=EDIT_PAD, pady=(12, 6))

        self._persp_group_header(f, "move", t("Vertical"))
        self.s_persp_v = self._persp_slider(
            f, t("Vertical"), "persp_v",
            t("Tilt the top/bottom — fix verticals that lean in or out"))

        self._persp_group_header(f, "move", t("Horizontal"))
        self.s_persp_h = self._persp_slider(
            f, t("Horizontal"), "persp_h",
            t("Tilt the left/right — fix horizontals that lean in or out"))

        self._build_perspective_actions(f)
        return f

    def _persp_group_header(self, parent, icon_name, text):
        "A small icon + dim caption titling a slider in the perspective panel."
        row = self._tw(tk.Frame(parent), bg="bar")
        row.pack(fill="x", padx=EDIT_PAD, pady=(12, 4))
        if self.icon(icon_name, size=12) is not None:
            self._icon_label(row, icon_name, size=12, token="fg_dim",
                             bg="bar").pack(side="left", padx=(0, 6))
        self._tw(tk.Label(row, text=text, anchor="w",
                          font=("Segoe UI", 8, "bold")), bg="bar", fg="fg_dim").pack(side="left")

    def _persp_slider(self, parent, label, attr, tip):
        "A −100…+100 keystone TitledSlider (0 = none); reset icon sits in its strip."
        # Bidirectional, so the signed delta readout (+35 / −20) shows which way
        # it leans — TitledSlider's default. Reset zeroes just this slider.
        s = tintkit.TitledSlider(
            parent, self.theme, label, value=0, lo=-100, hi=100, neutral=0,
            command=lambda v, a=attr: self._on_persp(a, v), bg="bar",
            reset_tip=t("Reset this slider"),
            on_reset=lambda a=attr: self._reset_persp_one(a))
        s.pack(fill="x", padx=EDIT_PAD, pady=2)
        tintkit.HoverTip(s.canvas, self.theme, tip)
        return s

    def _build_perspective_actions(self, parent):
        "Apply (accent) + a subtle Reset button, matching the crop panel."
        apply_btn = tintkit.Button(
            parent, self.theme, t("Apply perspective"), role="primary",
            variant="filled", stretch=True, bg="bar",
            command=self.apply_perspective_commit)
        apply_btn.pack(fill="x", padx=EDIT_PAD, pady=(16, 0))

        reset = tintkit.Button(
            parent, self.theme, t("Remove effect"), role="neutral",
            variant="outline", icon="x", stretch=True, bg="bar",
            command=lambda: self._reset_perspective(render=True))
        reset.pack(fill="x", padx=EDIT_PAD, pady=(8, 10))
        tintkit.HoverTip(reset.canvas, self.theme, t("Reset both sliders to zero"))

    # --- Behaviour ----------------------------------------------------------

    def _enter_perspective(self):
        "Open the tool: fit the whole photo so the live warp is fully visible."
        self.preview.configure(cursor="")
        if self.current_pil is None:
            self._render_preview()
            return
        self.fit_view()          # fit + recenter + render

    def _on_persp(self, attr, val):
        "Live keystone: set the slider value, keep the photo fitted, re-render."
        if self.current_pil is None:
            return
        setattr(self, attr, float(val))
        # The warp preview is correct only with the whole photo fitted, so
        # perspective always works on the fitted view (zoom is paused).
        self.fit_mode = True
        self.pan_x = self.pan_y = 0.0
        self._render_preview()

    def _reset_persp_one(self, attr):
        "Return one keystone slider to 0 (live)."
        setattr(self, attr, 0.0)
        s = self.s_persp_v if attr == "persp_v" else self.s_persp_h
        try:
            s.set(0)
        except tk.TclError:
            pass
        self._on_persp(attr, 0.0)

    def _reset_perspective(self, render=False):
        "Clear both pending keystone sliders (on commit / cancel / photo switch)."
        self.persp_v = 0.0
        self.persp_h = 0.0
        for s in (getattr(self, "s_persp_v", None), getattr(self, "s_persp_h", None)):
            if s is not None:
                try:
                    s.set(0)
                except tk.TclError:
                    pass
        if render and self.current_pil is not None:
            self._render_preview()

    def apply_perspective_commit(self):
        "Bake the keystone warp into current_pil (in memory; written via Save)."
        if self.current_pil is None:
            return
        if not self.persp_v and not self.persp_h:
            self.toast(t("Move a slider first"))
            return
        v, h = self.persp_v / 100.0, self.persp_h / 100.0
        from .. import imaging
        self.current_pil = imaging.apply_perspective(self.current_pil, v, h)
        if self._before_pil is not None:   # keep the compare "before" aligned
            self._before_pil = imaging.apply_perspective(self._before_pil, v, h)
            self._before_base_key = None
        self._perspd = True
        self._clear_focus_for_geometry()    # source-px focus shape no longer maps
        self._clear_text_for_geometry()     # …and the source-px text position no longer maps
        self.clone_src = self.clone_offset = None   # clone anchor moved
        # The crop box referenced the old pixel positions — reset it to full.
        iw, ih = self.current_pil.size
        self.crop_rect = [0.0, 0.0, float(iw), float(ih)]
        self.crop_ratio = None
        self._crop_btn_active = None
        self._restyle_crop_chips()
        self._reset_perspective()           # zero the sliders (now baked in)
        self._edits_saved = False
        self.fit_mode = True
        self.pan_x = self.pan_y = 0.0
        self._view_key = None               # pixels changed → drop the cached view
        self._render_preview()
        self._update_info(os.path.join(self.folder, self.files[self.index]))
        self._refresh_filter_strip()        # the warped photo needs fresh thumbnails
        self.toast(t("Perspective applied  ·  Save to write it to a file"))
