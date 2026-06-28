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
import tkinter.font as tkfont
import tkinter.filedialog as tkfd

from ..config import (BG, BAR, SIDEBAR, HOVER, ACCENT, ON_ACCENT, FG, FG_DIM,
                      CHIP_BG, BORDER, DIVIDER)
from .. import i18n
from ..i18n import t
from .dialogs import make_dialog_button
from .about import (APP_VERSION, AUTHOR_NAME, AUTHOR_HANDLE, BUILT_WITH,
                    PROJECT_LINKS, BMC_URL, BMC_BG, BMC_BG_HOVER, BMC_FG)

SEL_BG = "#2a2f37"          # selected tab-rail row (a faint blue-grey tint)


# --- rounded-rectangle drawing (shared by the canvas controls) --------------
def _round_pts(x0, y0, x1, y1, r):
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


def _draw_round(c, x0, y0, x1, y1, r, **kw):
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    if r <= 0:
        return c.create_rectangle(x0, y0, x1, y1, **kw)
    return c.create_polygon(_round_pts(x0, y0, x1, y1, r), smooth=True, **kw)


# --- DPI-aware canvas controls ----------------------------------------------
class _Toggle:
    "A rounded on/off switch — click flips it (accent when on)."

    def __init__(self, parent, dpi, on=False, command=None):
        self.on, self.command = on, command
        self.S = S = lambda v: round(v * dpi)
        self.c = tk.Canvas(parent, width=S(46), height=S(26), bg=BG,
                           highlightthickness=0, cursor="hand2")
        self.c.bind("<Button-1>", self._toggle)
        self._draw()

    def _toggle(self, _e=None):
        self.on = not self.on
        self._draw()
        if self.command:
            self.command(self.on)

    def _draw(self):
        c, S = self.c, self.S
        c.delete("all")
        _draw_round(c, S(2), S(4), S(44), S(22), S(9),
                    fill=ACCENT if self.on else CHIP_BG)
        kx = S(34) if self.on else S(12)
        c.create_oval(kx - S(8), S(5), kx + S(8), S(21),
                      fill=ON_ACCENT if self.on else FG_DIM, outline="")

    def pack(self, **kw):
        self.c.pack(**kw)
        return self


class _Segmented:
    "A row of pill chips; exactly one is active (accent)."

    def __init__(self, parent, dpi, options, active=0, command=None):
        self.options, self.active, self.command = options, active, command
        self.S = S = lambda v: round(v * dpi)
        self.fnt = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        widths = [self.fnt.measure(o) + S(26) for o in options]
        self.bounds, x = [], S(3)
        for w in widths:
            self.bounds.append((x, x + w))
            x += w
        self.c = tk.Canvas(parent, width=x + S(3), height=S(32), bg=BG,
                           highlightthickness=0, cursor="hand2")
        self.c.bind("<Button-1>", self._click)
        self._draw()

    def _click(self, e):
        for i, (a, b) in enumerate(self.bounds):
            if a <= e.x <= b:
                if i != self.active:
                    self.active = i
                    self._draw()
                    if self.command:
                        self.command(i)
                return

    def _draw(self):
        c, S = self.c, self.S
        c.delete("all")
        _draw_round(c, self.bounds[0][0] - S(2), S(3),
                    self.bounds[-1][1] + S(2), S(29), S(13), fill=CHIP_BG)
        for i, (a, b) in enumerate(self.bounds):
            act = (i == self.active)
            if act:
                _draw_round(c, a, S(5), b, S(27), S(11), fill=ACCENT)
            c.create_text((a + b) / 2, S(16), text=self.options[i],
                          fill=ON_ACCENT if act else FG, font=self.fnt)

    def pack(self, **kw):
        self.c.pack(**kw)
        return self


