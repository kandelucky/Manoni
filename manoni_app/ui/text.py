"""Text / watermark overlays for Manoni.

Strings laid over the photo — captions or a "© name" watermark. Like the focus
blur (and unlike crop / heal, which bake into current_pil), these are LIVE,
non-destructive effects: each string, its centre and its font height live in
SOURCE-image pixels, so the text stays glued to the photo through zoom + pan and
the small preview composites exactly like the full-res save (the imaging module
multiplies position AND size by the same `scale`).

The photo can hold MANY texts: `self.texts` is the list, `self.text_sel` the
selected index, and the `text_overlay` property exposes the selected element so
every per-control method stays single-overlay-simple. Text appears ONLY via the
"Add text" button (nothing is auto-inserted); "Delete text" drops the selected
one and "Delete all" wipes them. Each gesture rides one undo entry, shared with
the slider-edit machinery.

Click a text to select it, drag to move it, drag its bottom-right handle to
resize. The panel also offers a font, colour, opacity, a drop shadow and
one-click corner placement (the watermark staple). Mixin on the Manoni window —
every method uses the shared `self`.
"""

import math
import tkinter as tk
from tkinter import colorchooser

import tintkit

from ..config import (BAR, ACCENT, FG, FG_DIM, HOVER, ON_ACCENT,
                      EDIT_PAD, CHIP_BG, BORDER)
from ..i18n import t
from .. import imaging


