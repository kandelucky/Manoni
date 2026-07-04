"""The edit area: section panel + icon rail, the sliders, auto tone, and the
edit undo bookkeeping.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import tkinter as tk
import tkinter.ttk as ttk

import tintkit

from ..config import EDIT_PANEL_W, EDIT_RAIL_W, EDIT_PAD
from .. import imaging
from ..widgets import Tooltip, Histogram
from ..i18n import t


class EditPanelMixin:
    # --- Edit panel (below the preview) -------------------------------------

    # --- Edit area: Fotor-style section panel (col 2) + icon rail (col 3) ----

    # The rail's selectable tools and their blue-header titles (Save is a
    # separate bottom action, not a section, so it is not listed here).
    SECTION_TITLES = {"basic": "Basic Edits", "crop": "Crop", "resize": "Resize",
                      "perspective": "Perspective",
                      "heal": "Heal & Clone", "focus": "Focus blur",
                      "color": "Color mixer",
                      "effects": "Effects", "text": "Text & Watermark",
                      "filters": "Filters",
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
        panel = self._tw(tk.Frame(parent, width=self._edit_dpi_w(EDIT_PANEL_W)), bg="bar")
        panel.grid(row=0, column=3, rowspan=3, sticky="ns")   # full height: clips the strips
        panel.pack_propagate(False)
        self.edit_panel = panel
        if not self.panel_open:      # hidden until the toolbar toggle opens it
            panel.grid_remove()

        # Blue header that names the open section (Fotor "Basic Edits" tab look).
        self.section_title = self._tw(tk.Label(panel, text=t(self.SECTION_TITLES["basic"]),
                                      anchor="w",
                                      font=("Segoe UI", 10, "bold"),
                                      padx=14, pady=8), bg="accent", fg="on_accent")
        self.section_title.pack(side="top", fill="x")

        # Live histogram: sits under the header, above the swappable content, so
        # every tool shows the edited photo's tonal spread. It re-renders from
        # the current preview viewport on each _render_preview (see viewer).
        self.histogram = Histogram(panel, self._render_histogram,
                                   height=self._edit_dpi_w(84))
        self.histogram.pack(side="top", fill="x", padx=EDIT_PAD, pady=(8, 4))

        # One swappable content frame per section, in a vertical scroll area so a
        # tall section (all the V3 sliders in Basic / Color) scrolls instead of
        # being clipped — the fixed-height panel has no room to grow. Same canvas
        # + auto-hiding Sidebar scrollbar pattern as the crop size list.
        self._sec_host = self._tw(tk.Frame(panel), bg="bar")
        self._sec_host.pack(side="top", fill="both", expand=True)
        self._sec_canvas = self._tw(tk.Canvas(self._sec_host, highlightthickness=0,
                                     bd=0), bg="bar")
        self._sec_scrollbar = ttk.Scrollbar(
            self._sec_host, orient="vertical", command=self._sec_canvas.yview,
            style="Sidebar.Vertical.TScrollbar")
        self._sec_canvas.configure(yscrollcommand=self._sec_scrollbar.set)
        self.section_content = self._tw(tk.Frame(self._sec_canvas), bg="bar")
        self._sec_win = self._sec_canvas.create_window(
            (0, 0), window=self.section_content, anchor="nw")
        self._sec_canvas.pack(side="left", fill="both", expand=True)
        self.section_content.bind("<Configure>", self._sync_section_scroll)
        self._sec_canvas.bind("<Configure>", self._on_section_canvas_configure)
        self._refresh_histogram()    # honour the "Show histogram" setting
        self.sections = {
            "basic":   self._build_basic_section(self.section_content),
            "crop":    self._build_crop_section(self.section_content),
            "resize":  self._build_resize_section(self.section_content),
            "perspective": self._build_perspective_section(self.section_content),
            "heal":    self._build_heal_section(self.section_content),
            "focus":   self._build_focus_section(self.section_content),
            "color":   self._build_color_section(self.section_content),
            "effects": self._build_effects_section(self.section_content),
            "text":    self._build_text_section(self.section_content),
            "filters": self._build_filters_section(self.section_content),
            "actions": self._build_actions_section(self.section_content),
        }
        self.sections[self.active_section].pack(fill="both", expand=True)
        # Wheel-scroll the section from anywhere in it (the sliders included), and
        # settle the initial scroll extent once the panel has a real height.
        for frame in self.sections.values():
            self._bind_section_wheel(frame)
        self.root.after_idle(self._sync_section_scroll)

        # Panel foot: a full-width Restore-original over a full-width Save. These
        # are the panel's primary actions and only show while the panel is open
        # (the rail keeps a compact Save for the collapsed state).
        self._build_panel_actions(panel)
        self._build_filters_footer(panel)   # pinned Create/Undo, filters tool only
        self._build_crop_footer(panel)      # pinned Crop/Cancel, crop tool only
        self._build_resize_footer(panel)    # pinned Resize/Reset, resize tool only

    def _refresh_histogram(self):
        "Show or hide the panel's live histogram per the General setting."
        hist = getattr(self, "histogram", None)
        if hist is None:
            return
        if getattr(self, "show_histogram", True):
            if not hist.canvas.winfo_manager():   # re-insert above the section content
                hist.pack(side="top", fill="x", padx=EDIT_PAD, pady=(8, 4),
                          before=self._sec_host)
            self._update_histogram()
        else:
            hist.canvas.pack_forget()

    # --- Section scroll area -------------------------------------------------

    def _on_section_canvas_configure(self, e):
        "Keep the inner frame the canvas width; refresh the scroll extent."
        self._sec_canvas.itemconfigure(self._sec_win, width=e.width)
        self._sync_section_scroll()

    def _sync_section_scroll(self, _e=None):
        "Refresh the scroll region; show the scrollbar only when the panel overflows."
        cv = self._sec_canvas
        cv.configure(scrollregion=cv.bbox("all"))
        if self.section_content.winfo_reqheight() > cv.winfo_height() + 1:
            if not self._sec_scrollbar.winfo_ismapped():
                self._sec_scrollbar.pack(side="right", fill="y", before=cv)
        else:
            if self._sec_scrollbar.winfo_ismapped():
                self._sec_scrollbar.pack_forget()
            cv.yview_moveto(0)

    def _section_wheel(self, e):
        "Wheel over the panel scrolls the open section when it overflows."
        cv = self._sec_canvas
        if self.section_content.winfo_reqheight() > cv.winfo_height() + 1:
            cv.yview_scroll(-1 if e.delta > 0 else 1, "units")
            return "break"
        return None

    def _bind_section_wheel(self, w):
        "Wheel-scroll on a widget + all its descendants, so sliders scroll too."
        # Skip a nested scroll area (e.g. the crop size list) — it owns its wheel.
        if (isinstance(w, tk.Canvas) and w is not self._sec_canvas
                and w.cget("yscrollcommand")):
            return
        w.bind("<MouseWheel>", self._section_wheel, add="+")
        for c in w.winfo_children():
            self._bind_section_wheel(c)

    def _build_basic_section(self, parent):
        "Basic Edits: a simple seven-slider set + a toggle that reveals the full"
        " slider set (every tone / detail / colour control)."
        f = self._tw(tk.Frame(parent), bg="bar")

        # Simple version: the seven most-used controls, always visible. No group
        # headers — a short flat list reads simpler. The rest live in the advanced
        # block below, revealed by the Full-version toggle.
        ess = self._tw(tk.Frame(f), bg="bar")
        ess.pack(fill="x", pady=(8, 0))
        self.s_exposure   = self._slider(ess, t("Exposure"), "brightness")
        self.s_exposure_g = self._slider(ess, t("Brightness/Fill"), "exposure_g")
        self.s_contrast   = self._slider(ess, t("Contrast"), "contrast")
        self.s_highlights = self._slider(ess, t("Highlights"), "highlights")
        self.s_shadows    = self._slider(ess, t("Shadows"), "shadows")
        self.s_vibrance   = self._slider(ess, t("Vibrance"), "vibrance")
        self.s_sharpen    = self._slider(ess, t("Sharpen"), "sharpen")

        # Advanced version: everything else, in the Photoshop groups. Built now
        # (so its sliders still join the shared reset / undo / filter machinery)
        # but only shown while basic_full is on — see _apply_basic_full. It is NOT
        # packed here; the toggle packs it in above itself when the user expands.
        adv = self._tw(tk.Frame(f), bg="bar")
        self._basic_adv = adv
        self._group_header(adv, t("White balance"))
        self.s_temp       = self._slider(adv, t("Temperature"), "temperature")
        self.s_tint       = self._slider(adv, t("Tint"), "tint")
        self._group_header(adv, t("Tone"))
        self.s_whites     = self._slider(adv, t("Whites"), "whites")
        self.s_blacks     = self._slider(adv, t("Blacks"), "blacks")
        self._group_header(adv, t("Detail & Color"))
        self.s_clarity    = self._slider(adv, t("Clarity"), "clarity")
        self.s_dehaze     = self._slider(adv, t("Dehaze"), "dehaze")
        self.s_color      = self._slider(adv, t("Color"), "color")
        self.s_texture    = self._slider(adv, t("Texture"), "texture")
        # Noise reduction rests at 0 (off → full strength), like the effects.
        self.s_denoise    = self._slider(adv, t("Noise reduction"), "denoise",
                                         hi=100, neutral=0)

        # The Simple/Full toggle sits under the seven essentials; the advanced
        # block is revealed just above it (a "show more / show less" at the foot).
        self._basic_more = self._basic_toggle(f)

        self.sliders = {"brightness": self.s_exposure,
                        "exposure_g": self.s_exposure_g,
                        "contrast": self.s_contrast,
                        "highlights": self.s_highlights,
                        "shadows": self.s_shadows,
                        "whites": self.s_whites,
                        "blacks": self.s_blacks,
                        "clarity": self.s_clarity,
                        "dehaze": self.s_dehaze,
                        "vibrance": self.s_vibrance,
                        "color": self.s_color,
                        "texture": self.s_texture,
                        "sharpen": self.s_sharpen,
                        "denoise": self.s_denoise,
                        "temperature": self.s_temp,
                        "tint": self.s_tint}

        self._clear_button(f)
        self._apply_basic_full()      # honour the saved simple/full choice
        return f

    def _basic_toggle(self, parent):
        "Full-width Simple/Full-version toggle: reveals or hides the advanced basic"
        " sliders. Its chevron + caption flip with the state (see _apply_basic_full)."
        btn = self._tw(tk.Frame(parent, cursor="hand2"), bg="chip")
        btn.pack(fill="x", padx=EDIT_PAD, pady=(12, 8))
        inner = self._tw(tk.Frame(btn), bg="chip")   # centres the chevron + label
        inner.pack(pady=6)
        ic = self._tw(tk.Label(inner), bg="chip")    # image set by _sync_basic_chevron
        ic.pack(side="left", padx=(0, 6))
        self._basic_chevron = ic
        tx = self._tw(tk.Label(inner, font=("Segoe UI", 9, "bold")), bg="chip", fg="fg")
        tx.pack(side="left")
        self._basic_more_label = tx
        parts = [btn, inner, ic, tx]
        for w in parts:
            w.bind("<Button-1>", lambda e: self._toggle_basic_full())
            w.bind("<Enter>", lambda e: [p.configure(bg=self.theme["hover"]) for p in parts])
            w.bind("<Leave>", lambda e: [p.configure(bg=self.theme["chip"]) for p in parts])
        btn._tip = Tooltip(btn, t("Show every Basic Edit slider"))
        self.theme.subscribe(self._sync_basic_chevron)   # re-tint on dark<->light
        return btn

    def _toggle_basic_full(self):
        "Flip the Basic Edits simple/full view and remember the choice."
        self.basic_full = not getattr(self, "basic_full", False)
        self._apply_basic_full()
        self._save_state()

    def _apply_basic_full(self):
        "Show/hide the advanced basic sliders and sync the toggle's caption + chevron"
        " to self.basic_full."
        full = getattr(self, "basic_full", False)
        if full:
            self._basic_adv.pack(fill="x", before=self._basic_more)
        else:
            self._basic_adv.pack_forget()
        self._basic_more_label.configure(
            text=t("Simple version") if full else t("Full version"))
        self._sync_basic_chevron()
        self.root.after_idle(self._sync_section_scroll)   # content height changed

    def _sync_basic_chevron(self):
        "Point the toggle's chevron: down = collapsed (expand), up = expanded."
        ic = getattr(self, "_basic_chevron", None)
        if ic is None:
            return
        name = "chevron-up" if getattr(self, "basic_full", False) else "chevron-down"
        im = self.icon(name, size=15, color=self.theme["fg"])
        if im is not None:
            ic.configure(image=im)
            ic._icon_ref = im

    def _group_header(self, parent, text):
        "A thin divider + small bold caption that splits the basic sliders into"
        " Photoshop-style groups (white balance / tone / detail) instead of one"
        " glued strip."
        self._tw(tk.Frame(parent, height=1), bg="divider").pack(
            fill="x", padx=EDIT_PAD, pady=(12, 0))
        self._tw(tk.Label(parent, text=text, anchor="w",
                 font=("Segoe UI", 8, "bold")), bg="bar", fg="fg_dim").pack(
                     fill="x", padx=EDIT_PAD, pady=(4, 2))

    def _refresh_auto_buttons(self):
        "Repaint the auto buttons so the active mode is accent-filled, rest neutral."
        " No-op now that the auto buttons are gone from the UI (auto_buttons is"
        " never built) — kept because nav / filters / actions still call it."
        if not hasattr(self, "auto_buttons"):
            return
        for mode, btn in self.auto_buttons.items():
            active = (mode == self.auto_mode)
            btn.configure(bg=self.theme["accent"] if active else self.theme["chip"],
                          fg=self.theme["on_accent"] if active else self.theme["fg"])

    def _build_effects_section(self, parent):
        "Effects: creative looks, each a 0→full strength slider. B&W + sepia +"
        " vignette + film grain. They share the edit pipeline, undo and reset."
        f = self._tw(tk.Frame(parent), bg="bar")
        # Effects rest at 0 (off): hi=100, neutral=0 → strength 0.0–1.0.
        self.s_bw = self._slider(f, t("Black & White"), "bw", hi=100, neutral=0)
        self.sliders["bw"] = self.s_bw   # join the shared reset / undo machinery
        # Sepia: a warm-toned monochrome — grouped with B&W (both desaturating looks).
        self.s_sepia = self._slider(f, t("Sepia"), "sepia", hi=100, neutral=0)
        self.sliders["sepia"] = self.s_sepia
        # Split-tone (colour grading): warm↔cool tint for highlights vs shadows.
        # Bidirectional (neutral 100): left = cool/teal, right = warm/orange.
        self._group_header(f, t("Split tone"))
        self.s_split_hi = self._slider(f, t("Highlights tone"), "split_hi")
        self.sliders["split_hi"] = self.s_split_hi
        self.s_split_sh = self._slider(f, t("Shadows tone"), "split_sh")
        self.sliders["split_sh"] = self.s_split_sh
        # Bidirectional (centred at 0): left lightens the corners, right darkens.
        self.s_vignette = self._slider(f, t("Vignette"), "vignette")
        self.sliders["vignette"] = self.s_vignette
        # Film grain: 0 = off → full strength. Laid on top of the whole look.
        self.s_grain = self._slider(f, t("Film grain"), "grain", hi=100, neutral=0)
        self.sliders["grain"] = self.s_grain

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
        f = self._tw(tk.Frame(parent), bg="bar")

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
        "A labeled live TitledSlider with a colour chip in its title strip + reset."
        s = tintkit.TitledSlider(
            parent, self.theme, label, value=100, lo=0, hi=200, neutral=100,
            bg="bar", chip=chip, compact=True,
            command=lambda v, a=attr: self._on_slider(a, v),
            on_press=self._edit_gesture_start, on_release=self._edit_gesture_end,
            reset_tip=t("Reset this slider"),
            on_reset=lambda a=attr: self._reset_slider(a))
        s.pack(fill="x", padx=EDIT_PAD, pady=(1, 2))
        return s

    # --- Tool rail (col 4): vertical labeled icon buttons, Fotor-style -------

    def _build_tool_rail(self, parent):
        "Always-visible icon rail: a collapse chevron on top, then the tool icons"
        " (click one to open the panel to it); Save pinned to the bottom."
        rail = self._tw(tk.Frame(parent, width=self._edit_dpi_w(EDIT_RAIL_W)), bg="bar")
        rail.grid(row=0, column=4, rowspan=3, sticky="ns")   # full height: clips the strips
        rail.pack_propagate(False)   # children are packed → fix the width here
        self.rail = rail   # the rail itself never hides; only edit_panel collapses

        self.rail_buttons = {}   # section key -> cell frame (for active highlight)
        top = self._tw(tk.Frame(rail), bg="bar")
        top.pack(side="top", fill="x", pady=(8, 0))

        # Collapse chevron: '<' (panel closed) opens it, '>' (panel open) closes
        # it. The slider panel slides out to the LEFT of this rail.
        self.btn_chevron = self._tool_button(
            top, "chevron-left", self.toggle_panel, t("Open / collapse the panel"))
        self.btn_chevron.pack(side="top", pady=(0, 6))
        self._tw(tk.Frame(top, height=1), bg="border").pack(side="top", fill="x",
                                                   padx=12, pady=(0, 6))

        # Tools grouped by task: adjust · geometry · retouch · overlay ·
        # automate, with a thin separator between groups (no text headers —
        # the rail is too narrow for them).
        rail_groups = [
            [("basic",   "sliders-horizontal", "Basic Edit"),
             ("color",   "palette",            "Colors"),
             ("effects", "wand-sparkles",      "Effects"),
             ("filters", "blend",              "Filters")],
            [("crop",    "crop",               "Crop"),
             ("resize",  "scaling",            "Resize"),
             ("perspective", "frame",          "Perspective")],
            [("heal",    "bandage",            "Heal"),
             ("focus",   "circle-dot",         "Blur")],
            [("text",    "type",               "Text")],
            [("actions", "circle-play",        "Actions")],
        ]
        for gi, group in enumerate(rail_groups):
            if gi:
                self._tw(tk.Frame(top, height=1), bg="border").pack(
                    side="top", fill="x", padx=12, pady=(1, 3))
            for key, icon_name, label in group:
                self._rail_button(top, icon_name, label, key=key)

        # Quick save (one click, no dialog) — pinned to the bottom like Fotor, as
        # one accent button that spans the FULL rail width (the primary action).
        # "Save as…" with all the options lives in the ☰ menu instead.
        self._build_save_button(rail)

        self._update_rail()
        self.theme.subscribe(self._update_rail)   # repaint the rail on dark<->light
        # The chevron's direction is dynamic (open/closed), so restore it after a
        # switch too (its _tool_button restyle only knows the build-time icon).
        self.theme.subscribe(self._update_chevron)
        self._update_chevron()

    def _build_save_button(self, rail):
        "A compact accent Save button pinned to the rail foot (icon over label)."
        " Shown only while the panel is collapsed — the open panel carries its"
        " own full-width Save (see _build_panel_actions)."
        wrap = self._tw(tk.Frame(rail), bg="bar")
        wrap.pack(side="bottom", fill="x")
        self._rail_save_wrap = wrap   # hidden while the panel is open
        self._tw(tk.Frame(wrap, height=1), bg="border").pack(side="top", fill="x")

        btn = self._tw(tk.Frame(wrap, cursor="hand2"), bg="accent")
        btn.pack(side="top", fill="x")
        # Icon sits on the accent fill → tinted on_accent (light) in both schemes.
        ic = self._icon_label(btn, "save", token="on_accent", bg="accent",
                              fallback="💾", font=("Segoe UI", 14))
        ic.pack(pady=(8, 2))
        tx = self._tw(tk.Label(btn, text=t("Save"),
                      font=("Segoe UI", 8, "bold")), bg="accent", fg="on_accent")
        tx.pack(pady=(0, 8))
        for w in (btn, ic, tx):
            w.bind("<Button-1>", lambda e: self.quick_save())
            w.bind("<Enter>", lambda e: [c.configure(bg=self.theme["accent_hover"])
                                         for c in (btn, ic, tx)])
            w.bind("<Leave>", lambda e: [c.configure(bg=self.theme["accent"])
                                         for c in (btn, ic, tx)])
        btn._tip = Tooltip(btn, t("Save"))

    def _build_panel_actions(self, panel):
        "The open panel's foot: View original, over Restore-original, over Save — all full-width."
        wrap = self._tw(tk.Frame(panel), bg="bar")
        # Pin to the panel bottom; the swappable section content expands above it.
        wrap.pack(side="bottom", fill="x", before=self._sec_host)
        self._tw(tk.Frame(wrap, height=1), bg="border").pack(side="top", fill="x")
        self._build_peek_action(wrap)
        self._wide_action(wrap, "rotate-ccw", t("Restore original"),
                          self.restore_original,
                          tip=t("Discard every edit and reload the original photo"))
        self._wide_action(wrap, "save", t("Save"), self.quick_save, accent=True)

    def _build_peek_action(self, parent):
        "Full-width panel action: press-and-hold to peek the original, release for the edit."
        # No click `command` — the interaction is press/release, not a click, so
        # it binds those events on the button's own canvas instead.
        btn = tintkit.Button(
            parent, self.theme, t("View original"), icon="eye",
            stretch=True, bg="bar", role="neutral", variant="outline")
        btn.pack(side="top", fill="x", pady=(0, 2))
        btn.canvas.bind("<ButtonPress-1>", lambda e: self._peek_action_press(btn))
        btn.canvas.bind("<ButtonRelease-1>", lambda e: self._peek_action_release(btn))
        tintkit.HoverTip(btn.canvas, self.theme,
                         t("Hold to see the original — press for before, release for after"))
        return btn

    def _peek_action_press(self, btn):
        "Press → show the original (იყო); fill the button to mark it active."
        self._compare_peek_on()
        btn.role, btn.variant = "primary", "filled"
        btn.repaint()

    def _peek_action_release(self, btn):
        "Release → back to the edit (არის); restore the resting outline."
        self._compare_peek_off()
        btn.role, btn.variant = "neutral", "outline"
        btn.repaint()

    def _wide_action(self, parent, icon_name, label, command, accent=False, tip=None):
        "One full-width panel action button (icon left of label). accent = primary."
        # Two-button panel foot (UI standard #3): the Save is the primary filled
        # action; Restore is the outline secondary.
        btn = tintkit.Button(
            parent, self.theme, label, icon=icon_name, command=command,
            stretch=True, bg="bar",
            role="primary" if accent else "neutral",
            variant="filled" if accent else "outline")
        btn.pack(side="top", fill="x", pady=(0, 2))
        if tip:
            tintkit.HoverTip(btn.canvas, self.theme, tip)
        return btn

    def _set_panel(self, open_):
        "Show or hide the slider panel (col 3). The icon rail stays put."
        if open_ == self.panel_open:
            return
        self.panel_open = open_
        if open_:
            self.edit_panel.grid()
            self._rail_save_wrap.pack_forget()   # the open panel has its own Save
        else:
            self.edit_panel.grid_remove()
            self._rail_save_wrap.pack(side="bottom", fill="x")
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
        cell = tk.Frame(parent, bg=self.theme["bar"], cursor="hand2")
        cell.pack(side="top", fill="x", pady=1)
        img = self.icon(icon_name)
        if img is not None:
            ic = tk.Label(cell, image=img, bg=self.theme["bar"])
        else:
            ic = tk.Label(cell, text="□", bg=self.theme["bar"], fg=self.theme["fg"],
                          font=("Segoe UI", 14))
        ic.pack(pady=(4, 1))
        tx = tk.Label(cell, text=t(label), bg=self.theme["bar"],
                      fg=self.theme["fg_dim"], font=("Segoe UI", 8))
        tx.pack(pady=(0, 4))
        cell._widgets = (ic, tx)
        # The rail icon re-tints with state (see _update_rail): on_accent while the
        # cell is the active section, fg otherwise — so it flips dark<->light too.
        cell._icon_name = icon_name
        cell._icon_has = img is not None

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
        bg = self.theme["hover"] if entering else self.theme["bar"]
        fg = self.theme["fg"] if entering else self.theme["fg_dim"]
        ic, tx = cell._widgets
        cell.configure(bg=bg)
        ic.configure(bg=bg)
        tx.configure(bg=bg, fg=fg)

    def set_section(self, key):
        "Open a tool section: swap the panel content, update header + rail highlight."
        if key not in self.sections:
            return
        self._set_hand_tool(False)   # an edit tool claims the left button — release the hand
        if key in ("crop", "heal", "focus", "perspective", "text"):
            self._set_compare(False)  # these warp/drag the canvas — compare can't intercept it
        self.active_section = key
        self._filters_footer.pack_forget()   # only the filters tool pins its footer
        self._crop_footer.pack_forget()      # only the crop tool pins its footer
        self._resize_footer.pack_forget()    # only the resize tool pins its footer
        for k, frame in self.sections.items():
            if k == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        # Open each section scrolled to the top, and refresh the scrollbar for the
        # new content height.
        self._sec_canvas.yview_moveto(0)
        self.root.after_idle(self._sync_section_scroll)
        self.section_title.configure(text=t(self.SECTION_TITLES[key]))
        self._update_rail()
        if key == "crop":
            self._enter_crop()       # init a box + fit so the whole photo is seen
        elif key == "resize":
            self._enter_resize()     # refresh the size readout from the current photo
        elif key == "perspective":
            self._enter_perspective()  # fit the photo so the live warp is visible
        elif key == "heal":
            self._enter_heal()       # show the brush cursor + ring
        elif key == "focus":
            self._enter_focus()      # place the focus circle + fit to see it all
        elif key == "text":
            self._enter_text()       # place a default overlay + fit, focus the entry
        elif key == "actions":
            self._enter_actions()    # refresh the recorder + saved-action list
        elif key == "filters":
            self._enter_filters()    # show the pinned Create/Undo footer
        else:
            self.preview.configure(cursor="")
            self._render_preview()   # repaint without the crop/heal/focus overlay

    def _update_rail(self):
        "Fill the active section's rail cell with the accent colour; dim the rest."
        for k, cell in self.rail_buttons.items():
            active = (k == self.active_section)
            bg = self.theme["accent"] if active else self.theme["bar"]
            fg = self.theme["on_accent"] if active else self.theme["fg_dim"]
            ic, tx = cell._widgets
            cell.configure(bg=bg)
            ic.configure(bg=bg)
            tx.configure(bg=bg, fg=fg)
            # Icon: light on the accent fill, theme fg when resting.
            itok = "on_accent" if active else "fg"
            if getattr(cell, "_icon_has", False):
                im = self.icon(cell._icon_name, color=self.theme[itok])
                if im is not None:
                    ic.configure(image=im)
                    ic._icon_ref = im
            else:
                ic.configure(fg=self.theme[itok])

    def _slider(self, parent, label, attr, lo=0, hi=200, neutral=100):
        "A labeled live TitledSlider bound to an attribute, with its own reset icon."
        " Default 0–200 → factor 0.0–2.0 (neutral 1.0). Effects pass hi=100,"
        " neutral=0 → 0.0–1.0 (off→full)."
        s = tintkit.TitledSlider(
            parent, self.theme, label, value=neutral, lo=lo, hi=hi,
            neutral=neutral, bg="bar", compact=True,
            command=lambda v, a=attr: self._on_slider(a, v),
            on_press=self._edit_gesture_start, on_release=self._edit_gesture_end,
            reset_tip=t("Reset this slider"),
            value_fmt=self._slider_fmt(lo, hi, neutral),
            on_reset=lambda a=attr: self._reset_slider(a))
        s.pack(fill="x", padx=EDIT_PAD, pady=(1, 2))
        return s

    def _slider_fmt(self, lo, hi, neutral):
        "Gauge sliders (rest at an end, e.g. effects) show the raw value; a"
        " bidirectional tone slider shows the signed delta from neutral."
        if neutral in (lo, hi):
            return lambda v, n: str(v)
        return None                       # TitledSlider default = signed delta

    def _clear_button(self, parent):
        "Full-width 'clear all' button (resets every slider as one undo step) —"
        " a real filled button, replacing the old plain-text reset link."
        btn = self._tw(tk.Frame(parent, cursor="hand2"), bg="chip")
        btn.pack(fill="x", padx=EDIT_PAD, pady=(12, 8))
        inner = self._tw(tk.Frame(btn), bg="chip")   # centers the icon + label
        inner.pack(pady=7)
        parts = [btn, inner]
        ic = self._icon_label(inner, "rotate-ccw", size=16, token="fg", bg="chip")
        ic.pack(side="left", padx=(0, 6))
        parts.append(ic)
        tx = self._tw(tk.Label(inner, text=t("Clear all"),
                      font=("Segoe UI", 9, "bold")), bg="chip", fg="fg")
        tx.pack(side="left")
        parts.append(tx)
        for w in parts:
            w.bind("<Button-1>", lambda e: self._reset_edits())
            w.bind("<Enter>", lambda e: [p.configure(bg=self.theme["hover"]) for p in parts])
            w.bind("<Leave>", lambda e: [p.configure(bg=self.theme["chip"]) for p in parts])
        btn._tip = Tooltip(btn, t("Reset all sliders"))
        return btn

    def _slider_neutral(self, attr):
        "The rest value of a factor: 1.0 for most, 0.0 for the effects in SLIDER_NEUTRAL."
        return self.SLIDER_NEUTRAL.get(attr, 1.0)

    def _on_slider(self, attr, val):
        setattr(self, attr, val / 100.0)
        self._edits_saved = False   # a fresh edit → the saved copy (if any) is stale
        self._schedule_preview()    # coalesce the drag's renders into one per idle (see viewer)

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
        self.texts = []              # …and every text / watermark overlay
        self.text_sel = None
        self._text_drag = None
        self._sync_focus_controls()
        self._sync_text_controls()
        self._recompute_auto()
        self._refresh_auto_buttons()

    # --- Auto-correction LUTs (plumbing; the buttons were removed) -----------
    # The Auto tone / level / contrast buttons are gone from the UI, but this
    # stays so a saved filter or action that still carries an auto_mode keeps
    # applying — and so the feature is trivial to restore later.

    def _recompute_auto(self):
        "Rebuild the cached auto LUTs from the full base image (or clear them)."
        if self.auto_mode is None or self.current_pil is None:
            self._auto_luts = None
        else:
            self._auto_luts = imaging.build_auto_luts(self.current_pil, self.auto_mode)

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
        return {"brightness": self.brightness, "exposure_g": self.exposure_g,
                "contrast": self.contrast,
                "color": self.color, "temperature": self.temperature,
                "tint": self.tint, "highlights": self.highlights,
                "shadows": self.shadows, "whites": self.whites,
                "blacks": self.blacks, "clarity": self.clarity,
                "vibrance": self.vibrance, "texture": self.texture,
                "dehaze": self.dehaze,
                "sharpen": self.sharpen, "denoise": self.denoise,
                "sat_red": self.sat_red, "sat_orange": self.sat_orange,
                "sat_yellow": self.sat_yellow, "sat_green": self.sat_green,
                "sat_aqua": self.sat_aqua, "sat_blue": self.sat_blue,
                "sat_purple": self.sat_purple, "sat_magenta": self.sat_magenta,
                "gold_hue": self.gold_hue, "gold_sat": self.gold_sat,
                "gold_light": self.gold_light,
                "skin_hue": self.skin_hue, "skin_sat": self.skin_sat,
                "skin_light": self.skin_light,
                "bw": self.bw, "sepia": self.sepia, "vignette": self.vignette,
                "grain": self.grain,
                "split_hi": self.split_hi, "split_sh": self.split_sh,
                "focus": dict(self.focus) if self.focus else None,
                # A blank text box is NOT an edit: keep only the elements that
                # actually carry text, so adding an empty box (or clearing one)
                # never marks the photo changed or pushes an undo step. Selection
                # (text_sel) is transient UI state and is deliberately excluded.
                "texts": [dict(ov) for ov in self.texts
                          if (ov.get("text") or "").strip()],
                "auto_mode": self.auto_mode}

    def _edit_snapshot(self):
        "Remember the edit state so a whole gesture (drag or typing session) folds"
        " into one undo step. No draft mode — used by the text entry while typing,"
        " where keystroke renders are infrequent and want full quality."
        self._edit_before = self._edit_state()

    def _edit_commit(self):
        "Record one undo entry if the gesture changed anything."
        if self._edit_before is not None:
            self._record_edit(self._edit_before)
            self._edit_before = None
            self._repaint_filter_strip()

    def _edit_gesture_start(self):
        "A slider / canvas drag begins: draft-quality renders + one undo step."
        self._interacting = True     # drag → draft renders (low-res, no histogram)
        self._edit_snapshot()

    def _edit_gesture_end(self):
        "A slider / canvas drag ends: back to full quality, record the undo step."
        self._interacting = False    # back to full quality...
        self._render_preview()       # ...and snap the photo + histogram to it now
        self._edit_commit()

    def _record_edit(self, before, is_filter=False):
        "Push an 'edit' undo entry for the current image if state changed."
        " Any edit that ISN'T a filter application clears the filter-trying anchor"
        " (see _apply_filter_values / _filter_remove) — it's no longer just the"
        " photo's pre-filter state once something else has been done on purpose."
        after = self._edit_state()
        if after != before and self.files:
            self._push_undo({"kind": "edit", "folder": self.folder,
                             "file": self.files[self.index],
                             "before": before, "after": after})
        if not is_filter:
            self._filter_anchor = None