class _Slider:
    "A thick-track / pill-knob slider with a live read-out; commits on release."

    def __init__(self, parent, dpi, value, lo, hi, unit="", width=240,
                 on_release=None):
        self.value, self.lo, self.hi, self.unit = value, lo, hi, unit
        self.on_release = on_release
        self.S = S = lambda v: round(v * dpi)
        self.W, self.x0, self.x1 = S(width), S(8), S(width) - S(52)
        self.c = tk.Canvas(parent, width=self.W, height=S(30), bg=BG,
                           highlightthickness=0, cursor="hand2")
        self.c.bind("<Button-1>", self._drag)
        self.c.bind("<B1-Motion>", self._drag)
        self.c.bind("<ButtonRelease-1>", self._release)
        self._draw()

    def _v2x(self, v):
        return self.x0 + (v - self.lo) / (self.hi - self.lo) * (self.x1 - self.x0)

    def _drag(self, e):
        f = min(1.0, max(0.0, (e.x - self.x0) / (self.x1 - self.x0)))
        self.value = round(self.lo + f * (self.hi - self.lo))
        self._draw()

    def _release(self, _e):
        if self.on_release:
            self.on_release(self.value)

    def _draw(self):
        c, S = self.c, self.S
        c.delete("all")
        y = S(15)
        c.create_line(self.x0, y, self.x1, y, fill=DIVIDER, width=S(6),
                      capstyle="round")
        kx = self._v2x(self.value)
        c.create_line(self.x0, y, kx, y, fill=ACCENT, width=S(6),
                      capstyle="round")
        _draw_round(c, kx - S(6), y - S(9), kx + S(6), y + S(9), S(5),
                    fill=ACCENT)
        c.create_text(self.x1 + S(44), y, text=f"{self.value}{self.unit}",
                      anchor="e", fill=FG, font=("Segoe UI", 9, "bold"))

    def pack(self, **kw):
        self.c.pack(**kw)
        return self


