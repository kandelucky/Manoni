"""Settings: a tabbed preferences window (☰ menu → Settings).

A non-modal Toplevel in the app's dark-blue style: a header bar, then a
`tintkit.SettingsWindow` (the kit's left tab rail + scrollable pane), then a
footer (Restore defaults · Done). Tabs: General · Appearance · Performance ·
Export · Culling · About.

The rail, the swappable pane, the section headers and setting rows all come
from the kit now — the same component the TintKit gallery shows — so Settings
shares one look with the rest of the migrated UI. This mixin only supplies the
window shell (header / footer / centring / persistence) and the *content* of
each tab: builders that lay out REAL, already-persisted controls via the pane's
`group` / `row` / `note` helpers.

Every control is wired to a REAL setting — there are no dead toggles here. The
window only gathers settings that live elsewhere into one place:
  * General     — UI language, launch + confirmation preferences
  * Appearance  — sidebar view, interface (light mode, accent, strips, rulers)
  * Performance — the fast-preview + off-thread render toggles
  * Export      — the Save dialog's defaults (format / quality / metadata / sRGB
                  / output folder), stored in self.last_save + friends
  * Culling     — the two keep / reject sort folders + the end-of-folder action

Mixin on the Manoni window — every method uses the shared `self`, like the other
ui mixins.
"""

import os
import webbrowser
import tkinter as tk
import tkinter.filedialog as tkfd

import tintkit

from ..config import ACCENTS
from .. import i18n
from ..i18n import t
from .about import (APP_VERSION, AUTHOR_NAME, AUTHOR_HANDLE, BUILT_WITH,
                    PROJECT_LINKS, BMC_URL, BMC_BG, BMC_BG_HOVER, BMC_FG)

# The window's controls (toggle / segmented / slider / dropdown / buttons) and
# now its whole body (rail + scroll pane + section headers + rows) are stock
# TintKit reading self.theme, so the entire window switches dark<->light live.
# The header bar + footer chrome are plain tk threaded onto self.theme via
# chrome's _tw. The rail glyphs are drawn from Manoni's own icon set by handing
# the component `self.icon` as its icon_loader.


# --- tab spec: (key, label-source, icon, builder-method-name) ----------------
# Labels are translated where the tabs are built (so a language switch retexts).
_TABS = [
    ("general",     "General",     "settings",     "_set_tab_general"),
    ("appearance",  "Appearance",  "palette",      "_set_tab_appearance"),
    ("performance", "Performance", "aperture",     "_set_tab_performance"),
    ("export",      "Export",      "upload",       "_set_tab_export"),
    ("culling",     "Culling",     "folder-check", "_set_tab_culling"),
    ("about",       "About",       "info",         "_set_tab_about"),
]


