"""Window chrome: icons, info bar, toolbar, menu, body split, sidebar header,
breadcrumbs, and sidebar resize / thumbnail-size zoom.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import sys
import json
import tkinter as tk
import tkinter.ttk as ttk
import tkinter.filedialog as tkfd

from PIL import Image, ImageTk

from ..config import (BG, BAR, SIDEBAR, HOVER, ACCENT, FG, FG_DIM, ICON_SIZE,
                      ICON_DIR)
from ..widgets import Tooltip
from .. import i18n
from ..i18n import t


class ChromeMixin:
    # --- Icons --------------------------------------------------------------

    def icon(self, name, size=None):
        "Load a Lucide icon (white) scaled to `size` logical px (default"
        " ICON_SIZE), cached. None if missing."
        # Cache per (name, size): the bare name keeps the default-size key so
        # existing callers are unaffected; a custom size gets its own entry.
        key = name if size is None else f"{name}@{size}"
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
                img = ImageTk.PhotoImage(im)
            except Exception:
                img = None
        self.icons[key] = img
        return img

    def _tool_button(self, parent, icon_name, command, tooltip=""):
        "A flat icon button with hover effect (falls back to text if no icon)."
        img = self.icon(icon_name)
        if img is not None:
            btn = tk.Label(parent, image=img, bg=BAR, cursor="hand2")
        else:
            btn = tk.Label(parent, text=tooltip or "?", bg=BAR, fg=FG,
                           cursor="hand2", font=("Segoe UI", 10))
        btn.bind("<Enter>", lambda e: btn.configure(bg=HOVER))
        btn.bind("<Leave>", lambda e: btn.configure(bg=BAR))
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
                        troughcolor=SIDEBAR, background="#3a3a3a",
                        bordercolor=SIDEBAR, borderwidth=0, relief="flat",
                        arrowcolor=SIDEBAR, width=10)
        style.map("Sidebar.Vertical.TScrollbar",
                  background=[("active", "#5a5a5a"), ("pressed", "#666666")])

    def _glyph_button(self, parent, glyph, command, tooltip=""):
        "A flat text-glyph button with hover (for nav controls lacking an icon)."
        btn = tk.Label(parent, text=glyph, bg=BAR, fg=FG, cursor="hand2",
                       font=("Segoe UI", 13), padx=4)
        btn.bind("<Enter>", lambda e: btn.configure(bg=HOVER))
        btn.bind("<Leave>", lambda e: btn.configure(bg=BAR))
        btn.bind("<Button-1>", lambda e: command())
        if tooltip:
            btn._tip = Tooltip(btn, tooltip)
        return btn

    def _sep(self, parent):
        "Vertical separator in a bar."
        return tk.Frame(parent, bg="#3a3a3a", width=1)

    # --- Hand (pan) tool toggle ---------------------------------------------

    def _build_hand_button(self, parent):
        "A toggle icon button for the hand (pan) tool — accent-filled while active."
        img = self.icon("hand")
        if img is not None:
            btn = tk.Label(parent, image=img, bg=BAR, cursor="hand2")
        else:
            btn = tk.Label(parent, text="✋", bg=BAR, fg=FG, cursor="hand2",
                           font=("Segoe UI", 11))
        btn.bind("<Enter>", lambda e: self._hand_btn_paint(hover=True))
        btn.bind("<Leave>", lambda e: self._hand_btn_paint(hover=False))
        btn.bind("<Button-1>", lambda e: self.toggle_hand_tool())
        btn._tip = Tooltip(btn, t("Hand tool — drag to pan the photo"))
        self.btn_hand = btn
        return btn

    def _hand_btn_paint(self, hover=False):
        "Repaint the hand toggle: accent fill while active, hover tint otherwise."
        if not hasattr(self, "btn_hand"):
            return
        if self.hand_tool:
            self.btn_hand.configure(bg=ACCENT)
        else:
            self.btn_hand.configure(bg=HOVER if hover else BAR)

    def _set_hand_tool(self, on):
        "Turn the hand (pan) tool on/off: repaint the toggle + set the canvas cursor."
        if on == self.hand_tool:
            return
        self.hand_tool = on
        self._hand_btn_paint()
        # 'hand2' marks the tool as armed; turning it off clears the cursor and the
        # next pointer move lets the active edit tool (if any) reclaim its own.
        self.preview.configure(cursor="hand2" if on else "")

    def toggle_hand_tool(self):
        "Toolbar action: flip the hand (pan) tool on/off."
        self._set_hand_tool(not self.hand_tool)

    # --- Top info bar -------------------------------------------------------

    def _build_infobar(self):
        self.infobar = tk.Frame(self.root, bg=BAR, height=30)
        self.infobar.grid(row=0, column=0, sticky="ew")
        self.infobar.grid_propagate(False)

        self.lbl_name = tk.Label(self.infobar, text="Manoni", bg=BAR, fg=FG,
                                 font=("Segoe UI", 9, "bold"))
        self.lbl_name.pack(side="left", padx=12)

        self.lbl_info = tk.Label(self.infobar, text="", bg=BAR, fg=FG_DIM,
                                 font=("Segoe UI", 9))
        self.lbl_info.pack(side="left", padx=8)

    # --- Toolbar ------------------------------------------------------------

    def _build_toolbar(self):
        "Three-zone bar: open (left) · undo/redo (center) · cull/view/menu (right)."
        bar = tk.Frame(self.root, bg=BAR, height=46)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)

        # LEFT zone: open. Photo navigation (prev/next/first/last) lives on the
        # bottom strip, next to the position counter — not repeated here.
        left = tk.Frame(bar, bg=BAR)
        left.pack(side="left", padx=8)
        self._tool_button(left, "folder-open", self.open_folder,
                          t("Open folder")).pack(side="left", padx=4, pady=8)
        # Save as… sits next to Open — both are file operations. (Moved up here
        # from the ☰ menu so saving is one click away.)
        self._tool_button(left, "save", self._save_as_dialog,
                          t("Save as…")).pack(side="left", padx=4, pady=8)
        # Hand (pan) tool: a toggle — while on, dragging with the left button
        # moves the photo on the canvas (like Photoshop's hand). Separated from
        # the open button so it reads as its own viewport control.
        self._sep(left).pack(side="left", fill="y", padx=6, pady=10)
        self._build_hand_button(left).pack(side="left", padx=4, pady=8)

        # CENTER zone: undo/redo, truly centered over the bar (placed, so the
        # left/right zones don't shift it off-center).
        center = tk.Frame(bar, bg=BAR)
        center.place(relx=0.5, rely=0.5, anchor="center")
        for spec in [
            ("undo", self.undo, t("Undo (Ctrl+Z)")),
            ("redo", self.redo, t("Redo (Ctrl+Y)")),
        ]:
            self._tool_button(center, *spec).pack(side="left", padx=4, pady=8)

        # RIGHT zone: the ☰ menu at the far right, then the cull group.
        right = tk.Frame(bar, bg=BAR)
        right.pack(side="right", padx=8)

        self.btn_menu = self._tool_button(right, "menu", self.open_menu, t("Menu"))
        self.btn_menu.pack(side="right", padx=4, pady=8)   # anchor for the dropdown
        self._sep(right).pack(side="right", fill="y", padx=6, pady=10)

        # Cull group: one block — keep · reject (matched folder icons) then the
        # ⚙ options (set the two sort folders) and a "?" help button. The two
        # actions are gated until the folders are configured (see nav).
        cull = tk.Frame(right, bg=BAR)
        cull.pack(side="right")
        for spec in [
            ("folder-check", self.move_to_folder,       t("Keep (keeper)")),
            ("folder-x",     self.delete,               t("Reject")),
            ("settings",     self._cull_options_dialog, t("Sorting folders")),
        ]:
            self._tool_button(cull, *spec).pack(side="left", padx=4, pady=8)
        self._glyph_button(cull, "?", self._cull_help_dialog,
                           t("Culling — Help")).pack(side="left", padx=4, pady=8)

        # The edit panel's open/close lives on the always-visible icon rail
        # (a collapse chevron), not here — see _build_tool_rail / toggle_panel.

    # --- ☰ Menu (dark dropdown under the toolbar button) --------------------

    def open_menu(self):
        "Toggle a small dark dropdown under the ☰ button with app-level actions."
        if getattr(self, "_menu_popup", None) is not None:
            self._close_menu()
            return
        self._open_dropdown([
            ("settings",    t("Settings"),     self._open_settings_menu),
            ("languages",   t("Language"),     self._open_language_menu),
            ("sep",),
            ("info",        t("About Manoni"), self._about_dialog),
        ])

    def _open_settings_menu(self):
        "Settings submenu — placeholder for now (text only; no options yet)."
        pass

    def _open_language_menu(self):
        "The Language sub-dropdown: 'Add your language' first, then each language"
        " (✓ on the active one). Choosing one relaunches the app."
        specs = [("plus", t("Add your language"), self._language_studio), ("sep",)]
        current = i18n.get_language()
        for code, native in i18n.available():
            mark = "   ✓" if code == current else ""
            specs.append(("languages", native + mark,
                          lambda c=code: self.switch_language(c)))
        self._open_dropdown(specs)

    def _open_dropdown(self, specs):
        "Build the borderless dark popup under the ☰ button. Each spec is either"
        " ('sep',) for a hairline divider or (icon_name, label, command) for a"
        " clickable row. Tracked in self._menu_popup so a re-open toggles it."
        pop = tk.Toplevel(self.root)
        pop.overrideredirect(True)                 # borderless: a real popup menu
        pop.configure(bg="#3a3a3a")                # 1px hairline border via inset
        self._menu_popup = pop
        inner = tk.Frame(pop, bg=BAR)
        inner.pack(padx=1, pady=1)

        def add_row(icon_name, label, command):
            r = tk.Frame(inner, bg=BAR, cursor="hand2")
            r.pack(fill="x")
            img = self.icon(icon_name)
            if img is not None:
                tk.Label(r, image=img, bg=BAR).pack(side="left", padx=(10, 8), pady=7)
            lab = tk.Label(r, text=label, bg=BAR, fg=FG, anchor="w",
                           font=("Segoe UI", 9))
            lab.pack(side="left", padx=(0, 18), pady=7)
            cells = (r, lab)

            def enter(_e):
                for w in cells:
                    w.configure(bg=HOVER)

            def leave(_e):
                for w in cells:
                    w.configure(bg=BAR)

            def click(_e):
                self._close_menu()
                command()
            for w in cells:
                w.bind("<Enter>", enter)
                w.bind("<Leave>", leave)
                w.bind("<Button-1>", click)

        for spec in specs:
            if spec[0] == "sep":
                tk.Frame(inner, bg="#3a3a3a", height=1).pack(fill="x")
            else:
                add_row(*spec)

        # Position the popup under the ☰ button, right edges aligned.
        pop.update_idletasks()
        bx = self.btn_menu.winfo_rootx()
        by = self.btn_menu.winfo_rooty() + self.btn_menu.winfo_height() + 2
        x = bx + self.btn_menu.winfo_width() - pop.winfo_width()
        pop.geometry(f"+{max(0, x)}+{by}")
        pop.bind("<Escape>", lambda e: self._close_menu())
        pop.bind("<FocusOut>", lambda e: self._close_menu())
        pop.focus_force()                          # so clicking elsewhere closes it

    def _close_menu(self):
        "Tear down the ☰ dropdown if it is open."
        pop = getattr(self, "_menu_popup", None)
        if pop is not None:
            self._menu_popup = None
            try:
                pop.destroy()
            except tk.TclError:
                pass

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
        dlg = tk.Toplevel(self.root)
        dlg.title(t("Add your language"))
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=BG, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=t("Add your language"), bg=BG, fg=FG,
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        steps = t("Manoni can speak any language. Here's how:\n"
                  "1. Generate a template file — it lists every English text.\n"
                  "2. Open it in any text editor and fill in your translations.\n"
                  "3. Import the finished file — your language appears in the menu.")
        tk.Label(wrap, text=steps, bg=BG, fg=FG_DIM, justify="left", anchor="w",
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
        body = tk.Frame(self.root, bg=BG)
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
        side = tk.Frame(body, bg=SIDEBAR, width=self.sidebar_width)
        side.grid(row=0, column=0, rowspan=3, sticky="ns")
        side.pack_propagate(False)   # honor our width; children are packed, not gridded
        self.sidebar = side

        # Hero header (top): where-you-are address + folder navigation +
        # thumbnail-size zoom. (Replaces the old bottom footer strip.)
        self._build_sidebar_hero(side)

        # Top section: a minimalist, auto-height list of the folder's sub-folders
        # (filled by browser._build_folder_list). Sits above the thumbnail grid.
        self._build_folder_panel(side)

        # Bottom strip of the sidebar: view-mode picker + thumbnail-size zoom.
        # Packed (side="bottom") before the canvas so the grid fills above it.
        self._build_sidebar_footer(side)

        self.canvas = tk.Canvas(side, bg=SIDEBAR, highlightthickness=0)
        sb = ttk.Scrollbar(side, orient="vertical", command=self.canvas.yview,
                           style="Sidebar.Vertical.TScrollbar")
        self._thumb_scrollbar = sb     # folder list packs just above this
        self.thumb_holder = tk.Frame(self.canvas, bg=SIDEBAR)
        self.thumb_holder.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._thumb_window = self.canvas.create_window(
            (0, 0), window=self.thumb_holder, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        # Keep the grid wrapped to the visible width, and reflow on resize.
        self.canvas.bind("<Configure>", self._on_sidebar_configure)
        for w in (self.canvas, self.thumb_holder):
            w.bind("<MouseWheel>", self._on_wheel)

        # Drag-sash between the sidebar and the preview (horizontal resize). A
        # centred vertical grip nub mirrors the folder divider so both clearly
        # read as draggable; the strip lightens and the nub turns accent on hover.
        sash = tk.Frame(body, bg=BAR, width=8, cursor="sb_h_double_arrow")
        sash.grid(row=0, column=1, rowspan=3, sticky="ns")
        grip = tk.Frame(sash, bg=FG_DIM)
        grip.place(relx=0.5, rely=0.5, anchor="center", width=4, height=40)
        self.sash, self.sash_grip = sash, grip
        for w in (sash, grip):
            w.bind("<Button-1>", self._sash_press)
            w.bind("<B1-Motion>", self._sash_drag)
            w.bind("<Enter>",
                   lambda e: (sash.configure(bg=HOVER), grip.configure(bg=ACCENT)))
            w.bind("<Leave>",
                   lambda e: (sash.configure(bg=BAR), grip.configure(bg=FG_DIM)))

        # Big preview fills the center (Canvas so it can zoom + pan)
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
        self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    # --- Sidebar top section: the auto-height sub-folder list ---------------

    def _build_folder_panel(self, side):
        """Scaffold the sidebar's top section: a sub-folder list whose height
        tracks its content (capped at FOLDER_LIST_MAX, then it scrolls). The rows
        are filled in by browser._build_folder_list, which also shows/hides this
        whole panel depending on whether the folder has any sub-folders. A 1px
        divider at its foot separates the list from the thumbnail grid below."""
        self.folder_panel = tk.Frame(side, bg=SIDEBAR)   # packed on demand
        # A draggable divider at the foot separates the list from the grid below and
        # lets the user set the list's height (drag up/down). It's a slim grab strip
        # with a centred 1px line — packed first so it always spans the full width
        # under the canvas + scrollbar. See _folder_sash_drag.
        sash = tk.Frame(self.folder_panel, bg=SIDEBAR, height=11,
                        cursor="sb_v_double_arrow")
        sash.pack(side="bottom", fill="x")
        sash.pack_propagate(False)
        # Faint full-width hairline marks the boundary; the centred grip nub on top
        # of it says "drag me" (turns accent on hover). Same idiom as the side sash.
        line = tk.Frame(sash, bg="#3a3a3a")
        line.place(relx=0.0, rely=0.5, relwidth=1.0, height=1, anchor="w")
        grip = tk.Frame(sash, bg=FG_DIM)
        grip.place(relx=0.5, rely=0.5, anchor="center", width=40, height=4)
        self.folder_sash, self.folder_sash_grip = sash, grip
        for w in (sash, line, grip):
            w.bind("<Enter>", lambda e: grip.configure(bg=ACCENT))
            w.bind("<Leave>", lambda e: grip.configure(bg=FG_DIM))
            w.bind("<Button-1>", self._folder_sash_press)
            w.bind("<B1-Motion>", self._folder_sash_drag)
            w.bind("<ButtonRelease-1>", self._folder_sash_release)
        self.folder_canvas = tk.Canvas(self.folder_panel, bg=SIDEBAR,
                                       highlightthickness=0, height=1)
        # A slim scrollbar, shown only while the sub-folder list overflows its cap
        # (so a folder with many sub-folders is fully reachable, not just by wheel).
        self.folder_scrollbar = ttk.Scrollbar(
            self.folder_panel, orient="vertical", command=self.folder_canvas.yview,
            style="Sidebar.Vertical.TScrollbar")
        self.folder_canvas.configure(yscrollcommand=self.folder_scrollbar.set)
        self.folder_canvas.pack(side="left", fill="both", expand=True)
        self.folder_holder = tk.Frame(self.folder_canvas, bg=SIDEBAR)
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
        "Match the inner frame to the viewport, and reflow to 1/2 columns on width change."
        self.folder_canvas.itemconfigure(self._folder_window, width=event.width)
        cols = self._calc_folder_cols(event.width)
        if cols != self._folder_cols and self.folder_widgets:
            self._folder_cols = cols
            self._place_folder_rows()
        self._fit_folder_names()         # re-fit names to the new column width

    def _calc_folder_cols(self, width=None):
        "How many folder columns fit the sidebar width — 1 when narrow, up to 2 when wide."
        if width is None:
            width = self.folder_canvas.winfo_width()
        return max(1, min(self.FOLDER_MAX_COLS,
                          int(max(width, 1) // self.FOLDER_COL_MIN)))

    def _place_folder_rows(self):
        "Grid the folder cells into self._folder_cols equal columns (left-to-right)."
        cols = self._folder_cols
        for c in range(self.FOLDER_MAX_COLS):
            # Only the USED columns share the 'folders' uniform group. Leaving an
            # unused column in the group makes the grid reserve a phantom column
            # (doubling its requested width); when the sidebar is narrow (1 column)
            # that overflowed the forced canvas width and the rows never mapped —
            # the folder list looked blank. Excluding it keeps the list visible.
            used = c < cols
            self.folder_holder.grid_columnconfigure(
                c, weight=1 if used else 0, uniform="folders" if used else "")
        for i, row in enumerate(self.folder_widgets):
            row.grid(row=i // cols, column=i % cols, sticky="ew")

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
        hero = tk.Frame(side, bg=BAR)
        hero.pack(side="top", fill="x")

        # A single address row: up-a-folder (left) + clickable breadcrumb.
        row = tk.Frame(hero, bg=BAR)
        row.pack(side="top", fill="x", padx=6, pady=5)

        self.btn_up = self._glyph_button(row, "↑", self.go_up_folder,
                                         t("Up a folder"))
        self.btn_up.pack(side="left", padx=(0, 2))

        # Click an ancestor crumb to navigate there; the leaf is the open folder.
        self.crumbs = tk.Frame(row, bg=BAR)
        self.crumbs.pack(side="left", fill="x", expand=True)

        # A clearly-visible header divider (the old #3a3a3a line was too faint).
        tk.Frame(side, bg="#555555", height=1).pack(side="top", fill="x")
        self._update_breadcrumbs()

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
            tk.Label(self.crumbs, text=t("No folder open"), bg=BAR,
                     fg=FG_DIM, font=("Segoe UI", 8)).pack(side="left")
            self.btn_up.configure(fg="#5a5a5a")   # nothing to go up to
            return
        self.btn_up.configure(fg=FG)
        segs = self._path_segments(self.folder)
        truncated = len(segs) > self.MAX_CRUMBS
        shown = segs[-self.MAX_CRUMBS:]
        if truncated:                  # "…" jumps to the level above the window
            self._crumb_label("…", segs[-self.MAX_CRUMBS - 1][1], leaf=False)
        for i, (label, full) in enumerate(shown):
            if i > 0 or truncated:
                tk.Label(self.crumbs, text="›", bg=BAR, fg=FG_DIM,
                         font=("Segoe UI", 8)).pack(side="left")
            self._crumb_label(label, full, leaf=(i == len(shown) - 1))

    def _crumb_label(self, text, full, leaf):
        "One breadcrumb: the leaf (current folder) is bright + inert; ancestors"
        " are dim and clickable to navigate into that folder."
        lbl = tk.Label(self.crumbs, text=text, bg=BAR,
                       fg=FG if leaf else FG_DIM,
                       font=("Segoe UI", 8, "bold" if leaf else "normal"),
                       cursor="arrow" if leaf else "hand2")
        lbl.pack(side="left")
        if not leaf:
            lbl.bind("<Enter>", lambda e: lbl.configure(fg=ACCENT))
            lbl.bind("<Leave>", lambda e: lbl.configure(fg=FG_DIM))
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
        panel. Left: a view-mode dropdown (large / medium / small icons · list).
        Right: the thumbnail-size zoom −/+ (moved here from the header). Packed at
        the very bottom so the thumbnail grid fills the space above it."""
        foot = tk.Frame(side, bg=BAR)
        foot.pack(side="bottom", fill="x")
        self.sidebar_footer = foot

        # A 1px divider on top so the footer reads as a strip below the grid.
        tk.Frame(foot, bg="#555555", height=1).pack(side="top", fill="x")

        row = tk.Frame(foot, bg=BAR)
        row.pack(side="top", fill="x", padx=6, pady=4)

        # LEFT: the view-mode dropdown (large icons / small / list …).
        self._build_view_button(row).pack(side="left")

        # RIGHT: thumbnail-size zoom −/+.
        fz = tk.Frame(row, bg=BAR)
        fz.pack(side="right")
        self._tool_button(fz, "zoom-out", self.thumbs_smaller,
                          t("Smaller thumbnails")).pack(side="left", padx=2)
        self._tool_button(fz, "zoom-in", self.thumbs_larger,
                          t("Larger thumbnails")).pack(side="left", padx=2)

    def _build_view_button(self, parent):
        "A flat dropdown button (icon + current view + ▾) that opens the view menu."
        btn = tk.Frame(parent, bg=BAR, cursor="hand2")
        img = self.icon("layout-grid")
        icon = (tk.Label(btn, image=img, bg=BAR) if img is not None
                else tk.Label(btn, text="▦", bg=BAR, fg=FG, font=("Segoe UI", 11)))
        icon.pack(side="left", padx=(4, 4), pady=3)
        label = tk.Label(btn, text="", bg=BAR, fg=FG, font=("Segoe UI", 9))
        label.pack(side="left")
        chev = tk.Label(btn, text="▾", bg=BAR, fg=FG_DIM, font=("Segoe UI", 8))
        chev.pack(side="left", padx=(4, 6))
        self.btn_view = btn
        self.view_btn_icon = icon
        self.view_btn_label = label
        cells = (btn, icon, label, chev)

        def enter(_e):
            for w in cells:
                w.configure(bg=HOVER)

        def leave(_e):
            for w in cells:
                w.configure(bg=BAR)
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
        "Refresh the dropdown face so it mirrors the active view (icon + label)."
        if not hasattr(self, "view_btn_label"):
            return
        if self.view_mode == "list":
            text, icon_name = t("List"), "menu"
        else:
            key = self._active_view()
            text = t(next((l for k, l, _s in self.VIEW_MENU if k == key), "Icons"))
            icon_name = "layout-grid"
        self.view_btn_label.configure(text=text)
        img = self.icon(icon_name)
        if img is not None:
            self.view_btn_icon.configure(image=img)

    def _open_view_menu(self):
        "Open (or toggle shut) the view-mode dropdown above the footer button."
        if getattr(self, "_view_popup", None) is not None:
            self._close_view_menu()
            return
        pop = tk.Toplevel(self.root)
        pop.overrideredirect(True)                 # borderless: a real popup menu
        pop.configure(bg="#3a3a3a")                # 1px hairline border via inset
        self._view_popup = pop
        inner = tk.Frame(pop, bg=BAR)
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
        r = tk.Frame(parent, bg=BAR, cursor="hand2")
        r.pack(fill="x")
        mark = tk.Label(r, text="✓" if is_active else "", bg=BAR, fg=ACCENT,
                        width=2, font=("Segoe UI", 9))
        mark.pack(side="left", padx=(8, 2), pady=6)
        lab = tk.Label(r, text=t(label), bg=BAR, anchor="w",
                       fg=ACCENT if is_active else FG, font=("Segoe UI", 9))
        lab.pack(side="left", padx=(0, 20), pady=6)
        cells = (r, mark, lab)

        def enter(_e):
            for w in cells:
                w.configure(bg=HOVER)

        def leave(_e):
            for w in cells:
                w.configure(bg=BAR)

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
        self._build_thumbs()
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
        self._set_thumb_size(self.thumb_size - self.THUMB_STEP)

    def thumbs_larger(self):
        self._set_thumb_size(self.thumb_size + self.THUMB_STEP)

    def _set_thumb_size(self, size):
        "Change the thumbnail size (clamped) and rebuild the grid at the new size."
        size = max(self.THUMB_MIN, min(self.THUMB_MAX, int(size)))
        # Zooming the thumbnails implies the icon grid — leave list view if active.
        if size == self.thumb_size and self.view_mode == "grid":
            return
        self.thumb_size = size
        self.view_mode = "grid"
        self._thumb_cols = self._calc_cols()
        self._build_thumbs()
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
        "Match the inner frame to the viewport so the grid wraps; reflow if cols change."
        self.canvas.itemconfigure(self._thumb_window, width=event.width)
        # The sidebar's height changed too (window resize): re-evaluate the folder
        # cap so it keeps its fair share of the height.
        self._on_folder_holder_configure()
        cols = self._calc_cols(event.width)
        if cols != self._thumb_cols:
            self._thumb_cols = cols
            self._reflow_thumbs()
        # Re-fit list names AFTER the column count settles (the room per name is the
        # per-column width, so it shrinks/grows as the list gains/loses columns).
        self._reflow_list_names()

    def _config_thumb_columns(self, cols):
        "Weight the thumbnail grid columns: list columns stretch equally (so rows fill"
        " and tile into 2/3/4…); grid columns stay unweighted (fixed, centered cells)."
        listy = self.view_mode == "list"
        for c in range(self.MAX_GRID_COLS):
            used = listy and c < cols
            self.thumb_holder.grid_columnconfigure(
                c, weight=1 if used else 0, uniform="listcols" if used else "")

    def _reflow_thumbs(self):
        "Re-place every loaded thumbnail cell into the current column count."
        cols = self._thumb_cols
        self._config_thumb_columns(cols)          # weights follow the new column count
        pos = 0
        for cell in self.thumb_widgets:           # sub-folders live in their own list now
            if cell is None:
                continue
            cell.grid_configure(row=pos // cols, column=pos % cols)
            pos += 1
