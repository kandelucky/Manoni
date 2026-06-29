"""Text / watermark overlay for Manoni.

A single string laid over the photo — a caption or a "© name" watermark. Like
the focus blur (and unlike crop / heal, which bake into current_pil), this is a
LIVE, non-destructive effect: the string, its centre and its font height live in
SOURCE-image pixels inside `self.text_overlay`, so the text stays glued to the
photo through zoom + pan and the small preview composites exactly like the
full-res save (the imaging module multiplies position AND size by the same
`scale`). The whole overlay rides one undo entry per gesture, shared with the
slider-edit machinery.

Drag the text on the canvas to move it; the bottom-right handle resizes it. The
panel also offers a font, colour, opacity, a drop shadow and one-click corner
placement (the watermark staple). Mixin on the Manoni window — every method uses
the shared `self`.
"""

import math
import tkinter as tk
from tkinter import colorchooser

from ..config import (BAR, ACCENT, FG, FG_DIM, HOVER, ON_ACCENT,
                      EDIT_PAD, CHIP_GAP, CHIP_BG, BORDER)
from ..widgets import Slider, Tooltip
from ..i18n import t
from .dialogs import make_panel_chip, set_chip_active
from .. import imaging


class TextMixin:
    # --- Text overlay (col 3 panel + interactive box on the preview) ---------

    TEXT_HANDLE   = 5      # half-size of the resize handle square, screen px
    TEXT_MIN_SIZE = 6.0    # smallest font height, source px
    TEXT_MARGIN   = 0.04   # corner-placement inset, as a fraction of the short side
    TEXT_EMPTY_HW = 46     # placeholder half-width while no text is typed, screen px
    TEXT_EMPTY_HH = 16     # placeholder half-height while no text is typed, screen px

    # --- Panel --------------------------------------------------------------

    def _build_text_section(self, parent):
        "Text panel: the string, font, size + opacity, colour, shadow, placement."
        f = tk.Frame(parent, bg=BAR)

        tk.Label(f, text=t("Type a caption or a watermark, then drag it on the "
                           "photo to place it. The corner handle resizes it."),
                 bg=BAR, fg=FG_DIM, font=("Segoe UI", 8), justify="left",
                 anchor="w", wraplength=self._edit_dpi_w(190)).pack(
            fill="x", padx=EDIT_PAD, pady=(10, 6))

        # The string itself: a small multi-line box. A whole typing session is
        # one undo step (snapshot on focus-in, recorded on focus-out).
        self._text_entry = tk.Text(f, height=2, bg=CHIP_BG, fg=FG,
                                   insertbackground=FG, relief="flat", wrap="word",
                                   font=("Segoe UI", 10), padx=6, pady=4,
                                   highlightthickness=1, highlightbackground=BORDER,
                                   highlightcolor=ACCENT)
        self._text_entry.pack(fill="x", padx=EDIT_PAD, pady=(0, 4))
        self._text_entry.bind("<KeyRelease>", self._on_text_typed)
        self._text_entry.bind("<FocusIn>", lambda e: self._edit_gesture_start())
        self._text_entry.bind("<FocusOut>", lambda e: self._edit_gesture_end())

        # Font: two chips per row (accent-filled while active).
        self._group_header(f, t("Font"))
        self._text_font_chips = {}
        grid = tk.Frame(f, bg=BAR)
        grid.pack(fill="x", padx=EDIT_PAD, pady=2)
        grid.columnconfigure(0, weight=1, uniform="tf")
        grid.columnconfigure(1, weight=1, uniform="tf")
        for i, fam in enumerate(imaging.TEXT_FONTS):
            row = tk.Frame(grid, bg=BAR)
            row.grid(row=i // 2, column=i % 2, sticky="ew",
                     padx=(0, CHIP_GAP // 2) if i % 2 == 0 else (CHIP_GAP // 2, 0),
                     pady=2)
            row.columnconfigure(0, weight=1)
            chip = make_panel_chip(row, t(fam),
                                   lambda fm=fam: self._set_text_font(fm), 0, 0)
            chip.grid(sticky="ew")
            self._text_font_chips[fam] = chip

        # Size (as % of the photo's short side) and opacity. The press/release
        # hooks fold a whole drag into one undo step.
        self.s_text_size = Slider(f, t("Size"), self._set_text_size,
                                  lo=1, hi=50, neutral=8,
                                  on_press=self._edit_gesture_start,
                                  on_release=self._edit_gesture_end)
        self.s_text_size.pack(fill="x", padx=EDIT_PAD, pady=(8, 2))
        self.s_text_opacity = Slider(f, t("Opacity"), self._set_text_opacity,
                                     lo=0, hi=100, neutral=100,
                                     on_press=self._edit_gesture_start,
                                     on_release=self._edit_gesture_end)
        self.s_text_opacity.pack(fill="x", padx=EDIT_PAD, pady=2)

        # Colour swatch + a shadow toggle, side by side.
        row = tk.Frame(f, bg=BAR)
        row.pack(fill="x", padx=EDIT_PAD, pady=(10, 2))
        tk.Label(row, text=t("Colour"), bg=BAR, fg=FG_DIM,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        self._text_swatch = tk.Frame(row, bg="#ffffff", cursor="hand2",
                                     width=self._edit_dpi_w(28),
                                     height=self._edit_dpi_w(16),
                                     highlightthickness=1,
                                     highlightbackground=BORDER)
        self._text_swatch.pack(side="left", padx=(8, 0))
        self._text_swatch.pack_propagate(False)
        self._text_swatch.bind("<Button-1>", lambda e: self._pick_text_color())
        self._text_swatch._tip = Tooltip(self._text_swatch, t("Pick the text colour"))
        self._text_shadow_chip = tk.Label(
            row, text=t("Shadow"), bg=CHIP_BG, fg=FG, cursor="hand2",
            font=("Segoe UI", 8, "bold"), padx=10, pady=6)
        self._text_shadow_chip.pack(side="right")
        self._text_shadow_chip.bind("<Button-1>", lambda e: self._toggle_text_shadow())
        self._text_shadow_chip._tip = Tooltip(
            self._text_shadow_chip, t("A soft drop shadow, for light text on a bright photo"))

        # Alignment (matters for multi-line text): left / centre / right.
        self._group_header(f, t("Alignment"))
        self._text_align_chips = {}
        arow = tk.Frame(f, bg=BAR)
        arow.pack(fill="x", padx=EDIT_PAD, pady=2)
        for col, (key, label) in enumerate(
                (("left", "Left"), ("center", "Centre"), ("right", "Right"))):
            arow.columnconfigure(col, weight=1, uniform="ta")
            chip = tk.Label(arow, text=t(label), bg=CHIP_BG, fg=FG, cursor="hand2",
                            font=("Segoe UI", 8, "bold"), padx=4, pady=6)
            pad = (0, CHIP_GAP // 2) if col == 0 else \
                  (CHIP_GAP // 2, CHIP_GAP // 2) if col == 1 else (CHIP_GAP // 2, 0)
            chip.grid(row=0, column=col, sticky="ew", padx=pad)
            chip.bind("<Button-1>", lambda e, k=key: self._set_text_align(k))
            self._text_align_chips[key] = chip

        # One-click placement: a 3×3 grid snapping the text to a corner / edge /
        # centre with a small margin — the watermark staple.
        self._group_header(f, t("Position"))
        self._build_text_position_grid(f)

        remove = tk.Label(f, text=t("Remove text"), bg=BAR, fg=FG_DIM,
                          cursor="hand2", anchor="w", font=("Segoe UI", 9))
        remove.bind("<Enter>", lambda e: remove.configure(fg=FG))
        remove.bind("<Leave>", lambda e: remove.configure(fg=FG_DIM))
        remove.bind("<Button-1>", lambda e: self._remove_text())
        remove.pack(fill="x", padx=EDIT_PAD, pady=(14, 8))
        remove._tip = Tooltip(remove, t("Turn the text overlay off"))
        return f

    def _build_text_position_grid(self, parent):
        "A 3×3 grid of buttons; each snaps the text to that anchor with a margin."
        grid = tk.Frame(parent, bg=BAR)
        grid.pack(padx=EDIT_PAD, pady=2)
        for r, v in enumerate(("t", "m", "b")):
            for c, h in enumerate(("l", "c", "r")):
                cell = tk.Frame(grid, bg=CHIP_BG, cursor="hand2",
                                width=self._edit_dpi_w(34),
                                height=self._edit_dpi_w(22))
                cell.grid(row=r, column=c, padx=2, pady=2)
                cell.pack_propagate(False)
                dot = tk.Frame(cell, bg=FG_DIM,
                               width=self._edit_dpi_w(6), height=self._edit_dpi_w(6))
                # Place the dot toward the cell side it represents (a visual hint).
                dot.place(relx={"l": 0.18, "c": 0.5, "r": 0.82}[h],
                          rely={"t": 0.22, "m": 0.5, "b": 0.78}[v], anchor="center")
                for w in (cell, dot):
                    w.bind("<Button-1>", lambda e, hh=h, vv=v: self._place_text(hh, vv))
                    w.bind("<Enter>", lambda e, cc=cell, dd=dot:
                           (cc.configure(bg=HOVER), dd.configure(bg=FG)))
                    w.bind("<Leave>", lambda e, cc=cell, dd=dot:
                           (cc.configure(bg=CHIP_BG), dd.configure(bg=FG_DIM)))

    # --- State + entry ------------------------------------------------------

    def _default_text_overlay(self):
        "A centred, empty overlay sized to the photo, so the tool opens ready."
        iw, ih = self.current_pil.size
        return {"text": "", "cx": iw / 2.0, "cy": ih / 2.0,
                "size": max(12.0, min(iw, ih) * 0.08),
                "color": "#ffffff", "opacity": 1.0, "font": "Sans",
                "align": "center", "shadow": True}

    def _enter_text(self):
        "Open the text tool: place a default overlay, fit the photo, show controls."
        if self.current_pil is None:
            self._render_preview()
            return
        if self.text_overlay is None:
            self.text_overlay = self._default_text_overlay()
            self._edits_saved = False
        self._sync_text_controls()
        self.preview.configure(cursor="")
        self.fit_view()                      # fit so the whole photo is visible
        self._text_entry.focus_set()         # ready to type immediately

    def _text_active(self):
        "True when the text tool is open with a live overlay (drives clicks + overlay)."
        return (self.panel_open and self.active_section == "text"
                and self.current_pil is not None and self.text_overlay is not None)

    def _sync_text_controls(self):
        "Push the overlay values into the entry, sliders, chips + swatch (safe early)."
        if not hasattr(self, "_text_entry"):
            return
        ov = self.text_overlay or {}
        cur = self._text_entry.get("1.0", "end-1c")
        if cur != ov.get("text", ""):
            self._text_entry.delete("1.0", "end")
            self._text_entry.insert("1.0", ov.get("text", ""))
        if self.current_pil is not None and ov:
            short = max(1, min(self.current_pil.size))
            self.s_text_size.set(round(ov.get("size", 0.0) / short * 100))
        self.s_text_opacity.set(round(ov.get("opacity", 1.0) * 100))
        self._text_swatch.configure(bg=ov.get("color", "#ffffff"))
        active_font = ov.get("font", "Sans")
        for fam, chip in getattr(self, "_text_font_chips", {}).items():
            set_chip_active(chip, fam == active_font, CHIP_BG)
        active_align = ov.get("align", "center")
        for key, chip in getattr(self, "_text_align_chips", {}).items():
            set_chip_active(chip, key == active_align, CHIP_BG)
        set_chip_active(self._text_shadow_chip, bool(ov.get("shadow")), CHIP_BG)

    def _clear_text_for_geometry(self):
        "Drop the text when the image geometry changes (rotate / crop / resize /"
        " perspective): its source-px position no longer maps to the new pixels."
        " No undo entry — it rides along with the geometry action that called it."
        if self.text_overlay is None:
            return
        self.text_overlay = None
        self._text_drag = None
        self._sync_text_controls()

    # --- Panel controls -----------------------------------------------------

    def _on_text_typed(self, _event=None):
        "Live: copy the entry's content into the overlay and repaint (no undo step)."
        if self.text_overlay is None:
            return
        self.text_overlay = {**self.text_overlay,
                             "text": self._text_entry.get("1.0", "end-1c")}
        self._edits_saved = False
        self._render_preview()

    def _set_text_size(self, v):
        "Slider: font height as a % of the photo's short side (live, no undo step)."
        if self.text_overlay is None or self.current_pil is None:
            return
        short = max(1, min(self.current_pil.size))
        self.text_overlay = {**self.text_overlay,
                             "size": max(self.TEXT_MIN_SIZE, int(v) / 100.0 * short)}
        self._edits_saved = False
        self._render_preview()

    def _set_text_opacity(self, v):
        "Slider: text opacity 0..100 → 0..1 (live, no undo step)."
        if self.text_overlay is None:
            return
        self.text_overlay = {**self.text_overlay,
                             "opacity": max(0.0, min(1.0, int(v) / 100.0))}
        self._edits_saved = False
        self._render_preview()

    def _set_text_font(self, family):
        "Switch the font (undoable)."
        if self.text_overlay is None or self.text_overlay.get("font") == family:
            return
        before = self._edit_state()
        self.text_overlay = {**self.text_overlay, "font": family}
        self._sync_text_controls()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    def _set_text_align(self, key):
        "Switch the multi-line alignment (undoable)."
        if self.text_overlay is None or self.text_overlay.get("align") == key:
            return
        before = self._edit_state()
        self.text_overlay = {**self.text_overlay, "align": key}
        self._sync_text_controls()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    def _toggle_text_shadow(self):
        "Flip the drop shadow on / off (undoable)."
        if self.text_overlay is None:
            return
        before = self._edit_state()
        self.text_overlay = {**self.text_overlay,
                             "shadow": not self.text_overlay.get("shadow")}
        self._sync_text_controls()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    def _pick_text_color(self):
        "Open the colour chooser; apply the picked colour (undoable)."
        if self.text_overlay is None:
            return
        cur = self.text_overlay.get("color", "#ffffff")
        rgb, hexv = colorchooser.askcolor(color=cur, parent=self.root,
                                          title=t("Text colour"))
        if not hexv:
            return
        before = self._edit_state()
        self.text_overlay = {**self.text_overlay, "color": hexv}
        self._sync_text_controls()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    def _place_text(self, h, v):
        "Snap the text to a 3×3 anchor (h in l/c/r, v in t/m/b) with a margin. Undoable."
        if self.text_overlay is None or self.current_pil is None:
            return
        before = self._edit_state()
        iw, ih = self.current_pil.size
        tw, th = imaging.text_extent(self.text_overlay)
        margin = min(iw, ih) * self.TEXT_MARGIN
        cx = {"l": margin + tw / 2, "c": iw / 2, "r": iw - margin - tw / 2}[h]
        cy = {"t": margin + th / 2, "m": ih / 2, "b": ih - margin - th / 2}[v]
        self.text_overlay = {**self.text_overlay, "cx": cx, "cy": cy}
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    def _remove_text(self):
        "Turn the text overlay off entirely, as one undoable step."
        if self.text_overlay is None:
            return
        before = self._edit_state()
        self.text_overlay = None
        self._text_drag = None
        self._sync_text_controls()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    # --- Canvas geometry + hit testing --------------------------------------

    def _text_box_screen(self):
        "The overlay box on screen: centre (cxs, cys) and half-extent (hw, hh)."
        scale = self._disp[0] or 1.0
        cxs, cys = self._src_to_scr(self.text_overlay["cx"], self.text_overlay["cy"])
        tw, th = imaging.text_extent(self.text_overlay)
        if tw <= 0 or th <= 0:               # nothing typed yet → a placeholder box
            return cxs, cys, self.TEXT_EMPTY_HW, self.TEXT_EMPTY_HH
        return cxs, cys, tw * scale / 2.0, th * scale / 2.0

    def _text_hit(self, x, y):
        "What is under screen (x, y): 'resize' (corner handle), 'move', or None."
        cxs, cys, hw, hh = self._text_box_screen()
        hx, hy = cxs + hw, cys + hh
        if math.hypot(x - hx, y - hy) <= self.TEXT_HANDLE + 5:
            return "resize"
        if abs(x - cxs) <= hw and abs(y - cys) <= hh:
            return "move"
        return None

    # --- Mouse interaction --------------------------------------------------

    def _text_press(self, event):
        "Begin a drag: grab the corner handle (resize) or the box (move)."
        if not self._text_active():
            return
        hit = self._text_hit(event.x, event.y)
        if hit is None:
            return "break"
        self._edit_gesture_start()           # snapshot so the whole drag is one undo
        sx, sy = self._scr_to_src(event.x, event.y)
        if hit == "move":
            self._text_drag = ("move", sx, sy,
                               self.text_overlay["cx"], self.text_overlay["cy"])
        else:
            d0 = max(1.0, math.hypot(sx - self.text_overlay["cx"],
                                     sy - self.text_overlay["cy"]))
            self._text_drag = ("resize", d0, self.text_overlay["size"], None, None)
        return "break"

    def _text_move(self, event):
        "Drag in progress: move the box or scale the font, then repaint."
        if self._text_drag is None:
            return
        iw, ih = self.current_pil.size
        sx, sy = self._scr_to_src(event.x, event.y)
        mode = self._text_drag[0]
        if mode == "move":
            _, psx, psy, ocx, ocy = self._text_drag
            cx = min(max(0.0, ocx + (sx - psx)), float(iw))
            cy = min(max(0.0, ocy + (sy - psy)), float(ih))
            self.text_overlay = {**self.text_overlay, "cx": cx, "cy": cy}
        else:                                # resize: scale size by the distance ratio
            _, d0, s0, _, _ = self._text_drag
            d = max(1.0, math.hypot(sx - self.text_overlay["cx"],
                                    sy - self.text_overlay["cy"]))
            size = max(self.TEXT_MIN_SIZE, min(s0 * d / d0, float(max(iw, ih))))
            self.text_overlay = {**self.text_overlay, "size": size}
            short = max(1, min(iw, ih))
            self.s_text_size.set(round(size / short * 100))
        self._edits_saved = False
        self._render_preview()
        return "break"

    def _text_release(self, event):
        "End the drag: record one undo entry if the overlay actually changed."
        if self._text_drag is None:
            return
        self._text_drag = None
        self._edit_gesture_end()
        return "break"

    def _text_hover(self, event):
        "Show a move / resize cursor over the box while idle."
        if not self._text_active() or self._text_drag is not None:
            return
        hit = self._text_hit(event.x, event.y)
        cur = {"resize": "bottom_right_corner", "move": "fleur"}.get(hit, "")
        self.preview.configure(cursor=cur)

    # --- Overlay ------------------------------------------------------------

    def _draw_text_overlay(self):
        "Draw the dashed bounding box, the resize handle and (if empty) a hint."
        c = self.preview
        cxs, cys, hw, hh = self._text_box_screen()
        x0, y0, x1, y1 = cxs - hw, cys - hh, cxs + hw, cys + hh
        c.create_rectangle(x0, y0, x1, y1, outline=ACCENT, dash=(4, 3), width=1)
        r = self.TEXT_HANDLE
        c.create_rectangle(x1 - r, y1 - r, x1 + r, y1 + r,
                           fill=ACCENT, outline=ON_ACCENT)
        if not (self.text_overlay.get("text") or "").strip():
            c.create_text(cxs, cys, text=t("Type your text"), fill=FG_DIM,
                          font=("Segoe UI", 9))
