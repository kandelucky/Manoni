"""Selective focus blur for Manoni (Fotor-style depth of field): a draggable
shape stays sharp while everything outside it is Gaussian-blurred. Two shapes
share one panel, undo and pipeline:

  • Circle  (circle) — a round in-focus area (portrait look).
  • Line  (line)   — a straight in-focus band that can be rotated (tilt-shift).

Unlike crop / heal (destructive bakes into current_pil), this is a LIVE,
non-destructive effect — exactly like the vignette. The shape is stored in
SOURCE-image pixels (so it stays glued to the photo through zoom + pan) and the
whole thing rides in `self.focus`; the imaging module applies it every render
(cheap on the small preview, exact on the full-res save). One drag = one undo
step, shared with the slider-edit undo machinery.

Mixin on the Manoni window — every method uses the shared `self`, so behaviour
is identical to when it lived directly on the class.
"""

import math
import tkinter as tk

import tintkit

from ..config import ACCENT, EDIT_PANEL_W, EDIT_PAD, ON_ACCENT
from ..i18n import t


class FocusMixin:
    # --- Focus blur (col 3 panel + interactive shape on the preview) ---------

    FOCUS_HANDLE   = 6     # half-size of a handle square, in screen px
    FOCUS_MIN_R    = 16    # smallest circle radius, in source px
    FOCUS_MIN_W    = 24    # smallest line band width, in source px
    FOCUS_ROT_DIST = 64    # rotation handle distance from centre, in screen px

    def _build_focus_section(self, parent):
        "Focus-blur panel: a shape toggle, a hint, blur + feather sliders, remove."
        f = self._tw(tk.Frame(parent), bg="bar")

        # Shape toggle: circle vs line (tilt-shift) — a segmented control.
        self._focus_shapes = ["circle", "line"]
        self._focus_shape_tabs = tintkit.SegmentedTabs(
            f, self.theme, [t("Circle"), t("Line")], selected=0, bg="bar",
            command=lambda i, _l: self._set_focus_shape(self._focus_shapes[i]))
        self._focus_shape_tabs.pack(padx=EDIT_PAD, pady=(10, 2))

        self._focus_hint = self._tw(tk.Label(f, text="", anchor="w",
                                    font=("Segoe UI", 8), justify="left",
                                    wraplength=self._edit_dpi_w(
                                        EDIT_PANEL_W - 2 * EDIT_PAD)),
                                    bg="bar", fg="fg_dim")
        self._focus_hint.pack(fill="x", padx=EDIT_PAD, pady=(8, 6))

        # Blur strength and edge softness, in the shared Foldout visual. Absolute
        # magnitudes (neutral = the low end), so the accent fill reads as a gauge
        # — like the heal sliders. Each slider carries its own reset button, so
        # one part can be zeroed without dropping the whole effect. The
        # press/release hooks make a drag one undo.
        blur = self._fold_group(f, "fc_blur", t("Blur"))
        self.s_focus_blur = self._focus_slider(
            blur, t("Blur strength"), self._set_focus_blur, "blur")
        self.s_focus_feather = self._focus_slider(
            blur, t("Transition softness"), self._set_focus_feather, "feather")

        # Done (close the tool, keep the live effect) + Remove (turn it off).
        done = tintkit.Button(
            f, self.theme, t("Done"), role="primary", variant="filled",
            stretch=True, bg="bar", command=self._focus_done)
        done.pack(fill="x", padx=EDIT_PAD, pady=(14, 0))

        remove = tintkit.Button(
            f, self.theme, t("Remove blur"), role="neutral", variant="outline",
            icon="x", stretch=True, bg="bar", command=self._remove_focus)
        remove.pack(fill="x", padx=EDIT_PAD, pady=(8, 10))
        tintkit.HoverTip(remove.canvas, self.theme, t("Turn the focus blur off"))
        return f

    def _focus_slider(self, parent, label, setter, which):
        "A focus TitledSlider (blur/feather): title strip + reset over a bare"
        " track. Lives in a Foldout body, whose own inset aligns it (padx=0)."
        # Gauge sliders (0→100), so show the raw value. The press/release hooks
        # batch a whole drag into one undo step; reset zeroes just this slider.
        s = tintkit.TitledSlider(
            parent, self.theme, label, value=0, lo=0, hi=100, neutral=0,
            command=setter, bg="bar", value_fmt=lambda v, n: str(v),
            on_press=self._edit_gesture_start, on_release=self._edit_gesture_end,
            reset_tip=t("Reset this slider"),
            on_reset=lambda: self._reset_focus_slider(which))
        s.pack(fill="x", pady=2)
        return s

    def _focus_done(self):
        "Done button: commit the blur (no leave prompt) and return to Basic."
        self._focus_auto = False
        self.set_section("basic")

    def _reset_focus_slider(self, which):
        "Zero just the blur or feather slider (one undoable step), keeping the shape."
        if self.focus is None:
            return
        self._focus_auto = False
        before = self._edit_state()
        self.focus = {**self.focus, which: 0.0}
        s = self.s_focus_blur if which == "blur" else self.s_focus_feather
        s.set(0)
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    # --- Shape toggle -------------------------------------------------------

    def _set_focus_shape(self, shape):
        "Switch the in-focus shape (circle ↔ line), keeping the blur + feather. Undoable."
        if self.current_pil is None:
            return
        if self.focus and self.focus.get("shape") == shape:
            return
        self._focus_auto = False
        before = self._edit_state()
        blur = self.focus.get("blur", 0.6) if self.focus else 0.6
        feather = self.focus.get("feather", 0.4) if self.focus else 0.4
        new = self._default_focus(shape)
        new["blur"], new["feather"] = blur, feather
        if self.focus:                       # keep the centre where the user had it
            new["cx"], new["cy"] = self.focus["cx"], self.focus["cy"]
        self.focus = new
        self._refresh_focus_mode()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    def _refresh_focus_mode(self):
        "Sync the shape toggle and swap the hint to match the active shape."
        if not hasattr(self, "_focus_shape_tabs"):
            return
        active = (self.focus or {}).get("shape", "circle")
        idx = self._focus_shapes.index(active) if active in self._focus_shapes else 0
        if self._focus_shape_tabs.selected != idx:
            self._focus_shape_tabs.selected = idx
            self._focus_shape_tabs.repaint()
        if active == "line":
            self._focus_hint.configure(
                text=t("Drag the band to set the focus; an edge changes its width, the end dot rotates it. Sharp in the band, blurred outside."))
        else:
            self._focus_hint.configure(
                text=t("Drag the circle to set the focus; the edge resizes it. Sharp inside, blurred outside."))

    # --- State + entry ------------------------------------------------------

    def _default_focus(self, shape="circle"):
        "A centred shape with a visible blur, so opening the tool shows the effect."
        iw, ih = self.current_pil.size
        base = {"shape": shape, "cx": iw / 2.0, "cy": ih / 2.0,
                "blur": 0.6, "feather": 0.4}
        if shape == "line":
            base.update(angle=0.0, width=min(iw, ih) * 0.35)
        else:
            base.update(r=min(iw, ih) * 0.30)
        return base

    def _enter_focus(self):
        "Open the focus tool: place a default shape, fit the photo, show the overlay."
        if self.current_pil is None:
            self._render_preview()
            return
        if self.focus is None:
            self.focus = self._default_focus("circle")
            self._focus_auto = True       # untouched auto-default: ask before leaving
            self._edits_saved = False
        self._refresh_focus_mode()
        self._sync_focus_controls()
        self.preview.configure(cursor="crosshair")
        self.fit_view()          # fit so the whole photo is visible to place it

    def _prompt_keep_focus_if_untouched(self):
        "Leaving the focus tool with the auto-applied default still untouched: ask"
        " whether to keep the blur. Any edit or the Done button clears _focus_auto,"
        " so this only fires when the user opened the tool and changed nothing."
        if self.focus is None or not getattr(self, "_focus_auto", False):
            return
        self._focus_auto = False          # decided now — don't ask again this pass
        # Nothing was changed, so removal is the likely intent: make it the primary
        # (Enter) button. Escape / the secondary button keeps the blur.
        remove = self._confirm(
            t("Blur was added automatically. Remove it?"),
            ok_label=t("Remove blur"), cancel_label=t("Keep blur"))
        if remove:
            self._remove_focus()

    def _focus_active(self):
        "True when the focus tool is open with a live shape (drives overlay + clicks)."
        return (self.panel_open and self.active_section == "focus"
                and self.current_pil is not None and self.focus is not None)

    def _sync_focus_controls(self):
        "Set the blur / feather sliders + shape chips from self.focus (no-op early)."
        if not hasattr(self, "s_focus_blur"):
            return
        fb = self.focus or {}
        self.s_focus_blur.set(round(fb.get("blur", 0.0) * 100))
        self.s_focus_feather.set(round(fb.get("feather", 0.4) * 100))
        self._refresh_focus_mode()

    # --- Sliders ------------------------------------------------------------

    def _set_focus_blur(self, v):
        "Slider: blur strength (0 = off, 100 = max background blur)."
        if self.focus is None:
            return
        self._focus_auto = False
        self.focus = {**self.focus, "blur": max(0.0, min(1.0, int(v) / 100.0))}
        self._edits_saved = False
        self._schedule_preview()

    def _set_focus_feather(self, v):
        "Slider: how soft the sharp→blurred transition is (0 = crisp edge)."
        if self.focus is None:
            return
        self._focus_auto = False
        self.focus = {**self.focus, "feather": max(0.0, min(1.0, int(v) / 100.0))}
        self._edits_saved = False
        self._schedule_preview()

    def _clear_focus_for_geometry(self):
        "Drop the focus shape when the image geometry changes (rotate / crop):"
        " its source-px coordinates no longer map to the new pixels. No separate"
        " undo entry — it rides along with the geometry action's own undo, which"
        " snapshots and restores the focus shape (see nav._geometry_snapshot)."
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

    # --- Shape geometry helpers ---------------------------------------------

    def _focus_axes(self):
        "Line shape: centre (screen), along-unit (u), across-unit (n), half-width (screen)."
        scale = self._disp[0] or 1.0
        cxs, cys = self._src_to_scr(self.focus["cx"], self.focus["cy"])
        ang = self.focus.get("angle", 0.0)
        ux, uy = math.cos(ang), math.sin(ang)
        nx, ny = -uy, ux
        hw = self.focus.get("width", 0.0) * 0.5 * scale
        return cxs, cys, ux, uy, nx, ny, hw

    def _focus_hit(self, x, y):
        "What is under screen (x, y): 'rotate' / 'resize' / 'move', or None."
        scale = self._disp[0] or 1.0
        cxs, cys = self._src_to_scr(self.focus["cx"], self.focus["cy"])
        if self.focus.get("shape") == "line":
            _, _, ux, uy, nx, ny, hw = self._focus_axes()
            rhx, rhy = cxs + ux * self.FOCUS_ROT_DIST, cys + uy * self.FOCUS_ROT_DIST
            if math.hypot(x - rhx, y - rhy) <= self.FOCUS_HANDLE + 4:
                return "rotate"
            perp = (x - cxs) * nx + (y - cys) * ny
            if abs(abs(perp) - hw) <= self.FOCUS_HANDLE + 4:
                return "resize"
            if abs(perp) < hw:
                return "move"
            return None
        rs = self.focus["r"] * scale
        d = math.hypot(x - cxs, y - cys)
        if abs(d - rs) <= self.FOCUS_HANDLE + 4:
            return "resize"
        if d < rs:
            return "move"
        return None

    # --- Mouse interaction --------------------------------------------------

    def _focus_press(self, event):
        "Begin a drag: grab the rotate handle, the edge (resize) or the inside (move)."
        if not self._focus_active():
            return
        hit = self._focus_hit(event.x, event.y)
        if hit is None:
            return "break"
        self._focus_auto = False         # dragging the shape counts as editing it
        self._edit_gesture_start()       # snapshot so the whole drag is one undo
        sx, sy = self._scr_to_src(event.x, event.y)
        if hit == "move":
            self._focus_drag = ("move", sx, sy, self.focus["cx"], self.focus["cy"])
        else:
            self._focus_drag = (hit, None, None, None, None)
        return "break"

    def _focus_move(self, event):
        "Drag in progress: move / resize / rotate the shape, then repaint."
        if self._focus_drag is None:
            return
        iw, ih = self.current_pil.size
        sx, sy = self._scr_to_src(event.x, event.y)
        mode = self._focus_drag[0]
        if mode == "move":
            _, psx, psy, ocx, ocy = self._focus_drag
            ncx = min(max(0.0, ocx + (sx - psx)), float(iw))
            ncy = min(max(0.0, ocy + (sy - psy)), float(ih))
            self.focus = {**self.focus, "cx": ncx, "cy": ncy}
        elif mode == "rotate":
            ang = math.atan2(sy - self.focus["cy"], sx - self.focus["cx"])
            self.focus = {**self.focus, "angle": ang}
        elif self.focus.get("shape") == "line":          # resize the band width
            ang = self.focus.get("angle", 0.0)
            nx, ny = -math.sin(ang), math.cos(ang)
            perp = (sx - self.focus["cx"]) * nx + (sy - self.focus["cy"]) * ny
            width = max(self.FOCUS_MIN_W, 2.0 * abs(perp))
            self.focus = {**self.focus, "width": width}
        else:                                              # resize the circle radius
            r = math.hypot(sx - self.focus["cx"], sy - self.focus["cy"])
            r = max(self.FOCUS_MIN_R, min(r, float(max(iw, ih))))
            self.focus = {**self.focus, "r": r}
        self._edits_saved = False
        self._render_preview()
        return "break"

    def _focus_release(self, event):
        "End the drag: record one undo entry if the shape actually changed."
        if self._focus_drag is None:
            return
        self._focus_drag = None
        self._edit_gesture_end()
        return "break"

    def _focus_hover(self, event):
        "Show the right cursor over the rotate handle / edge / inside while idle."
        if not self._focus_active() or self._focus_drag is not None:
            return
        hit = self._focus_hit(event.x, event.y)
        cur = {"rotate": "exchange", "resize": "sb_h_double_arrow",
               "move": "fleur"}.get(hit, "crosshair")
        self.preview.configure(cursor=cur)

    # --- Overlay ------------------------------------------------------------

    def _draw_focus_overlay(self):
        "Draw the focus shape (circle or line band) with its handles."
        c = self.preview
        if self.focus.get("shape") == "line":
            self._draw_focus_line(c)
        else:
            self._draw_focus_circle(c)

    def _draw_focus_circle(self, c):
        "Circle overlay: a dashed falloff ring, the sharp edge, centre + handle."
        scale = self._disp[0] or 1.0
        cxs, cys = self._src_to_scr(self.focus["cx"], self.focus["cy"])
        rs = self.focus["r"] * scale
        feather = self.focus.get("feather", 0.4)
        ro = rs * (1.0 + feather)
        c.create_oval(cxs - ro, cys - ro, cxs + ro, cys + ro,
                      outline="#ffffff", dash=(4, 3), width=1)
        c.create_oval(cxs - rs, cys - rs, cxs + rs, cys + rs,
                      outline=ACCENT, width=2)
        c.create_line(cxs - 6, cys, cxs + 6, cys, fill=ACCENT)
        c.create_line(cxs, cys - 6, cxs, cys + 6, fill=ACCENT)
        r = self.FOCUS_HANDLE
        c.create_rectangle(cxs + rs - r, cys - r, cxs + rs + r, cys + r,
                           fill=ACCENT, outline=ON_ACCENT)

    def _draw_focus_line(self, c):
        "Line (tilt-shift) overlay: the two band edges, a falloff pair, handles."
        cxs, cys, ux, uy, nx, ny, hw = self._focus_axes()
        feather = self.focus.get("feather", 0.4)
        vw = max(self.preview.winfo_width(), 1)
        vh = max(self.preview.winfo_height(), 1)
        L = vw + vh                       # long enough to span the canvas at any angle
        ho = hw * (1.0 + feather)
        for off, col, dash in ((ho, "#ffffff", (4, 3)), (hw, ACCENT, None)):
            for s in (1, -1):             # the two parallel edges
                ex, ey = cxs + nx * off * s, cys + ny * off * s
                c.create_line(ex - ux * L, ey - uy * L, ex + ux * L, ey + uy * L,
                              fill=col, width=(2 if col == ACCENT else 1),
                              dash=dash)
        # Centre handle + a rotation handle reached along the band.
        c.create_line(cxs - 6, cys, cxs + 6, cys, fill=ACCENT)
        c.create_line(cxs, cys - 6, cxs, cys + 6, fill=ACCENT)
        rhx, rhy = cxs + ux * self.FOCUS_ROT_DIST, cys + uy * self.FOCUS_ROT_DIST
        c.create_line(cxs, cys, rhx, rhy, fill=ACCENT, dash=(2, 2))
        r = self.FOCUS_HANDLE
        c.create_oval(rhx - r, rhy - r, rhx + r, rhy + r,
                      fill=ACCENT, outline=ON_ACCENT)
        # An edge resize handle on each band edge (where the across-axis crosses).
        for s in (1, -1):
            ex, ey = cxs + nx * hw * s, cys + ny * hw * s
            c.create_rectangle(ex - r, ey - r, ex + r, ey + r,
                               fill=ACCENT, outline=ON_ACCENT)
