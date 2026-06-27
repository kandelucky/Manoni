"""Retouch tool for Manoni — two modes that share one brush, paint loop and
undo:

  • ავტო შეკეთება (heal)  — paint over a blemish and it is cloned away from a
    clean neighbour, colour-matched (imaging.heal_region).
  • კლონი (clone stamp)  — Alt+click a source, then paint an exact copy of it
    with a locked offset (imaging.clone_region), like Photoshop.

Unlike the sliders — global, non-destructive, rebuilt every render — a retouch
is a LOCAL pixel edit baked straight into current_pil, the same way crop bakes
its result. Each stroke is one undo step.

Mixin on the Manoni window — every method uses the shared `self`, so behaviour
is identical to when it lived directly on the class.
"""

import tkinter as tk

from ..config import BAR, ACCENT, FG, FG_DIM, EDIT_PANEL_W, EDIT_PAD, CHIP_GAP
from .. import imaging
from ..widgets import Slider
from ..i18n import t


class HealMixin:
    # --- Retouch (col 3 panel + paint-on-preview) ---------------------------

    HEAL_MIN        = 4      # smallest brush radius, in source px
    HEAL_MAX        = 160    # largest brush radius, in source px
    HEAL_WHEEL_STEP = 4      # px per wheel notch / [ ] keypress
    CLONE_SRC       = "#ffcc44"   # colour of the clone source-ring overlay

    def _build_heal_section(self, parent):
        "Retouch panel: heal/clone mode, a hint, and the brush sliders."
        f = tk.Frame(parent, bg=BAR)

        # Mode toggle: auto heal vs manual clone stamp.
        self._heal_mode_chips = {}
        modes = tk.Frame(f, bg=BAR)
        modes.pack(fill="x", padx=EDIT_PAD, pady=(10, 2))
        modes.columnconfigure(0, weight=1, uniform="hm")
        modes.columnconfigure(1, weight=1, uniform="hm")
        self._heal_mode_chip(modes, "ავტო შეკეთება", "auto", 0)
        self._heal_mode_chip(modes, "კლონი", "clone", 1)

        self._heal_hint = tk.Label(f, text="", bg=BAR, fg=FG_DIM, anchor="w",
                                   font=("Segoe UI", 8), justify="left",
                                   wraplength=self._edit_dpi_w(
                                       EDIT_PANEL_W - 2 * EDIT_PAD))
        self._heal_hint.pack(fill="x", padx=EDIT_PAD, pady=(8, 6))

        # Clone-only options (alignment + mirror); shown only in clone mode.
        self._clone_opts = tk.Frame(f, bg=BAR)
        self._clone_opt_chips = {}
        self._clone_opts.columnconfigure(0, weight=1, uniform="co")
        self._clone_opts.columnconfigure(1, weight=1, uniform="co")
        self._clone_toggle_chip(self._clone_opts, "თანხვედრილი", "aligned", 0)
        self._clone_toggle_chip(self._clone_opts, "სარკისებური", "flip", 1)

        # Reuse the standard dark Slider. These are absolute magnitudes (not
        # bidirectional like the tone sliders), so neutral = the low end and the
        # accent fill reads as a gauge that grows with the value.
        self.s_heal_size = Slider(f, t("ფუნჯის ზომა"), self._set_heal_radius,
                                  lo=self.HEAL_MIN, hi=self.HEAL_MAX,
                                  neutral=self.HEAL_MIN)
        self.s_heal_size.set(self.heal_radius)
        self.s_heal_size.pack(fill="x", padx=EDIT_PAD, pady=2)

        # Strength: 100 = a solid clone (default), down to 0 = barely there, for
        # a soft, partial retouch (e.g. fading a wrinkle instead of erasing it).
        self.s_heal_strength = Slider(f, t("სიძლიერე"), self._set_heal_strength,
                                      lo=0, hi=100, neutral=0)
        self.s_heal_strength.set(round(self.heal_opacity * 100))
        self.s_heal_strength.pack(fill="x", padx=EDIT_PAD, pady=2)

        # Edge feather: 0 = a crisp disc edge, higher = a softer, more blurred
        # blend into the surrounding pixels.
        self.s_heal_feather = Slider(f, t("კიდის სიფაფუკე"), self._set_heal_feather,
                                     lo=0, hi=100, neutral=0)
        self.s_heal_feather.set(round(self.heal_feather * 100))
        self.s_heal_feather.pack(fill="x", padx=EDIT_PAD, pady=2)

        tk.Label(f, text=t("Ctrl+Z — ბოლო მოქმედების გაუქმება"), bg=BAR, fg=FG_DIM,
                 anchor="w", font=("Segoe UI", 8)).pack(fill="x", padx=EDIT_PAD,
                                                        pady=(12, 4))
        self._refresh_heal_mode()
        return f

    # --- Mode (heal vs clone) -----------------------------------------------

    def _heal_mode_chip(self, parent, label, mode, col):
        "One mode chip (accent-filled while its mode is active)."
        chip = tk.Label(parent, text=t(label), bg="#2f2f2f", fg=FG, cursor="hand2",
                        font=("Segoe UI", 8, "bold"), padx=4, pady=6)
        chip.bind("<Button-1>", lambda e, m=mode: self._set_heal_mode(m))
        pad = (0, CHIP_GAP // 2) if col == 0 else (CHIP_GAP // 2, 0)
        chip.grid(row=0, column=col, sticky="ew", padx=pad)
        self._heal_mode_chips[mode] = chip

    def _clone_toggle_chip(self, parent, label, key, col):
        "One clone-option toggle chip (accent-filled while on)."
        chip = tk.Label(parent, text=t(label), bg="#2f2f2f", fg=FG, cursor="hand2",
                        font=("Segoe UI", 8, "bold"), padx=4, pady=6)
        chip.bind("<Button-1>", lambda e, k=key: self._toggle_clone_opt(k))
        pad = (0, CHIP_GAP // 2) if col == 0 else (CHIP_GAP // 2, 0)
        chip.grid(row=0, column=col, sticky="ew", padx=pad)
        self._clone_opt_chips[key] = chip

    def _toggle_clone_opt(self, key):
        "Flip an aligned / mirror clone option and repaint its chip."
        if key == "aligned":
            self.clone_aligned = not self.clone_aligned
            if not self.clone_aligned:
                self.clone_offset = None    # next stroke re-anchors to the source
        else:
            self.clone_flip = not self.clone_flip
        self._refresh_clone_opts()
        self._render_preview()

    def _refresh_clone_opts(self):
        "Repaint the aligned / mirror chips to match their on/off state."
        states = {"aligned": self.clone_aligned, "flip": self.clone_flip}
        for k, chip in self._clone_opt_chips.items():
            on = states[k]
            chip.configure(bg=ACCENT if on else "#2f2f2f",
                           fg="#0b0b0b" if on else FG)

    def _set_heal_mode(self, mode):
        "Switch retouch mode; clear any clone source so the next one is deliberate."
        self.heal_mode = mode
        self.clone_src = None
        self.clone_offset = None
        self._refresh_heal_mode()
        self._render_preview()

    def _refresh_heal_mode(self):
        "Repaint the mode chips, swap the hint, and show clone options in clone mode."
        for m, chip in self._heal_mode_chips.items():
            active = (m == self.heal_mode)
            chip.configure(bg=ACCENT if active else "#2f2f2f",
                           fg="#0b0b0b" if active else FG)
        if self.heal_mode == "clone":
            self._heal_hint.configure(
                text=t("Alt+დააწკაპე — წყაროს არჩევა; მერე ხატე ზუსტი ასლი. "
                       "ბორბალი ან [ ] ფუნჯის ზომას ცვლის."))
            self._clone_opts.pack(fill="x", padx=EDIT_PAD, pady=(0, 6),
                                  before=self.s_heal_size.canvas)
            self._refresh_clone_opts()
        else:
            self._heal_hint.configure(
                text=t("დააწკაპე ან გადაუსვი ლაქას — ვშლი მახლობელი სუფთა ფონის "
                       "ასლით. ბორბალი ან [ ] ფუნჯის ზომას ცვლის."))
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
        self.toast(t("წყარო არჩეულია — ახლა ხატე ასლი"))
        return "break"

    # --- Painting -----------------------------------------------------------

    def _heal_press(self, event):
        "Begin a stroke: snapshot the image so the whole stroke is one undo step."
        if not self._heal_active():
            return
        if self.heal_mode == "clone":
            if self.clone_src is None:
                self.toast(t("ჯერ Alt+დააწკაპე წყაროზე"))
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
        self.current_pil.paste(patched, box)
        self._healed = True
        self._edits_saved = False
        self._grow_dirty(box)
        self._heal_last = (sx, sy)
        self._heal_cursor = (scrx, scry)
        self._view_key = None        # mutated in place → drop the cached scaled view
        self._render_preview()

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

    def _apply_heal_patch(self, cmd, patch):
        "Paste a stored before/after crop back at its box. Same-image only."
        if cmd["folder"] != self.folder or not self.files \
                or self.files[self.index] != cmd["file"]:
            self.toast(t("გაუქმება შეუძლებელია — სხვა სურათია"))
            return False
        if self.current_pil.mode != "RGB":
            self.current_pil = self.current_pil.convert("RGB")
        self.current_pil.paste(patch, cmd["box"])
        self._healed = True
        self._edits_saved = False
        self._view_key = None
        self._render_preview()
        return True
