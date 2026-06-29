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

from ..config import (ACCENT, BAR, FG, FG_DIM, HOVER,
                      EDIT_PAD, ON_ACCENT, ACCENT_HOVER, CHIP_BG)
from ..widgets import Slider, Tooltip
from ..i18n import t


# The black "Cancel/Reset" button, matching the crop panel's.
DARK_BTN = "#141414"


class PerspectiveMixin:
    # --- Panel --------------------------------------------------------------

    def _build_perspective_section(self, parent):
        "Perspective panel: vertical + horizontal keystone sliders, then Apply."
        f = tk.Frame(parent, bg=BAR)

        intro = tk.Label(
            f, text=t("Straighten converging verticals or horizontals "
                      "(buildings shot from below / to the side)."),
            bg=BAR, fg=FG_DIM, font=("Segoe UI", 8), justify="left", anchor="w",
            wraplength=self._edit_dpi_w(190))
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
        row = tk.Frame(parent, bg=BAR)
        row.pack(fill="x", padx=EDIT_PAD, pady=(12, 4))
        img = self.icon(icon_name, size=12)
        if img is not None:
            tk.Label(row, image=img, bg=BAR).pack(side="left", padx=(0, 6))
        tk.Label(row, text=text, bg=BAR, fg=FG_DIM, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(side="left")

    def _persp_slider(self, parent, label, attr, tip):
        "A −100…+100 keystone slider (0 = none) with its own reset button."
        row = tk.Frame(parent, bg=BAR)
        row.pack(fill="x", padx=EDIT_PAD, pady=2)
        s = Slider(row, label, lambda v, a=attr: self._on_persp(a, v),
                   lo=-100, hi=100, neutral=0)
        s.pack(side="left", fill="x", expand=True)
        s._tip = Tooltip(s.canvas, tip)
        self._persp_reset_btn(row, attr).pack(side="right", padx=(6, 0))
        return s

    def _persp_reset_btn(self, parent, attr):
        "A small reset icon that returns one keystone slider to 0."
        img = self.icon("rotate-ccw", size=14)
        if img is not None:
            b = tk.Label(parent, image=img, bg=BAR, cursor="hand2")
        else:
            b = tk.Label(parent, text="↺", bg=BAR, fg=FG_DIM, cursor="hand2",
                         font=("Segoe UI", 11))
        b.bind("<Enter>", lambda e: b.configure(bg=HOVER))
        b.bind("<Leave>", lambda e: b.configure(bg=BAR))
        b.bind("<Button-1>", lambda e, a=attr: self._reset_persp_one(a))
        b._tip = Tooltip(b, t("Reset this slider"))
        return b

    def _build_perspective_actions(self, parent):
        "Apply (accent) + a black Reset button, matching the crop panel."
        apply_btn = tk.Frame(parent, bg=ACCENT, cursor="hand2")
        apply_btn.pack(fill="x", padx=EDIT_PAD, pady=(16, 0))
        atx = tk.Label(apply_btn, text=t("Apply perspective"), bg=ACCENT,
                       fg=ON_ACCENT, font=("Segoe UI", 10, "bold"))
        atx.pack(expand=True, pady=10)
        for w in (apply_btn, atx):
            w.bind("<Button-1>", lambda e: self.apply_perspective_commit())
            w.bind("<Enter>", lambda e: [x.configure(bg=ACCENT_HOVER)
                                         for x in (apply_btn, atx)])
            w.bind("<Leave>", lambda e: [x.configure(bg=ACCENT)
                                         for x in (apply_btn, atx)])

        reset = tk.Frame(parent, bg=DARK_BTN, cursor="hand2",
                         highlightbackground="#2e2e2e", highlightthickness=1)
        reset.pack(fill="x", padx=EDIT_PAD, pady=(8, 10))
        rinner = tk.Frame(reset, bg=DARK_BTN)
        rinner.pack(pady=8)
        ximg = self.icon("rotate-ccw", size=13)
        if ximg is not None:
            tk.Label(rinner, image=ximg, bg=DARK_BTN).pack(side="left", padx=(0, 6))
        rtx = tk.Label(rinner, text=t("Reset"), bg=DARK_BTN, fg=FG_DIM,
                       font=("Segoe UI", 9))
        rtx.pack(side="left")
        rparts = [reset, rinner] + list(rinner.winfo_children())
        for w in rparts:
            w.bind("<Button-1>", lambda e: self._reset_perspective(render=True))
            w.bind("<Enter>", lambda e: [p.configure(bg="#0d0d0d") for p in rparts])
            w.bind("<Leave>", lambda e: [p.configure(bg=DARK_BTN) for p in rparts])
        reset._tip = Tooltip(reset, t("Reset both sliders to zero"))

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
