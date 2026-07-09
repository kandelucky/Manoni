"""Interactive crop tool for Manoni: ratio presets, the on-preview overlay,
and apply. Split out of the Manoni class as a mixin — every method uses the
shared `self`, so behaviour is identical to when it lived on the class.
"""

import os
import math
import tkinter as tk
import tkinter.ttk as ttk

from PIL import Image

import tintkit

# ACCENT / ON_ACCENT stay as fixed config constants for the on-photo crop-overlay
# draw (handles) — accent is scheme-independent and those draws sit over the
# image, not on chrome. Every crop-panel widget reads self.theme live instead so
# the panel switches dark<->light with the rest of the app.
from ..config import ACCENT, ON_ACCENT, EDIT_PAD
from ..i18n import t
from .dialogs import center_over


class CropMixin:
    # --- Crop tool (col 3 panel + interactive overlay on the preview) --------

    # Standard aspect-ratio cards (label, w/h). Listed once each.
    CROP_RATIO_CARDS = [("1:1", 1.0), ("4:3", 4 / 3), ("3:2", 3 / 2), ("5:4", 5 / 4)]
    # Social presets: (name, subtitle, ratio label, w/h). Platforms that share a
    # ratio share one row. name/subtitle go through t() at build time.
    CROP_SOCIAL = [
        ("Instagram portrait", "Post · vertical", "4:5", 4 / 5),
        ("Story · Reels · TikTok", "Full screen", "9:16", 9 / 16),
        ("YouTube · X", "Horizontal", "16:9", 16 / 9),
        ("FB · LinkedIn", "Share banner", "1.91", 1.91),
    ]

    def _build_crop_section(self, parent):
        "Crop's scrollable content: form segment + ratio cards + orientation +"
        " foldable social/saved-size presets. Crop/Cancel are a separate pinned"
        " footer — see _build_crop_footer."
        f = self._tw(tk.Frame(parent), bg="bar")
        # Every selectable element registers a (widget, paint) pair so one of them
        # can be shown active at a time. Fixed selectors (segment/cards/social) are
        # built once; the saved-size rows are rebuilt as that list changes.
        self._crop_selectors = []
        self._size_selectors = []
        self._crop_btn_active = None
        # A dark<->light switch repaints every selector to its resting/active look
        # through the same registry the panel uses at runtime (built once here, so
        # subscribing once is safe — same lifetime as the panel).
        self.theme.subscribe(self._restyle_crop_chips)

        # Shape is the highest-frequency control, so it stays expanded; the two
        # preset lists below are situational (not every crop needs a social ratio
        # or a saved size), so they live in the shared Foldout-group visual
        # (tintkit.Foldout via _fold_group) and start collapsed, their open
        # state persisting like every other fold.
        self._crop_group_header(f, "ratio", t("Shape"))
        self._build_crop_segment(f)
        self._build_ratio_cards(f)

        self._crop_group_header(f, "scan-line", t("Orientation"))
        self._build_straighten(f)
        self._build_orientation_tools(f)

        self._build_social_rows(
            self._fold_group(f, "cr_social", t("Social networks")))
        self._build_my_sizes(self._fold_group(f, "cr_sizes", t("My sizes")))
        # Crop/Cancel are NOT built here — they're a pinned footer (see
        # _build_crop_footer) so folding Social/My sizes open can't push them
        # out of view.
        return f

    # --- Active-state registry ----------------------------------------------

    def _crop_register(self, widget, paint):
        "Register a selectable element + its paint(active) callback; start inactive."
        self._crop_selectors.append((widget, paint))
        paint(False)

    def _restyle_crop_chips(self):
        "Repaint every selector so only `_crop_btn_active` reads as selected."
        active = self._crop_btn_active
        for w, paint in self._crop_selectors + getattr(self, "_size_selectors", []):
            try:
                paint(w is active)
            except tk.TclError:
                pass   # widget was destroyed (e.g. a rebuilt size row)

    def _pick_simple(self, widget, ratio):
        "Select a ratio preset (card / social / saved size): highlight + lock box."
        if self.current_pil is None:
            return
        self._crop_btn_active = widget
        self._restyle_crop_chips()
        self._set_crop_ratio(ratio)

    # --- Ratio-shape glyph (a small rectangle drawn at the right proportions) -

    def _ratio_glyph(self, parent, ratio, box=24, bg=None, stroke=None):
        "A tiny canvas holding a rectangle of aspect `ratio`, centered in `box` px."
        bg = bg or self.theme["chip"]
        stroke = stroke or self.theme["fg"]
        px = self._edit_dpi_w(box)
        cv = tk.Canvas(parent, width=px, height=px, bg=bg,
                       highlightthickness=0, bd=0)
        self._draw_ratio_glyph(cv, ratio, stroke)
        return cv

    def _draw_ratio_glyph(self, cv, ratio, stroke):
        "(Re)draw a ratio rectangle on its canvas in `stroke` (outline only)."
        cv.delete("all")
        px = int(cv["width"])
        m = px * 0.84
        if ratio >= 1.0:
            w, h = m, m / ratio
        else:
            w, h = m * ratio, m
        x0, y0 = (px - w) / 2, (px - h) / 2
        cv.create_rectangle(x0, y0, x0 + w, y0 + h, outline=stroke,
                            width=max(1, self._edit_dpi_w(1.4)))

    # --- Group header (small icon + dim caption) ----------------------------

    def _crop_group_header(self, parent, icon_name, text):
        "A small icon + dim bold caption that titles a group in the crop panel."
        row = self._tw(tk.Frame(parent), bg="bar")
        row.pack(fill="x", padx=EDIT_PAD, pady=(13, 6))
        if self.icon(icon_name, size=12) is not None:
            self._icon_label(row, icon_name, size=12, token="fg_dim",
                             bg="bar").pack(side="left", padx=(0, 6))
        self._tw(tk.Label(row, text=text, anchor="w",
                 font=("Segoe UI", 8, "bold")), bg="bar", fg="fg_dim").pack(side="left")

    # --- Form segment: Free / Orig. / Custom --------------------------------

    def _build_crop_segment(self, parent):
        "Segmented control for the crop kind (free / original / one-off custom)."
        track = self._tw(tk.Frame(parent), bg="bg")   # trough is the darkest surface
        track.pack(fill="x", padx=EDIT_PAD, pady=(0, 5))
        cells = [("maximize", t("Free"), None),
                 ("image", t("Orig."), "orig"),
                 ("scaling", t("Custom"), "custom")]
        # Grid + uniform: every cell is exactly 1/3 wide, regardless of label
        # length (plain pack/expand only splits the *spare* space evenly).
        for i in range(len(cells)):
            track.columnconfigure(i, weight=1, uniform="seg")
        for i, (icon_name, label, kind) in enumerate(cells):
            self._segment_button(track, icon_name, label, kind, i)

    def _segment_button(self, track, icon_name, label, kind, col):
        "One segment cell (icon over label); active = filled, like a tab."
        cell = tk.Frame(track, bg=self.theme["bg"], cursor="hand2")
        cell.grid(row=0, column=col, sticky="ew", padx=2, pady=2)
        img = self.icon(icon_name, size=15)
        if img is not None:
            ic = tk.Label(cell, image=img, bg=self.theme["bg"])
            self._reg_icon(ic, icon_name, size=15, token="fg")   # bg = segment paint's
        else:
            ic = tk.Label(cell, text="□", bg=self.theme["bg"], fg=self.theme["fg"])
        ic.pack(pady=(4, 1))
        tx = tk.Label(cell, text=label, bg=self.theme["bg"], fg=self.theme["fg_dim"],
                      font=("Segoe UI", 8))
        tx.pack(pady=(0, 4))

        def paint(active):
            bg = self.theme["chip"] if active else self.theme["bg"]
            cell.configure(bg=bg)
            ic.configure(bg=bg)
            tx.configure(bg=bg, fg=self.theme["fg"] if active else self.theme["fg_dim"])

        def hover(on):
            if cell is self._crop_btn_active:
                return
            # halfway between the trough and the active fill = a gentle hint
            bg = tintkit.mix(self.theme["bg"], self.theme["chip"], 0.5) if on \
                else self.theme["bg"]
            cell.configure(bg=bg)
            ic.configure(bg=bg)
            tx.configure(bg=bg)

        for w in (cell, ic, tx):
            w.bind("<Button-1>", lambda e: self._pick_segment(cell, kind))
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
        self._crop_register(cell, paint)

    def _pick_segment(self, cell, kind):
        "Segment clicked: free, the photo's own ratio, or a one-off custom ratio."
        if self.current_pil is None:
            return
        if kind is None:
            ratio = None
        elif kind == "orig":
            iw, ih = self.current_pil.size
            ratio = iw / ih
        else:                                # one-off custom ratio (not saved)
            res = self._ask_size_dialog("Custom shape", with_name=False)
            if res is None:
                return
            _, w, h = res
            ratio = w / h
        self._crop_btn_active = cell
        self._restyle_crop_chips()
        self._set_crop_ratio(ratio)

    # --- Standard ratio cards (1:1 · 4:3 · 3:2 · 5:4) -----------------------

    def _build_ratio_cards(self, parent):
        "A 4-column row of small ratio cards (shape + label)."
        grid = self._tw(tk.Frame(parent), bg="bar")
        grid.pack(fill="x", padx=EDIT_PAD, pady=(0, 2))
        for i in range(len(self.CROP_RATIO_CARDS)):
            grid.columnconfigure(i, weight=1, uniform="rc")
        for i, (label, ratio) in enumerate(self.CROP_RATIO_CARDS):
            self._ratio_card(grid, label, ratio, i)

    def _ratio_card(self, grid, label, ratio, col):
        "One ratio card: a proportion shape over its label; active = accent fill."
        card = tk.Frame(grid, bg=self.theme["chip"], cursor="hand2")
        card.grid(row=0, column=col, sticky="ew", padx=2, pady=2)
        glyph = self._ratio_glyph(card, ratio, box=22, bg=self.theme["chip"],
                                  stroke=self.theme["fg_dim"])
        glyph.pack(pady=(5, 2))
        tx = tk.Label(card, text=label, bg=self.theme["chip"], fg=self.theme["fg_dim"],
                      font=("Segoe UI", 8))
        tx.pack(pady=(0, 5))

        def paint(active):
            bg = self.theme["accent"] if active else self.theme["chip"]
            card.configure(bg=bg)
            glyph.configure(bg=bg)
            self._draw_ratio_glyph(
                glyph, ratio, self.theme["on_accent"] if active else self.theme["fg_dim"])
            tx.configure(bg=bg, fg=self.theme["on_accent"] if active else self.theme["fg_dim"])

        def hover(on):
            if card is self._crop_btn_active:
                return
            bg = self.theme["hover"] if on else self.theme["chip"]
            card.configure(bg=bg)
            glyph.configure(bg=bg)
            self._draw_ratio_glyph(glyph, ratio, self.theme["fg_dim"])
            tx.configure(bg=bg)

        for w in (card, glyph, tx):
            w.bind("<Button-1>", lambda e: self._pick_simple(card, ratio))
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
        self._crop_register(card, paint)

    # --- Orientation: straighten (horizon tilt) + rotate/mirror -------------
    # Two framed fields under the one header: a continuous "Straighten" (angle
    # slider) over a discrete "Flip & rotate" (90° swap + the two mirrors).
    # Boxing each and giving the transforms labelled tiles reads more clearly
    # than a slider stacked on a row of bare, unlabelled floating icons.

    def _crop_field(self, parent, title):
        "A bordered card titled with a small dim caption; returns its content"
        " frame for the caller to fill."
        card = self._tw(tk.Frame(parent, highlightthickness=1), bg="bar", hl="border")
        card.pack(fill="x", padx=EDIT_PAD, pady=(0, 8))
        inner = self._tw(tk.Frame(card), bg="bar")
        inner.pack(fill="x", padx=10, pady=(8, 9))
        self._tw(tk.Label(inner, text=title, font=("Segoe UI", 8, "bold")),
                 bg="bar", fg="fg_dim").pack(anchor="w", pady=(0, 6))
        return inner

    def _build_straighten(self, parent):
        "A horizon-straighten slider (−45…+45°, 0 = level) in its own field. It"
        " tilts the photo live; the crop box auto-fits so no empty corners stay."
        # A bidirectional TitledSlider (title strip: label · signed angle · reset)
        # over a full-width track, matching every other migrated slider.
        field = self._crop_field(parent, t("Straighten"))
        self.s_straighten = tintkit.TitledSlider(
            field, self.theme, t("Angle"), value=0, lo=-45, hi=45, neutral=0,
            bg="bar", command=self._on_straighten, reset_tip=t("Reset this slider"),
            on_reset=lambda: self._reset_straighten(render=True))
        self.s_straighten.pack(fill="x")
        tintkit.HoverTip(
            self.s_straighten.canvas, self.theme,
            t("Tilt to level the horizon (the crop trims the corners)"))

    # (icon, command-name, tile label, tooltip) for the transform tiles.
    # command-name is looked up on self at build time so this stays declarative.
    _CROP_TOOL_ROW = [
        ("rotate-cw-square", "_flip_crop_ratio", "Rotate",
         "Swap the selection's orientation (90°)"),
        ("flip-horizontal-2", "mirror_horizontal", "Flip H",
         "Mirror the photo horizontally"),
        ("flip-vertical-2", "mirror_vertical", "Flip V",
         "Mirror the photo vertically"),
    ]

    def _build_orientation_tools(self, parent):
        "The 90° swap + mirror-h/v transforms as three equal labelled tiles"
        " (icon over a short word) in their own field — clearer than the old row"
        " of bare floating icons."
        field = self._crop_field(parent, t("Flip & rotate"))
        grid = self._tw(tk.Frame(field), bg="bar")
        grid.pack(fill="x")
        for i in range(len(self._CROP_TOOL_ROW)):
            grid.columnconfigure(i, weight=1, uniform="ot")
        for i, (icon_name, cmd_name, label, tip) in enumerate(self._CROP_TOOL_ROW):
            self._orientation_tile(grid, icon_name, t(label),
                                   getattr(self, cmd_name), t(tip), i)

    def _orientation_tile(self, grid, icon_name, label, command, tip, col):
        "One transform tile: an icon over a short label; chip fill, border, hover."
        tile = self._tw(tk.Frame(grid, cursor="hand2", highlightthickness=1),
                        bg="chip", hl="border")
        tile.grid(row=0, column=col, sticky="ew", padx=2)
        ic = self._icon_label(tile, icon_name, size=16, token="fg", bg="chip")
        ic.pack(pady=(8, 2))
        tx = self._tw(tk.Label(tile, text=label, font=("Segoe UI", 8)),
                      bg="chip", fg="fg_dim")
        tx.pack(pady=(0, 7))
        parts = (tile, ic, tx)

        def hover(on):
            bg = self.theme["hover"] if on else self.theme["chip"]
            for w in parts:
                w.configure(bg=bg)

        for w in parts:
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
        tintkit.HoverTip(tile, self.theme, tip)

    def _on_straighten(self, deg):
        "Live tilt: set the angle, fit the auto crop box, re-render the preview."
        if self.current_pil is None:
            return
        self.straighten = float(deg)
        # The rotation preview is correct only with the whole photo in view, so
        # straightening always works on the fitted view (zoom is paused).
        self.fit_mode = True
        self.pan_x = self.pan_y = 0.0
        self._straighten_box()
        self._render_preview()

    def _reset_straighten(self, render=False):
        "Clear the pending tilt and zero the slider (on commit / geometry change)."
        self.straighten = 0.0
        if hasattr(self, "s_straighten"):
            try:
                self.s_straighten.set(0)
            except tk.TclError:
                pass
        if render:
            self._straighten_box()
            self._render_preview()

    def _straighten_box(self):
        "Center the crop box on the largest upright rectangle that stays inside"
        " the tilted photo — so committing the straighten never keeps empty"
        " corners. Reduces to the plain centered ratio box when the tilt is 0."
        if self.current_pil is None:
            return
        iw, ih = self.current_pil.size
        r = self.crop_ratio or (iw / ih)
        a = math.radians(abs(self.straighten))
        ca, sa = math.cos(a), math.sin(a)
        hx = min((iw / 2.0) / (ca + sa / r), (ih / 2.0) / (sa + ca / r))
        hy = hx / r
        cx, cy = iw / 2.0, ih / 2.0
        self.crop_rect = [cx - hx, cy - hy, cx + hx, cy + hy]

    @staticmethod
    def _rotate_keep_size(img, angle):
        "Rotate `img` about its center by `angle`° (positive = clockwise), keeping"
        " the canvas size. Used to bake a straighten before the crop trims it."
        if img.mode in ("P", "1"):
            img = img.convert("RGB")
        return img.rotate(-angle, resample=Image.BICUBIC, expand=False)

    # --- Social rows (name + subtitle + ratio, full width) ------------------

    def _build_social_rows(self, parent):
        "A vertical list of social-network presets, each a full-width row."
        " Lives in a Foldout body, whose own inset does the aligning (padx=0)."
        wrap = self._tw(tk.Frame(parent), bg="bar")
        wrap.pack(fill="x", pady=(0, 2))
        for name, sub, rlabel, ratio in self.CROP_SOCIAL:
            self._preset_row(wrap, t(name), t(sub), rlabel, ratio)

    def _preset_row(self, parent, name, sub, rlabel, ratio):
        "One social row: shape · name/subtitle · ratio. Active = accent-tinted."
        row = tk.Frame(parent, bg=self.theme["chip"], cursor="hand2")
        row.pack(fill="x", pady=2)
        glyph = self._ratio_glyph(row, ratio, box=24, bg=self.theme["chip"],
                                  stroke=self.theme["fg"])
        glyph.pack(side="left", padx=(8, 10), pady=6)
        txt = tk.Frame(row, bg=self.theme["chip"])
        txt.pack(side="left", fill="x", expand=True)
        t1 = tk.Label(txt, text=name, bg=self.theme["chip"], fg=self.theme["fg"],
                      anchor="w", font=("Segoe UI", 9))
        t1.pack(fill="x")
        t2 = tk.Label(txt, text=sub, bg=self.theme["chip"], fg=self.theme["fg_dim"],
                      anchor="w", font=("Segoe UI", 7))
        t2.pack(fill="x")
        rl = tk.Label(row, text=rlabel, bg=self.theme["chip"], fg=self.theme["fg_dim"],
                      font=("Segoe UI", 8))
        rl.pack(side="right", padx=10)
        cells = (row, txt, t2)

        def paint(active):
            bg = self.theme["accent_soft"] if active else self.theme["chip"]
            for w in cells:
                w.configure(bg=bg)
            t1.configure(bg=bg, fg=self.theme["on_accent"] if active else self.theme["fg"])
            rl.configure(bg=bg, fg=self.theme["accent"] if active else self.theme["fg_dim"])
            glyph.configure(bg=bg)
            self._draw_ratio_glyph(glyph, ratio,
                                   self.theme["accent"] if active else self.theme["fg"])

        def hover(on):
            if row is self._crop_btn_active:
                return
            bg = self.theme["hover"] if on else self.theme["chip"]
            for w in (row, txt, t1, t2, rl):
                w.configure(bg=bg)
            glyph.configure(bg=bg)
            self._draw_ratio_glyph(glyph, ratio, self.theme["fg"])

        for w in (row, glyph, txt, t1, t2, rl):
            w.bind("<Button-1>", lambda e: self._pick_simple(row, ratio))
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
        self._crop_register(row, paint)

    # --- "My sizes": add button + scrollable saved-size list ----------------

    def _build_my_sizes(self, parent):
        "The '+ Your size' add button plus the scrollable list of saved sizes."
        # The add button has only a resting look (no active state), so _tw keeps
        # its fill/accent text/border in sync on a theme switch; the hover closure
        # reads the live theme for its transient accent-tint.
        add = self._tw(tk.Frame(parent, cursor="hand2", highlightthickness=1),
                       bg="bar", hl="border")
        add.pack(fill="x", pady=(0, 6))
        inner = self._tw(tk.Frame(add), bg="bar")
        inner.pack(pady=6)
        plus = self._tw(tk.Label(inner, text="＋", font=("Segoe UI", 11, "bold")),
                        bg="bar", fg="accent")
        plus.pack(side="left", padx=(0, 5))
        lbl = self._tw(tk.Label(inner, text=t("Your size"),
                       font=("Segoe UI", 8, "bold")), bg="bar", fg="accent")
        lbl.pack(side="left")
        addparts = (add, inner, plus, lbl)

        def add_hover(on):
            bg = tintkit.mix(self.theme["bar"], self.theme["accent"], 0.12) if on \
                else self.theme["bar"]
            for w in addparts:
                w.configure(bg=bg)
            add.configure(highlightbackground=self.theme["accent"] if on
                          else self.theme["border"])

        for w in addparts:
            w.bind("<Button-1>", lambda e: self._add_custom_size())
            w.bind("<Enter>", lambda e: add_hover(True))
            w.bind("<Leave>", lambda e: add_hover(False))
        tintkit.HoverTip(add, self.theme, t("Add your size to the list"))

        # Scroll area: a fixed-height canvas + inner frame + slim scrollbar. The
        # canvas height tracks the content up to a cap, then the list scrolls.
        self._sizes_max_h = self._edit_dpi_w(116)
        holder = self._tw(tk.Frame(parent), bg="bar")
        holder.pack(fill="x")
        cv = self._tw(tk.Canvas(holder, highlightthickness=0, bd=0,
                      height=self._sizes_max_h), bg="bar")
        sb = ttk.Scrollbar(holder, orient="vertical", command=cv.yview,
                           style="Sidebar.Vertical.TScrollbar")
        cv.configure(yscrollcommand=sb.set)
        inner = self._tw(tk.Frame(cv), bg="bar")
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.pack(side="left", fill="x", expand=True)

        def on_inner(_e=None):
            cv.configure(scrollregion=cv.bbox("all"))
            need = inner.winfo_reqheight()
            cv.configure(height=min(need, self._sizes_max_h))
            if need > self._sizes_max_h:
                if not sb.winfo_ismapped():
                    sb.pack(side="right", fill="y", before=cv)
            else:
                sb.pack_forget()
                cv.yview_moveto(0)

        inner.bind("<Configure>", on_inner)
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        self._sizes_canvas = cv
        self._sizes_inner = inner
        self._bind_sizes_wheel(cv)
        self._rebuild_my_sizes_list()

    def _bind_sizes_wheel(self, widget):
        "Wheel over the saved-size list (its rows included) scrolls it, not the photo."
        widget.bind("<MouseWheel>", self._sizes_wheel)
        for c in widget.winfo_children():
            self._bind_sizes_wheel(c)

    def _sizes_wheel(self, e):
        "Scroll the saved-size list if it overflows; swallow the event either way."
        cv = self._sizes_canvas
        if self._sizes_inner.winfo_reqheight() > int(cv["height"]):
            cv.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

    def _rebuild_my_sizes_list(self):
        "Repopulate the saved-size rows from self.crop_sizes (called on any change)."
        inner = self._sizes_inner
        for w in inner.winfo_children():
            w.destroy()
        self._size_selectors = []
        if not self.crop_sizes:
            ph = self._tw(tk.Label(inner, text=t("No sizes yet"),
                          font=("Segoe UI", 8), anchor="w", justify="left",
                          wraplength=self._edit_dpi_w(self.FOLD_BODY_W - 10)),
                          bg="bar", fg="fg_dim")
            ph.pack(fill="x", pady=(2, 4))
        else:
            for i, sz in enumerate(self.crop_sizes):
                self._size_row(inner, i, sz)
        # Arm the wheel on the fresh rows/placeholder so hovering a row scrolls too.
        for c in inner.winfo_children():
            self._bind_sizes_wheel(c)
        inner.update_idletasks()

    def _size_row(self, parent, idx, sz):
        "One saved-size row: shape · name/dimensions · edit · delete. Selectable."
        ratio = sz["w"] / sz["h"]
        row = tk.Frame(parent, bg=self.theme["chip"], cursor="hand2")
        row.pack(fill="x", pady=2)
        glyph = self._ratio_glyph(row, ratio, box=22, bg=self.theme["chip"],
                                  stroke=self.theme["fg"])
        glyph.pack(side="left", padx=(8, 10), pady=5)
        acts = tk.Frame(row, bg=self.theme["chip"])
        acts.pack(side="right", padx=(0, 6))
        edit = self._size_action(acts, "pencil", "accent", t("Edit"),
                                 lambda: self._edit_custom_size(idx))
        edit.pack(side="left")
        dele = self._size_action(acts, "trash-2", "danger", t("Delete"),
                                 lambda: self._delete_custom_size(idx))
        dele.pack(side="left")
        txt = tk.Frame(row, bg=self.theme["chip"])
        txt.pack(side="left", fill="x", expand=True)
        t1 = tk.Label(txt, text=sz["name"] or self._size_dims(sz),
                      bg=self.theme["chip"], fg=self.theme["fg"], anchor="w",
                      font=("Segoe UI", 9))
        t1.pack(fill="x")
        t2 = tk.Label(txt, text=self._size_caption(sz), bg=self.theme["chip"],
                      fg=self.theme["fg_dim"], anchor="w", font=("Segoe UI", 7))
        t2.pack(fill="x")

        def paint(active):
            bg = self.theme["accent_soft"] if active else self.theme["chip"]
            for w in (row, txt, t2, acts):
                w.configure(bg=bg)
            t1.configure(bg=bg, fg=self.theme["on_accent"] if active else self.theme["fg"])
            glyph.configure(bg=bg)
            self._draw_ratio_glyph(glyph, ratio,
                                   self.theme["accent"] if active else self.theme["fg"])
            edit.configure(bg=bg)
            dele.configure(bg=bg)

        def hover(on):
            if row is self._crop_btn_active:
                return
            bg = self.theme["hover"] if on else self.theme["chip"]
            for w in (row, txt, t1, t2, acts, edit, dele):
                w.configure(bg=bg)
            glyph.configure(bg=bg)
            self._draw_ratio_glyph(glyph, ratio, self.theme["fg"])

        for w in (row, glyph, txt, t1, t2):
            w.bind("<Button-1>", lambda e: self._pick_simple(row, ratio))
            w.bind("<Enter>", lambda e: hover(True))
            w.bind("<Leave>", lambda e: hover(False))
        for w in (row, glyph, txt, t1, t2, acts, edit, dele):
            self._bind_sizes_wheel(w)
        self._size_selectors.append((row, paint))

    def _size_action(self, parent, icon_name, tint, tip, command):
        "A small edit/delete icon button inside a saved-size row (`tint` = the"
        " theme token its hover tints toward, e.g. 'accent' / 'danger')."
        img = self.icon(icon_name, size=13)
        chip = self.theme["chip"]
        if img is not None:
            b = tk.Label(parent, image=img, bg=chip, cursor="hand2")
            self._reg_icon(b, icon_name, size=13, token="fg")   # bg = row paint's
        else:
            b = tk.Label(parent, text="·", bg=chip, fg=self.theme["fg_dim"],
                         cursor="hand2")
        b.bind("<Button-1>", lambda e: command())
        b.bind("<Enter>", lambda e: b.configure(
            bg=tintkit.mix(self.theme["chip"], self.theme[tint], 0.35)))
        b.bind("<Leave>", lambda e: b.configure(bg=self.theme["chip"]))
        tintkit.HoverTip(b, self.theme, tip)
        return b

    # --- Saved-size formatting + CRUD ---------------------------------------

    @staticmethod
    def _num(x):
        "A stored dimension as a compact string (whole numbers drop the decimals)."
        return str(int(round(x))) if abs(x - round(x)) < 1e-6 else f"{x:g}"

    def _size_dims(self, sz):
        "The 'W × H' dimensions string for a saved size."
        return f"{self._num(sz['w'])} × {self._num(sz['h'])}"

    def _ratio_text(self, w, h):
        "A short ratio label: lowest-terms 'a:b' when whole, else a 2-dp decimal."
        if abs(w - round(w)) < 1e-6 and abs(h - round(h)) < 1e-6:
            iw, ih = int(round(w)), int(round(h))
            g = math.gcd(iw, ih) or 1
            return f"{iw // g}:{ih // g}"
        return f"{w / h:.2f}".rstrip("0").rstrip(".")

    def _size_caption(self, sz):
        "The dim line under a saved size's name: 'W × H · ratio'."
        return f"{self._size_dims(sz)} · {self._ratio_text(sz['w'], sz['h'])}"

    def _add_custom_size(self):
        "Open the create dialog; on save, add the size to the top of the list."
        res = self._ask_size_dialog("Create size", with_name=True)
        if res is None:
            return
        name, w, h = res
        self.crop_sizes.insert(0, {"name": name, "w": w, "h": h})
        self._save_state()
        self._rebuild_my_sizes_list()
        self._apply_size_index(0)         # select + lock the box to the new size

    def _edit_custom_size(self, idx):
        "Open the same dialog prefilled; on save, update that saved size in place."
        if not (0 <= idx < len(self.crop_sizes)):
            return
        sz = self.crop_sizes[idx]
        res = self._ask_size_dialog("Edit size", name=sz["name"],
                                    w=self._num(sz["w"]), h=self._num(sz["h"]),
                                    with_name=True)
        if res is None:
            return
        name, w, h = res
        self.crop_sizes[idx] = {"name": name, "w": w, "h": h}
        self._save_state()
        self._rebuild_my_sizes_list()
        self._apply_size_index(idx)

    def _delete_custom_size(self, idx):
        "Remove a saved size and clear the selection if it was the active one."
        if not (0 <= idx < len(self.crop_sizes)):
            return
        del self.crop_sizes[idx]
        self._save_state()
        self._crop_btn_active = None
        self._rebuild_my_sizes_list()
        self._restyle_crop_chips()

    def _apply_size_index(self, idx):
        "Highlight the saved-size row at `idx` and lock the crop box to its ratio."
        if not (0 <= idx < len(self._size_selectors)):
            return
        widget, _ = self._size_selectors[idx]
        sz = self.crop_sizes[idx]
        self._crop_btn_active = widget
        self._restyle_crop_chips()
        if self.current_pil is not None:
            self._set_crop_ratio(sz["w"] / sz["h"])

    # --- Pinned footer: Crop + Cancel ----------------------------------------
    # Crop/Cancel used to live inline at the bottom of the scrollable section
    # content, so opening the (now-foldable) Social networks / My sizes groups
    # pushed them down out of view. Same fix as the Filters manager's pinned
    # Create/Undo footer: built once in editpanel._build_edit_panel, OUTSIDE the
    # scroll canvas (before=self._sec_host), pinned just above the panel's
    # universal View original/Restore/Save footer, and shown only while the
    # crop tool is open (see _enter_crop / editpanel.set_section).

    def _build_crop_footer(self, panel):
        "Scaffold the pinned Crop/Cancel row; hidden until the crop tool opens."
        wrap = self._tw(tk.Frame(panel), bg="bar")
        wrap.pack(side="bottom", fill="x", before=self._sec_host)
        self._tw(tk.Frame(wrap, height=1), bg="divider").pack(side="top", fill="x")

        apply_btn = tintkit.Button(
            wrap, self.theme, t("Crop"), role="primary", variant="filled",
            stretch=True, bg="bar", command=self.apply_crop)
        apply_btn.pack(fill="x", padx=EDIT_PAD, pady=(8, 6))

        cancel = tintkit.Button(
            wrap, self.theme, t("Cancel"), role="neutral", variant="outline",
            icon="x", stretch=True, bg="bar", command=self._reset_crop)
        cancel.pack(fill="x", padx=EDIT_PAD, pady=(0, 8))
        tintkit.HoverTip(cancel.canvas, self.theme,
                         t("Reset the selection to the whole image"))

        self._crop_footer = wrap
        wrap.pack_forget()
        return wrap

    # --- Create / edit "Your size" dialog (same window for both) ------------

    def _ask_size_dialog(self, title, name="", w="", h="", with_name=True):
        "Modal dialog for a name + width:height. Returns (name, w, h) or None."
        # Modal (grab_set + wait_window) → can't outlive a theme switch, so read
        # the live theme once into locals (the nav/saving dialog pattern).
        bg, bar = self.theme["bg"], self.theme["bar"]
        fg, fg_dim = self.theme["fg"], self.theme["fg_dim"]
        result = {"val": None}
        dlg = tk.Toplevel(self.root)
        dlg.title(t(title))
        dlg.configure(bg=bg)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=bg, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=t(title), bg=bg, fg=fg,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(wrap, text=t("Name it and set width : height (pixels or a ratio, e.g. 4:5)."),
                 bg=bg, fg=fg_dim, font=("Segoe UI", 9), justify="left",
                 wraplength=300).pack(anchor="w", pady=(5, 14))

        e_name = None
        if with_name:
            tk.Label(wrap, text=t("Name"), bg=bg, fg=fg_dim,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")
            e_name = tk.Entry(wrap, bg=bar, fg=fg, insertbackground=fg,
                              relief="flat", font=("Segoe UI", 11))
            e_name.insert(0, name)
            e_name.pack(fill="x", ipady=5, pady=(4, 12))

        tk.Label(wrap, text=t("Size — Width : Height"), bg=bg, fg=fg_dim,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 4))
        row = tk.Frame(wrap, bg=bg)
        row.pack(anchor="w")

        def mkentry(value):
            e = tk.Entry(row, bg=bar, fg=fg, insertbackground=fg, width=6,
                         relief="flat", justify="center", font=("Segoe UI", 12))
            e.insert(0, value)
            return e

        # Prefill the size: explicit value (edit), else the current box (create).
        w0, h0 = str(w), str(h)
        if not w0 and not h0 and self.crop_rect is not None:
            w0 = str(int(round(self.crop_rect[2] - self.crop_rect[0])))
            h0 = str(int(round(self.crop_rect[3] - self.crop_rect[1])))
        e_w = mkentry(w0); e_w.pack(side="left", ipady=4)
        tk.Label(row, text=":", bg=bg, fg=fg,
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=8)
        e_h = mkentry(h0); e_h.pack(side="left", ipady=4)

        err = tk.Label(wrap, text="", bg=bg, fg=self.theme["danger"],
                       font=("Segoe UI", 8))
        err.pack(anchor="w", pady=(8, 0))

        def confirm():
            try:
                cw = float(e_w.get().replace(",", "."))
                ch = float(e_h.get().replace(",", "."))
            except ValueError:
                err.configure(text=t("Enter two positive numbers"))
                return
            if cw <= 0 or ch <= 0:
                err.configure(text=t("Numbers must be positive"))
                return
            nm = e_name.get().strip() if e_name is not None else ""
            if with_name and not nm:           # default name = the dimensions
                nm = f"{self._num(cw)} × {self._num(ch)}"
            result["val"] = (nm, cw, ch)
            dlg.destroy()

        btnrow = tk.Frame(wrap, bg=bg)
        btnrow.pack(anchor="e", pady=(14, 0))

        self._dialog_btn(btnrow, t("Cancel"), dlg.destroy).pack(
            side="right", padx=(8, 0))
        self._dialog_btn(btnrow, t("Save"), confirm, primary=True).pack(
            side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Return>", lambda e: confirm())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        (e_name or e_w).focus_set()
        if e_name is not None:
            e_name.select_range(0, "end")
        else:
            e_w.select_range(0, "end")

        center_over(self.root, dlg)
        dlg.grab_set()
        dlg.focus_set()
        self.root.wait_window(dlg)
        return result["val"]

    def _set_crop_ratio(self, ratio):
        "Lock the crop box to an aspect ratio (None = free) and reshape it to fit."
        self.crop_ratio = ratio
        if self.current_pil is None:
            return
        if self.straighten:               # tilt active → inscribe the ratio box
            self._straighten_box()
            self._render_preview()
            return
        iw, ih = self.current_pil.size
        if ratio is None:
            if self.crop_rect is None:
                self.crop_rect = [0.0, 0.0, float(iw), float(ih)]
            self._render_preview()
            return
        # Largest box of this ratio, centered in the image.
        if iw / ih > ratio:
            h = float(ih); w = h * ratio
        else:
            w = float(iw); h = w / ratio
        x0 = (iw - w) / 2.0
        y0 = (ih - h) / 2.0
        self.crop_rect = [x0, y0, x0 + w, y0 + h]
        self._render_preview()

    def _flip_crop_ratio(self):
        "Rotate the crop 90°: swap its width↔height (and any locked ratio) in place."
        if self.current_pil is None or self.crop_rect is None:
            return
        if self.straighten:               # tilt active → flip ratio, re-inscribe
            if self.crop_ratio:
                self.crop_ratio = 1.0 / self.crop_ratio
            self._straighten_box()
            self._render_preview()
            return
        if self.crop_ratio:
            self.crop_ratio = 1.0 / self.crop_ratio
        iw, ih = self.current_pil.size
        x0, y0, x1, y1 = self.crop_rect
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        nw, nh = (y1 - y0), (x1 - x0)            # swapped dimensions
        nw = min(nw, float(iw))                  # fit inside the image...
        nh = min(nh, float(ih))
        if self.crop_ratio:                      # ...while keeping the locked ratio
            if nw / nh > self.crop_ratio:
                nw = nh * self.crop_ratio
            else:
                nh = nw / self.crop_ratio
        nx0 = max(0.0, min(cx - nw / 2.0, iw - nw))
        ny0 = max(0.0, min(cy - nh / 2.0, ih - nh))
        self.crop_rect = [nx0, ny0, nx0 + nw, ny0 + nh]
        # The shown ratio changed, so a named preset chip no longer matches it.
        self._crop_btn_active = None
        self._restyle_crop_chips()
        self._render_preview()

    def _reset_crop(self):
        "Clear the selection back to the whole image (free ratio)."
        if self.current_pil is None:
            return
        iw, ih = self.current_pil.size
        self.crop_rect = [0.0, 0.0, float(iw), float(ih)]
        self.crop_ratio = None
        self._crop_btn_active = None
        self._restyle_crop_chips()
        self._reset_straighten()         # cancel drops any pending tilt too
        self._render_preview()

    def _enter_crop(self):
        "Open the crop tool: start a full-image box and fit the photo to see it all."
        self._crop_footer.pack(side="bottom", fill="x", before=self._sec_host)
        if self.current_pil is None:
            self._render_preview()
            return
        if self.crop_rect is None:
            iw, ih = self.current_pil.size
            self.crop_rect = [0.0, 0.0, float(iw), float(ih)]
        if self.straighten:              # a pending tilt → re-fit its inscribed box
            self._straighten_box()
        self.preview.configure(cursor="crosshair")
        self.fit_view()          # fit + recenter + render (shows the overlay)

    def apply_crop(self):
        "Crop current_pil to the selection (in memory; written out via Save)."
        if self.current_pil is None or self.crop_rect is None:
            return
        angle = self.straighten
        iw, ih = self.current_pil.size
        x0, y0, x1, y1 = self.crop_rect
        box = (max(0, int(round(x0))), max(0, int(round(y0))),
               min(iw, int(round(x1))), min(ih, int(round(y1))))
        playing = getattr(self, "_playing", False)
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            if not playing:
                self.toast(t("The crop area is too small"))
            return
        if box == (0, 0, iw, ih) and not angle:
            if not playing:
                self.toast(t("The whole image is selected — nothing changes"))
            return
        # A straighten isn't recorded by Actions yet (like rotate/resize), so a
        # plain crop step would replay without the tilt — skip recording then.
        if getattr(self, "_recording", False) and not angle:
            self._record_crop_step(box, iw, ih)   # capture as a macro step
        before_geom = self._geometry_snapshot()   # for one-step undo of the crop
        if angle:                          # bake the tilt, then crop the corners off
            self.current_pil = self._rotate_keep_size(self.current_pil, angle)
        self.current_pil = self.current_pil.crop(box)
        if self._before_pil is not None:   # keep the compare "before" aligned to the edit
            if angle:
                self._before_pil = self._rotate_keep_size(self._before_pil, angle)
            self._before_pil = self._before_pil.crop(box)
            self._before_base_key = None
        self._reset_straighten()           # the tilt is now baked in
        self._cropped = True
        self._clear_focus_for_geometry()  # source-px circle no longer maps after a crop
        self._clear_text_for_geometry()   # …and the source-px text position no longer maps
        self._clear_logo_for_geometry()   # …and the source-px logo position no longer maps
        self._edits_saved = False
        nw, nh = self.current_pil.size
        # Reset the box to the new full image; ready for a second crop.
        self.crop_rect = [0.0, 0.0, float(nw), float(nh)]
        self.crop_ratio = None
        self._crop_btn_active = None
        self._restyle_crop_chips()
        self.fit_mode = True
        self.pan_x = self.pan_y = 0.0
        self._view_key = None       # size changed → drop the cached scaled view
        self._render_preview()
        self._update_info(os.path.join(self.folder, self.files[self.index]))
        self._record_geometry(before_geom)   # crop / straighten is now undoable
        if not playing:
            self.toast(t("Cropped → {w}×{h}px  ·  Save to write it to a file").format(w=nw, h=nh))

    # --- Crop overlay geometry + mouse interaction --------------------------

    CROP_HANDLE = 6    # half-size of a handle square, logical px (DPI-scaled)
    CROP_MIN    = 16   # smallest crop side, in source px
    _CROP_CURSORS = {"nw": "top_left_corner", "se": "bottom_right_corner",
                     "ne": "top_right_corner", "sw": "bottom_left_corner",
                     "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
                     "w": "sb_h_double_arrow", "e": "sb_h_double_arrow",
                     "move": "fleur"}

    def _crop_active(self):
        "True when the crop tool is open and a box exists (drives overlay + clicks)."
        return (self.panel_open and self.active_section == "crop"
                and self.current_pil is not None and self.crop_rect is not None)

    def _src_to_scr(self, sx, sy):
        "Source-pixel (sx, sy) → screen (x, y), using the last render transform."
        scale, ox, oy = self._disp
        return ox + sx * scale, oy + sy * scale

    def _scr_to_src(self, x, y):
        "Screen (x, y) → source-pixel (sx, sy), using the last render transform."
        scale, ox, oy = self._disp
        scale = scale or 1.0
        return (x - ox) / scale, (y - oy) / scale

    def _crop_handles(self):
        "Map handle name → screen (x, y). Corners always; edges only when free."
        x0, y0 = self._src_to_scr(self.crop_rect[0], self.crop_rect[1])
        x1, y1 = self._src_to_scr(self.crop_rect[2], self.crop_rect[3])
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        h = {"nw": (x0, y0), "ne": (x1, y0), "se": (x1, y1), "sw": (x0, y1)}
        if self.crop_ratio is None:
            h.update({"n": (mx, y0), "s": (mx, y1), "w": (x0, my), "e": (x1, my)})
        return h

    def _crop_hit(self, x, y):
        "Handle/'move' under screen (x, y), or None. Handles take priority."
        tol = self._edit_dpi_w(self.CROP_HANDLE + 4)
        for mode, (hx, hy) in self._crop_handles().items():
            if abs(x - hx) <= tol and abs(y - hy) <= tol:
                return mode
        x0, y0 = self._src_to_scr(self.crop_rect[0], self.crop_rect[1])
        x1, y1 = self._src_to_scr(self.crop_rect[2], self.crop_rect[3])
        if x0 <= x <= x1 and y0 <= y <= y1:
            return "move"
        return None

    def _crop_anchor_for(self, mode):
        "The fixed corner a corner-handle drag pivots around (the opposite corner)."
        x0, y0, x1, y1 = self.crop_rect
        return {"nw": (x1, y1), "ne": (x0, y1),
                "se": (x0, y0), "sw": (x1, y0)}[mode]

    def _corner_box(self, ax, ay, mx, my):
        "Box from fixed anchor corner (ax,ay) toward moving point (mx,my)."
        iw, ih = self.current_pil.size
        r = self.crop_ratio
        if r:
            dirx = 1.0 if mx >= ax else -1.0
            diry = 1.0 if my >= ay else -1.0
            maxw = (iw - ax) if dirx > 0 else ax
            maxh = (ih - ay) if diry > 0 else ay
            w = max(abs(mx - ax), abs(my - ay) * r)   # follow the dominant axis
            w = min(w, maxw, maxh * r)
            w = max(w, self.CROP_MIN)
            h = w / r
            xo, yo = ax + dirx * w, ay + diry * h
        else:
            xo, yo = mx, my
            if abs(xo - ax) < self.CROP_MIN:
                xo = ax + (self.CROP_MIN if xo >= ax else -self.CROP_MIN)
            if abs(yo - ay) < self.CROP_MIN:
                yo = ay + (self.CROP_MIN if yo >= ay else -self.CROP_MIN)
        x0, x1 = sorted((ax, xo))
        y0, y1 = sorted((ay, yo))
        return [max(0.0, x0), max(0.0, y0),
                min(float(iw), x1), min(float(ih), y1)]

    def _edge_resize(self, mode, sx, sy):
        "Free-ratio edge drag: move one edge to (sx, sy), keeping a minimum size."
        x0, y0, x1, y1 = self.crop_rect
        if mode == "n":
            y0 = min(sy, y1 - self.CROP_MIN)
        elif mode == "s":
            y1 = max(sy, y0 + self.CROP_MIN)
        elif mode == "w":
            x0 = min(sx, x1 - self.CROP_MIN)
        elif mode == "e":
            x1 = max(sx, x0 + self.CROP_MIN)
        self.crop_rect = [x0, y0, x1, y1]

    def _crop_press(self, event):
        "Begin a crop drag: grab a handle, the box body (move), or draw a fresh box."
        if not self._crop_active():
            return
        if self.straighten:               # while tilting, the auto box owns the frame
            return "break"
        hit = self._crop_hit(event.x, event.y)
        sx, sy = self._scr_to_src(event.x, event.y)
        if hit == "move":
            self._crop_drag = ("move", event.x, event.y, list(self.crop_rect))
        elif hit in ("nw", "ne", "se", "sw"):
            self._crop_drag = (hit, self._crop_anchor_for(hit))
        elif hit in ("n", "s", "w", "e"):
            self._crop_drag = (hit, None)
        else:
            iw, ih = self.current_pil.size
            if 0 <= sx <= iw and 0 <= sy <= ih:     # rubber-band a new box
                self._crop_drag = ("se", (sx, sy))
                self.crop_rect = [sx, sy, sx, sy]
                self._render_preview()
        return "break"

    def _crop_move(self, event):
        "Drag in progress: move/resize the box, then repaint the overlay."
        if self._crop_drag is None:
            return
        mode = self._crop_drag[0]
        iw, ih = self.current_pil.size
        sx, sy = self._scr_to_src(event.x, event.y)
        sx = max(0.0, min(float(iw), sx))
        sy = max(0.0, min(float(ih), sy))
        if mode == "move":
            _, px, py, base = self._crop_drag
            opx, opy = self._scr_to_src(px, py)
            csx, csy = self._scr_to_src(event.x, event.y)
            dx, dy = csx - opx, csy - opy
            w, h = base[2] - base[0], base[3] - base[1]
            nx0 = min(max(0.0, base[0] + dx), iw - w)
            ny0 = min(max(0.0, base[1] + dy), ih - h)
            self.crop_rect = [nx0, ny0, nx0 + w, ny0 + h]
        elif mode in ("nw", "ne", "se", "sw"):
            ax, ay = self._crop_drag[1]
            self.crop_rect = self._corner_box(ax, ay, sx, sy)
        else:
            self._edge_resize(mode, sx, sy)
        self._render_preview()
        return "break"

    def _crop_release(self, event):
        "End the drag (the box stays as drawn; nothing is committed until Crop)."
        if self._crop_drag is None:
            return
        self._crop_drag = None
        return "break"

    def _crop_hover(self, event):
        "Show the right resize/move cursor while hovering over the crop box."
        if not self._crop_active() or self._crop_drag is not None:
            return
        if self.straighten:               # auto box: no resize/move handles
            self.preview.configure(cursor="crosshair")
            return
        hit = self._crop_hit(event.x, event.y)
        self.preview.configure(cursor=self._CROP_CURSORS.get(hit, "crosshair"))

    def _draw_crop_overlay(self):
        "Dim outside the crop box; draw its border, thirds grid and handles."
        c = self.preview
        iw, ih = self.current_pil.size
        ix0, iy0 = self._src_to_scr(0, 0)
        ix1, iy1 = self._src_to_scr(iw, ih)
        x0, y0 = self._src_to_scr(self.crop_rect[0], self.crop_rect[1])
        x1, y1 = self._src_to_scr(self.crop_rect[2], self.crop_rect[3])
        dim = dict(fill="#000000", stipple="gray50", outline="")
        c.create_rectangle(ix0, iy0, ix1, y0, **dim)   # above the box
        c.create_rectangle(ix0, y1, ix1, iy1, **dim)   # below the box
        c.create_rectangle(ix0, y0, x0, y1, **dim)     # left of the box
        c.create_rectangle(x1, y0, ix1, y1, **dim)     # right of the box
        for k in (1, 2):                               # rule-of-thirds guides
            gx = x0 + (x1 - x0) * k / 3
            gy = y0 + (y1 - y0) * k / 3
            c.create_line(gx, y0, gx, y1, fill="#ffffff", stipple="gray25")
            c.create_line(x0, gy, x1, gy, fill="#ffffff", stipple="gray25")
        c.create_rectangle(x0, y0, x1, y1, outline="#ffffff",
                           width=max(1, self._edit_dpi_w(1.4)))
        if self.straighten:           # tilting: the box is auto-fitted, no handles
            return
        r = self._edit_dpi_w(self.CROP_HANDLE)
        for hx, hy in self._crop_handles().values():
            c.create_rectangle(hx - r, hy - r, hx + r, hy + r,
                               fill=ACCENT, outline=ON_ACCENT)
