"""Selective focus blur for Manoni (Fotor-style depth of field): a draggable
circle stays sharp while everything outside it is Gaussian-blurred.

Unlike crop / heal (destructive bakes into current_pil), this is a LIVE,
non-destructive effect — exactly like the vignette. The circle is stored in
SOURCE-image pixels (so it stays glued to the photo through zoom + pan) and the
whole thing rides in `self.focus`; the imaging module applies it every render
(cheap on the small preview, exact on the full-res save). One drag = one undo
step, shared with the slider-edit undo machinery.

Mixin on the Manoni window — every method uses the shared `self`, so behaviour
is identical to when it lived directly on the class.
"""

import math
import tkinter as tk

from ..config import BAR, ACCENT, FG, FG_DIM, EDIT_PANEL_W, EDIT_PAD
from ..widgets import Slider, Tooltip
from ..i18n import t


class FocusMixin:
    # --- Focus blur (col 3 panel + interactive circle on the preview) --------

    FOCUS_HANDLE = 6     # half-size of the resize handle square, in screen px
    FOCUS_MIN_R  = 16    # smallest focus radius, in source px

    def _build_focus_section(self, parent):
        "Focus-blur panel: a hint, the blur + feather sliders, and a remove link."
        f = tk.Frame(parent, bg=BAR)
        wrap = self._edit_dpi_w(EDIT_PANEL_W - 2 * EDIT_PAD)
        tk.Label(f, text=t("გადაათრიე წრე ფოკუსისთვის; კიდე ზომას ცვლის. "
                           "შიგნით მკვეთრია, გარეთ — ბლური."),
                 bg=BAR, fg=FG_DIM, font=("Segoe UI", 8), justify="left",
                 anchor="w", wraplength=wrap).pack(fill="x", padx=EDIT_PAD,
                                                   pady=(10, 6))

        # Blur strength and edge softness. Absolute magnitudes (neutral = the low
        # end), so the accent fill reads as a gauge — like the heal sliders. The
        # press/release hooks make a whole drag one undo step.
        self.s_focus_blur = Slider(f, t("ბლურის სიძლიერე"), self._set_focus_blur,
                                   lo=0, hi=100, neutral=0,
                                   on_press=self._edit_gesture_start,
                                   on_release=self._edit_gesture_end)
        self.s_focus_blur.pack(fill="x", padx=EDIT_PAD, pady=2)

        self.s_focus_feather = Slider(f, t("გადასვლის სიფაფუკე"),
                                      self._set_focus_feather,
                                      lo=0, hi=100, neutral=0,
                                      on_press=self._edit_gesture_start,
                                      on_release=self._edit_gesture_end)
        self.s_focus_feather.pack(fill="x", padx=EDIT_PAD, pady=2)

        remove = tk.Label(f, text=t("ბლურის მოშორება"), bg=BAR, fg=FG_DIM,
                          cursor="hand2", anchor="w", font=("Segoe UI", 9))
        remove.bind("<Enter>", lambda e: remove.configure(fg=FG))
        remove.bind("<Leave>", lambda e: remove.configure(fg=FG_DIM))
        remove.bind("<Button-1>", lambda e: self._remove_focus())
        remove.pack(fill="x", padx=EDIT_PAD, pady=(14, 6))
        remove._tip = Tooltip(remove, t("ფოკუსის ბლურის გამორთვა"))
        return f

    # --- State + entry ------------------------------------------------------

    def _default_focus(self):
        "A centred circle with a visible blur, so opening the tool shows the effect."
        iw, ih = self.current_pil.size
        return {"cx": iw / 2.0, "cy": ih / 2.0, "r": min(iw, ih) * 0.30,
                "blur": 0.6, "feather": 0.4}

    def _enter_focus(self):
        "Open the focus tool: place a default circle, fit the photo, show the ring."
        if self.current_pil is None:
            self._render_preview()
            return
        if self.focus is None:
            self.focus = self._default_focus()
            self._edits_saved = False
        self._sync_focus_controls()
        self.preview.configure(cursor="crosshair")
        self.fit_view()          # fit so the whole photo is visible to place it

    def _focus_active(self):
        "True when the focus tool is open with a live circle (drives overlay + clicks)."
        return (self.panel_open and self.active_section == "focus"
                and self.current_pil is not None and self.focus is not None)

    def _sync_focus_controls(self):
        "Set the blur / feather sliders from self.focus (no-op before they exist)."
        if not hasattr(self, "s_focus_blur"):
            return
        fb = self.focus or {}
        self.s_focus_blur.set(round(fb.get("blur", 0.0) * 100))
        self.s_focus_feather.set(round(fb.get("feather", 0.4) * 100))

    # --- Sliders ------------------------------------------------------------

    def _set_focus_blur(self, v):
        "Slider: blur strength (0 = off, 100 = max background blur)."
        if self.focus is None:
            return
        self.focus = {**self.focus, "blur": max(0.0, min(1.0, int(v) / 100.0))}
        self._edits_saved = False
        self._render_preview()

    def _set_focus_feather(self, v):
        "Slider: how soft the sharp→blurred transition is (0 = crisp edge)."
        if self.focus is None:
            return
        self.focus = {**self.focus, "feather": max(0.0, min(1.0, int(v) / 100.0))}
        self._edits_saved = False
        self._render_preview()

    def _clear_focus_for_geometry(self):
        "Drop the focus circle when the image geometry changes (rotate / crop):"
        " its source-px centre no longer maps to the new pixels. No undo entry —"
        " it rides along with the rotate/crop action that called it."
        if self.focus is None:
            return
        self.focus = None
        self._focus_cache.clear()
        self._sync_focus_controls()

    def _remove_focus(self):
        "Turn the focus blur off entirely, as one undoable step."
        if self.focus is None:
            return
        before = self._edit_state()
        self.focus = None
        self._sync_focus_controls()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    # --- Circle geometry + mouse interaction --------------------------------

    def _focus_center_screen(self):
        "The circle's centre (screen x, y) and radius (screen px) for the overlay."
        cxs, cys = self._src_to_scr(self.focus["cx"], self.focus["cy"])
        rs = self.focus["r"] * (self._disp[0] or 1.0)
        return cxs, cys, rs

    def _focus_hit(self, x, y):
        "What is under screen (x, y): 'resize' (the ring), 'move' (inside), or None."
        cxs, cys, rs = self._focus_center_screen()
        d = math.hypot(x - cxs, y - cys)
        if abs(d - rs) <= self.FOCUS_HANDLE + 4:
            return "resize"
        if d < rs:
            return "move"
        return None

    def _focus_press(self, event):
        "Begin a drag: grab the ring (resize) or the inside (move). One undo step."
        if not self._focus_active():
            return
        hit = self._focus_hit(event.x, event.y)
        if hit is None:
            return "break"
        self._edit_gesture_start()       # snapshot so the whole drag is one undo
        sx, sy = self._scr_to_src(event.x, event.y)
        if hit == "move":
            self._focus_drag = ("move", sx, sy, self.focus["cx"], self.focus["cy"])
        else:
            self._focus_drag = ("resize", None, None, None, None)
        return "break"

    def _focus_move(self, event):
        "Drag in progress: move the centre or resize the radius, then repaint."
        if self._focus_drag is None:
            return
        iw, ih = self.current_pil.size
        sx, sy = self._scr_to_src(event.x, event.y)
        if self._focus_drag[0] == "move":
            _, psx, psy, ocx, ocy = self._focus_drag
            ncx = min(max(0.0, ocx + (sx - psx)), float(iw))
            ncy = min(max(0.0, ocy + (sy - psy)), float(ih))
            self.focus = {**self.focus, "cx": ncx, "cy": ncy}
        else:
            r = math.hypot(sx - self.focus["cx"], sy - self.focus["cy"])
            r = max(self.FOCUS_MIN_R, min(r, float(max(iw, ih))))
            self.focus = {**self.focus, "r": r}
        self._edits_saved = False
        self._render_preview()
        return "break"

    def _focus_release(self, event):
        "End the drag: record one undo entry if the circle actually changed."
        if self._focus_drag is None:
            return
        self._focus_drag = None
        self._edit_gesture_end()
        return "break"

    def _focus_hover(self, event):
        "Show the right cursor over the ring (resize) / inside (move) while idle."
        if not self._focus_active() or self._focus_drag is not None:
            return
        hit = self._focus_hit(event.x, event.y)
        cur = {"resize": "sb_h_double_arrow", "move": "fleur"}.get(hit, "crosshair")
        self.preview.configure(cursor=cur)

    def _draw_focus_overlay(self):
        "Draw the focus circle: the falloff ring (dashed), the edge, centre + handle."
        c = self.preview
        cxs, cys, rs = self._focus_center_screen()
        # Outer dashed ring: roughly where the blur reaches full strength.
        feather = self.focus.get("feather", 0.4)
        ro = rs * (1.0 + feather)
        c.create_oval(cxs - ro, cys - ro, cxs + ro, cys + ro,
                      outline="#ffffff", dash=(4, 3), width=1)
        # The sharp-area edge.
        c.create_oval(cxs - rs, cys - rs, cxs + rs, cys + rs,
                      outline=ACCENT, width=2)
        c.create_line(cxs - 6, cys, cxs + 6, cys, fill=ACCENT)
        c.create_line(cxs, cys - 6, cxs, cys + 6, fill=ACCENT)
        # East resize handle.
        r = self.FOCUS_HANDLE
        c.create_rectangle(cxs + rs - r, cys - r, cxs + rs + r, cys + r,
                           fill=ACCENT, outline="#0b0b0b")