class SettingsMixin:
    # --- window -------------------------------------------------------------

    def _settings_dialog(self):
        "Open the tabbed Settings window (or re-focus it if already open)."
        win = getattr(self, "_settings_win", None)
        if win is not None:
            try:
                win.deiconify()
                win.lift()
                win.focus_force()
                return
            except tk.TclError:
                self._settings_win = None

        dlg = self._tw(tk.Toplevel(self.root), bg="bg")
        dlg.title(t("Settings"))
        dlg.transient(self.root)
        self._settings_win = dlg

        dlg.rowconfigure(1, weight=1)
        dlg.columnconfigure(0, weight=1)

        self._set_build_header(dlg)
        self._set_build_body(dlg)
        self._set_build_footer(dlg)

        def close():
            self._settings_win = None
            try:
                dlg.destroy()
            except tk.TclError:
                pass
        dlg.protocol("WM_DELETE_WINDOW", close)
        dlg.bind("<Escape>", lambda e: close())
        # Wheel anywhere in the window scrolls the pane (the component also binds
        # the pane itself); the body owns the canvas now.
        dlg.bind("<MouseWheel>", lambda e: self._settings_body.canvas.yview_scroll(
            int(-e.delta / 120), "units"))

        w, h = self._edit_dpi_w(720), self._edit_dpi_w(560)
        dlg.minsize(self._edit_dpi_w(620), self._edit_dpi_w(440))
        dlg.geometry(f"{w}x{h}")
        self._center_dialog(dlg)
        dlg.focus_force()

    def _set_build_header(self, dlg):
        bar = self._tw(tk.Frame(dlg, height=self._edit_dpi_w(52)), bg="bar")
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        if self.icon("settings", size=20) is not None:
            self._icon_label(bar, "settings", size=20, token="fg",
                             bg="bar").pack(side="left", padx=(16, 10))
        self._tw(tk.Label(bar, text=t("Settings"),
                 font=("Segoe UI", 13, "bold")), bg="bar", fg="fg").pack(side="left")
        self._tw(tk.Frame(dlg, height=1), bg="border").grid(
            row=0, column=0, sticky="sew")

    def _set_build_body(self, dlg):
        "The kit's tab rail + scrollable pane; each tab's content is a builder."
        self._settings_body = tintkit.SettingsWindow(
            dlg, self.theme,
            tabs=[(key, t(label), icon, getattr(self, method))
                  for key, label, icon, method in _TABS],
            header=None, rail_w=180, icon_loader=self.icon)
        self._settings_body.root.grid(row=1, column=0, sticky="nsew")

    def _set_build_footer(self, dlg):
        self._tw(tk.Frame(dlg, height=1), bg="border").grid(
            row=2, column=0, sticky="new")
        foot = self._tw(tk.Frame(dlg, height=self._edit_dpi_w(58)), bg="bar")
        foot.grid(row=2, column=0, sticky="ew")
        foot.grid_propagate(False)
        inner = self._tw(tk.Frame(foot), bg="bar")
        inner.pack(fill="x", padx=16, pady=11)
        tintkit.Button(inner, self.theme, t("Restore defaults"), role="neutral",
                       variant="outline", bg="bar",
                       command=self._set_restore_defaults).pack(side="left")

        def close():
            self._settings_win = None
            try:
                dlg.destroy()
            except tk.TclError:
                pass
        tintkit.Button(inner, self.theme, t("Done"), role="primary",
                       variant="filled", bg="bar", command=close).pack(
            side="right")

    # --- General tab --------------------------------------------------------

    def _set_tab_general(self, win):
        win.group(t("Language"))
        r = win.row(t("Interface language"),
                    t("Switching relaunches Manoni and restores your place."))
        langs = i18n.available()
        codes = [c for c, _n in langs]
        names = [n for _c, n in langs]
        cur = i18n.get_language()
        active = codes.index(cur) if cur in codes else 0

        def pick_lang(i):
            if codes[i] != i18n.get_language():
                self.switch_language(codes[i])   # prompts save + relaunches
        tintkit.Dropdown(r, self.theme, names, selected=active,
                         command=lambda i, _l: pick_lang(i)).pack()

        r = win.row(t("Add your language"),
                    t("Generate a template, translate it, then import it."))
        tintkit.Button(r, self.theme, t("Add…"), role="neutral",
                       variant="outline", bg="bg",
                       command=self._language_studio).pack()

        win.group(t("On launch"))
        r = win.row(t("Reopen the last folder"))
        tintkit.Toggle(r, self.theme, value=self.restore_session,
                command=lambda on: self._set_pref("restore_session", on)).pack()
        r = win.row(t("Jump back to the last photo"))
        tintkit.Toggle(r, self.theme, value=self.restore_photo,
                command=lambda on: self._set_pref("restore_photo", on)).pack()

        win.group(t("Confirmations"))
        r = win.row(t("Ask before rejecting a photo"),
                    t("A quick confirm before a photo moves to the Reject folder."))
        tintkit.Toggle(r, self.theme, value=self.confirm_reject,
                command=lambda on: self._set_pref("confirm_reject", on)).pack()
        r = win.row(t("Warn about unsaved edits when leaving a photo"))
        tintkit.Toggle(r, self.theme, value=self.warn_unsaved,
                command=lambda on: self._set_pref("warn_unsaved", on)).pack()

    # --- Appearance tab -----------------------------------------------------

    def _set_tab_appearance(self, win):
        win.group(t("Sidebar"))
        r = win.row(t("Default view"))
        keys = ["large", "medium", "small", "list"]
        labels = [t("Large"), t("Medium"), t("Small"), t("List")]

        def pick_view(i):
            self.set_view(keys[i])
            self._save_state()
        tintkit.SegmentedTabs(r, self.theme, labels,
                              selected=self._set_view_index(keys),
                              command=lambda i, _l: pick_view(i)).pack()

        win.group(t("Interface"))
        r = win.row(t("Light mode"),
                    t("Switch between the dark and light interface."))

        def pick_scheme(on):
            self.theme.set(scheme="light" if on else "dark")  # repaints the app live
            self._save_state()
        tintkit.Toggle(r, self.theme, value=(self.theme.scheme == "light"),
                       command=pick_scheme).pack()

        r = win.row(t("Accent color"), t("The app's highlight colour."))
        self._set_accent_swatches(r).pack()

        r = win.row(t("Show filter strip"),
                    t("The row of filter previews under the photo."))

        def pick_filters(on):
            self.show_filter_strip = on
            self._save_state()
            self._refresh_filter_strip()         # show / hide the strip live
        tintkit.Toggle(r, self.theme, value=getattr(self, "show_filter_strip", True),
                command=pick_filters).pack()

        r = win.row(t("Show histogram"),
                    t("The live tonal graph at the top of the edit panel."))

        def pick_histogram(on):
            self.show_histogram = on
            self._save_state()
            self._refresh_histogram()            # show / hide the graph live
        tintkit.Toggle(r, self.theme, value=getattr(self, "show_histogram", True),
                command=pick_histogram).pack()

        r = win.row(t("Show pixel rulers"),
                    t("The top and left rulers over the photo (Ctrl+R)."))

        def pick_rulers(on):
            if on != getattr(self, "show_rulers", True):
                self.toggle_rulers()             # re-renders + persists itself
        tintkit.Toggle(r, self.theme, value=getattr(self, "show_rulers", True),
                command=pick_rulers).pack()

    # --- Performance tab ----------------------------------------------------

    def _set_tab_performance(self, win):
        win.group(t("Rendering"))
        r = win.row(t("Fast preview while dragging"),
                    t("Skip the heavy filters (clarity, sharpen, denoise, "
                      "dehaze, focus, grain) while a slider is dragged; "
                      "full quality returns the moment you let go."))
        tintkit.Toggle(r, self.theme, value=getattr(self, "fast_preview", True),
                command=lambda on: self._set_pref("fast_preview", on)).pack()

        r = win.row(t("Render off the main thread"),
                    t("Do the heavy edit work on a background thread so the "
                      "window never freezes while a costly effect renders; "
                      "the photo catches up a moment behind the slider. Turn "
                      "off to render on the main thread (the older behaviour)."))
        tintkit.Toggle(r, self.theme, value=getattr(self, "async_render", True),
                command=lambda on: self._set_pref("async_render", on)).pack()

    def _set_pref(self, key, val):
        "Set a simple on/off General preference attribute and persist it."
        setattr(self, key, val)
        self._save_state()

    def _set_accent_swatches(self, parent):
        "A row of accent-colour swatches; the active one wears a theme-fg ring."
        " Clicking re-derives the whole app's accent (TintKit) and persists it."
        box = self._tw(tk.Frame(parent), bg="bg")
        sz = self._edit_dpi_w(20)
        swatches = []
        for name, hexcol in ACCENTS:
            sw = tk.Frame(box, width=sz, height=sz, bg=hexcol, cursor="hand2",
                          highlightthickness=2)
            sw.pack_propagate(False)
            sw.pack(side="left", padx=3)
            sw._accent = hexcol
            sw.bind("<Button-1>", lambda e, c=hexcol: self._pick_accent(c))
            tintkit.HoverTip(sw, self.theme, t(name))
            swatches.append(sw)

        def repaint():
            # The ring is theme fg on the active swatch; on the rest it matches the
            # panel bg so it reads as a plain colour chip. Re-runs on accent + on a
            # dark<->light switch (both fire theme subscribers).
            try:
                for sw in swatches:
                    active = sw._accent.lower() == self.theme.accent.lower()
                    ring = self.theme["fg"] if active else self.theme["bg"]
                    sw.configure(highlightbackground=ring, highlightcolor=ring)
            except tk.TclError:
                self.theme.unsubscribe(repaint)

        self.theme.subscribe(repaint)
        box.bind("<Destroy>",
                 lambda e: e.widget is box and self.theme.unsubscribe(repaint),
                 add="+")
        repaint()
        return box

    def _pick_accent(self, hexcol):
        "Set the app accent (repaints every accent-using widget) and persist it."
        self.theme.set(accent=hexcol)
        self._save_state()

    def _set_view_index(self, keys):
        "Which segmented index reflects the live view (closest grid preset, or list)."
        if self.view_mode == "list":
            return keys.index("list")
        presets = {k: s for k, _l, s in self.VIEW_MENU}
        for i, k in enumerate(keys):
            if presets.get(k) == self.thumb_size:
                return i
        grid = [(k, presets[k]) for k in keys if isinstance(presets.get(k), int)]
        best = min(grid, key=lambda ks: abs(ks[1] - self.thumb_size))[0]
        return keys.index(best)

    # --- Export tab ---------------------------------------------------------

    def _set_export_get(self, key, default):
        ls = self.last_save if isinstance(self.last_save, dict) else {}
        return ls.get(key, default)

    def _set_export_set(self, key, val):
        "Update one Save-dialog default + persist it (creating last_save if needed)."
        if not isinstance(self.last_save, dict):
            # dir "" → the Save dialog falls back to <folder>/_edited at open time.
            self.last_save = {"dir": "", "fmt": "JPEG", "quality": 95,
                              "keep_meta": True, "to_srgb": False}
        self.last_save[key] = val
        self._save_state()

    def _set_tab_export(self, win):
        win.group(t("Default format"))
        r = win.row(t("File format"))
        fmts = ["JPEG", "PNG", "WEBP"]
        cur_fmt = self._set_export_get("fmt", "JPEG")
        active = fmts.index(cur_fmt) if cur_fmt in fmts else 0
        tintkit.SegmentedTabs(
            r, self.theme, fmts, selected=active,
            command=lambda i, _l: self._set_export_set("fmt", fmts[i])).pack()

        r = win.row(t("Quality"),
                    t("Used for JPEG and WEBP (PNG is always lossless)."))
        # Gauge slider: raw read-out (no signed delta), persist on release only.
        def commit_quality():
            self._set_export_set("quality", int(qsl.get()))
        qsl = tintkit.TitledSlider(
            r, self.theme, "", value=int(self._set_export_get("quality", 95)),
            lo=50, hi=100, neutral=50, value_fmt=lambda v, _n: str(v),
            on_release=commit_quality, bg="bg")
        qsl.pack()

        win.group(t("Metadata"))
        r = win.row(t("Keep metadata"),
                    t("Camera info, date, GPS and the colour profile."))
        tintkit.Toggle(r, self.theme, value=bool(self._set_export_get("keep_meta", True)),
                command=lambda on: self._set_export_set("keep_meta", on)).pack()

        r = win.row(t("Convert to sRGB"),
                    t("Best for the web — keeps colours consistent across browsers."))
        tintkit.Toggle(r, self.theme, value=bool(self._set_export_get("to_srgb", False)),
                command=lambda on: self._set_export_set("to_srgb", on)).pack()

        win.group(t("Output"))
        r = win.row(t("Save edited photos to"))
        modes = ["subfolder", "fixed"]
        labels = [t("Subfolder"), t("Fixed folder")]
        active = modes.index(self.export_dir_mode) \
            if self.export_dir_mode in modes else 0

        def pick_mode(i):
            if modes[i] == self.export_dir_mode:
                return
            self.export_dir_mode = modes[i]
            self._save_state()
            self._settings_body.rebuild()    # re-render to show the matching control
        tintkit.SegmentedTabs(r, self.theme, labels, selected=active,
                              command=lambda i, _l: pick_mode(i)).pack()
        if self.export_dir_mode == "fixed":
            self._set_export_fixed_row(win)
        else:
            self._set_export_subfolder_row(win)

        win.note(t("These are the defaults the Save dialog opens with."))

        win.group(t("Overwrite (Ctrl+S)"))
        r = win.row(t("Ask before overwriting the original"),
                    t("Ctrl+S and the Save button write your edits back over the "
                      "open file. Keep this on to confirm first — there is no "
                      "backup of the original."))
        tintkit.Toggle(r, self.theme, value=getattr(self, "confirm_overwrite", True),
                command=lambda on: self._set_pref("confirm_overwrite", on)).pack()

    def _set_export_subfolder_row(self, win):
        "Edit the per-photo subfolder name (mode “subfolder”)."
        right = win.row(t("Subfolder name"),
                        t("Created next to each photo (e.g. folder/_edited)."))
        var = tk.StringVar(value=self.export_subfolder or "_edited")
        ent = self._tw(tk.Entry(right, textvariable=var, relief="flat", width=16,
                       font=("Segoe UI", 9)), bg="chip", fg="fg", insert="fg")
        ent.pack(side="left", ipady=4, ipadx=6)

        def commit(_e=None):
            name = var.get().strip().strip("/\\").strip()
            if name in ("", ".", ".."):
                name = "_edited"
            var.set(name)
            self.export_subfolder = name
            self._save_state()
        ent.bind("<FocusOut>", commit)
        ent.bind("<Return>", commit)

    def _set_export_fixed_row(self, win):
        "Pick one fixed output folder for every export (mode “fixed”)."
        right = win.row(t("Folder"))
        cur = self.export_fixed_dir
        lbl = self._tw(tk.Label(right,
                       text=self._set_short_path(cur) if cur else t("Not set"),
                       font=("Segoe UI", 9), anchor="e", padx=10, pady=5),
                       bg="chip", fg="fg" if cur else "fg_dim")
        lbl.pack(side="left", padx=(0, 8))

        def change():
            d = tkfd.askdirectory(
                parent=self._settings_win, title=t("Output folder"),
                initialdir=cur or self.folder or os.path.expanduser("~"))
            if not d:
                return
            self.export_fixed_dir = d
            self._save_state()
            self._settings_body.rebuild()   # rebuild → label re-threaded fg="fg"
        tintkit.Button(right, self.theme, t("Change…"), role="neutral",
                       variant="outline", bg="bg", command=change).pack(side="left")

    # --- Culling tab --------------------------------------------------------

    def _set_tab_culling(self, win):
        win.group(t("Sorting folders"))
        self._set_cull_row(win, t("Keep (keeper) folder"), "keep")
        self._set_cull_row(win, t("Reject folder"), "reject")
        win.note(t("The keep / reject buttons (and the ↑ / ↓ keys) move "
                   "the current photo into these folders. Ctrl+Z undoes "
                   "the last move."))

        win.group(t("Auto-save while culling"))
        r = win.row(t("Save an edited copy when you move on"),
                    t("As you ← / → or ↑ / ↓ off an edited photo, silently write "
                      "a copy to the export folder — no prompt. Off shows the "
                      "usual Save / Discard prompt instead."))
        tintkit.Toggle(r, self.theme, value=getattr(self, "autosave_copy", False),
                command=lambda on: self._set_pref("autosave_copy", on)).pack()

        win.group(t("At the end of the folder"))
        r = win.row(t("When you pass the last photo"),
                    t("← / → past the edge of the folder."))
        keys = [None, "wrap", "sibling"]
        labels = [t("Ask"), t("First photo"), t("Next folder")]
        active = keys.index(self.edge_action) if self.edge_action in keys else 0

        def pick_edge(i):
            self.edge_action = keys[i]
            self._save_state()
        tintkit.SegmentedTabs(r, self.theme, labels, selected=active,
                              command=lambda i, _l: pick_edge(i)).pack()
        win.note(t("“Ask” pops a small chooser each time you reach the "
                   "edge. “First photo” loops back; “Next folder” opens "
                   "the next folder that has photos."))

    def _set_cull_row(self, win, title, which):
        right = win.row(title)
        cur = self.cull_keep if which == "keep" else self.cull_reject
        lbl = self._tw(tk.Label(right,
                       text=self._set_short_path(cur) if cur else t("Not set"),
                       font=("Segoe UI", 9), anchor="e", padx=10, pady=5),
                       bg="chip", fg="fg" if cur else "fg_dim")
        lbl.pack(side="left", padx=(0, 8))

        def change():
            d = tkfd.askdirectory(
                parent=self._settings_win, title=title,
                initialdir=cur or self.folder or os.path.expanduser("~"))
            if not d:
                return
            if which == "keep":
                self.cull_keep = d
            else:
                self.cull_reject = d
            self._save_state()
            self._settings_body.rebuild()   # rebuild → label re-threaded fg="fg"
        tintkit.Button(right, self.theme, t("Change…"), role="neutral",
                       variant="outline", bg="bg", command=change).pack(side="left")

    @staticmethod
    def _set_short_path(path):
        "Show a long folder path compactly: '…\\parent\\leaf'."
        if not path:
            return path
        parts = os.path.normpath(path).split(os.sep)
        if len(parts) <= 2:
            return path
        return "…" + os.sep + os.sep.join(parts[-2:])

    # --- About tab ----------------------------------------------------------

    def _set_tab_about(self, win):
        p = win.body.widget
        box = self._tw(tk.Frame(p), bg="bg")
        box.pack(fill="x", pady=(16, 0))
        self._tw(tk.Label(box, text="Manoni", font=("Segoe UI", 17, "bold")),
                 bg="bg", fg="fg").pack(anchor="w")
        self._tw(tk.Label(box, text="v" + APP_VERSION + "  ·  " +
                 t("a fast, simple photo browser, culler and editor"),
                 font=("Segoe UI", 9)), bg="bg", fg="fg_dim").pack(
            anchor="w", pady=(2, 0))
        self._tw(tk.Label(box, text="{label}: {name} · {handle}".format(
            label=t("Author"), name=AUTHOR_NAME, handle=AUTHOR_HANDLE),
            font=("Segoe UI", 9)), bg="bg", fg="fg").pack(anchor="w", pady=(12, 0))
        self._tw(tk.Label(box, text=t("Written in Python"),
                 font=("Segoe UI", 9)), bg="bg", fg="fg_dim").pack(
            anchor="w", pady=(2, 0))

        win.group(t("Built with"))
        for name, url, lic in BUILT_WITH:
            self._set_link_row(p, name, url, lic)

        win.group(t("Links"))
        for label, url in PROJECT_LINKS:
            self._set_link_row(p, label, url)

        self._tw(tk.Frame(p, height=16), bg="bg").pack()
        # Buy-me-a-coffee keeps its brand colours (not theme tokens) in both schemes.
        bmc = tk.Label(p, text=t("Buy me a coffee"), bg=BMC_BG, fg=BMC_FG,
                       font=("Segoe UI", 10, "bold"), padx=20, pady=8,
                       cursor="hand2")
        bmc.pack(anchor="w")
        bmc.bind("<Enter>", lambda e: bmc.configure(bg=BMC_BG_HOVER))
        bmc.bind("<Leave>", lambda e: bmc.configure(bg=BMC_BG))
        bmc.bind("<Button-1>", lambda e: webbrowser.open(BMC_URL))

    def _set_link_row(self, parent, label, url, lic=None):
        row = self._tw(tk.Frame(parent), bg="bg")
        row.pack(fill="x", pady=1)
        self._tw(tk.Label(row, text=label + "  ", anchor="w",
                 font=("Segoe UI", 9)), bg="bg", fg="fg").pack(side="left")
        link = self._tw(tk.Label(row, text=url, cursor="hand2",
                        font=("Segoe UI", 9, "underline")), bg="bg", fg="accent")
        link.pack(side="left")
        link.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
        if lic:
            self._tw(tk.Label(row, text="  (" + lic + ")",
                     font=("Segoe UI", 8)), bg="bg", fg="fg_dim").pack(side="left")

    # --- Restore defaults ---------------------------------------------------

    def _set_restore_defaults(self):
        "Reset the DISPLAY + EXPORT defaults (not language, not cull folders)."
        if not self._confirm(
                t("Reset the view and export defaults to their original values?\n\n"
                  "Your language and sorting folders are left unchanged."),
                ok_label=t("Restore defaults")):
            return
        self.set_view("large")                       # default sidebar view
        if not getattr(self, "show_rulers", True):   # rulers default = on
            self.toggle_rulers()
        self.show_filter_strip = True                # filter strip default = on
        self._refresh_filter_strip()
        self.show_histogram = True                   # histogram default = on
        self._refresh_histogram()
        self.fast_preview = True                      # fast preview default = on
        self.last_save = {"dir": "", "fmt": "JPEG", "quality": 95,
                          "keep_meta": True, "to_srgb": False}
        self._save_state()
        self._settings_body.rebuild()                # repaint the open tab
        self.toast(t("Settings restored to defaults"))
