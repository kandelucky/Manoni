"""Window chrome: icons, info bar, toolbar, menu, body split, sidebar header,
breadcrumbs, and sidebar resize / thumbnail-size zoom.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import sys
import json
import time
import tkinter as tk
import tkinter.ttk as ttk
import tkinter.filedialog as tkfd

from PIL import Image, ImageTk

# Live theming: chrome now reads colours from self.theme (dark<->light) via the
# `_tw` helper, so only the preview canvas / rulers keep a fixed config colour.
# BG = preview letterbox (stays dark regardless of theme).
from ..config import (BG, ICON_SIZE, ICON_DIR,
                      CULL_KEEP_TINT, CULL_REJECT_TINT,
                      CULL_KEEP_TINT_LIGHT, CULL_REJECT_TINT_LIGHT)
from ..widgets import Tooltip
from .. import i18n
from ..i18n import t


class ChromeMixin:
    # --- Icons --------------------------------------------------------------

    def icon(self, name, size=None, color=None):
        "Load a Lucide icon scaled to `size` logical px (default ICON_SIZE),"
        " cached. Tinted to the theme foreground by default so icons follow the"
        " dark<->light switch; pass an explicit `color` (hex) to override — e.g."
        " the scheme-independent keep/reject tints or the always-light peek eye."
        " None if the PNG is missing."
        # None → the live theme foreground, so a light switch flips the strokes.
        if color is None:
            color = self.theme["fg"]
        # Cache per (name, size, resolved colour) so dark + light tints coexist.
        key = name
        if size is not None:
            key += f"@{size}"
        key += f"#{color}"
        if key in self.icons:
            return self.icons[key]
        path = os.path.join(ICON_DIR, name + ".png")
        img = None
        # Render at the DPI-scaled pixel size so icons stay crisp (not blurry
        # or undersized) next to the now point-scaled text. Source PNGs are
        # high-res, so the LANCZOS resize downsamples cleanly.
        px = round((size or ICON_SIZE) * getattr(self, "dpi", 1.0))
        if os.path.exists(path):
            try:
                im = Image.open(path).convert("RGBA")
                im = im.resize((px, px), Image.LANCZOS)
                if color is not None:
                    # Replace the white strokes with `color`, keeping the
                    # anti-aliased alpha as a mask so edges stay smooth.
                    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
                    tinted = Image.new("RGBA", im.size, rgb + (0,))
                    tinted.putalpha(im.split()[3])
                    im = tinted
                img = ImageTk.PhotoImage(im)
            except Exception:
                img = None
        self.icons[key] = img
        return img

    # --- Live theming for plain tk widgets ----------------------------------

    def _tw(self, w, bg=None, fg=None, insert=None, hl=None):
        "Bind a plain tk widget to theme tokens; restyle now + on every theme.set."
        " Lets a not-yet-tintkit tk.Label/Frame/Entry follow dark<->light like the"
        " migrated widgets do. Args are token KEYS (\"bar\", \"fg_dim\"…): bg/fg for"
        " Labels/Frames, `insert` = an Entry's caret, `hl` = highlightbackground"
        " (a focus-ring / swatch border)."
        def restyle():
            kw = {}
            if bg is not None:
                kw["bg"] = self.theme[bg]
            if fg is not None:
                kw["fg"] = self.theme[fg]
            if insert is not None:
                kw["insertbackground"] = self.theme[insert]
            if hl is not None:
                kw["highlightbackground"] = self.theme[hl]
            try:
                w.configure(**kw)
            except tk.TclError:                  # widget already destroyed
                self.theme.unsubscribe(restyle)

        def _drop(e):
            if e.widget is w:                    # ignore child <Destroy> bubbling
                self.theme.unsubscribe(restyle)
        self.theme.subscribe(restyle)
        w.bind("<Destroy>", _drop, add="+")
        restyle()
        return w

    def _icon_label(self, parent, name, size=None, token="fg", bg="bar",
                    fallback="", **kw):
        "A tk.Label holding a Lucide icon tinted to theme[`token`], re-tinted on"
        " every dark<->light switch — the icon analogue of _tw (plain Manoni"
        " icons don't follow the theme on their own). Falls back to `fallback`"
        " text if the PNG is missing. Pass bg=<token> to also thread the label"
        " bg, or bg=None to leave it to the caller (bespoke hover / active rows"
        " that paint their own bg)."
        lbl = tk.Label(parent, **kw)
        has_img = self.icon(name, size, self.theme[token]) is not None

        def restyle():
            try:
                if has_img:
                    im = self.icon(name, size, self.theme[token])
                    lbl.configure(image=im)
                    lbl._icon_ref = im            # keep a hard ref alive
                else:
                    lbl.configure(text=fallback, fg=self.theme[token])
                if bg is not None:
                    lbl.configure(bg=self.theme[bg])
            except tk.TclError:                   # widget destroyed
                self.theme.unsubscribe(restyle)

        self.theme.subscribe(restyle)
        lbl.bind("<Destroy>",
                 lambda e: e.widget is lbl and self.theme.unsubscribe(restyle),
                 add="+")
        restyle()
        return lbl

    def _reg_icon(self, label, name, size=None, token="fg"):
        "Re-tint an ALREADY-created icon label's image on every theme switch — the"
        " bg stays the caller's to manage (for bespoke hover / active rows that"
        " paint their own bg, so _icon_label's bg handling would fight them)."
        def restyle():
            try:
                im = self.icon(name, size, self.theme[token])
                if im is not None:
                    label.configure(image=im)
                    label._icon_ref = im
            except tk.TclError:
                self.theme.unsubscribe(restyle)
        self.theme.subscribe(restyle)
        label.bind("<Destroy>",
                   lambda e: e.widget is label and self.theme.unsubscribe(restyle),
                   add="+")
        restyle()
        return label

    def _cull_tint(self, which):
        "The keep/reject accent for the active scheme: near-white on the dark"
        " chrome, a saturated green/red on light so the icon + its info-line text"
        " stay legible. `which` is 'keep' or 'reject'."
        light = self.theme.scheme == "light"
        if which == "keep":
            return CULL_KEEP_TINT_LIGHT if light else CULL_KEEP_TINT
        return CULL_REJECT_TINT_LIGHT if light else CULL_REJECT_TINT

    def _tool_button(self, parent, icon_name, command, tooltip="", size=None,
                     color=None):
        "A flat icon button with hover effect (falls back to text if no icon)."
        " `color` may be a hex string (fixed) or a zero-arg callable resolved on"
        " each repaint — the keep/reject buttons pass a callable so their tint"
        " follows the dark<->light switch; a plain icon defaults to the theme fg."
        btn = tk.Label(parent, bg=self.theme["bar"], cursor="hand2")
        resolve = (lambda: color()) if callable(color) else (lambda: color)
        has_img = self.icon(icon_name, size, resolve()) is not None

        def restyle():
            try:
                if has_img:
                    im = self.icon(icon_name, size, resolve())
                    btn.configure(image=im)
                    btn._icon_ref = im
                else:
                    btn.configure(text=tooltip or "?", fg=self.theme["fg"],
                                  font=("Segoe UI", 10))
                btn.configure(bg=self.theme["bar"])
            except tk.TclError:
                self.theme.unsubscribe(restyle)

        self.theme.subscribe(restyle)
        btn.bind("<Destroy>",
                 lambda e: e.widget is btn and self.theme.unsubscribe(restyle),
                 add="+")
        restyle()
        btn.bind("<Enter>", lambda e: btn.configure(bg=self.theme["hover"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=self.theme["bar"]))
        btn.bind("<Button-1>", lambda e: command())
        btn._tooltip = tooltip
        if tooltip:
            btn._tip = Tooltip(btn, tooltip)
        return btn

    def _init_scrollbar_style(self):
        "A slim, dark, arrow-less scrollbar that suits the dark theme (was the"
        " bright default Windows bar). 'clam' is the only theme that recolors fully."
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        # Drop the up/down arrow buttons → just a trough + a draggable thumb.
        style.layout("Sidebar.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb",
                 {"expand": "1", "sticky": "nswe"})]})])
        style.configure("Sidebar.Vertical.TScrollbar",
                        troughcolor=self.theme["sidebar"],
                        background=self.theme["border"],
                        bordercolor=self.theme["sidebar"], borderwidth=0,
                        relief="flat", arrowcolor=self.theme["sidebar"], width=10)
        style.map("Sidebar.Vertical.TScrollbar",
                  background=[("active", "#5a5a5a"), ("pressed", "#666666")])

    def _glyph_button(self, parent, glyph, command, tooltip=""):
        "A flat text-glyph button with hover (for nav controls lacking an icon)."
        # bg follows the theme; fg is managed by the caller (see _update_breadcrumbs,
        # which switches btn_up between the active and disabled fg).
        btn = tk.Label(parent, text=glyph, bg=self.theme["bar"], fg=self.theme["fg"],
                       cursor="hand2", font=("Segoe UI", 13), padx=4)
        self._tw(btn, bg="bar")
        btn.bind("<Enter>", lambda e: btn.configure(bg=self.theme["hover"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=self.theme["bar"]))
        btn.bind("<Button-1>", lambda e: command())
        if tooltip:
            btn._tip = Tooltip(btn, tooltip)
        return btn

    def _sep(self, parent):
        "Vertical separator in a bar."
        return self._tw(tk.Frame(parent, width=1), bg="border")

    # --- Hand (pan) tool toggle ---------------------------------------------

    def _build_hand_button(self, parent):
        "A toggle icon button for the hand (pan) tool — accent-filled while active."
        img = self.icon("hand")
        if img is not None:
            btn = tk.Label(parent, image=img, bg=self.theme["bar"], cursor="hand2")
            btn._icon = "hand"
        else:
            btn = tk.Label(parent, text="✋", bg=self.theme["bar"],
                           fg=self.theme["fg"], cursor="hand2",
                           font=("Segoe UI", 11))
        btn.bind("<Enter>", lambda e: self._hand_btn_paint(hover=True))
        btn.bind("<Leave>", lambda e: self._hand_btn_paint(hover=False))
        btn.bind("<Button-1>", lambda e: self.toggle_hand_tool())
        btn._tip = Tooltip(btn, t("Hand tool — drag to pan the photo"))
        self.btn_hand = btn
        # Its resting/active fill is theme-dependent, so repaint on dark<->light.
        self.theme.subscribe(self._hand_btn_paint)
        return btn

    def _hand_btn_paint(self, hover=False):
        "Repaint the hand toggle: accent fill while active, hover tint otherwise."
        if not hasattr(self, "btn_hand"):
            return
        active = self.hand_tool
        if active:
            self.btn_hand.configure(bg=self.theme["accent"])
        else:
            self.btn_hand.configure(
                bg=self.theme["hover"] if hover else self.theme["bar"])
        self._retint_toggle_icon(self.btn_hand, active)

    def _retint_toggle_icon(self, btn, active):
        "Re-tint a toolbar toggle's icon: on_accent while accent-filled, else fg."
        name = getattr(btn, "_icon", None)
        if name is None:                          # text-glyph fallback (no PNG)
            btn.configure(fg=self.theme["on_accent"] if active else self.theme["fg"])
            return
        im = self.icon(name, color=self.theme["on_accent" if active else "fg"])
        if im is not None:
            btn.configure(image=im)
            btn._icon_ref = im

    def _set_hand_tool(self, on):
        "Turn the hand (pan) tool on/off: repaint the toggle + set the canvas cursor."
        if on == self.hand_tool:
            return
        self.hand_tool = on
        if on:
            self._set_compare(False)     # both claim the left-drag — only one at a time
        self._hand_btn_paint()
        # 'hand2' marks the tool as armed; turning it off clears the cursor and the
        # next pointer move lets the active edit tool (if any) reclaim its own.
        self.preview.configure(cursor="hand2" if on else "")

    def toggle_hand_tool(self):
        "Toolbar action: flip the hand (pan) tool on/off."
        self._set_hand_tool(not self.hand_tool)

    # --- Before/after compare (იყო / არის) ----------------------------------

    def _build_compare_button(self, parent):
        "A before/after toggle: click splits the photo with a draggable line;"
        " press-and-hold peeks the full original, releasing back to the edit."
        img = self.icon("square-split-horizontal")
        if img is not None:
            btn = tk.Label(parent, image=img, bg=self.theme["bar"], cursor="hand2")
            btn._icon = "square-split-horizontal"
        else:
            btn = tk.Label(parent, text="◧", bg=self.theme["bar"],
                           fg=self.theme["fg"], cursor="hand2",
                           font=("Segoe UI", 11))
        btn.bind("<Enter>", lambda e: self._compare_btn_paint(hover=True))
        btn.bind("<Leave>", lambda e: self._compare_btn_paint(hover=False))
        # Press = start peeking the original; release = stop. A quick tap (no
        # real hold) toggles the persistent split-line view instead.
        btn.bind("<ButtonPress-1>", self._compare_btn_press)
        btn.bind("<ButtonRelease-1>", self._compare_btn_release)
        btn._tip = Tooltip(btn, t("Compare before / after — click to split, "
                                  "hold to see the original"))
        self.btn_compare = btn
        # Its resting/active fill is theme-dependent, so repaint on dark<->light.
        self.theme.subscribe(self._compare_btn_paint)
        return btn

    def _compare_btn_paint(self, hover=False):
        "Repaint the compare toggle: accent fill while split is on, else hover tint."
        if not hasattr(self, "btn_compare"):
            return
        active = self.compare_mode
        if active:
            self.btn_compare.configure(bg=self.theme["accent"])
        else:
            self.btn_compare.configure(
                bg=self.theme["hover"] if hover else self.theme["bar"])
        self._retint_toggle_icon(self.btn_compare, active)

    def _compare_btn_press(self, event):
        "Button pressed: peek the full original and start timing the hold."
        self._compare_press_t = time.monotonic()
        self._compare_peek_on()

    def _compare_btn_release(self, event):
        "Button released: stop peeking; a quick tap also toggles the split view."
        self._compare_peek_off()
        held = time.monotonic() - getattr(self, "_compare_press_t", 0.0)
        if held < 0.25:
            self.toggle_compare()

    def _set_compare(self, on):
        "Turn the split-line compare view on/off: repaint toggle + canvas cursor."
        if on == self.compare_mode:
            return
        self.compare_mode = on
        if on:
            self._set_hand_tool(False)   # both claim the left-drag — only one at a time
        self._compare_btn_paint()
        self.preview.configure(cursor="sb_h_double_arrow" if on else "")
        self._render_preview()

    def toggle_compare(self):
        "Toolbar action: flip the before/after split-line view on/off."
        self._set_compare(not self.compare_mode)

    # --- Top info bar -------------------------------------------------------

    def _build_infobar(self):
        # Status bar pinned to the very bottom of the window (root row 3, below
        # the editor body). A 1px hairline along its top edge separates it from
        # the body and spans the full window width.
        self.infobar = self._tw(tk.Frame(self.root, height=30), bg="bar")
        self.infobar.grid(row=3, column=0, sticky="ew")
        self.infobar.grid_propagate(False)

        self._tw(tk.Frame(self.infobar, height=1), bg="border").pack(
            side="top", fill="x")

        # Photo info button: pops a window with the current photo's metadata
        # (colour profile, camera, capture settings, GPS) — the same data the
        # Save dialog can keep or strip. Sits on the right, opposite the info
        # text it explains. (Moved here from the toolbar; icon shrunk ~30%.)
        self._tool_button(self.infobar, "info", self._metadata_dialog,
                          t("Photo info (metadata)"), size=15).pack(
                              side="right", padx=10, pady=4)

        # Labels ~30% smaller than the old 9pt, and clickable: clicking either
        # opens the same metadata window as the info button.
        self.lbl_name = self._tw(
            tk.Label(self.infobar, text="Manoni", font=("Segoe UI", 8),
                     cursor="hand2"), bg="bar", fg="fg")
        self.lbl_name.pack(side="left", padx=12)

        self.lbl_info = self._tw(
            tk.Label(self.infobar, text="", font=("Segoe UI", 7),
                     cursor="hand2"), bg="bar", fg="fg_dim")
        self.lbl_info.pack(side="left", padx=8)

        for _lbl in (self.lbl_name, self.lbl_info):
            _lbl.bind("<Button-1>", lambda e: self._metadata_dialog())
            _lbl._tip = Tooltip(_lbl, t("Photo info (metadata)"))

    # --- Toolbar ------------------------------------------------------------

    def _build_toolbar(self):
        "Three-zone bar: file + history (left) · viewport tools (center) · menu (right)."
        bar = self._tw(tk.Frame(self.root, height=46), bg="bar")
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)

        # LEFT zone: file operations (open / save) then edit history (undo / redo),
        # read left-to-right as one "file & history" cluster. Photo navigation
        # (prev/next/first/last) lives on the bottom strip, next to the position
        # counter — not repeated here.
        left = self._tw(tk.Frame(bar), bg="bar")
        left.pack(side="left", padx=8)
        self._tool_button(left, "folder-open", self.open_folder,
                          t("Open folder")).pack(side="left", padx=4, pady=8)
        # Save as… sits next to Open — both are file operations. (Moved up here
        # from the ☰ menu so saving is one click away.)
        self._tool_button(left, "save", self._save_as_dialog,
                          t("Save as…")).pack(side="left", padx=4, pady=8)
        # Undo / redo follow the file buttons, split off by a separator: the eye
        # reads open → save → undo → redo as one file-and-history run instead of
        # hunting for undo out in the centre of the bar.
        self._sep(left).pack(side="left", fill="y", padx=6, pady=10)
        for spec in [
            ("undo", self.undo, t("Undo (Ctrl+Z)")),
            ("redo", self.redo, t("Redo (Ctrl+Y)")),
        ]:
            self._tool_button(left, *spec).pack(side="left", padx=4, pady=8)

        # CENTER zone: viewport tools. The hand (pan) and before/after compare
        # both act on the preview, so they sit centred over it. Placed (not
        # packed) so the left/right zones don't shift them off-centre.
        center = self._tw(tk.Frame(bar), bg="bar")
        center.place(relx=0.5, rely=0.5, anchor="center")
        # Hand (pan) tool: a toggle — while on, dragging with the left button
        # moves the photo on the canvas (like Photoshop's hand).
        self._build_hand_button(center).pack(side="left", padx=4, pady=8)
        # Before/after compare: a split line you drag, or hold to peek the original.
        self._build_compare_button(center).pack(side="left", padx=4, pady=8)

        # RIGHT zone: two app-level controls — a ⚙ gear opening the tabbed
        # Settings window, and a "?" opening the tabbed Help window. These replace
        # the old single ☰ menu: its other entries (Language · About) now live
        # inside Settings, so no dropdown is needed here anymore.
        right = self._tw(tk.Frame(bar), bg="bar")
        right.pack(side="right", padx=8)
        # Pack help first so it sits rightmost, gear to its left → reads ⚙ ?.
        self.btn_help = self._tool_button(right, "circle-help",
                                          self._help_dialog, t("Help"))
        self.btn_help.pack(side="right", padx=4, pady=8)
        self.btn_settings = self._tool_button(right, "settings",
                                              self._settings_dialog, t("Settings"))
        self.btn_settings.pack(side="right", padx=4, pady=8)

        # The edit panel's open/close lives on the always-visible icon rail
        # (a collapse chevron), not here — see _build_tool_rail / toggle_panel.

    # --- Language ----------------------------------------------------------

    def switch_language(self, lang):
        "Switch the UI language: persist the choice, then relaunch so every"
        " widget is rebuilt in the new language (the session is restored)."
        if lang == i18n.get_language():
            return
        if not self._maybe_prompt_save():   # honor unsaved edits, like closing
            return
        i18n.set_language(lang)             # so _save_state writes the new choice
        self._save_state()
        self._relaunch()

    def _relaunch(self):
        "Restart the Manoni process in place (after a language change)."
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            # Couldn't re-exec (rare) — exit; the new language applies next launch.
            sys.exit(0)

    # --- "Add your language" studio ----------------------------------------

    def _language_studio(self):
        "A window to add a UI language: generate a template, import a finished"
        " translation, or export an installed language to share."
        bg, fg, fg_dim = self.theme["bg"], self.theme["fg"], self.theme["fg_dim"]
        dlg = tk.Toplevel(self.root)
        dlg.title(t("Add your language"))
        dlg.configure(bg=bg)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=bg, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=t("Add your language"), bg=bg, fg=fg,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        steps = t("Manoni can speak any language. Here's how:\n"
                  "1. Generate a template file — it lists every English text.\n"
                  "2. Open it in any text editor and fill in your translations.\n"
                  "3. Import the finished file — your language appears in the menu.")
        tk.Label(wrap, text=steps, bg=bg, fg=fg_dim, justify="left", anchor="w",
                 font=("Segoe UI", 9), wraplength=self._edit_dpi_w(380)) \
            .pack(anchor="w", pady=(8, 16))

        self._filter_action(wrap, "download", t("Generate template file"),
                            self._lang_export_template,
                            t("Save a .json file with every text to translate"))
        self._filter_action(wrap, "folder-input", t("Import a language"),
                            lambda: self._lang_import(dlg),
                            t("Load a finished .json translation and install it"))
        self._filter_action(wrap, "share-2", t("Export a language"),
                            self._lang_export_pack,
                            t("Save an installed language to a .json file to share"))

        self._dialog_btn(wrap, t("Close"), dlg.destroy).pack(anchor="e",
                                                              pady=(16, 0))
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        self._place_filter_dialog(dlg)

    def _lang_export_template(self):
        "Write a .json template: every English source string, ready to translate."
        payload = {
            "_readme": ("Fill in 'code' (e.g. fr) and 'name' (e.g. Francais), "
                        "then translate the right-hand value of each line under "
                        "'strings'. Leave the left-hand key exactly as it is."),
            "code": "",
            "name": "",
            "strings": {s: s for s in i18n.source_strings()},
        }
        path = tkfd.asksaveasfilename(
            parent=self.root, title=t("Save template"),
            defaultextension=".json", initialfile="manoni-language.json",
            filetypes=[(t("Language file"), "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self.toast(t("Template saved → {name}").format(
                name=os.path.basename(path)))
        except Exception:
            self.toast(t("Could not write the file"))

    def _lang_import(self, parent_dlg=None):
        "Load a finished translation .json, install it to LANG_DIR, switch to it."
        from ..config import LANG_DIR
        path = tkfd.askopenfilename(
            parent=self.root, title=t("Import a language"),
            filetypes=[(t("Language file"), "*.json"), (t("All files"), "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                code, name = i18n.load_pack(json.load(f))
        except Exception:
            self.toast(t("That isn't a valid language file"))
            return
        # Strip path separators so a hand-written code can't escape LANG_DIR.
        safe = "".join(ch for ch in code if ch.isalnum() or ch in "-_")
        if not safe or code == i18n.DEFAULT_LANG:
            self.toast(t("That language code is reserved"))
            return
        try:
            os.makedirs(LANG_DIR, exist_ok=True)
            with open(os.path.join(LANG_DIR, f"{safe}.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"code": code, "name": name,
                           "strings": i18n.catalog(code)}, f,
                          ensure_ascii=False, indent=2)
        except Exception:
            self.toast(t("Could not write the file"))
            return
        if parent_dlg is not None:
            try:
                parent_dlg.destroy()
            except tk.TclError:
                pass
        self.toast(t("Language added: {name}").format(name=name))
        # Switch to the freshly added language (relaunches, restoring the session).
        self.switch_language(code)

    def _lang_export_pack(self):
        "Pick an installed language and save its pack to a .json file to share."
        langs = [(c, n) for c, n in i18n.available() if c != i18n.DEFAULT_LANG]
        if not langs:
            self.toast(t("No languages to export yet"))
            return
        if len(langs) == 1:
            self._write_lang_pack(*langs[0])
            return
        dlg, body = self._filter_dialog(t("Export a language"))
        for code, name in langs:
            self._filter_action_plain(
                body, "share-2", name,
                lambda c=code, n=name: (self._write_lang_pack(c, n), dlg.destroy()))
        self._place_filter_dialog(dlg)

    def _write_lang_pack(self, code, name):
        "Save one installed language ({code,name,strings}) to a chosen .json file."
        path = tkfd.asksaveasfilename(
            parent=self.root, title=t("Export a language"),
            defaultextension=".json", initialfile=f"manoni-{code}.json",
            filetypes=[(t("Language file"), "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"code": code, "name": name,
                           "strings": i18n.catalog(code)}, f,
                          ensure_ascii=False, indent=2)
            self.toast(t("Exported → {name}").format(name=os.path.basename(path)))
        except Exception:
            self.toast(t("Could not write the file"))

    # --- Body: sidebar + preview -------------------------------------------

    def _build_body(self):
        body = self._tw(tk.Frame(self.root), bg="bg")
        body.grid(row=2, column=0, sticky="nsew")
        self.body = body
        body.rowconfigure(0, weight=1)      # preview row expands
        body.rowconfigure(1, weight=0)      # filter preview strip (shown on demand)
        body.rowconfigure(2, weight=0)      # bottom strip (nav + zoom) fixed
        body.columnconfigure(0, weight=0)   # thumbnail sidebar (drag-resizable)
        body.columnconfigure(1, weight=0)   # drag sash
        body.columnconfigure(2, weight=1)   # preview expands
        body.columnconfigure(3, weight=0)   # tool section panel fixed
        body.columnconfigure(4, weight=0)   # Fotor-style icon rail fixed

        # Sidebar (scrollable thumbnail grid) — full height, left of the bottom strips
        side = self._tw(tk.Frame(body, width=self.sidebar_width), bg="sidebar")
        side.grid(row=0, column=0, rowspan=3, sticky="ns")
        side.pack_propagate(False)   # honor our width; children are packed, not gridded
        self.sidebar = side

        # Hero header (top): where-you-are address + folder navigation +
        # thumbnail-size zoom. (Replaces the old bottom footer strip.)
        self._build_sidebar_hero(side)

        # Top section: an auto-height, nested folder tree (tintkit.FolderTree,
        # filled by browser._refresh_folder_tree). Sits above the thumbnail grid.
        self._build_folder_panel(side)

        # Bottom strip of the sidebar: view-mode picker + thumbnail-size zoom.
        # Packed (side="bottom") before the canvas so the grid fills above it.
        self._build_sidebar_footer(side)

        self.canvas = self._tw(tk.Canvas(side, highlightthickness=0), bg="sidebar")
        # The scrollbar is driven entirely by hand (browser._render_window / the
        # _thumb_yview / _on_wheel below) via self._scroll_row (row units, not
        # pixels) — the strip's own canvas scrollregion is kept tiny (bounded to the
        # realized viewport window, not the whole folder) to stay under Tk's
        # ~32,767 px canvas coordinate ceiling, so it can't drive the scrollbar
        # itself the way a normal canvas + scrollbar pairing would.
        sb = ttk.Scrollbar(side, orient="vertical", command=self._thumb_yview,
                           style="Sidebar.Vertical.TScrollbar")
        self._thumb_scrollbar = sb     # folder list packs just above this
        self.thumb_holder = self._tw(tk.Frame(self.canvas), bg="sidebar")
        self._thumb_window = self.canvas.create_window(
            (0, 0), window=self.thumb_holder, anchor="nw")
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        # Keep the grid wrapped to the visible width, and reflow on resize.
        self.canvas.bind("<Configure>", self._on_sidebar_configure)
        for w in (self.canvas, self.thumb_holder):
            w.bind("<MouseWheel>", self._on_wheel)

        # Drag-sash between the sidebar and the preview (horizontal resize). A
        # centred vertical grip nub mirrors the folder divider so both clearly
        # read as draggable; the strip lightens and the nub turns accent on hover.
        sash = self._tw(tk.Frame(body, width=8, cursor="sb_h_double_arrow"),
                        bg="bar")
        sash.grid(row=0, column=1, rowspan=3, sticky="ns")
        grip = self._tw(tk.Frame(sash), bg="fg_dim")
        grip.place(relx=0.5, rely=0.5, anchor="center", width=4, height=40)
        self.sash, self.sash_grip = sash, grip
        for w in (sash, grip):
            w.bind("<Button-1>", self._sash_press)
            w.bind("<B1-Motion>", self._sash_drag)
            w.bind("<Enter>",
                   lambda e: (sash.configure(bg=self.theme["hover"]),
                              grip.configure(bg=self.theme["accent"])))
            w.bind("<Leave>",
                   lambda e: (sash.configure(bg=self.theme["bar"]),
                              grip.configure(bg=self.theme["fg_dim"])))

        # Big preview fills the center (Canvas so it can zoom + pan). Its
        # letterbox stays the dark BG even in light mode — the photo is judged
        # against a neutral dark surround (like Lightroom / Photoshop).
        self.preview = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.preview.grid(row=0, column=2, sticky="nsew")
        # Wheel = zoom at the cursor (or resize the heal brush); middle-button
        # drag = pan (hand).
        self.preview.bind("<MouseWheel>", self._preview_wheel)
        self.preview.bind("<Button-2>", self._on_pan_start)
        self.preview.bind("<B2-Motion>", self._on_pan_move)
        self.preview.bind("<ButtonRelease-2>", self._on_pan_end)
        # Left button drives the active tool: retouch painting or the crop
        # selection (each acts only while its own tool is open). Alt+click sets
        # the clone source in clone mode. See viewer._preview_*.
        self.preview.bind("<Button-1>", self._preview_press)
        self.preview.bind("<Alt-Button-1>", self._preview_alt_press)
        self.preview.bind("<B1-Motion>", self._preview_drag)
        self.preview.bind("<ButtonRelease-1>", self._preview_release)
        self.preview.bind("<Motion>", self._preview_hover)

        # Fotor-style edit area on the right: section panel + labeled icon rail
        self._build_edit_panel(body)
        self._build_tool_rail(body)

        # Horizontal filter preview strip below the preview (row 1, col 2). It is
        # built last so the section panel / rail already exist, and stays hidden
        # until there are saved filters AND a photo to render them on.
        self._build_filter_strip(body)

    def _on_wheel(self, event):
        "Mouse wheel over the strip: nudge self._scroll_row (row units) directly —"
        " never the canvas's own yview, which browser.py deliberately keeps tiny"
        " (see _render_window) so it never nears Tk's canvas coordinate ceiling."
        notches = -event.delta / 120
        self._scroll_row = getattr(self, "_scroll_row", 0.0) \
            + notches * self.THUMB_WHEEL_ROWS
        self._render_window()        # realize cells that scrolled into view
        return "break"

    def _thumb_yview(self, *args):
        "Scrollbar command: translate the native moveto/scroll protocol into a row"
        " offset (self._scroll_row), then realize the newly-visible cells. Never lets"
        " the canvas's own (deliberately tiny) yview drive this — see"
        " browser._render_window."
        cell_w, cell_h, cols = self._cell_metrics()
        n = len(self.files)
        total_rows = (n + cols - 1) // cols if cols else 0
        visible_rows = max(1.0, self._canvas_view_h() / cell_h)
        row = getattr(self, "_scroll_row", 0.0)
        if args[0] == "moveto":
            row = float(args[1]) * total_rows
        elif args[0] == "scroll":
            amount = int(args[1])
            row += amount * visible_rows if args[2] == "pages" else amount
        self._scroll_row = max(0.0, min(row, max(0.0, total_rows - visible_rows)))
        self._render_window()

    # --- Sidebar top section: the auto-height sub-folder list ---------------

    def _build_folder_panel(self, side):
        """Scaffold the sidebar's top section: a folder tree whose height tracks
        its content (capped at FOLDER_LIST_MAX, then it scrolls). The tree is
        filled in by browser._refresh_folder_tree, which also shows/hides this
        whole panel depending on whether the root has any sub-folders. A 1px
        divider at its foot separates the tree from the thumbnail grid below."""
        self.folder_panel = self._tw(tk.Frame(side), bg="sidebar")  # packed on demand
        # A draggable divider at the foot separates the list from the grid below and
        # lets the user set the list's height (drag up/down). It's a slim grab strip
        # with a centred 1px line — packed first so it always spans the full width
        # under the canvas + scrollbar. See _folder_sash_drag.
        sash = self._tw(tk.Frame(self.folder_panel, height=11,
                                 cursor="sb_v_double_arrow"), bg="sidebar")
        sash.pack(side="bottom", fill="x")
        sash.pack_propagate(False)
        # Faint full-width hairline marks the boundary; the centred grip nub on top
        # of it says "drag me" (turns accent on hover). Same idiom as the side sash.
        line = self._tw(tk.Frame(sash), bg="border")
        line.place(relx=0.0, rely=0.5, relwidth=1.0, height=1, anchor="w")
        grip = self._tw(tk.Frame(sash), bg="fg_dim")
        grip.place(relx=0.5, rely=0.5, anchor="center", width=40, height=4)
        self.folder_sash, self.folder_sash_grip = sash, grip
        for w in (sash, line, grip):
            w.bind("<Enter>", lambda e: grip.configure(bg=self.theme["accent"]))
            w.bind("<Leave>", lambda e: grip.configure(bg=self.theme["fg_dim"]))
            w.bind("<Button-1>", self._folder_sash_press)
            w.bind("<B1-Motion>", self._folder_sash_drag)
            w.bind("<ButtonRelease-1>", self._folder_sash_release)
        self.folder_canvas = self._tw(
            tk.Canvas(self.folder_panel, highlightthickness=0, height=1),
            bg="sidebar")
        # A slim scrollbar, shown only while the sub-folder list overflows its cap
        # (so a folder with many sub-folders is fully reachable, not just by wheel).
        self.folder_scrollbar = ttk.Scrollbar(
            self.folder_panel, orient="vertical", command=self.folder_canvas.yview,
            style="Sidebar.Vertical.TScrollbar")
        self.folder_canvas.configure(yscrollcommand=self.folder_scrollbar.set)
        self.folder_canvas.pack(side="left", fill="both", expand=True)
        self.folder_holder = self._tw(tk.Frame(self.folder_canvas), bg="sidebar")
        self._folder_window = self.folder_canvas.create_window(
            (0, 0), window=self.folder_holder, anchor="nw")
        self.folder_holder.bind("<Configure>", self._on_folder_holder_configure)
        self.folder_canvas.bind("<Configure>", self._on_folder_canvas_configure)
        for w in (self.folder_canvas, self.folder_holder):
            w.bind("<MouseWheel>", self._on_folder_wheel)

    def _folder_cap(self):
        "Tallest the folder list AUTO-grows: the smaller of the absolute ceiling and a"
        " share of the sidebar height — so it never crowds out the photo list below."
        avail = self.sidebar.winfo_height()
        if avail <= 1:                       # not laid out yet → use the ceiling
            return self.FOLDER_LIST_MAX
        return max(self.FOLDER_LIST_MIN,
                   min(self.FOLDER_LIST_MAX, int(avail * self.FOLDER_CAP_FRACTION)))

    def _folder_drag_max(self):
        "Tallest the user may DRAG the list — a larger share of the sidebar than the"
        " auto cap, but still leaving room for the photo grid below."
        avail = self.sidebar.winfo_height()
        if avail <= 1:
            return self.FOLDER_LIST_MAX
        return max(self.FOLDER_LIST_MIN, int(avail * self.FOLDER_DRAG_MAX_FRACTION))

    def _folder_target_height(self):
        "Height the folder list wants: the user's dragged height (clamped to the live"
        " sidebar) if set, else the auto cap. Display is still bounded by its content."
        if self.folder_list_height is not None:
            return max(self.FOLDER_LIST_MIN,
                       min(self.folder_list_height, self._folder_drag_max()))
        return self._folder_cap()

    def _on_folder_holder_configure(self, event=None):
        "Size the folder list to the user's height (or auto cap), bounded by its content."
        h = self.folder_holder.winfo_reqheight()
        cap = self._folder_target_height()
        self.folder_canvas.configure(height=max(1, min(h, cap)),
                                     scrollregion=(0, 0, 0, h))
        # Show the slim scrollbar only while the list overflows its visible height.
        # Deciding this here (from content vs cap) is reliable; driving it from the
        # canvas's yscrollcommand instead raced the incremental loader's redraws.
        if h > cap:
            if not self.folder_scrollbar.winfo_ismapped():
                # 'before' the canvas so pack allocates the scrollbar's width FIRST;
                # the expand=True canvas would otherwise claim all the room and the
                # late-packed scrollbar would get zero width (packed but invisible).
                self.folder_scrollbar.pack(side="right", fill="y",
                                           before=self.folder_canvas)
        elif self.folder_scrollbar.winfo_ismapped():
            self.folder_scrollbar.pack_forget()
            self.folder_canvas.yview_moveto(0.0)   # nothing to scroll → snap to top

    # --- Folder-list divider: drag to resize the sub-folder list ------------

    def _folder_sash_press(self, event):
        "Grab the folder divider: remember the pointer Y + the list's current height."
        self._folder_sash_start = (event.y_root, self.folder_canvas.winfo_height())

    def _folder_sash_drag(self, event):
        "Drag the divider up/down to set the sub-folder list height (it scrolls past"
        " its content; display never exceeds the rows it holds)."
        if not hasattr(self, "_folder_sash_start"):
            return
        y0, h0 = self._folder_sash_start
        new_h = max(self.FOLDER_LIST_MIN,
                    min(self._folder_drag_max(), h0 + (event.y_root - y0)))
        if new_h != self.folder_list_height:
            self.folder_list_height = new_h
            self._on_folder_holder_configure()

    def _folder_sash_release(self, event):
        "End the drag and persist the chosen folder-list height across sessions."
        if hasattr(self, "_folder_sash_start"):
            del self._folder_sash_start
            self._save_state()

    def _on_folder_canvas_configure(self, event):
        "Match the inner tree frame width to the folder canvas viewport."
        self.folder_canvas.itemconfigure(self._folder_window, width=event.width)

    def _on_folder_wheel(self, event):
        "Scroll the folder list (a no-op until it overflows its height cap)."
        self.folder_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    # --- Sidebar hero header (address + navigation + thumb-size zoom) --------

    MAX_CRUMBS = 3   # most path segments shown in the address (leading "…" else)

    def _build_sidebar_hero(self, side):
        """Top 'hero' strip of the sidebar: just the address of the open folder
        (up-a-folder button + clickable breadcrumb). The thumbnail-size zoom and
        view-mode picker moved to the sidebar footer (_build_sidebar_footer), so
        this header is a clean, single-line address bar. A 1px divider below it
        makes it read as a header above the thumbnail grid."""
        hero = self._tw(tk.Frame(side), bg="bar")
        hero.pack(side="top", fill="x")

        # A single address row: up-a-folder (left) + clickable breadcrumb.
        row = self._tw(tk.Frame(hero), bg="bar")
        row.pack(side="top", fill="x", padx=6, pady=5)

        self.btn_up = self._glyph_button(row, "↑", self.go_up_folder,
                                         t("Up a folder"))
        self.btn_up.pack(side="left", padx=(0, 2))

        # Click an ancestor crumb to navigate there; the leaf is the open folder.
        self.crumbs = self._tw(tk.Frame(row), bg="bar")
        self.crumbs.pack(side="left", fill="x", expand=True)

        # A clearly-visible header divider (the old #3a3a3a line was too faint).
        # This deliberately-strong #555555 has no theme token — kept fixed for now;
        # revisit its light-mode value when the dark/light toggle is built.
        tk.Frame(side, bg="#555555", height=1).pack(side="top", fill="x")
        self._update_breadcrumbs()
        # The crumbs are rebuilt from theme colours; repaint them on dark<->light.
        self.theme.subscribe(self._update_breadcrumbs)

    def _path_segments(self, path):
        "Split a folder path into [(label, fullpath), ...] from root to leaf."
        path = os.path.normpath(path)
        parts = []
        head, tail = os.path.split(path)
        while tail:
            parts.append((tail, path))
            path = head
            head, tail = os.path.split(path)
        if path:                       # the drive / root (e.g. 'C:\\' or '/')
            parts.append((path, path))
        parts.reverse()
        return parts

    def _update_breadcrumbs(self):
        "Rebuild the address from self.folder (ancestors clickable, leaf inert)."
        if not hasattr(self, "crumbs"):
            return
        for w in self.crumbs.winfo_children():
            w.destroy()
        if not self.folder:
            tk.Label(self.crumbs, text=t("No folder open"), bg=self.theme["bar"],
                     fg=self.theme["fg_dim"], font=("Segoe UI", 8)).pack(side="left")
            self.btn_up.configure(fg="#5a5a5a")   # nothing to go up to
            return
        self.btn_up.configure(fg=self.theme["fg"])
        segs = self._path_segments(self.folder)
        truncated = len(segs) > self.MAX_CRUMBS
        shown = segs[-self.MAX_CRUMBS:]
        if truncated:                  # "…" jumps to the level above the window
            self._crumb_label("…", segs[-self.MAX_CRUMBS - 1][1], leaf=False)
        for i, (label, full) in enumerate(shown):
            if i > 0 or truncated:
                tk.Label(self.crumbs, text="›", bg=self.theme["bar"],
                         fg=self.theme["fg_dim"], font=("Segoe UI", 8)).pack(side="left")
            self._crumb_label(label, full, leaf=(i == len(shown) - 1))

    def _crumb_label(self, text, full, leaf):
        "One breadcrumb: the leaf (current folder) is bright + inert; ancestors"
        " are dim and clickable to navigate into that folder."
        lbl = tk.Label(self.crumbs, text=text, bg=self.theme["bar"],
                       fg=self.theme["fg"] if leaf else self.theme["fg_dim"],
                       font=("Segoe UI", 8, "bold" if leaf else "normal"),
                       cursor="arrow" if leaf else "hand2")
        lbl.pack(side="left")
        if not leaf:
            lbl.bind("<Enter>", lambda e: lbl.configure(fg=self.theme["accent"]))
            lbl.bind("<Leave>", lambda e: lbl.configure(fg=self.theme["fg_dim"]))
            lbl.bind("<Button-1>", lambda e, p=full: self._navigate_to(p))
        if full != text:
            lbl._tip = Tooltip(lbl, full)
        return lbl

    def _navigate_to(self, path):
        "Open a folder from the address bar (loads its images; empty is fine)."
        if path and os.path.isdir(path):
            self.load_folder(path)

    def go_up_folder(self):
        "Navigate to the parent of the current folder (address-bar ↑)."
        if not self.folder:
            return
        parent = os.path.dirname(os.path.normpath(self.folder))
        if parent and parent != self.folder and os.path.isdir(parent):
            self.load_folder(parent)

    # --- Sidebar footer (view-mode picker + thumbnail-size zoom) -------------

    def _build_sidebar_footer(self, side):
        """Bottom strip of the sidebar — a horizontal footer that is part of the
        panel. Holds only the view-mode dropdown (large / medium / small icons ·
        list); the dropdown's size presets are the thumbnail-size control, so the
        separate −/+ zoom buttons are gone. Packed at the very bottom so the
        thumbnail grid fills the space above it."""
        foot = self._tw(tk.Frame(side), bg="bar")
        foot.pack(side="bottom", fill="x")
        self.sidebar_footer = foot

        # A 1px divider on top so the footer reads as a strip below the grid.
        # (Fixed strong #555555 — see the note in _build_sidebar_hero.)
        tk.Frame(foot, bg="#555555", height=1).pack(side="top", fill="x")

        row = self._tw(tk.Frame(foot), bg="bar")
        row.pack(side="top", fill="x", padx=6, pady=4)

        # The view-mode dropdown (large icons / small / list …) — the whole footer.
        self._build_view_button(row).pack(side="left")

    def _build_view_button(self, parent):
        "A flat dropdown button (current view label + ▾) that opens the view menu."
        btn = self._tw(tk.Frame(parent, cursor="hand2"), bg="bar")
        label = self._tw(tk.Label(btn, text="", font=("Segoe UI", 9)),
                         bg="bar", fg="fg")
        label.pack(side="left", padx=(6, 0), pady=3)
        chev = self._tw(tk.Label(btn, text="▾", font=("Segoe UI", 8)),
                        bg="bar", fg="fg_dim")
        chev.pack(side="left", padx=(4, 6))
        self.btn_view = btn
        self.view_btn_label = label
        cells = (btn, label, chev)

        def enter(_e):
            for w in cells:
                w.configure(bg=self.theme["hover"])

        def leave(_e):
            for w in cells:
                w.configure(bg=self.theme["bar"])
        for w in cells:
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
            w.bind("<Button-1>", lambda e: self._open_view_menu())
        self._update_view_button()
        return btn

    def _active_view(self):
        "Which view-menu key is currently active ('list', a grid preset, or None)."
        if self.view_mode == "list":
            return "list"
        for key, _label, size in self.VIEW_MENU:
            if isinstance(size, int) and size == self.thumb_size:
                return key
        return None                       # a custom (zoomed) icon size

    def _update_view_button(self):
        "Refresh the dropdown face so it mirrors the active view (label only)."
        if not hasattr(self, "view_btn_label"):
            return
        if self.view_mode == "list":
            text = t("List")
        else:
            key = self._active_view()
            text = t(next((l for k, l, _s in self.VIEW_MENU if k == key), "Icons"))
        self.view_btn_label.configure(text=text)

    def _open_view_menu(self):
        "Open (or toggle shut) the view-mode dropdown above the footer button."
        if getattr(self, "_view_popup", None) is not None:
            self._close_view_menu()
            return
        pop = tk.Toplevel(self.root)
        pop.overrideredirect(True)                 # borderless: a real popup menu
        pop.configure(bg=self.theme["border"])  # 1px hairline border via inset
        self._view_popup = pop
        inner = tk.Frame(pop, bg=self.theme["bar"])
        inner.pack(padx=1, pady=1)
        active = self._active_view()
        for key, label, _size in self.VIEW_MENU:
            self._view_menu_row(inner, key, label, active)

        # Open UPWARD: the footer sits at the window's bottom edge, so a downward
        # popup would fall off-screen. Align the popup's left with the button.
        pop.update_idletasks()
        bx = self.btn_view.winfo_rootx()
        by = self.btn_view.winfo_rooty()
        y = by - pop.winfo_height() - 2
        pop.geometry(f"+{max(0, bx)}+{max(0, y)}")
        pop.bind("<Escape>", lambda e: self._close_view_menu())
        pop.bind("<FocusOut>", lambda e: self._close_view_menu())
        pop.focus_force()                          # so clicking elsewhere closes it

    def _close_view_menu(self):
        "Tear down the view dropdown if it is open."
        pop = getattr(self, "_view_popup", None)
        if pop is not None:
            self._view_popup = None
            try:
                pop.destroy()
            except tk.TclError:
                pass

    def _view_menu_row(self, parent, key, label, active_key):
        "One row in the view dropdown; the active view is checked + accent-colored."
        is_active = (key == active_key)
        bar, hover, accent, fg = (self.theme["bar"], self.theme["hover"],
                                  self.theme["accent"], self.theme["fg"])
        r = tk.Frame(parent, bg=bar, cursor="hand2")
        r.pack(fill="x")
        mark = tk.Label(r, text="✓" if is_active else "", bg=bar, fg=accent,
                        width=2, font=("Segoe UI", 9))
        mark.pack(side="left", padx=(8, 2), pady=6)
        lab = tk.Label(r, text=t(label), bg=bar, anchor="w",
                       fg=accent if is_active else fg, font=("Segoe UI", 9))
        lab.pack(side="left", padx=(0, 20), pady=6)
        cells = (r, mark, lab)

        def enter(_e):
            for w in cells:
                w.configure(bg=hover)

        def leave(_e):
            for w in cells:
                w.configure(bg=bar)

        def click(_e):
            self._close_view_menu()
            self.set_view(key)
        for w in cells:
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
            w.bind("<Button-1>", click)

    def set_view(self, key):
        "Switch the sidebar between icon sizes and the compact list view."
        sizes = {k: s for k, _l, s in self.VIEW_MENU}
        if key == "list":
            self.view_mode = "list"
        else:
            self.view_mode = "grid"
            size = sizes.get(key)
            if isinstance(size, int):
                self.thumb_size = max(self.THUMB_MIN, min(self.THUMB_MAX, size))
        self._thumb_cols = self._calc_cols()
        self._build_thumbs(overlay=True)   # cover the rebuild like a folder load
        self._update_view_button()

    # --- Sidebar resize (drag-sash) + thumbnail-size zoom -------------------

    def _sash_press(self, event):
        "Grab the sash: remember the pointer + sidebar width at the start of a drag."
        self._sash_start = (event.x_root, self.sidebar.winfo_width())

    def _sash_drag(self, event):
        "Drag the sash: widen/narrow the sidebar; the grid reflows via <Configure>."
        if not hasattr(self, "_sash_start"):
            return
        x0, w0 = self._sash_start
        new_w = max(self.SIDEBAR_MIN,
                    min(self.SIDEBAR_MAX, w0 + (event.x_root - x0)))
        if new_w != self.sidebar_width:
            self.sidebar_width = new_w
            self.sidebar.configure(width=new_w)

    def thumbs_smaller(self):
        self._set_thumb_size(self._snap_thumb_level(self.thumb_size, -1))

    def thumbs_larger(self):
        self._set_thumb_size(self._snap_thumb_level(self.thumb_size, +1))

    def _set_thumb_size(self, size):
        "Snap to a THUMB_LEVELS size and rebuild the grid at it (icon view)."
        size = self._snap_thumb_level(int(size))
        # Zooming the thumbnails implies the icon grid — leave list view if active.
        if size == self.thumb_size and self.view_mode == "grid":
            return
        self.thumb_size = size
        self.view_mode = "grid"
        self._thumb_cols = self._calc_cols()
        self._build_thumbs(overlay=True)   # cover the rebuild like a folder load
        self._update_view_button()

    def _calc_cols(self, width=None):
        "How many columns fit the visible sidebar width — for the icon grid AND the"
        " compact list (the list reflows to 2/3/4… columns once the panel is wide)."
        if width is None:
            width = self.canvas.winfo_width()
        cell_w = self.LIST_COL_MIN if self.view_mode == "list" \
            else self.thumb_size + self.THUMB_PAD
        return max(1, int(max(width, 1) // cell_w))

    def _on_sidebar_configure(self, event):
        "On a sidebar resize: keep the folder cap in sync, then re-realize the strip."
        # The folder cap tracks the sidebar height — cheap, so keep it per-event so
        # the folder list follows smoothly while you drag its sash / the window.
        self._on_folder_holder_configure()
        # The thumbnail re-realize is the EXPENSIVE part. A resize DRAG (sidebar
        # width, OR the folder sash — which resizes the strip below it) fires a
        # <Configure> per pixel; rebuilding the visible cells each one flickers and
        # janks. Throttle it to ~25 fps — the last event still lands the final size.
        self._schedule_strip_relayout()

    def _schedule_strip_relayout(self):
        "Coalesce a burst of resize events into one thumbnail relayout (~40 ms)."
        if getattr(self, "_strip_relayout_job", None) is not None:
            return                            # one already pending → it reads live size
        self._strip_relayout_job = self.root.after(40, self._do_strip_relayout)

    def _do_strip_relayout(self):
        "Re-realize the thumbnail strip for the current sidebar width (throttled)."
        self._strip_relayout_job = None
        width = self.canvas.winfo_width()
        cols = self._calc_cols(width)
        changed = cols != getattr(self, "_thumb_cols", 0)
        self._thumb_cols = cols
        self._layout_strip()                  # only resets things if the folder is empty
        if changed or self.view_mode == "list":
            self._clear_cells()               # positions/widths moved → rebuild the window
        self._render_window()
        # Re-fit list names AFTER the column count settles (the room per name is the
        # per-column width, so it shrinks/grows as the list gains/loses columns).
        self._reflow_list_names()