class _Dropdown:
    "A flat value button (label + ▾) that opens a small dark popup of options."

    def __init__(self, parent, dpi, options, active=0, command=None, icon=None):
        self.options, self.active, self.command = options, active, command
        self.box = tk.Frame(parent, bg=CHIP_BG, cursor="hand2")
        self.lbl = tk.Label(self.box, text=options[active], bg=CHIP_BG, fg=FG,
                            anchor="w", font=("Segoe UI", 9))
        self.lbl.pack(side="left", padx=(10, 8), pady=6)
        chev = icon("chevron-down", 14) if icon else None
        self.chev = (tk.Label(self.box, image=chev, bg=CHIP_BG) if chev
                     else tk.Label(self.box, text="▾", bg=CHIP_BG, fg=FG_DIM))
        self.chev.pack(side="right", padx=(0, 8))
        for w in (self.box, self.lbl, self.chev):
            w.bind("<Enter>", lambda e: self._paint(HOVER))
            w.bind("<Leave>", lambda e: self._paint(CHIP_BG))
            w.bind("<Button-1>", lambda e: self._open())
        self._pop = None

    def _paint(self, bg):
        for w in (self.box, self.lbl, self.chev):
            w.configure(bg=bg)

    def _open(self):
        if self._pop is not None:
            self._close()
            return
        pop = tk.Toplevel(self.box)
        pop.overrideredirect(True)
        pop.configure(bg=BORDER)
        self._pop = pop
        inner = tk.Frame(pop, bg=BAR)
        inner.pack(padx=1, pady=1)
        for i, opt in enumerate(self.options):
            self._row(inner, i, opt)
        pop.update_idletasks()
        bx, by = self.box.winfo_rootx(), self.box.winfo_rooty()
        pop.geometry(f"+{bx}+{by + self.box.winfo_height() + 2}")
        pop.bind("<Escape>", lambda e: self._close())
        pop.bind("<FocusOut>", lambda e: self._close())
        pop.focus_force()

    def _row(self, parent, i, opt):
        act = (i == self.active)
        r = tk.Frame(parent, bg=BAR, cursor="hand2")
        r.pack(fill="x")
        mark = tk.Label(r, text="✓" if act else "", bg=BAR, fg=ACCENT, width=2,
                        font=("Segoe UI", 9))
        mark.pack(side="left", padx=(6, 0), pady=5)
        lab = tk.Label(r, text=opt, bg=BAR, fg=ACCENT if act else FG, anchor="w",
                       font=("Segoe UI", 9))
        lab.pack(side="left", padx=(0, 20), pady=5)
        cells = (r, mark, lab)
        for w in cells:
            w.bind("<Enter>", lambda e: [x.configure(bg=HOVER) for x in cells])
            w.bind("<Leave>", lambda e: [x.configure(bg=BAR) for x in cells])
            w.bind("<Button-1>", lambda e, idx=i: self._pick(idx))

    def _pick(self, i):
        self.active = i
        self.lbl.configure(text=self.options[i])
        self._close()
        if self.command:
            self.command(i)

    def _close(self):
        if self._pop is not None:
            try:
                self._pop.destroy()
            except tk.TclError:
                pass
            self._pop = None

    def pack(self, **kw):
        self.box.pack(**kw)
        return self


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

        dlg = tk.Toplevel(self.root)
        dlg.title(t("Settings"))
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        self._settings_win = dlg
        self._set_active = "general"
        self._set_rail_rows = {}

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
        dlg.bind("<MouseWheel>", lambda e: self._set_canvas.yview_scroll(
            int(-e.delta / 120), "units"))

        w, h = self._edit_dpi_w(720), self._edit_dpi_w(560)
        dlg.minsize(self._edit_dpi_w(620), self._edit_dpi_w(440))
        dlg.geometry(f"{w}x{h}")
        self._center_dialog(dlg)
        self._set_show_tab("general")
        dlg.focus_force()

    def _set_build_header(self, dlg):
        bar = tk.Frame(dlg, bg=BAR, height=self._edit_dpi_w(52))
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        im = self.icon("settings", size=20)
        if im is not None:
            tk.Label(bar, image=im, bg=BAR).pack(side="left", padx=(16, 10))
        tk.Label(bar, text=t("Settings"), bg=BAR, fg=FG,
                 font=("Segoe UI", 13, "bold")).pack(side="left")
        tk.Frame(dlg, bg=BORDER, height=1).grid(row=0, column=0, sticky="sew")

    def _set_build_body(self, dlg):
        body = tk.Frame(dlg, bg=BG)
        body.grid(row=1, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        # LEFT: vertical tab rail.
        rail = tk.Frame(body, bg=SIDEBAR, width=self._edit_dpi_w(180))
        rail.grid(row=0, column=0, sticky="ns")
        rail.grid_propagate(False)
        tk.Frame(rail, bg=BG, height=self._edit_dpi_w(8)).pack(fill="x")
        for key, label, icon, _m in _TABS:
            self._set_rail_row(rail, key, t(label), icon)
        tk.Frame(body, bg=BORDER, width=1).grid(row=0, column=0, sticky="nse")

        # RIGHT: a scrollable content pane.
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        self._set_canvas = tk.Canvas(right, bg=BG, highlightthickness=0)
        sb = self._make_scrollbar(right, self._set_canvas)
        self._set_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._set_canvas.pack(side="left", fill="both", expand=True)
        self._set_body = tk.Frame(self._set_canvas, bg=BG)
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
        row = tk.Frame(parent, bg=SIDEBAR, cursor="hand2")
        row.pack(fill="x")
        bar = tk.Frame(row, bg=SIDEBAR, width=3)      # accent bar when active
        bar.pack(side="left", fill="y")
        im = self.icon(icon, size=17)
        ic = (tk.Label(row, image=im, bg=SIDEBAR) if im is not None
              else tk.Label(row, text="•", bg=SIDEBAR, fg=FG))
        ic.pack(side="left", padx=(13, 10), pady=10)
        lab = tk.Label(row, text=label, bg=SIDEBAR, fg=FG, anchor="w",
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
        bg = HOVER if on else SIDEBAR
        for w in (row, bar, ic, lab):
            w.configure(bg=bg)

    def _set_paint_rail(self):
        for key, (row, bar, ic, lab) in self._set_rail_rows.items():
            act = (key == self._set_active)
            bg = SEL_BG if act else SIDEBAR
            bar.configure(bg=ACCENT if act else SIDEBAR)
            for w in (row, ic, lab):
                w.configure(bg=bg)
            lab.configure(font=("Segoe UI", 10, "bold" if act else "normal"))

    def _set_show_tab(self, key):
        "Switch tabs: repaint the rail, rebuild the content pane, scroll to top."
        self._set_active = key
        self._set_paint_rail()
        for w in self._set_body.winfo_children():
            w.destroy()
        pad = tk.Frame(self._set_body, bg=BG)
        pad.pack(fill="both", expand=True, padx=26, pady=(4, 24))
        method = next(m for k, _l, _i, m in _TABS if k == key)
        getattr(self, method)(pad)
        self._set_canvas.yview_moveto(0.0)

    def _set_build_footer(self, dlg):
        tk.Frame(dlg, bg=BORDER, height=1).grid(row=2, column=0, sticky="new")
        foot = tk.Frame(dlg, bg=BAR, height=self._edit_dpi_w(58))
        foot.grid(row=2, column=0, sticky="ew")
        foot.grid_propagate(False)
        inner = tk.Frame(foot, bg=BAR)
        inner.pack(fill="x", padx=16, pady=11)
        make_dialog_button(inner, t("Restore defaults"),
                           self._set_restore_defaults).pack(side="left")

        def close():
            self._settings_win = None
            try:
                dlg.destroy()
            except tk.TclError:
                pass
        make_dialog_button(inner, t("Done"), close, primary=True).pack(
            side="right")

    # --- shared content blocks ---------------------------------------------

    def _set_group(self, parent, title):
        "A thin divider + small bold caption titling a block of settings."
        tk.Frame(parent, bg=DIVIDER, height=1).pack(fill="x", pady=(20, 0))
        tk.Label(parent, text=title.upper(), bg=BG, fg=FG_DIM, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(fill="x", pady=(8, 4))

    def _set_row(self, parent, title, desc=None):
        "One setting line: title (+ optional description) left, control frame right."
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=6)
        left = tk.Frame(row, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, bg=BG, fg=FG, anchor="w",
                 font=("Segoe UI", 10)).pack(anchor="w")
        if desc:
            tk.Label(left, text=desc, bg=BG, fg=FG_DIM, anchor="w",
                     justify="left", font=("Segoe UI", 8),
                     wraplength=self._edit_dpi_w(330)).pack(anchor="w",
                                                            pady=(2, 0))
        right = tk.Frame(row, bg=BG)
        right.pack(side="right", padx=(16, 0))
        return right

    def _set_note(self, parent, text):
        "A small dim explanatory line under a block."
        tk.Label(parent, text=text, bg=BG, fg=FG_DIM, anchor="w",
                 justify="left", font=("Segoe UI", 8),
                 wraplength=self._edit_dpi_w(440)).pack(fill="x", pady=(10, 0))

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
        _Dropdown(r, self.dpi, names, active=active, command=pick_lang,
                  icon=self.icon).pack()

        self._set_group(p, t("Sidebar"))
        r = self._set_row(p, t("Default view"))
        keys = ["large", "medium", "small", "list"]
        labels = [t("Large"), t("Medium"), t("Small"), t("List")]

        def pick_view(i):
            self.set_view(keys[i])
            self._save_state()
        _Segmented(r, self.dpi, labels, active=self._set_view_index(keys),
                   command=pick_view).pack()

        self._set_group(p, t("Interface"))
        r = self._set_row(p, t("Show pixel rulers"),
                          t("The top and left rulers over the photo (Ctrl+R)."))

        def pick_rulers(on):
            if on != getattr(self, "show_rulers", True):
                self.toggle_rulers()             # re-renders + persists itself
        _Toggle(r, self.dpi, on=getattr(self, "show_rulers", True),
                command=pick_rulers).pack()

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
        _Segmented(r, self.dpi, fmts, active=active,
                   command=lambda i: self._set_export_set("fmt", fmts[i])).pack()

        r = self._set_row(p, t("Quality"),
                          t("Used for JPEG and WEBP (PNG is always lossless)."))
        _Slider(r, self.dpi, value=int(self._set_export_get("quality", 95)),
                lo=50, hi=100,
                on_release=lambda v: self._set_export_set("quality", int(v))).pack()

        self._set_group(p, t("Metadata"))
        r = self._set_row(p, t("Keep metadata"),
                          t("Camera info, date, GPS and the colour profile."))
        _Toggle(r, self.dpi, on=bool(self._set_export_get("keep_meta", True)),
                command=lambda on: self._set_export_set("keep_meta", on)).pack()

        r = self._set_row(p, t("Convert to sRGB"),
                          t("Best for the web — keeps colours consistent across browsers."))
        _Toggle(r, self.dpi, on=bool(self._set_export_get("to_srgb", False)),
                command=lambda on: self._set_export_set("to_srgb", on)).pack()

        self._set_note(p, t("These are the defaults the Save dialog opens with."))

    # --- Culling tab --------------------------------------------------------

    def _set_tab_culling(self, p):
        self._set_group(p, t("Sorting folders"))
        self._set_cull_row(p, t("Keep (keeper) folder"), "keep")
        self._set_cull_row(p, t("Reject folder"), "reject")
        self._set_note(p, t("The keep / reject buttons (and the ↑ / ↓ keys) move "
                            "the current photo into these folders. Ctrl+Z undoes "
                            "the last move."))

    def _set_cull_row(self, parent, title, which):
        right = self._set_row(parent, title)
        cur = self.cull_keep if which == "keep" else self.cull_reject
        lbl = tk.Label(right, text=self._set_short_path(cur) if cur else t("Not set"),
                       bg=CHIP_BG, fg=FG if cur else FG_DIM, font=("Segoe UI", 9),
                       anchor="e", padx=10, pady=5)
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
            lbl.configure(text=self._set_short_path(d), fg=FG)
        make_dialog_button(right, t("Change…"), change).pack(side="left")

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
        box = tk.Frame(p, bg=BG)
        box.pack(fill="x", pady=(16, 0))
        tk.Label(box, text="Manoni", bg=BG, fg=FG,
                 font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(box, text="v" + APP_VERSION + "  ·  " +
                 t("a fast, simple dark photo browser and culler"),
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 9)).pack(anchor="w",
                                                              pady=(2, 0))
        tk.Label(box, text="{label}: {name} · {handle}".format(
            label=t("Author"), name=AUTHOR_NAME, handle=AUTHOR_HANDLE),
            bg=BG, fg=FG, font=("Segoe UI", 9)).pack(anchor="w", pady=(12, 0))
        tk.Label(box, text=t("Written in Python"), bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        self._set_group(p, t("Built with"))
        for name, url, lic in BUILT_WITH:
            self._set_link_row(p, name, url, lic)

        self._set_group(p, t("Links"))
        for label, url in PROJECT_LINKS:
            self._set_link_row(p, label, url)

        tk.Frame(p, bg=BG, height=16).pack()
        bmc = tk.Label(p, text=t("Buy me a coffee"), bg=BMC_BG, fg=BMC_FG,
                       font=("Segoe UI", 10, "bold"), padx=20, pady=8,
                       cursor="hand2")
        bmc.pack(anchor="w")
        bmc.bind("<Enter>", lambda e: bmc.configure(bg=BMC_BG_HOVER))
        bmc.bind("<Leave>", lambda e: bmc.configure(bg=BMC_BG))
        bmc.bind("<Button-1>", lambda e: webbrowser.open(BMC_URL))

    def _set_link_row(self, parent, label, url, lic=None):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=1)
        tk.Label(row, text=label + "  ", bg=BG, fg=FG, anchor="w",
                 font=("Segoe UI", 9)).pack(side="left")
        link = tk.Label(row, text=url, bg=BG, fg=ACCENT, cursor="hand2",
                        font=("Segoe UI", 9, "underline"))
        link.pack(side="left")
        link.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
        if lic:
            tk.Label(row, text="  (" + lic + ")", bg=BG, fg=FG_DIM,
                     font=("Segoe UI", 8)).pack(side="left")

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
        self.last_save = {"dir": "", "fmt": "JPEG", "quality": 95,
                          "keep_meta": True, "to_srgb": False}
        self._save_state()
        self._set_show_tab(self._set_active)         # repaint the open tab
        self.toast(t("Settings restored to defaults"))
