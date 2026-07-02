"""Settings: a tabbed preferences window (☰ menu → Settings).

A non-modal Toplevel in the app's dark-blue style: a left vertical tab rail
(icon + label) + a scrollable content pane + a footer (Restore defaults · Done).
Tabs: General · Export · Culling · About.

Every control is wired to a REAL, already-persisted setting — there are no dead
toggles here. The window only gathers settings that live elsewhere into one
place:
  * General  — UI language (relaunches), default sidebar view, pixel rulers
  * Export   — the Save dialog's defaults (format / quality / metadata / sRGB),
               stored in self.last_save and persisted across sessions
  * Culling  — the two keep / reject sort folders (self.cull_keep/.cull_reject)

Mixin on the Manoni window — every method uses the shared `self`, like the other
ui mixins. The small canvas-drawn controls (toggle / segmented / slider) live at
module level so the window code below stays declarative; each is DPI-aware.
"""

import os
import webbrowser
import tkinter as tk
import tkinter.filedialog as tkfd

import tintkit

from .. import i18n
from ..i18n import t
from .about import (APP_VERSION, AUTHOR_NAME, AUTHOR_HANDLE, BUILT_WITH,
                    PROJECT_LINKS, BMC_URL, BMC_BG, BMC_BG_HOVER, BMC_FG)

# The window's controls (toggle / segmented / slider / dropdown / buttons) are
# stock TintKit widgets reading self.theme; the window chrome (tab rail, scroll
# pane, headers, path labels, About links) is plain tk threaded onto self.theme
# via chrome's _tw so the whole window switches dark<->light live. The rail's
# selected-row tint has no theme token, so it's mixed live from sidebar+accent.
# Buy-me-a-coffee keeps its brand colours (not theme tokens).