class TextMixin:
    # --- Text overlay (col 3 panel + interactive box on the preview) ---------

    TEXT_HANDLE   = 5      # half-size of the resize handle square, screen px
    TEXT_HIT_PAD  = 4      # click slack around a text box for selection, screen px
    TEXT_MIN_SIZE = 6.0    # smallest font height, source px
    TEXT_MARGIN   = 0.04   # corner-placement inset, as a fraction of the short side
    TEXT_EMPTY_HW = 46     # placeholder half-width while no text is typed, screen px
    TEXT_EMPTY_HH = 16     # placeholder half-height while no text is typed, screen px

    # --- Panel --------------------------------------------------------------

    def _build_text_section(self, parent):
        "Text panel: the string, font, size + opacity, colour, shadow, placement."
        f = tk.Frame(parent, bg=BAR)

        tk.Label(f, text=t("Add a text, then drag it on the photo to place it. "
                           "The corner handle resizes it. Add as many as you like."),
                 bg=BAR, fg=FG_DIM, font=("Segoe UI", 8), justify="left",
                 anchor="w", wraplength=self._edit_dpi_w(190)).pack(
            fill="x", padx=EDIT_PAD, pady=(10, 6))

        # Top row: ‘Add text’ (the ONLY way a text appears — accent primary) and
        # a trash icon that removes the selected one.
        addrow = tk.Frame(f, bg=BAR)
        addrow.pack(fill="x", padx=EDIT_PAD, pady=(0, 8))
        add = tintkit.Button(addrow, self.theme, t("Add text"), role="primary",
                             variant="filled", stretch=True, bg="bar",
                             command=self._add_text)
        add.pack(side="left", fill="x", expand=True)
        tintkit.HoverTip(add.canvas, self.theme,
                         t("Drop a new text element on the photo"))
        self._text_del_btn = tintkit.IconButton(
            addrow, self.theme, "trash-2", w=36, h=36, icon_px=15, bg="bar",
            command=self._delete_text)
        self._text_del_btn.pack(side="left", padx=(6, 0))
        tintkit.HoverTip(self._text_del_btn.canvas, self.theme,
                         t("Remove the selected text from the photo"))

        # The string itself: a small multi-line box (tintkit.TextArea — a themed,
        # focus-accented frame around a real tk.Text). A whole typing session is
        # one undo step (snapshot on focus-in, recorded on focus-out). `_text_entry`
        # stays the tk.Text so every get / insert / state= call is unchanged.
        self._text_area = tintkit.TextArea(f, self.theme, height=2, bg="bar")
        self._text_area.pack(fill="x", padx=EDIT_PAD, pady=(0, 4))
        self._text_entry = self._text_area.text
        self._text_entry.bind("<KeyRelease>", self._on_text_typed)
        self._text_entry.bind("<FocusIn>", lambda e: self._edit_snapshot())
        self._text_entry.bind("<FocusOut>", lambda e: self._edit_commit())

        # Font: a compact dropdown (six families is too many for a segmented pill).
        self._group_header(f, t("Font"))
        self._text_fonts = list(imaging.TEXT_FONTS)
        self._text_font_dd = tintkit.Dropdown(
            f, self.theme, [t(fam) for fam in self._text_fonts], selected=0,
            bg="bar", command=lambda i, _l: self._set_text_font(self._text_fonts[i]))
        self._text_font_dd.pack(fill="x", padx=EDIT_PAD, pady=2)

        # Size (as % of the photo's short side) and opacity, each a TitledSlider
        # with its own reset. The press/release hooks fold a whole drag into one
        # undo step; the readouts are raw gauges (a % and 0–100).
        self.s_text_size = tintkit.TitledSlider(
            f, self.theme, t("Size"), value=8, lo=1, hi=50, neutral=8, bg="bar",
            command=self._set_text_size, on_press=self._edit_gesture_start,
            on_release=self._edit_gesture_end, reset_tip=t("Reset this slider"),
            value_fmt=lambda v, n: str(v),
            on_reset=lambda: self._reset_text_slider("size"))
        self.s_text_size.pack(fill="x", padx=EDIT_PAD, pady=(8, 2))
        self.s_text_opacity = tintkit.TitledSlider(
            f, self.theme, t("Opacity"), value=100, lo=0, hi=100, neutral=100,
            bg="bar", command=self._set_text_opacity,
            on_press=self._edit_gesture_start, on_release=self._edit_gesture_end,
            reset_tip=t("Reset this slider"), value_fmt=lambda v, n: str(v),
            on_reset=lambda: self._reset_text_slider("opacity"))
        self.s_text_opacity.pack(fill="x", padx=EDIT_PAD, pady=2)

        # Colour swatch + a shadow checkbox, side by side.
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
        tintkit.HoverTip(self._text_swatch, self.theme, t("Pick the text colour"))
        self._text_shadow_chk = tintkit.Checkbox(
            row, self.theme, t("Shadow"), state="off", bg="bar",
            command=lambda _st: self._toggle_text_shadow())
        self._text_shadow_chk.pack(side="right")
        tintkit.HoverTip(
            self._text_shadow_chk.canvas, self.theme,
            t("A soft drop shadow, for light text on a bright photo"))

        # Alignment (matters for multi-line text): left / centre / right.
        self._group_header(f, t("Alignment"))
        self._text_aligns = ["left", "center", "right"]
        self._text_align_tabs = tintkit.SegmentedTabs(
            f, self.theme, [t("Left"), t("Centre"), t("Right")], selected=1,
            bg="bar",
            command=lambda i, _l: self._set_text_align(self._text_aligns[i]))
        self._text_align_tabs.pack(padx=EDIT_PAD, pady=2)

        # One-click placement: a 3×3 grid snapping the text to a corner / edge /
        # centre with a small margin — the watermark staple.
        self._group_header(f, t("Position"))
        self._build_text_position_grid(f)

        # Footer: Done closes the tool (the texts stay live on the photo); Delete
        # all wipes every text. 'Delete text' (the selected one) is the trash icon
        # up by 'Add text'. Delete all dims to disabled while there's nothing to wipe.
        done = tintkit.Button(
            f, self.theme, t("Done"), role="primary", variant="filled",
            stretch=True, bg="bar", command=lambda: self.set_section("basic"))
        done.pack(fill="x", padx=EDIT_PAD, pady=(14, 0))
        self._text_delall_btn = tintkit.Button(
            f, self.theme, t("Delete all"), role="neutral", variant="outline",
            icon="x", stretch=True, bg="bar", command=self._delete_all_text)
        self._text_delall_btn.pack(fill="x", padx=EDIT_PAD, pady=(8, 8))
        tintkit.HoverTip(self._text_delall_btn.canvas, self.theme,
                         t("Remove every text from the photo"))
        self._refresh_text_buttons()          # start Delete-all disabled if empty
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

    @property
    def text_overlay(self):
        "The selected text element (or None). Every per-element control reads and"
        " writes THIS, so the editing code stays single-overlay-simple while the"
        " photo can hold many texts in `self.texts`."
        ts = getattr(self, "texts", None)
        i = getattr(self, "text_sel", None)
        if ts and i is not None and 0 <= i < len(ts):
            return ts[i]
        return None

    @text_overlay.setter
    def text_overlay(self, value):
        "A dict replaces the selected element (or becomes the first one); None is"
        " the legacy 'clear everything' used by reset / geometry changes. Always"
        " rebinds `self.texts` to a NEW list so undo snapshots are never aliased."
        if value is None:
            self.texts = []
            self.text_sel = None
            return
        if self.text_sel is not None and 0 <= self.text_sel < len(self.texts):
            new = list(self.texts)
            new[self.text_sel] = value
            self.texts = new
        else:
            self.texts = self.texts + [value]
            self.text_sel = len(self.texts) - 1

    def _default_text_overlay(self):
        "A centred overlay sized to the photo (the caller sets its text)."
        iw, ih = self.current_pil.size
        return {"text": "", "cx": iw / 2.0, "cy": ih / 2.0,
                "size": max(12.0, min(iw, ih) * 0.08),
                "color": "#ffffff", "opacity": 1.0, "font": "Sans",
                "align": "center", "shadow": True}

    def _add_text(self):
        "‘Add text’: drop ONE new, real, editable text element on the photo and"
        " select it. This is the ONLY way text appears — nothing is auto-inserted."
        if self.current_pil is None:
            return
        before = self._edit_state()
        ov = self._default_text_overlay()
        ov["text"] = t("Text")               # a real default you can edit / delete
        # Cascade each new text down-right of the centre so several don't pile up
        # exactly on top of each other (which leaves only the topmost clickable).
        n = len(self.texts)
        if n:
            iw, ih = self.current_pil.size
            step = min(iw, ih) * 0.05
            k = n % 10                        # wrap so it never marches off-frame
            ov["cx"] = min(max(0.0, ov["cx"] + step * k), float(iw))
            ov["cy"] = min(max(0.0, ov["cy"] + step * k), float(ih))
        self.texts = self.texts + [ov]       # rebind (never alias an undo snapshot)
        self.text_sel = len(self.texts) - 1
        self._edits_saved = False
        self._sync_text_controls()
        self._render_preview()
        self._record_edit(before)
        # Focus the box and pre-select the default word so typing replaces it.
        self._text_entry.focus_set()
        self._text_entry.tag_add("sel", "1.0", "end-1c")

    def _delete_text(self):
        "‘Delete text’: remove the SELECTED element from the photo (undoable)."
        if self.text_sel is None or not (0 <= self.text_sel < len(self.texts)):
            return
        before = self._edit_state()
        self.texts = [o for j, o in enumerate(self.texts) if j != self.text_sel]
        self.text_sel = (len(self.texts) - 1) if self.texts else None
        self._text_drag = None
        self._edits_saved = False
        self._sync_text_controls()
        self._render_preview()
        self._record_edit(before)

    def _delete_all_text(self):
        "‘Delete all’: remove every text element from the photo (undoable)."
        if not self.texts:
            return
        before = self._edit_state()
        self.texts = []
        self.text_sel = None
        self._text_drag = None
        self._edits_saved = False
        self._sync_text_controls()
        self._render_preview()
        self._record_edit(before)

    def _enter_text(self):
        "Open the text tool: fit the photo and show controls. Adds NO text on its"
        " own — the user clicks ‘Add text’ for that."
        if self.current_pil is None:
            self._render_preview()
            return
        self._sync_text_controls()
        self.preview.configure(cursor="")
        self.fit_view()                      # fit so the whole photo is visible
        if self.text_overlay is not None:    # something already selected → type away
            self._text_entry.focus_set()

    def _text_active(self):
        "True whenever the text tool is open (so clicks can select / add text)."
        return (self.panel_open and self.active_section == "text"
                and self.current_pil is not None)

    def _sync_text_controls(self):
        "Push the selected element's values into the entry, sliders, chips + swatch."
        " With no selection the entry is disabled and controls show neutral."
        if not hasattr(self, "_text_entry"):
            return
        # Keep the selection index valid after deletes / undo.
        if self.text_sel is not None and not (0 <= self.text_sel < len(self.texts)):
            self.text_sel = (len(self.texts) - 1) if self.texts else None
        ov = self.text_overlay
        has = ov is not None
        # The entry edits the SELECTED element; disable it when nothing is selected.
        self._text_entry.configure(state="normal")
        cur = self._text_entry.get("1.0", "end-1c")
        want = ov.get("text", "") if has else ""
        if cur != want:
            self._text_entry.delete("1.0", "end")
            if want:
                self._text_entry.insert("1.0", want)
        if not has:
            self._text_entry.configure(state="disabled")
        if self.current_pil is not None and has:
            short = max(1, min(self.current_pil.size))
            self.s_text_size.set(round(ov.get("size", 0.0) / short * 100))
        self.s_text_opacity.set(round((ov.get("opacity", 1.0) if has else 1.0) * 100))
        self._text_swatch.configure(bg=ov.get("color", "#ffffff") if has else "#ffffff")
        active_font = imaging.resolve_font_family(ov.get("font", "Sans") if has else "Sans")
        if hasattr(self, "_text_font_dd"):
            fidx = (self._text_fonts.index(active_font)
                    if active_font in self._text_fonts else 0)
            if self._text_font_dd.selected != fidx:
                self._text_font_dd.selected = fidx
                self._text_font_dd.repaint()
        active_align = ov.get("align", "center") if has else "center"
        if hasattr(self, "_text_align_tabs"):
            aidx = (self._text_aligns.index(active_align)
                    if active_align in self._text_aligns else 1)
            if self._text_align_tabs.selected != aidx:
                self._text_align_tabs.selected = aidx
                self._text_align_tabs.repaint()
        if hasattr(self, "_text_shadow_chk"):
            self._text_shadow_chk.state = "on" if (has and ov.get("shadow")) else "off"
            self._text_shadow_chk.repaint()
        self._refresh_text_buttons()

    def _refresh_text_buttons(self):
        "Disable ‘Delete all’ while there's no text to wipe (the trash icon by"
        " 'Add text' just no-ops when nothing is selected)."
        if hasattr(self, "_text_delall_btn"):
            want = not bool(self.texts)
            if self._text_delall_btn.disabled != want:
                self._text_delall_btn.disabled = want
                self._text_delall_btn.repaint()

    def _clear_text_for_geometry(self):
        "Drop ALL text when the image geometry changes (rotate / crop / resize /"
        " perspective): the source-px positions no longer map to the new pixels."
        " No undo entry — it rides along with the geometry action that called it."
        if not self.texts:
            return
        self.texts = []
        self.text_sel = None
        self._text_drag = None
        self._sync_text_controls()

    # --- Panel controls -----------------------------------------------------

    def _on_text_typed(self, _event=None):
        "Live: copy the entry's content into the selected element (no undo step)."
        if self.text_overlay is None:           # nothing selected → entry is inert
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
        self._schedule_preview()

    def _set_text_opacity(self, v):
        "Slider: text opacity 0..100 → 0..1 (live, no undo step)."
        if self.text_overlay is None:
            return
        self.text_overlay = {**self.text_overlay,
                             "opacity": max(0.0, min(1.0, int(v) / 100.0))}
        self._edits_saved = False
        self._schedule_preview()

    def _reset_text_slider(self, which):
        "Return one text slider to neutral on the selected element (one undo step)."
        if self.text_overlay is None or self.current_pil is None:
            return
        before = self._edit_state()
        if which == "size":
            short = max(1, min(self.current_pil.size))
            self.text_overlay = {**self.text_overlay,
                                 "size": max(self.TEXT_MIN_SIZE, 8 / 100.0 * short)}
            self.s_text_size.set(8)
        else:
            self.text_overlay = {**self.text_overlay, "opacity": 1.0}
            self.s_text_opacity.set(100)
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

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

    # --- Canvas geometry + hit testing --------------------------------------

    def _text_box_screen(self, ov):
        "Screen box for ONE overlay: centre (cxs, cys) and half-extent (hw, hh)."
        scale = self._disp[0] or 1.0
        cxs, cys = self._src_to_scr(ov["cx"], ov["cy"])
        tw, th = imaging.text_extent(ov)
        if tw <= 0 or th <= 0:               # nothing typed yet → a placeholder box
            return cxs, cys, self.TEXT_EMPTY_HW, self.TEXT_EMPTY_HH
        return cxs, cys, tw * scale / 2.0, th * scale / 2.0

    def _text_at(self, x, y):
        "Topmost text under screen (x, y): (index, 'resize'|'move') or (None, None)."
        # The resize handle belongs to the selected element only.
        if self.text_sel is not None and 0 <= self.text_sel < len(self.texts):
            cxs, cys, hw, hh = self._text_box_screen(self.texts[self.text_sel])
            if math.hypot(x - (cxs + hw), y - (cys + hh)) <= self.TEXT_HANDLE + 5:
                return self.text_sel, "resize"
        # Otherwise the front-most box (last drawn) that contains the point. A
        # few px of slack makes selecting a glyph-tight box forgiving — it no
        # longer needs a pixel-perfect click right on the letters.
        pad = self.TEXT_HIT_PAD
        for i in range(len(self.texts) - 1, -1, -1):
            cxs, cys, hw, hh = self._text_box_screen(self.texts[i])
            if abs(x - cxs) <= hw + pad and abs(y - cys) <= hh + pad:
                return i, "move"
        return None, None

    # --- Mouse interaction --------------------------------------------------

    def _text_press(self, event):
        "Click a text to select it, then drag to move it / its corner to resize."
        if not self._text_active():
            return
        i, hit = self._text_at(event.x, event.y)
        if hit is None:
            return "break"                   # empty click: keep the selection
        if i != self.text_sel:
            self.text_sel = i                # clicking a box selects it
            self._sync_text_controls()
        self._edit_gesture_start()           # snapshot so the whole drag is one undo
        sx, sy = self._scr_to_src(event.x, event.y)
        ov = self.text_overlay
        if hit == "move":
            self._text_drag = ("move", sx, sy, ov["cx"], ov["cy"])
        else:
            d0 = max(1.0, math.hypot(sx - ov["cx"], sy - ov["cy"]))
            self._text_drag = ("resize", d0, ov["size"], None, None)
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
        "Show a move / resize cursor over a box while idle."
        if not self._text_active() or self._text_drag is not None:
            return
        _, hit = self._text_at(event.x, event.y)
        cur = {"resize": "bottom_right_corner", "move": "fleur"}.get(hit, "")
        self.preview.configure(cursor=cur)

    # --- Overlay ------------------------------------------------------------

    def _draw_text_overlay(self):
        "Chrome for the SELECTED text only (a bright box + resize handle); the"
        " other texts show as their plain composited glyphs, with no outline."
        c = self.preview
        for i, ov in enumerate(self.texts):
            cxs, cys, hw, hh = self._text_box_screen(ov)
            sel = (i == self.text_sel)
            if sel:
                x0, y0, x1, y1 = cxs - hw, cys - hh, cxs + hw, cys + hh
                c.create_rectangle(x0, y0, x1, y1,
                                   outline=ACCENT, dash=(4, 3), width=1)
                r = self.TEXT_HANDLE
                c.create_rectangle(x1 - r, y1 - r, x1 + r, y1 + r,
                                   fill=ACCENT, outline=ON_ACCENT)
            if not (ov.get("text") or "").strip():
                # An empty text has no glyphs — keep a faint hint so it stays
                # findable / clickable even when it isn't the selected one.
                c.create_text(cxs, cys, text=t("Type your text"), fill=FG_DIM,
                              font=("Segoe UI", 9))
