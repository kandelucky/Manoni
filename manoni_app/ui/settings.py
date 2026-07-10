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
import threading
import webbrowser
import tkinter as tk
import tkinter.filedialog as tkfd

import tintkit

from ..config import ACCENTS
from .. import i18n
from ..i18n import t
from .. import update
from .about import (APP_VERSION, AUTHOR_NAME, AUTHOR_HANDLE, BUILT_WITH,
                    PROJECT_LINKS, BMC_URL, BMC_BG, BMC_BG_HOVER, BMC_FG,
                    DEV_EMAIL, ISSUES_URL, LINKEDIN_URL)

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
    ("contact",     "Contact developer", "share-2", "_set_tab_contact"),
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
        self._set_pin_contact_bottom()

    def _set_pin_contact_bottom(self):
        "Float the Contact row at the very bottom of the rail, set off by a rule."
        # The kit packs rail rows top-to-bottom in order and never re-packs them
        # (rebuild() only redraws the right pane), so re-packing here is stable.
        body = self._settings_body
        rail = body._rail
        contact_row = body._rows["contact"][0]
        contact_row.pack_forget()
        # An expanding spacer pushes Contact down; a hairline rule sets it apart.
        self._tw(tk.Frame(rail), bg="sidebar").pack(fill="both", expand=True)
        self._tw(tk.Frame(rail, height=1), bg="divider").pack(fill="x")
        contact_row.pack(fill="x")

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
            if on != getattr(self, "show_filter_strip", False):
                self.toggle_filter_strip()       # flips, re-renders, syncs the toolbar
        tintkit.Toggle(r, self.theme, value=getattr(self, "show_filter_strip", False),
                command=pick_filters).pack()

        r = win.row(t("Show histogram"),
                    t("The live tonal graph at the top of the edit panel."))

        def pick_histogram(on):
            if on != getattr(self, "show_histogram", False):
                self.toggle_histogram()          # flips, re-renders, syncs the toolbar
        tintkit.Toggle(r, self.theme, value=getattr(self, "show_histogram", False),
                command=pick_histogram).pack()

        r = win.row(t("Show pixel rulers"),
                    t("The top and left rulers over the photo (Ctrl+R)."))

        def pick_rulers(on):
            if on != getattr(self, "show_rulers", False):
                self.toggle_rulers()             # re-renders + persists itself
        tintkit.Toggle(r, self.theme, value=getattr(self, "show_rulers", False),
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

        r = win.row(t("Show cost dots"),
                    t("A small coloured dot beside the sliders and filters that "
                      "make every later edit slower — red for the heaviest, "
                      "amber for the rest. Switch those on last."))

        def pick_cost_dots(on):
            self._set_pref("show_cost_dots", on)
            self._refresh_cost_dots()        # shows / hides them in place
        tintkit.Toggle(r, self.theme, value=getattr(self, "show_cost_dots", True),
                command=pick_cost_dots).pack()

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

        win.group(t("Quick copy (Ctrl+E)"))
        self._set_quick_copy_row(win)
        win.note(t("Ctrl+E and the copy button write your edits here as a new, "
                   "numbered file — the original is never touched, and an earlier "
                   "copy is never replaced. Left unset, the first copy asks for "
                   "the folder."))

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

    def _set_quick_copy_row(self, win):
        "Pick the one folder every Ctrl+E copy lands in (independent of Output)."
        right = win.row(t("Folder"))
        cur = self.quick_copy_dir
        lbl = self._tw(tk.Label(right,
                       text=self._set_short_path(cur) if cur else t("Not set"),
                       font=("Segoe UI", 9), anchor="e", padx=10, pady=5),
                       bg="chip", fg="fg" if cur else "fg_dim")
        lbl.pack(side="left", padx=(0, 8))

        def change():
            d = tkfd.askdirectory(
                parent=self._settings_win, title=t("Quick-copy folder"),
                initialdir=cur or self.folder or os.path.expanduser("~"))
            if not d:
                return
            self.quick_copy_dir = d
            self._save_state()
            self._settings_body.rebuild()   # rebuild → label re-threaded fg="fg"
        tintkit.Button(right, self.theme, t("Change…"), role="neutral",
                       variant="outline", bg="bg", command=change).pack(side="left")

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
        win.note(t("The keep / reject buttons (and the Enter / Backspace keys) "
                   "move the current photo into these folders. Ctrl+Z undoes "
                   "the last move."))

        win.group(t("Auto-save while culling"))
        r = win.row(t("Save an edited copy when you move on"),
                    t("As you step away from or cull an edited photo, silently write "
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

        # --- Check for updates (manual only — no background / auto check) ------
        upd = self._tw(tk.Frame(box), bg="bg")
        upd.pack(anchor="w", fill="x", pady=(14, 0))
        status = self._tw(tk.Label(upd, text="", font=("Segoe UI", 9),
                                   anchor="w", justify="left"),
                          bg="bg", fg="fg_dim")
        btn = tintkit.Button(
            upd, self.theme, t("Check for updates"), role="neutral",
            variant="outline", bg="bg",
            command=lambda: self._check_updates(btn, status))
        btn.pack(side="left")
        status.pack(side="left", padx=(12, 0))

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

    # --- Contact tab --------------------------------------------------------

    def _set_tab_contact(self, win):
        "Reach the developer: one email button + a GitHub issues link (both channels)."
        p = win.body.widget
        box = self._tw(tk.Frame(p), bg="bg")
        box.pack(fill="x", pady=(16, 0))
        self._tw(tk.Label(box, text=t("Contact the developer"),
                 font=("Segoe UI", 17, "bold")), bg="bg", fg="fg").pack(anchor="w")
        self._tw(tk.Label(box, text=t("Questions, bugs or ideas — write to me directly."),
                 font=("Segoe UI", 9), justify="left"),
                 bg="bg", fg="fg_dim").pack(anchor="w", pady=(2, 0))

        # A promo call-to-action: opens the "Work with me" pitch (hire the dev).
        self._tw(tk.Frame(box, height=12), bg="bg").pack()
        tintkit.Button(box, self.theme, t("Need something built?"), role="primary",
                       variant="filled", bg="bg",
                       command=self._offer_dialog).pack(anchor="w")

        # The three reasons someone might get in touch (plain text, one button below).
        win.group(t("Get in touch about"))
        for reason in (t("Ordering a custom program"),
                       t("Reporting a bug"),
                       t("Suggesting an improvement")):
            row = self._tw(tk.Frame(p), bg="bg")
            row.pack(fill="x", pady=1)
            self._tw(tk.Label(row, text="•  " + reason, anchor="w",
                     font=("Segoe UI", 9)), bg="bg", fg="fg").pack(side="left")

        # Primary channel: one email button (opens the user's mail client).
        self._tw(tk.Frame(p, height=14), bg="bg").pack()
        mailto = "mailto:{}?subject=Manoni".format(DEV_EMAIL)
        tintkit.Button(p, self.theme, t("Email the developer"), role="primary",
                       variant="filled", bg="bg",
                       command=lambda: webbrowser.open(mailto)).pack(anchor="w")
        # The address, with a small dim "copy" affordance that flips to "Copied"
        # for a few seconds so the user gets feedback without a popup.
        erow = self._tw(tk.Frame(p), bg="bg")
        erow.pack(anchor="w", pady=(6, 0))
        self._tw(tk.Label(erow, text=DEV_EMAIL, font=("Segoe UI", 9)),
                 bg="bg", fg="fg_dim").pack(side="left")
        copy = self._tw(tk.Label(erow, text=t("Copy email"), cursor="hand2",
                        font=("Segoe UI", 8)), bg="bg", fg="fg_dim")
        copy.pack(side="left", padx=(10, 0))
        copy.bind("<Button-1>", lambda e: self._copy_email(copy))

        # Second channel: GitHub issues (handy for bugs and suggestions).
        win.group(t("Or on GitHub"))
        self._set_link_row(p, t("Issues"), ISSUES_URL)

    def _copy_email(self, lbl):
        "Copy DEV_EMAIL to the clipboard; flash the label to 'Copied' for 3s."
        self.root.clipboard_clear()
        self.root.clipboard_append(DEV_EMAIL)
        lbl.configure(text=t("Copied"))
        job = getattr(self, "_copy_revert_job", None)
        if job:
            self.root.after_cancel(job)
        self._copy_revert_job = self.root.after(
            3000,
            lambda: lbl.winfo_exists() and lbl.configure(text=t("Copy email")))

    def _offer_dialog(self):
        "A small 'work with me' pitch modal: what I build + a LinkedIn link."
        parent = getattr(self, "_settings_win", None) or self.root
        dlg = tk.Toplevel(parent)
        dlg.title(t("Work with me"))
        self._tw(dlg, bg="bg")
        dlg.transient(parent)
        dlg.resizable(False, False)

        wrap = self._tw(tk.Frame(dlg, padx=28, pady=24), bg="bg")
        wrap.pack(fill="both", expand=True)

        self._tw(tk.Label(wrap, text=t("Work with me"),
                 font=("Segoe UI", 15, "bold")), bg="bg", fg="fg").pack(anchor="w")
        self._tw(tk.Label(wrap, text=t(
            "Manoni is a free tool I build in my spare time. I'm also available "
            "for paid, custom work:"), font=("Segoe UI", 9),
            justify="left", wraplength=360), bg="bg", fg="fg_dim").pack(
            anchor="w", pady=(8, 0))

        for line in (t("Programs and games — small to medium complexity"),
                     t("Websites — almost any complexity")):
            self._tw(tk.Label(wrap, text="•  " + line, anchor="w",
                     font=("Segoe UI", 9), justify="left", wraplength=360),
                     bg="bg", fg="fg").pack(anchor="w", pady=(6, 0))

        self._tw(tk.Label(wrap, text=t(
            "Got an idea? Let's build it — see my work and get in touch on LinkedIn."),
            font=("Segoe UI", 9), justify="left", wraplength=360),
            bg="bg", fg="fg_dim").pack(anchor="w", pady=(12, 0))

        self._tw(tk.Frame(wrap, height=16), bg="bg").pack()
        btns = self._tw(tk.Frame(wrap), bg="bg")
        btns.pack(fill="x")
        tintkit.Button(btns, self.theme, t("Open LinkedIn"), role="primary",
                       variant="filled", bg="bg",
                       command=lambda: webbrowser.open(LINKEDIN_URL)).pack(side="left")
        tintkit.Button(btns, self.theme, t("Close"), role="neutral",
                       variant="outline", bg="bg",
                       command=dlg.destroy).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        self._center_dialog(dlg)
        dlg.grab_set()
        dlg.focus_set()

    # --- Manual update check (About tab) ------------------------------------
    # Strictly on demand: the network is touched only on this click, never on a
    # timer or at launch. The blocking GitHub call runs on a short daemon thread
    # and the result is marshalled back to the UI thread with root.after.

    def _check_updates(self, btn, status):
        "Ask GitHub for the latest release and report the result in `status`."
        if getattr(self, "_update_checking", False):
            return                      # ignore re-clicks while one is in flight
        self._update_checking = True
        status.unbind("<Button-1>")     # clear any prior 'download' affordance
        status.configure(text=t("Checking…"), cursor="",
                         fg=self.theme["fg_dim"], font=("Segoe UI", 9))

        def work():
            try:
                latest, err = update.fetch_latest_version(), None
            except Exception:
                latest, err = None, True
            self.root.after(0, lambda: self._update_done(status, latest, err))

        threading.Thread(target=work, name="manoni-update-check",
                         daemon=True).start()

    def _update_done(self, status, latest, err):
        "Back on the UI thread: show the outcome of an update check."
        self._update_checking = False
        if not status.winfo_exists():
            return                      # Settings closed mid-check
        if err or not latest:
            status.configure(text=t("Couldn't check — check your connection."),
                             fg=self.theme["fg_dim"], font=("Segoe UI", 9))
            return
        if update.is_newer(latest, APP_VERSION):
            status.configure(
                text=t("New version available: v{ver} — download").format(ver=latest),
                fg=self.theme["accent"], cursor="hand2",
                font=("Segoe UI", 9, "underline"))
            status.bind("<Button-1>",
                        lambda e: webbrowser.open(update.RELEASES_PAGE))
        else:
            status.configure(
                text=t("You have the latest version (v{ver})").format(ver=APP_VERSION),
                fg=self.theme["fg_dim"], font=("Segoe UI", 9))

    # --- Restore defaults ---------------------------------------------------

    def _set_restore_defaults(self):
        "Reset the DISPLAY + EXPORT defaults (not language, not cull folders)."
        if not self._confirm(
                t("Reset the view and export defaults to their original values?\n\n"
                  "Your language and sorting folders are left unchanged."),
                ok_label=t("Restore defaults")):
            return
        self.set_view("large")                       # default sidebar view
        if getattr(self, "show_rulers", False):      # rulers default = off
            self.toggle_rulers()
        self.show_filter_strip = True                # filter strip default = on
        self._refresh_filter_strip()
        self.show_histogram = False                  # histogram default = off
        self._refresh_histogram()
        self._repaint_view_toggles()                 # sync the toolbar toggles
        self.fast_preview = True                      # fast preview default = on
        self.show_cost_dots = True                    # cost dots default = on
        self._refresh_cost_dots()
        self.last_save = {"dir": "", "fmt": "JPEG", "quality": 95,
                          "keep_meta": True, "to_srgb": False}
        self._save_state()
        self._settings_body.rebuild()                # repaint the open tab
        self.toast(t("Settings restored to defaults"))