# --- tab spec: (key, label-source, icon, builder-method-name) ----------------
# Labels are translated where the rail is built (so a language switch retexts).
_TABS = [
    ("general", "General", "settings",     "_set_tab_general"),
    ("export",  "Export",  "upload",       "_set_tab_export"),
    ("culling", "Culling", "folder-check", "_set_tab_culling"),
    ("about",   "About",   "info",         "_set_tab_about"),
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
        self._set_active = "general"
        self._set_rail_rows = {}

        dlg.rowconfigure(1, weight=1)
        dlg.columnconfigure(0, weight=1)

        self._set_build_header(dlg)
        self._set_build_body(dlg)
        self._set_build_footer(dlg)

        # The window is non-modal (kept in self._settings_win), so it can outlive a
        # dark<->light switch. The rail rows are bespoke active-state controls built
        # once here → subscribe their repaint and drop it when the window closes.
        self.theme.subscribe(self._set_paint_rail)
        dlg.bind("<Destroy>",
                 lambda e: e.widget is dlg and self.theme.unsubscribe(self._set_paint_rail),
                 add="+")

        def close():
            self._settings_win = None
            try:
                dlg.destroy()
            except tk.TclError:
                pass
        dlg.protocol("WM_DELETE_WINDOW", close)
        dlg.bind("<Escape>", lambda e: close())
        dlg.bind("<MouseWheel>", lambda e: self._set_canvas.yview_scroll(
            int(-e.delta / 120), "units"))

        w, h = self._edit_dpi_w(720), self._edit_dpi_w(560)
        dlg.minsize(self._edit_dpi_w(620), self._edit_dpi_w(440))
        dlg.geometry(f"{w}x{h}")
        self._center_dialog(dlg)
        self._set_show_tab("general")
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
        body = self._tw(tk.Frame(dlg), bg="bg")
        body.grid(row=1, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        # LEFT: vertical tab rail.
        rail = self._tw(tk.Frame(body, width=self._edit_dpi_w(180)), bg="sidebar")
        rail.grid(row=0, column=0, sticky="ns")
        rail.grid_propagate(False)
        self._tw(tk.Frame(rail, height=self._edit_dpi_w(8)), bg="bg").pack(fill="x")
        for key, label, icon, _m in _TABS:
            self._set_rail_row(rail, key, t(label), icon)
        self._tw(tk.Frame(body, width=1), bg="border").grid(
            row=0, column=0, sticky="nse")

        # RIGHT: a scrollable content pane.
        right = self._tw(tk.Frame(body), bg="bg")
        right.grid(row=0, column=1, sticky="nsew")
        self._set_canvas = self._tw(tk.Canvas(right, highlightthickness=0), bg="bg")
        sb = self._make_scrollbar(right, self._set_canvas)
        self._set_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._set_canvas.pack(side="left", fill="both", expand=True)
        self._set_body = self._tw(tk.Frame(self._set_canvas), bg="bg")
        self._set_win = self._set_canvas.create_window(
            (0, 0), window=self._set_body, anchor="nw")
        self._set_body.bind(
            "<Configure>",
            lambda e: self._set_canvas.configure(
                scrollregion=self._set_canvas.bbox("all")))
        self._set_canvas.bind(
            "<Configure>",
            lambda e: self._set_canvas.itemconfigure(self._set_win,
                                                     width=e.width))

    def _set_rail_row(self, parent, key, label, icon):
        # Bespoke active-state row (like crop's chips): built once, its resting /
        # hover / active look comes from _set_paint_rail + _set_rail_hover reading
        # self.theme live, so a dark<->light switch (subscribed) repaints it.
        side = self.theme["sidebar"]
        row = tk.Frame(parent, bg=side, cursor="hand2")
        row.pack(fill="x")
        bar = tk.Frame(row, bg=side, width=3)      # accent bar when active
        bar.pack(side="left", fill="y")
        im = self.icon(icon, size=17)
        if im is not None:
            ic = tk.Label(row, image=im, bg=side)
            self._reg_icon(ic, icon, size=17, token="fg")   # bg = rail paint's
        else:
            ic = tk.Label(row, text="•", bg=side, fg=self.theme["fg"])
        ic.pack(side="left", padx=(13, 10), pady=10)
        lab = tk.Label(row, text=label, bg=side, fg=self.theme["fg"], anchor="w",
                       font=("Segoe UI", 10))
        lab.pack(side="left")
        self._set_rail_rows[key] = (row, bar, ic, lab)
        for w in (row, ic, lab):
            w.bind("<Button-1>", lambda e, k=key: self._set_show_tab(k))
            w.bind("<Enter>", lambda e, k=key: self._set_rail_hover(k, True))
            w.bind("<Leave>", lambda e, k=key: self._set_rail_hover(k, False))

    def _set_rail_hover(self, key, on):
        if key == self._set_active:
            return
        row, bar, ic, lab = self._set_rail_rows[key]
        bg = self.theme["hover"] if on else self.theme["sidebar"]
        for w in (row, bar, ic, lab):
            w.configure(bg=bg)

    def _set_paint_rail(self):
        side = self.theme["sidebar"]
        # No theme token for the faint selected-row tint → mix sidebar toward accent.
        sel = tintkit.mix(side, self.theme["accent"], 0.12)
        for key, (row, bar, ic, lab) in self._set_rail_rows.items():
            act = (key == self._set_active)
            bg = sel if act else side
            bar.configure(bg=self.theme["accent"] if act else side)
            for w in (row, ic, lab):
                w.configure(bg=bg)
            lab.configure(fg=self.theme["fg"],
                          font=("Segoe UI", 10, "bold" if act else "normal"))

    def _set_show_tab(self, key):
        "Switch tabs: repaint the rail, rebuild the content pane, scroll to top."
        self._set_active = key
        self._set_paint_rail()
        for w in self._set_body.winfo_children():
            w.destroy()
        pad = self._tw(tk.Frame(self._set_body), bg="bg")
        pad.pack(fill="both", expand=True, padx=26, pady=(4, 24))
        method = next(m for k, _l, _i, m in _TABS if k == key)
        getattr(self, method)(pad)
        self._set_canvas.yview_moveto(0.0)

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

    # --- shared content blocks ---------------------------------------------

    def _set_group(self, parent, title):
        "A thin divider + small bold caption titling a block of settings."
        self._tw(tk.Frame(parent, height=1), bg="divider").pack(fill="x", pady=(20, 0))
        self._tw(tk.Label(parent, text=title.upper(), anchor="w",
                 font=("Segoe UI", 8, "bold")), bg="bg", fg="fg_dim").pack(
            fill="x", pady=(8, 4))

    def _set_row(self, parent, title, desc=None):
        "One setting line: title (+ optional description) left, control frame right."
        row = self._tw(tk.Frame(parent), bg="bg")
        row.pack(fill="x", pady=6)
        left = self._tw(tk.Frame(row), bg="bg")
        left.pack(side="left", fill="x", expand=True)
        self._tw(tk.Label(left, text=title, anchor="w",
                 font=("Segoe UI", 10)), bg="bg", fg="fg").pack(anchor="w")
        if desc:
            self._tw(tk.Label(left, text=desc, anchor="w", justify="left",
                     font=("Segoe UI", 8), wraplength=self._edit_dpi_w(330)),
                     bg="bg", fg="fg_dim").pack(anchor="w", pady=(2, 0))
        right = self._tw(tk.Frame(row), bg="bg")
        right.pack(side="right", padx=(16, 0))
        return right

    def _set_note(self, parent, text):
        "A small dim explanatory line under a block."
        self._tw(tk.Label(parent, text=text, anchor="w", justify="left",
                 font=("Segoe UI", 8), wraplength=self._edit_dpi_w(440)),
                 bg="bg", fg="fg_dim").pack(fill="x", pady=(10, 0))

    # --- General tab --------------------------------------------------------

    def _set_tab_general(self, p):
        self._set_group(p, t("Language"))
        r = self._set_row(p, t("Interface language"),
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

        self._set_group(p, t("Sidebar"))
        r = self._set_row(p, t("Default view"))
        keys = ["large", "medium", "small", "list"]
        labels = [t("Large"), t("Medium"), t("Small"), t("List")]

        def pick_view(i):
            self.set_view(keys[i])
            self._save_state()
        tintkit.SegmentedTabs(r, self.theme, labels,
                              selected=self._set_view_index(keys),
                              command=lambda i, _l: pick_view(i)).pack()

        self._set_group(p, t("Interface"))
        r = self._set_row(p, t("Light mode"),
                          t("Switch between the dark and light interface."))

        def pick_scheme(on):
            self.theme.set(scheme="light" if on else "dark")  # repaints the app live
            self._save_state()
        tintkit.Toggle(r, self.theme, value=(self.theme.scheme == "light"),
                       command=pick_scheme).pack()

        r = self._set_row(p, t("Show filter strip"),
                          t("The row of filter previews under the photo."))

        def pick_filters(on):
            self.show_filter_strip = on
            self._save_state()
            self._refresh_filter_strip()         # show / hide the strip live
        tintkit.Toggle(r, self.theme, value=getattr(self, "show_filter_strip", True),
                command=pick_filters).pack()

        r = self._set_row(p, t("Show histogram"),
                          t("The live tonal graph at the top of the edit panel."))

        def pick_histogram(on):
            self.show_histogram = on
            self._save_state()
            self._refresh_histogram()            # show / hide the graph live
        tintkit.Toggle(r, self.theme, value=getattr(self, "show_histogram", True),
                command=pick_histogram).pack()

        r = self._set_row(p, t("Show pixel rulers"),
                          t("The top and left rulers over the photo (Ctrl+R)."))

        def pick_rulers(on):
            if on != getattr(self, "show_rulers", True):
                self.toggle_rulers()             # re-renders + persists itself
        tintkit.Toggle(r, self.theme, value=getattr(self, "show_rulers", True),
                command=pick_rulers).pack()

        self._set_group(p, t("Performance"))
        r = self._set_row(p, t("Fast preview while dragging"),
                          t("Skip the heavy filters (clarity, sharpen, denoise, "
                            "dehaze, focus, grain) while a slider is dragged; "
                            "full quality returns the moment you let go."))
        tintkit.Toggle(r, self.theme, value=getattr(self, "fast_preview", True),
                command=lambda on: self._set_pref("fast_preview", on)).pack()

        r = self._set_row(p, t("Render off the main thread"),
                          t("Do the heavy edit work on a background thread so the "
                            "window never freezes while a costly effect renders; "
                            "the photo catches up a moment behind the slider. Turn "
                            "off to render on the main thread (the older behaviour)."))
        tintkit.Toggle(r, self.theme, value=getattr(self, "async_render", True),
                command=lambda on: self._set_pref("async_render", on)).pack()

        self._set_group(p, t("On launch"))
        r = self._set_row(p, t("Reopen the last folder"))
        tintkit.Toggle(r, self.theme, value=self.restore_session,
                command=lambda on: self._set_pref("restore_session", on)).pack()
        r = self._set_row(p, t("Jump back to the last photo"))
        tintkit.Toggle(r, self.theme, value=self.restore_photo,
                command=lambda on: self._set_pref("restore_photo", on)).pack()

        self._set_group(p, t("Confirmations"))
        r = self._set_row(p, t("Ask before rejecting a photo"),
                          t("A quick confirm before a photo moves to the Reject folder."))
        tintkit.Toggle(r, self.theme, value=self.confirm_reject,
                command=lambda on: self._set_pref("confirm_reject", on)).pack()
        r = self._set_row(p, t("Warn about unsaved edits when leaving a photo"))
        tintkit.Toggle(r, self.theme, value=self.warn_unsaved,
                command=lambda on: self._set_pref("warn_unsaved", on)).pack()

    def _set_pref(self, key, val):
        "Set a simple on/off General preference attribute and persist it."
        setattr(self, key, val)
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

    def _set_tab_export(self, p):
        self._set_group(p, t("Default format"))
        r = self._set_row(p, t("File format"))
        fmts = ["JPEG", "PNG", "WEBP"]
        cur_fmt = self._set_export_get("fmt", "JPEG")
        active = fmts.index(cur_fmt) if cur_fmt in fmts else 0
        tintkit.SegmentedTabs(
            r, self.theme, fmts, selected=active,
            command=lambda i, _l: self._set_export_set("fmt", fmts[i])).pack()

        r = self._set_row(p, t("Quality"),
                          t("Used for JPEG and WEBP (PNG is always lossless)."))
        # Gauge slider: raw read-out (no signed delta), persist on release only.
        def commit_quality():
            self._set_export_set("quality", int(qsl.get()))
        qsl = tintkit.TitledSlider(
            r, self.theme, "", value=int(self._set_export_get("quality", 95)),
            lo=50, hi=100, neutral=50, value_fmt=lambda v, _n: str(v),
            on_release=commit_quality, bg="bg")
        qsl.pack()

        self._set_group(p, t("Metadata"))
        r = self._set_row(p, t("Keep metadata"),
                          t("Camera info, date, GPS and the colour profile."))
        tintkit.Toggle(r, self.theme, value=bool(self._set_export_get("keep_meta", True)),
                command=lambda on: self._set_export_set("keep_meta", on)).pack()

        r = self._set_row(p, t("Convert to sRGB"),
                          t("Best for the web — keeps colours consistent across browsers."))
        tintkit.Toggle(r, self.theme, value=bool(self._set_export_get("to_srgb", False)),
                command=lambda on: self._set_export_set("to_srgb", on)).pack()

        self._set_group(p, t("Output"))
        r = self._set_row(p, t("Save edited photos to"))
        modes = ["subfolder", "fixed"]
        labels = [t("Subfolder"), t("Fixed folder")]
        active = modes.index(self.export_dir_mode) \
            if self.export_dir_mode in modes else 0

        def pick_mode(i):
            if modes[i] == self.export_dir_mode:
                return
            self.export_dir_mode = modes[i]
            self._save_state()
            self._set_show_tab("export")     # re-render to show the matching control
        tintkit.SegmentedTabs(r, self.theme, labels, selected=active,
                              command=lambda i, _l: pick_mode(i)).pack()
        if self.export_dir_mode == "fixed":
            self._set_export_fixed_row(p)
        else:
            self._set_export_subfolder_row(p)

        self._set_note(p, t("These are the defaults the Save dialog opens with."))

    def _set_export_subfolder_row(self, parent):
        "Edit the per-photo subfolder name (mode “subfolder”)."
        right = self._set_row(parent, t("Subfolder name"),
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

    def _set_export_fixed_row(self, parent):
        "Pick one fixed output folder for every export (mode “fixed”)."
        right = self._set_row(parent, t("Folder"))
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
            self._set_show_tab(self._set_active)   # rebuild → label re-threaded fg="fg"
        tintkit.Button(right, self.theme, t("Change…"), role="neutral",
                       variant="outline", bg="bg", command=change).pack(side="left")

    # --- Culling tab --------------------------------------------------------

    def _set_tab_culling(self, p):
        self._set_group(p, t("Sorting folders"))
        self._set_cull_row(p, t("Keep (keeper) folder"), "keep")
        self._set_cull_row(p, t("Reject folder"), "reject")
        self._set_note(p, t("The keep / reject buttons (and the ↑ / ↓ keys) move "
                            "the current photo into these folders. Ctrl+Z undoes "
                            "the last move."))

        self._set_group(p, t("At the end of the folder"))
        r = self._set_row(p, t("When you pass the last photo"),
                          t("← / → past the edge of the folder."))
        keys = [None, "wrap", "sibling"]
        labels = [t("Ask"), t("First photo"), t("Next folder")]
        active = keys.index(self.edge_action) if self.edge_action in keys else 0

        def pick_edge(i):
            self.edge_action = keys[i]
            self._save_state()
        tintkit.SegmentedTabs(r, self.theme, labels, selected=active,
                              command=lambda i, _l: pick_edge(i)).pack()
        self._set_note(p, t("“Ask” pops a small chooser each time you reach the "
                            "edge. “First photo” loops back; “Next folder” opens "
                            "the next folder that has photos."))

    def _set_cull_row(self, parent, title, which):
        right = self._set_row(parent, title)
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
            self._set_show_tab(self._set_active)   # rebuild → label re-threaded fg="fg"
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

    def _set_tab_about(self, p):
        box = self._tw(tk.Frame(p), bg="bg")
        box.pack(fill="x", pady=(16, 0))
        self._tw(tk.Label(box, text="Manoni", font=("Segoe UI", 17, "bold")),
                 bg="bg", fg="fg").pack(anchor="w")
        self._tw(tk.Label(box, text="v" + APP_VERSION + "  ·  " +
                 t("a fast, simple dark photo browser and culler"),
                 font=("Segoe UI", 9)), bg="bg", fg="fg_dim").pack(
            anchor="w", pady=(2, 0))
        self._tw(tk.Label(box, text="{label}: {name} · {handle}".format(
            label=t("Author"), name=AUTHOR_NAME, handle=AUTHOR_HANDLE),
            font=("Segoe UI", 9)), bg="bg", fg="fg").pack(anchor="w", pady=(12, 0))
        self._tw(tk.Label(box, text=t("Written in Python"),
                 font=("Segoe UI", 9)), bg="bg", fg="fg_dim").pack(
            anchor="w", pady=(2, 0))

        self._set_group(p, t("Built with"))
        for name, url, lic in BUILT_WITH:
            self._set_link_row(p, name, url, lic)

        self._set_group(p, t("Links"))
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
        self._set_show_tab(self._set_active)         # repaint the open tab
        self.toast(t("Settings restored to defaults"))
