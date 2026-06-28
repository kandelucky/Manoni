"""The edit area: section panel + icon rail, the sliders, auto tone, and the
edit undo bookkeeping.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import tkinter as tk

from ..config import (BAR, HOVER, ACCENT, FG, FG_DIM,
                      EDIT_PANEL_W, EDIT_RAIL_W, EDIT_PAD, CHIP_GAP,
                      ON_ACCENT, ACCENT_HOVER, CHIP_BG, BORDER, DIVIDER)
from .. import imaging
from ..widgets import Slider, Tooltip
from ..i18n import t


class EditPanelMixin:
    # --- Edit panel (below the preview) -------------------------------------

    # --- Edit area: Fotor-style section panel (col 2) + icon rail (col 3) ----

    # The rail's selectable tools and their blue-header titles (Save is a
    # separate bottom action, not a section, so it is not listed here).
    SECTION_TITLES = {"basic": "Basic Edits", "crop": "Crop", "resize": "Resize",
                      "heal": "Heal & Clone", "focus": "Focus blur",
                      "color": "Color mixer",
                      "effects": "Effects", "filters": "Filters",
                      "actions": "Actions"}

    def _edit_dpi_w(self, logical):
        "Logical px → physical px for the edit area (so DPI-scaled text fits)."
        return round(logical * getattr(self, "dpi", 1.0))

    def _build_edit_panel(self, parent):
        "Section panel (col 3): a blue Fotor header + the active tool's controls."
        # Fixed width for ALL sections: pack_propagate(False) (the children are
        # packed, so grid_propagate would be a no-op) stops the panel shrinking /
        # growing to whichever tool's content is open. Width is DPI-scaled so the
        # (DPI-scaled) labels fit the same at any Windows scaling.
        panel = tk.Frame(parent, bg=BAR, width=self._edit_dpi_w(EDIT_PANEL_W))
        panel.grid(row=0, column=3, rowspan=3, sticky="ns")   # full height: clips the strips
        panel.pack_propagate(False)
        self.edit_panel = panel
        if not self.panel_open:      # hidden until the toolbar toggle opens it
            panel.grid_remove()

        # Blue header that names the open section (Fotor "Basic Edits" tab look).
        self.section_title = tk.Label(panel, text=t(self.SECTION_TITLES["basic"]),
                                      bg=ACCENT, fg=ON_ACCENT, anchor="w",
                                      font=("Segoe UI", 10, "bold"),
                                      padx=14, pady=8)
        self.section_title.pack(side="top", fill="x")

        # One swappable content frame per section, stacked in this holder.
        self.section_content = tk.Frame(panel, bg=BAR)
        self.section_content.pack(side="top", fill="both", expand=True)
        self.sections = {
            "basic":   self._build_basic_section(self.section_content),
            "crop":    self._build_crop_section(self.section_content),
            "resize":  self._build_resize_section(self.section_content),
            "heal":    self._build_heal_section(self.section_content),
            "focus":   self._build_focus_section(self.section_content),
            "color":   self._build_color_section(self.section_content),
            "effects": self._build_effects_section(self.section_content),
            "filters": self._build_filters_section(self.section_content),
            "actions": self._build_actions_section(self.section_content),
        }
        self.sections[self.active_section].pack(fill="both", expand=True)

    def _build_basic_section(self, parent):
        "Basic Edits: auto-fix buttons + grouped live sliders (Photoshop order)."
        f = tk.Frame(parent, bg=BAR)

        # Auto corrections at the very top, like Photoshop's Auto Levels / Auto
        # Contrast. They are mutually exclusive one-click toggles.
        self.auto_buttons = {}
        autobar = tk.Frame(f, bg=BAR)
        autobar.pack(fill="x", padx=EDIT_PAD, pady=(10, 2))
        autobar.columnconfigure(0, weight=1, uniform="auto")
        autobar.columnconfigure(1, weight=1, uniform="auto")
        self._auto_btn(autobar, t("Auto level"), "levels", 0,
                       t("Auto-correct color balance (each channel stretched separately)"))
        self._auto_btn(autobar, t("Auto contrast"), "contrast", 1,
                       t("Auto-correct contrast (color stays unchanged)"))

        # Photoshop order: white balance at the very top, then tone, then detail.
        # Each group is split off with its own header so the sliders read as
        # distinct sections rather than one long glued strip.
        self._group_header(f, t("White balance"))
        self.s_temp       = self._slider(f, t("Temperature"), "temperature")
        self.s_tint       = self._slider(f, t("Tint"), "tint")

        self._group_header(f, t("Tone"))
        self.s_exposure   = self._slider(f, t("Exposure"), "brightness")
        self.s_contrast   = self._slider(f, t("Contrast"), "contrast")
        self.s_highlights = self._slider(f, t("Highlights"), "highlights")
        self.s_shadows    = self._slider(f, t("Shadows"), "shadows")
        self.s_whites     = self._slider(f, t("Whites"), "whites")
        self.s_blacks     = self._slider(f, t("Blacks"), "blacks")

        self._group_header(f, t("Detail & Color"))
        self.s_clarity    = self._slider(f, t("Clarity"), "clarity")
        self.s_vibrance   = self._slider(f, t("Vibrance"), "vibrance")
        self.s_color      = self._slider(f, t("Color"), "color")
        self.s_texture    = self._slider(f, t("Texture"), "texture")
        self.s_sharpen    = self._slider(f, t("Sharpen"), "sharpen")
        self.sliders = {"brightness": self.s_exposure,
                        "contrast": self.s_contrast,
                        "highlights": self.s_highlights,
                        "shadows": self.s_shadows,
                        "whites": self.s_whites,
                        "blacks": self.s_blacks,
                        "clarity": self.s_clarity,
                        "vibrance": self.s_vibrance,
                        "color": self.s_color,
                        "texture": self.s_texture,
                        "sharpen": self.s_sharpen,
                        "temperature": self.s_temp,
                        "tint": self.s_tint}

        self._clear_button(f)
        return f

    def _group_header(self, parent, text):
        "A thin divider + small bold caption that splits the basic sliders into"
        " Photoshop-style groups (white balance / tone / detail) instead of one"
        " glued strip."
        tk.Frame(parent, bg=DIVIDER, height=1).pack(fill="x", padx=EDIT_PAD,
                                                       pady=(12, 0))
        tk.Label(parent, text=text, bg=BAR, fg=FG_DIM, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=EDIT_PAD,
                                                    pady=(4, 2))

    def _auto_btn(self, parent, text, mode, col, tip):
        "One auto-correction toggle button (accent-filled while its mode is on)."
        b = tk.Label(parent, text=text, bg=CHIP_BG, fg=FG, cursor="hand2",
                     font=("Segoe UI", 8, "bold"), padx=4, pady=6)
        b._mode = mode
        pad = (0, CHIP_GAP // 2) if col == 0 else (CHIP_GAP // 2, 0)
        b.grid(row=0, column=col, sticky="ew", padx=pad)
        b.bind("<Button-1>", lambda e, m=mode: self._set_auto(m))
        b.bind("<Enter>", lambda e, w=b: self._auto_btn_hover(w, True))
        b.bind("<Leave>", lambda e, w=b: self._auto_btn_hover(w, False))
        b._tip = Tooltip(b, tip)
        self.auto_buttons[mode] = b

    def _auto_btn_hover(self, btn, entering):
        "Brighten an auto button on hover; the active one keeps its accent fill."
        if btn._mode == self.auto_mode:
            return
        btn.configure(bg=HOVER if entering else CHIP_BG)

    def _refresh_auto_buttons(self):
        "Repaint the auto buttons so the active mode is accent-filled, rest neutral."
        if not hasattr(self, "auto_buttons"):
            return
        for mode, btn in self.auto_buttons.items():
            active = (mode == self.auto_mode)
            btn.configure(bg=ACCENT if active else CHIP_BG,
                          fg=ON_ACCENT if active else FG)

    def _build_effects_section(self, parent):
        "Effects: creative looks, each a 0→full strength slider. B&W + sepia +"
        " vignette now; grain next. They share the edit pipeline, undo and reset."
        f = tk.Frame(parent, bg=BAR)
        # Effects rest at 0 (off): hi=100, neutral=0 → strength 0.0–1.0.
        self.s_bw = self._slider(f, t("Black & White"), "bw", hi=100, neutral=0)
        self.sliders["bw"] = self.s_bw   # join the shared reset / undo machinery
        # Sepia: a warm-toned monochrome — grouped with B&W (both desaturating looks).
        self.s_sepia = self._slider(f, t("Sepia"), "sepia", hi=100, neutral=0)
        self.sliders["sepia"] = self.s_sepia
        # Bidirectional (centred at 0): left lightens the corners, right darkens.
        self.s_vignette = self._slider(f, t("Vignette"), "vignette")
        self.sliders["vignette"] = self.s_vignette

        self._clear_button(f)
        return f

    # The eight HSL bands: (attr, label) in the warm→cool order they sit on the
    # hue wheel, matching imaging.HSL_BANDS. A small colour chip is drawn beside
    # each so the band reads at a glance.
    COLOR_BANDS = [
        ("sat_red",     "Red",     "#e0564f"),
        ("sat_orange",  "Orange",  "#e08a3c"),
        ("sat_yellow",  "Yellow",  "#d9c13a"),
        ("sat_green",   "Green",   "#5fb85f"),
        ("sat_aqua",    "Aqua",    "#4fc2c2"),
        ("sat_blue",    "Blue",    "#5a8fe0"),
        ("sat_purple",  "Purple",  "#9b7ad6"),
        ("sat_magenta", "Magenta", "#d066b0"),
    ]

    def _build_color_section(self, parent):
        "Color mixer (HSL): per-hue saturation for the eight bands, plus a"
        " separate 'gold shine'. Each slider strengthens (right) or weakens"
        " (left) just that colour; they share the edit pipeline, undo and reset."
        f = tk.Frame(parent, bg=BAR)

        self._group_header(f, t("Saturation"))
        for attr, label, chip in self.COLOR_BANDS:
            self.sliders[attr] = self._color_slider(f, t(label), attr, chip)

        # Gold gets its own three-slider mini-HSL — the special treatment for
        # golden tones, unlike the plain (saturation-only) bands above.
        self._group_header(f, t("Gold"))
        self.sliders["gold_hue"] = self._color_slider(
            f, t("Gold hue"), "gold_hue", "#d4af37")
        self.sliders["gold_sat"] = self._color_slider(
            f, t("Gold saturation"), "gold_sat", "#d4af37")
        self.sliders["gold_light"] = self._color_slider(
            f, t("Gold shine"), "gold_light", "#d4af37")

        # Skin: the same targeted mini-HSL for skin tones (hue + saturation gated
        # so only skin moves, not the warm walls behind it).
        self._group_header(f, t("Skin"))
        self.sliders["skin_hue"] = self._color_slider(
            f, t("Skin hue"), "skin_hue", "#e0ac8b")
        self.sliders["skin_sat"] = self._color_slider(
            f, t("Skin saturation"), "skin_sat", "#e0ac8b")
        self.sliders["skin_light"] = self._color_slider(
            f, t("Skin brightness"), "skin_light", "#e0ac8b")

        self._clear_button(f)
        return f

    def _color_slider(self, parent, label, attr, chip):
        "A labeled live slider with a small colour chip, its own reset button."
        row = tk.Frame(parent, bg=BAR)
        row.pack(fill="x", padx=EDIT_PAD, pady=2)
        sw = tk.Frame(row, bg=chip, width=self._edit_dpi_w(10),
                      height=self._edit_dpi_w(10))
        sw.pack(side="left", padx=(0, 6))
        sw.pack_propagate(False)
        s = Slider(row, label, lambda v, a=attr: self._on_slider(a, v),
                   lo=0, hi=200, neutral=100,
                   on_press=self._edit_gesture_start,
                   on_release=self._edit_gesture_end)
        s.pack(side="left", fill="x", expand=True)
        self._slider_reset_button(row, attr).pack(side="right", padx=(6, 0))
        return s

    # --- Tool rail (col 4): vertical labeled icon buttons, Fotor-style -------

    def _build_tool_rail(self, parent):
        "Always-visible icon rail: a collapse chevron on top, then the tool icons"
        " (click one to open the panel to it); Save pinned to the bottom."
        rail = tk.Frame(parent, bg=BAR, width=self._edit_dpi_w(EDIT_RAIL_W))
        rail.grid(row=0, column=4, rowspan=3, sticky="ns")   # full height: clips the strips
        rail.pack_propagate(False)   # children are packed → fix the width here
        self.rail = rail   # the rail itself never hides; only edit_panel collapses

        self.rail_buttons = {}   # section key -> cell frame (for active highlight)
        top = tk.Frame(rail, bg=BAR)
        top.pack(side="top", fill="x", pady=(8, 0))

        # Collapse chevron: '<' (panel closed) opens it, '>' (panel open) closes
        # it. The slider panel slides out to the LEFT of this rail.
        self.btn_chevron = self._tool_button(
            top, "chevron-left", self.toggle_panel, t("Open / collapse the panel"))
        self.btn_chevron.pack(side="top", pady=(0, 6))
        tk.Frame(top, bg=BORDER, height=1).pack(side="top", fill="x",
                                                   padx=12, pady=(0, 6))

        for key, icon_name, label in [
            ("basic",   "sliders-horizontal", "Basic Edit"),
            ("crop",    "crop",               "Crop"),
            ("resize",  "scaling",            "Resize"),
            ("heal",    "bandage",            "Heal"),
            ("focus",   "aperture",           "Blur"),
            ("color",   "droplets",           "Colors"),
            ("effects", "wand-sparkles",      "Effects"),
            ("filters", "palette",            "Filters"),
            ("actions", "clapperboard",       "Actions"),
        ]:
            self._rail_button(top, icon_name, label, key=key)

        # Quick save (one click, no dialog) — pinned to the bottom like Fotor, as
        # one accent button that spans the FULL rail width (the primary action).
        # "Save as…" with all the options lives in the ☰ menu instead.
        self._build_save_button(rail)

        self._update_rail()
        self._update_chevron()

    def _build_save_button(self, rail):
        "A full-width accent Save button pinned to the rail foot (icon over label)."
        wrap = tk.Frame(rail, bg=BAR)
        wrap.pack(side="bottom", fill="x")
        tk.Frame(wrap, bg=BORDER, height=1).pack(side="top", fill="x")

        btn = tk.Frame(wrap, bg=ACCENT, cursor="hand2")
        btn.pack(side="top", fill="x")
        img = self.icon("save")
        if img is not None:
            ic = tk.Label(btn, image=img, bg=ACCENT)
        else:
            ic = tk.Label(btn, text="💾", bg=ACCENT, fg=ON_ACCENT,
                          font=("Segoe UI", 14))
        ic.pack(pady=(8, 2))
        tx = tk.Label(btn, text=t("Save"), bg=ACCENT, fg=ON_ACCENT,
                      font=("Segoe UI", 8, "bold"))
        tx.pack(pady=(0, 8))
        for w in (btn, ic, tx):
            w.bind("<Button-1>", lambda e: self.quick_save())
            w.bind("<Enter>", lambda e: [c.configure(bg=ACCENT_HOVER)
                                         for c in (btn, ic, tx)])
            w.bind("<Leave>", lambda e: [c.configure(bg=ACCENT)
                                         for c in (btn, ic, tx)])
        btn._tip = Tooltip(btn, t("Save"))

    def _set_panel(self, open_):
        "Show or hide the slider panel (col 3). The icon rail stays put."
        if open_ == self.panel_open:
            return
        self.panel_open = open_
        if open_:
            self.edit_panel.grid()
        else:
            self.edit_panel.grid_remove()
            self.preview.configure(cursor="")   # leave crop cursor behind
        self._update_chevron()
        # The preview just changed width; re-fit on the next idle layout pass.
        self._view_key = None
        self.root.after_idle(self._render_preview)

    def toggle_panel(self):
        "Chevron action: flip the slider panel open/closed."
        self._set_panel(not self.panel_open)

    def open_panel(self):
        "Open the slider panel (used when a tool icon is clicked)."
        self._set_panel(True)

    def _update_chevron(self):
        "Point the chevron: '<' (chevron-left) opens, '>' (chevron-right) closes."
        img = self.icon("chevron-right" if self.panel_open else "chevron-left")
        if img is not None:
            self.btn_chevron.configure(image=img)

    def _rail_button(self, parent, icon_name, label, key=None, command=None):
        "One rail cell: icon stacked over a label. key = selectable section."
        cell = tk.Frame(parent, bg=BAR, cursor="hand2")
        cell.pack(side="top", fill="x", pady=2)
        img = self.icon(icon_name)
        if img is not None:
            ic = tk.Label(cell, image=img, bg=BAR)
        else:
            ic = tk.Label(cell, text="□", bg=BAR, fg=FG, font=("Segoe UI", 14))
        ic.pack(pady=(8, 2))
        tx = tk.Label(cell, text=t(label), bg=BAR, fg=FG_DIM, font=("Segoe UI", 8))
        tx.pack(pady=(0, 8))
        cell._widgets = (ic, tx)

        def on_click(_e=None):
            if key is not None:
                self.open_panel()      # ensure the panel is visible...
                self.set_section(key)  # ...then show this tool's section
            if command is not None:
                command()
        for w in (cell, ic, tx):
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", lambda e, c=cell, k=key: self._rail_hover(c, k, True))
            w.bind("<Leave>", lambda e, c=cell, k=key: self._rail_hover(c, k, False))
        if key is not None:
            self.rail_buttons[key] = cell
        return cell

    def _rail_hover(self, cell, key, entering):
        "Brighten a rail cell on hover; the active section keeps its accent fill."
        if key is not None and key == self.active_section:
            return
        bg = HOVER if entering else BAR
        fg = FG if entering else FG_DIM
        ic, tx = cell._widgets
        cell.configure(bg=bg)
        ic.configure(bg=bg)
        tx.configure(bg=bg, fg=fg)

    def set_section(self, key):
        "Open a tool section: swap the panel content, update header + rail highlight."
        if key not in self.sections:
            return
        self._set_hand_tool(False)   # an edit tool claims the left button — release the hand
        if key in ("crop", "heal", "focus"):
            self._set_compare(False)  # these need the canvas drag — compare can't intercept it
        self.active_section = key
        for k, frame in self.sections.items():
            if k == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        self.section_title.configure(text=t(self.SECTION_TITLES[key]))
        self._update_rail()
        if key == "crop":
            self._enter_crop()       # init a box + fit so the whole photo is seen
        elif key == "resize":
            self._enter_resize()     # refresh the size readout from the current photo
        elif key == "heal":
            self._enter_heal()       # show the brush cursor + ring
        elif key == "focus":
            self._enter_focus()      # place the focus circle + fit to see it all
        elif key == "actions":
            self._enter_actions()    # refresh the recorder + saved-action list
        else:
            self.preview.configure(cursor="")
            self._render_preview()   # repaint without the crop/heal/focus overlay

    def _update_rail(self):
        "Fill the active section's rail cell with the accent colour; dim the rest."
        for k, cell in self.rail_buttons.items():
            active = (k == self.active_section)
            bg = ACCENT if active else BAR
            fg = ON_ACCENT if active else FG_DIM
            ic, tx = cell._widgets
            cell.configure(bg=bg)
            ic.configure(bg=bg)
            tx.configure(bg=bg, fg=fg)

    def _slider(self, parent, label, attr, lo=0, hi=200, neutral=100):
        "A labeled live slider + its own reset button, bound to an attribute."
        " Default 0–200 → factor 0.0–2.0 (neutral 1.0). Effects pass hi=100,"
        " neutral=0 → 0.0–1.0 (off→full)."
        # Slider and its reset button share one row so the button sits to the
        # right of the track; the slider expands to fill the rest of the width.
        row = tk.Frame(parent, bg=BAR)
        row.pack(fill="x", padx=EDIT_PAD, pady=2)
        s = Slider(row, label, lambda v, a=attr: self._on_slider(a, v),
                   lo=lo, hi=hi, neutral=neutral,
                   on_press=self._edit_gesture_start,
                   on_release=self._edit_gesture_end)
        s.pack(side="left", fill="x", expand=True)
        self._slider_reset_button(row, attr).pack(side="right", padx=(6, 0))
        return s

    def _slider_reset_button(self, parent, attr):
        "A small reset icon that returns just this slider to neutral (undoable)."
        img = self.icon("rotate-ccw", size=14)
        if img is not None:
            b = tk.Label(parent, image=img, bg=BAR, cursor="hand2")
        else:
            b = tk.Label(parent, text="↺", bg=BAR, fg=FG_DIM, cursor="hand2",
                         font=("Segoe UI", 11))
        b.bind("<Enter>", lambda e: b.configure(bg=HOVER))
        b.bind("<Leave>", lambda e: b.configure(bg=BAR))
        b.bind("<Button-1>", lambda e, a=attr: self._reset_slider(a))
        b._tip = Tooltip(b, t("Reset this slider"))
        return b

    def _clear_button(self, parent):
        "Full-width 'clear all' button (resets every slider as one undo step) —"
        " a real filled button, replacing the old plain-text reset link."
        NORMAL = CHIP_BG
        btn = tk.Frame(parent, bg=NORMAL, cursor="hand2")
        btn.pack(fill="x", padx=EDIT_PAD, pady=(12, 8))
        inner = tk.Frame(btn, bg=NORMAL)          # centers the icon + label
        inner.pack(pady=7)
        parts = [btn, inner]
        img = self.icon("rotate-ccw", size=16)
        if img is not None:
            ic = tk.Label(inner, image=img, bg=NORMAL)
            ic.pack(side="left", padx=(0, 6))
            parts.append(ic)
        tx = tk.Label(inner, text=t("Clear all"), bg=NORMAL, fg=FG,
                      font=("Segoe UI", 9, "bold"))
        tx.pack(side="left")
        parts.append(tx)
        for w in parts:
            w.bind("<Button-1>", lambda e: self._reset_edits())
            w.bind("<Enter>", lambda e: [p.configure(bg=HOVER) for p in parts])
            w.bind("<Leave>", lambda e: [p.configure(bg=NORMAL) for p in parts])
        btn._tip = Tooltip(btn, t("Reset all sliders"))
        return btn

    def _slider_neutral(self, attr):
        "The rest value of a factor: 1.0 for most, 0.0 for the effects in SLIDER_NEUTRAL."
        return self.SLIDER_NEUTRAL.get(attr, 1.0)

    def _on_slider(self, attr, val):
        setattr(self, attr, val / 100.0)
        self._edits_saved = False   # a fresh edit → the saved copy (if any) is stale
        self._render_preview()

    def _reset_slider(self, attr):
        "Return one slider to its neutral value as a single undoable step."
        s = self.sliders.get(attr)
        if s is None:
            return
        before = self._edit_state()
        n = self._slider_neutral(attr)
        setattr(self, attr, n)
        s.set(round(n * 100))
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)
        self._repaint_filter_strip()

    def _reset_sliders(self):
        "Put every slider back to its neutral (1.0, or 0.0 for effects). No re-render."
        for attr, s in self.sliders.items():
            n = self._slider_neutral(attr)
            setattr(self, attr, n)
            s.set(round(n * 100))
        self.auto_mode = None        # auto correction is part of the edit too
        self.focus = None            # the selective focus blur resets too
        self._sync_focus_controls()
        self._recompute_auto()
        self._refresh_auto_buttons()

    # --- Auto tone (Photoshop "Auto Levels" / "Auto Contrast") --------------

    def _recompute_auto(self):
        "Rebuild the cached auto LUTs from the full base image (or clear them)."
        if self.auto_mode is None or self.current_pil is None:
            self._auto_luts = None
        else:
            self._auto_luts = imaging.autocontrast_luts(
                self.current_pil, self.auto_mode == "levels")

    def _set_auto(self, mode):
        "Toggle an auto correction (levels/contrast are mutually exclusive). Undoable."
        before = self._edit_state()
        self.auto_mode = None if self.auto_mode == mode else mode
        self._recompute_auto()
        self._refresh_auto_buttons()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)
        self._repaint_filter_strip()

    def _reset_edits(self):
        "Reset all sliders to neutral as a single undoable step."
        before = self._edit_state()
        self._reset_sliders()
        self._render_preview()
        self._record_edit(before)
        self._repaint_filter_strip()

    # --- Edit undo bookkeeping ----------------------------------------------

    def _edit_state(self):
        "Snapshot of the live edit factors."
        return {"brightness": self.brightness, "contrast": self.contrast,
                "color": self.color, "temperature": self.temperature,
                "tint": self.tint, "highlights": self.highlights,
                "shadows": self.shadows, "whites": self.whites,
                "blacks": self.blacks, "clarity": self.clarity,
                "vibrance": self.vibrance, "texture": self.texture,
                "sharpen": self.sharpen,
                "sat_red": self.sat_red, "sat_orange": self.sat_orange,
                "sat_yellow": self.sat_yellow, "sat_green": self.sat_green,
                "sat_aqua": self.sat_aqua, "sat_blue": self.sat_blue,
                "sat_purple": self.sat_purple, "sat_magenta": self.sat_magenta,
                "gold_hue": self.gold_hue, "gold_sat": self.gold_sat,
                "gold_light": self.gold_light,
                "skin_hue": self.skin_hue, "skin_sat": self.skin_sat,
                "skin_light": self.skin_light,
                "bw": self.bw, "sepia": self.sepia, "vignette": self.vignette,
                "focus": dict(self.focus) if self.focus else None,
                "auto_mode": self.auto_mode}

    def _edit_gesture_start(self):
        "A slider drag begins: remember the state so we can undo the whole drag."
        self._edit_before = self._edit_state()

    def _edit_gesture_end(self):
        "A slider drag ends: record one undo entry if anything actually changed."
        if self._edit_before is not None:
            self._record_edit(self._edit_before)
            self._edit_before = None
            self._repaint_filter_strip()

    def _record_edit(self, before):
        "Push an 'edit' undo entry for the current image if state changed."
        after = self._edit_state()
        if after != before and self.files:
            self._push_undo({"kind": "edit", "folder": self.folder,
                             "file": self.files[self.index],
                             "before": before, "after": after})
