"""Filters: a manager for user-made presets (saved slider/effect values).

A "filter" here is NOT a baked colour table — it is a named snapshot of the
edit factors (temperature, contrast, vignette, …). Creating one captures the
current sliders; applying one (from the horizontal strip below the editor)
just plays those factors back onto the open photo.

Two parts live here. The MANAGER panel (in the edit panel's "filters" section)
offers four actions: create (from the current edit), edit (rename / refresh /
delete), import and export — it never lists the filters as clickable looks. The
clickable looks are the PREVIEW STRIP (_build_filter_strip): a horizontal
filmstrip under the preview that renders each saved filter onto a thumbnail of
the current photo, so a click applies the look you can already see.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import json
import tkinter as tk
import tkinter.filedialog as tkfd

from PIL import Image, ImageTk

from ..config import BG, BAR, HOVER, ACCENT, FG, FG_DIM, EDIT_PAD
from ..widgets import Tooltip
from ..i18n import t
from .. import imaging


class FiltersMixin:
    # The edit factors a filter stores. These mirror _edit_state(): all are live
    # float factors except auto_mode, which is a label (or None). Listed once
    # here so load/import can validate a (possibly hand-edited) file against it.
    FILTER_KEYS = ("brightness", "contrast", "color", "temperature", "tint",
                   "highlights", "shadows", "whites", "blacks", "clarity",
                   "vibrance", "texture", "sharpen", "bw", "sepia", "vignette")
    AUTO_MODES = (None, "levels", "contrast")

    # Standard built-in filters: a palette of popular looks shipped with the app.
    # Unlike user filters these are defined in code (not the JSON store), so they
    # are always present, the same on every install, and are NOT listed in the
    # manager (no rename / delete) — a starting point the user can apply, then
    # tweak and re-save as their own. Only the NON-neutral factors are listed;
    # any key left out falls back to its neutral value when applied. Names go
    # through t() in the strip, so the descriptive ones translate. Tuned against
    # the real pipeline in imaging.py (temperature k≈±0.3, tone push ±70, etc.).
    BUILTIN_FILTERS = (
        ("Clarendon", {"brightness": 1.06, "contrast": 1.18, "color": 1.12,
                       "vibrance": 1.22, "temperature": 0.94, "clarity": 1.12,
                       "blacks": 0.96}),
        ("Vivid", {"contrast": 1.24, "clarity": 1.38, "vibrance": 1.32,
                   "color": 1.1, "texture": 1.15, "whites": 1.08,
                   "blacks": 0.9, "vignette": 1.08}),
        ("Warm", {"temperature": 1.34, "brightness": 1.05, "vibrance": 1.16,
                  "shadows": 1.1, "contrast": 1.04, "tint": 1.05,
                  "highlights": 0.97}),
        ("Cool", {"temperature": 0.78, "contrast": 1.14, "color": 0.96,
                  "vibrance": 1.1, "shadows": 1.08, "blacks": 0.92,
                  "vignette": 1.16}),
        ("Vintage", {"contrast": 0.9, "color": 0.85, "temperature": 1.28,
                     "blacks": 1.18, "shadows": 1.1, "highlights": 0.95,
                     "clarity": 0.95, "vignette": 1.12}),
        ("Matte", {"contrast": 0.88, "blacks": 1.22, "shadows": 1.05,
                   "highlights": 0.95, "color": 0.92, "clarity": 0.96}),
        ("Mono", {"bw": 1.0, "contrast": 1.22, "clarity": 1.2,
                  "whites": 1.05, "blacks": 0.94}),
        ("Sepia", {"sepia": 0.85, "contrast": 0.96, "brightness": 1.03,
                   "clarity": 0.95, "vignette": 1.14}),
    )

    # --- Filter store (persisted to FILTERS_FILE) ---------------------------

    def _load_filters(self):
        "Read the saved filters from FILTERS_FILE into self.user_filters."
        from ..config import FILTERS_FILE
        self.user_filters = []
        try:
            with open(FILTERS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        for it in self._coerce_filter_list(data):
            self.user_filters.append(it)

    def _save_filters(self):
        "Write self.user_filters back to FILTERS_FILE (best effort)."
        from ..config import FILTERS_FILE
        try:
            with open(FILTERS_FILE, "w", encoding="utf-8") as f:
                json.dump({"manoni_filters": 1, "filters": self.user_filters},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _coerce_filter_list(self, data):
        "Accept either one filter object or a {filters:[…]} bundle → clean list."
        raw = []
        if isinstance(data, dict) and isinstance(data.get("filters"), list):
            raw = data["filters"]
        elif isinstance(data, list):
            raw = data
        elif isinstance(data, dict) and "values" in data:
            raw = [data]                      # a single exported filter object
        out = []
        for it in raw:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            vals = self._sanitize_filter_values(it.get("values"))
            if name and vals:
                out.append({"name": name, "values": vals})
        return out

    def _sanitize_filter_values(self, vals):
        "Keep only known factors (coerced to float) + a valid auto_mode."
        if not isinstance(vals, dict):
            return None
        clean = {}
        for k in self.FILTER_KEYS:
            if k in vals:
                try:
                    clean[k] = float(vals[k])
                except (TypeError, ValueError):
                    pass
        am = vals.get("auto_mode")
        clean["auto_mode"] = am if am in self.AUTO_MODES else None
        return clean

    def _unique_filter_name(self, base):
        "A name not already taken: 'Name', then 'Name 2', 'Name 3', …"
        names = {fl["name"] for fl in self.user_filters}
        if base not in names:
            return base
        i = 2
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    # --- The manager panel (shown in the edit panel's "filters" section) ----

    def _build_filters_section(self, parent):
        "Filter MANAGER: create / edit / import / export. No filter list here."
        f = tk.Frame(parent, bg=BAR)

        tk.Label(f, text=t("Save the current edit as a filter, or add ready-made filters from a file."),
                 bg=BAR, fg=FG_DIM, anchor="w", justify="left",
                 font=("Segoe UI", 8), wraplength=self._edit_dpi_w(210)) \
            .pack(fill="x", padx=EDIT_PAD, pady=(12, 2))

        self.lbl_filter_count = tk.Label(f, text="", bg=BAR, fg=FG, anchor="w",
                                         font=("Segoe UI", 8, "bold"))
        self.lbl_filter_count.pack(fill="x", padx=EDIT_PAD, pady=(2, 8))

        self._filter_action(f, "plus",         t("Create filter"),
                            self._filter_create,
                            t("Saves the current slider values as a filter"))
        self._filter_action(f, "pencil",       t("Edit"),
                            self._filter_edit,
                            t("Rename / refresh / delete saved filters"))

        tk.Frame(f, bg="#333333", height=1).pack(fill="x", padx=EDIT_PAD,
                                                 pady=(8, 8))

        self._filter_action(f, "folder-input", t("Import"),
                            self._filter_import,
                            t("Load filters from a .json file"))
        self._filter_action(f, "share-2",      t("Export"),
                            self._filter_export,
                            t("Save filters to a .json file to share"))

        self._refresh_filter_count()
        return f

    def _filter_action(self, parent, icon_name, label, command, tip):
        "One full-width filled action button (icon left, label) for the manager."
        NORMAL = "#2f2f2f"
        btn = tk.Frame(parent, bg=NORMAL, cursor="hand2")
        btn.pack(fill="x", padx=EDIT_PAD, pady=3)
        inner = tk.Frame(btn, bg=NORMAL)
        inner.pack(side="left", padx=12, pady=8)
        parts = [btn, inner]
        img = self.icon(icon_name, size=16)
        if img is not None:
            ic = tk.Label(inner, image=img, bg=NORMAL)
            ic.pack(side="left", padx=(0, 8))
            parts.append(ic)
        tx = tk.Label(inner, text=label, bg=NORMAL, fg=FG,
                      font=("Segoe UI", 9, "bold"))
        tx.pack(side="left")
        parts.append(tx)
        for w in parts:
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: [p.configure(bg=HOVER) for p in parts])
            w.bind("<Leave>", lambda e: [p.configure(bg=NORMAL) for p in parts])
        btn._tip = Tooltip(btn, tip)
        return btn

    def _refresh_filter_count(self):
        "Repaint the 'saved: N' caption from the current store."
        if not hasattr(self, "lbl_filter_count"):
            return
        n = len(getattr(self, "user_filters", []))
        self.lbl_filter_count.configure(
            text=t("Saved filters: {n}").format(n=n))

    # --- The filter preview strip (horizontal, below the editor) ------------
    # A live filmstrip under the preview: each saved filter is rendered onto a
    # small copy of the CURRENT photo, so the look is visible before it is
    # applied. Clicking a cell plays that filter's factors onto the open photo
    # as one undoable step. The whole strip hides itself while there are no
    # saved filters or no photo open, so non-filter users never see it.

    FILTER_THUMB_W = 68       # logical px: the cell image's width budget
    FILTER_THUMB_H = 50       # logical px: the cell image's height budget
    FSTRIP_BORDER  = "#3a3a3a"  # idle cell border (accent when that look is active)

    def _build_filter_strip(self, body):
        "Scaffold the strip (row 1, col 2). Cells are filled by _refresh_filter_strip."
        strip = tk.Frame(body, bg=BAR)
        strip.grid(row=1, column=2, sticky="ew")
        strip.grid_propagate(False)
        strip.configure(height=round((self.FILTER_THUMB_H + 40) * self.dpi))
        # A 1px divider on top so the strip reads as a band below the canvas.
        tk.Frame(strip, bg="#333333", height=1).pack(side="top", fill="x")
        self.filter_strip = strip

        # Horizontal scroll area: a canvas holding a left-packed row of cells.
        canvas = tk.Canvas(strip, bg=BAR, highlightthickness=0,
                           height=round((self.FILTER_THUMB_H + 34) * self.dpi))
        canvas.pack(side="top", fill="both", expand=True)
        holder = tk.Frame(canvas, bg=BAR)
        canvas.create_window((0, 0), window=holder, anchor="nw")
        holder.bind("<Configure>",
                    lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        # The wheel scrolls the strip along its natural (horizontal) axis.
        for w in (canvas, holder):
            w.bind("<MouseWheel>",
                   lambda e: canvas.xview_scroll(int(-e.delta / 120), "units"))
        self.filter_strip_canvas = canvas
        self.filter_strip_holder = holder
        self._filter_cells = []        # one dict per cell (for the active repaint)
        self._filter_thumb_imgs = []   # PhotoImages kept alive
        self._fstrip_base = None       # cached small RGB copy of the current photo
        self._fstrip_base_key = None   # id(current_pil) the base was built from

        strip.grid_remove()            # hidden until there are filters + a photo

    def _refresh_filter_strip(self):
        "Rebuild every cell for the current photo + saved filters (or hide the strip)."
        if not hasattr(self, "filter_strip"):
            return
        # Built-in filters are always present, so the strip shows whenever a photo
        # is open (base is None only when nothing is loaded).
        base = self._filter_thumb_base()
        if base is None:
            self.filter_strip.grid_remove()
            return
        holder = self.filter_strip_holder
        for w in holder.winfo_children():
            w.destroy()
        self._filter_cells = []
        self._filter_thumb_imgs = []
        # "Original" first: a neutral reference and a one-click way to drop the
        # look. Then the standard built-in looks, then the user's saved filters.
        self._add_filter_cell(holder, t("Original"), {})
        for name, vals in self.BUILTIN_FILTERS:
            self._add_filter_cell(holder, t(name), vals)
        for fl in self.user_filters:
            self._add_filter_cell(holder, fl["name"], fl["values"])
        self.filter_strip.grid()
        self.filter_strip_canvas.xview_moveto(0.0)
        self.filter_strip_canvas.configure(
            scrollregion=self.filter_strip_canvas.bbox("all"))

    def _filter_thumb_base(self):
        "A small RGB copy of the current photo, cached by photo identity (or None)."
        if self.current_pil is None:
            return None
        key = id(self.current_pil)
        if self._fstrip_base_key == key and self._fstrip_base is not None:
            return self._fstrip_base
        box = (round(self.FILTER_THUMB_W * self.dpi),
               round(self.FILTER_THUMB_H * self.dpi))
        im = self.current_pil.convert("RGB").copy()
        im.thumbnail(box, Image.LANCZOS)
        self._fstrip_base = im
        self._fstrip_base_key = key
        return im

    def _filter_thumb_image(self, base, vals):
        "Render the base photo through one filter's factors → a PhotoImage."
        fields = {k: float(vals[k]) for k in self.FILTER_KEYS if k in vals}
        e = imaging.Edits(**fields)
        auto = vals.get("auto_mode")
        auto_luts = (imaging.autocontrast_luts(base, auto == "levels")
                     if auto in ("levels", "contrast") else None)
        return ImageTk.PhotoImage(imaging.apply_edits(base, e, auto_luts=auto_luts))

    def _add_filter_cell(self, parent, label, vals):
        "One filmstrip cell: the filtered thumbnail + its name; click applies the look."
        photo = self._filter_thumb_image(self._fstrip_base, vals)
        self._filter_thumb_imgs.append(photo)
        active = self._filter_active(vals)
        frame = tk.Frame(parent, bg=ACCENT if active else self.FSTRIP_BORDER,
                         cursor="hand2")
        frame.pack(side="left", padx=(8, 0), pady=7)
        inner = tk.Frame(frame, bg=BAR)
        inner.pack(padx=2, pady=2)
        pic = tk.Label(inner, image=photo, bg=BAR)
        pic.pack()
        name = tk.Label(inner, text=label, bg=BAR, fg=ACCENT if active else FG_DIM,
                        font=("Segoe UI", 8), anchor="center")
        name.pack(fill="x", pady=(2, 1))

        cell = {"frame": frame, "name": name, "vals": vals, "active": active}
        self._filter_cells.append(cell)
        parts = (frame, inner, pic, name)

        def enter(_e=None):
            if not cell["active"]:
                frame.configure(bg=HOVER)
                name.configure(fg=FG)

        def leave(_e=None):
            if not cell["active"]:
                frame.configure(bg=self.FSTRIP_BORDER)
                name.configure(fg=FG_DIM)
        for w in parts:
            w.bind("<Button-1>", lambda e, v=vals: self._apply_filter_values(v))
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
            w.bind("<MouseWheel>",
                   lambda e: self.filter_strip_canvas.xview_scroll(
                       int(-e.delta / 120), "units"))
        tip = (t("Remove the filter (show the original)") if not vals
               else t("Apply filter: {name}").format(name=label))
        frame._tip = Tooltip(frame, tip)
        return frame

    def _filter_active(self, vals):
        "True when the live edit factors equal this filter's values (the applied look)."
        cur = self._edit_state()
        for k in self.FILTER_KEYS:
            target = float(vals.get(k, self._slider_neutral(k)))
            if abs(float(cur.get(k, self._slider_neutral(k))) - target) > 1e-6:
                return False
        return (cur.get("auto_mode") or None) == (vals.get("auto_mode") or None)

    def _repaint_filter_strip(self):
        "Recolor cells so the filter matching the live edit (if any) reads as active."
        for cell in getattr(self, "_filter_cells", []):
            active = self._filter_active(cell["vals"])
            cell["active"] = active
            cell["frame"].configure(bg=ACCENT if active else self.FSTRIP_BORDER)
            cell["name"].configure(fg=ACCENT if active else FG_DIM)

    def _apply_filter_values(self, vals):
        "Play a filter's factors (FILTER_KEYS + auto mode) onto the photo, undoably."
        if self.current_pil is None:
            return
        before = self._edit_state()
        for k in self.FILTER_KEYS:
            v = float(vals.get(k, self._slider_neutral(k)))
            setattr(self, k, v)
            s = self.sliders.get(k)
            if s is not None:
                s.set(round(v * 100))
        auto = vals.get("auto_mode")
        self.auto_mode = auto if auto in self.AUTO_MODES else None
        self._recompute_auto()
        self._refresh_auto_buttons()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)
        self._repaint_filter_strip()

    # --- Create -------------------------------------------------------------

    def _filter_create(self):
        "Save the current edit factors as a new named filter."
        default = self._unique_filter_name(t("My filter"))
        name = self._ask_filter_name(t("New filter"), default)
        if name is None:
            return
        name = self._unique_filter_name(name)
        self.user_filters.append({"name": name,
                                  "values": self._sanitize_filter_values(
                                      self._edit_state())})
        self._save_filters()
        self._refresh_filter_count()
        self._refresh_filter_strip()
        self.toast(t("Filter saved: {name}").format(name=name))

    # --- Edit (rename / refresh / delete) -----------------------------------

    def _filter_edit(self):
        "Open the manage dialog: rename, refresh-from-current, or delete filters."
        if not self.user_filters:
            self.toast(t("No filters saved yet"))
            return
        self._open_filter_manager()

    def _open_filter_manager(self):
        dlg, body = self._filter_dialog(t("Edit filters"))

        def redraw():
            for w in body.winfo_children():
                w.destroy()
            if not self.user_filters:
                tk.Label(body, text=t("No filters left"), bg=BG, fg=FG_DIM,
                         font=("Segoe UI", 9)).pack(pady=20)
                return
            for fl in list(self.user_filters):
                self._manager_row(body, fl, redraw)

        redraw()
        self._place_filter_dialog(dlg)

    def _manager_row(self, parent, fl, redraw):
        "One row in the manage dialog: name + rename / refresh / delete icons."
        row = tk.Frame(parent, bg=BAR)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=fl["name"], bg=BAR, fg=FG, anchor="w",
                 font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True,
                                            padx=(10, 6), pady=6)

        def rename():
            new = self._ask_filter_name(t("Rename"), fl["name"])
            if new and new != fl["name"]:
                fl["name"] = self._unique_filter_name(new)
                self._save_filters()
                self._refresh_filter_count()
                self._refresh_filter_strip()
                redraw()

        def refresh():
            fl["values"] = self._sanitize_filter_values(self._edit_state())
            self._save_filters()
            self._refresh_filter_strip()
            self.toast(t("Filter refreshed: {name}").format(name=fl["name"]))

        def delete():
            self.user_filters.remove(fl)
            self._save_filters()
            self._refresh_filter_count()
            self._refresh_filter_strip()
            redraw()

        self._row_icon(row, "pencil",     rename,
                       t("Rename"))
        self._row_icon(row, "refresh-cw", refresh,
                       t("Refresh from current edit"))
        self._row_icon(row, "trash-2",    delete, t("Delete"))

    def _row_icon(self, parent, icon_name, command, tip):
        "A small hover-highlighted icon button inside a dialog row."
        img = self.icon(icon_name, size=15)
        if img is not None:
            b = tk.Label(parent, image=img, bg=BAR, cursor="hand2")
        else:
            b = tk.Label(parent, text="•", bg=BAR, fg=FG_DIM, cursor="hand2")
        b.pack(side="right", padx=(0, 8))
        b.bind("<Enter>", lambda e: b.configure(bg=HOVER))
        b.bind("<Leave>", lambda e: b.configure(bg=BAR))
        b.bind("<Button-1>", lambda e: command())
        b._tip = Tooltip(b, tip)
        return b

    # --- Import / Export ----------------------------------------------------

    def _filter_import(self):
        "Load filters from one or more .json files into the store."
        paths = tkfd.askopenfilenames(
            parent=self.root, title=t("Import filters"),
            filetypes=[(t("Filter file"), "*.json"), (t("All files"), "*.*")])
        if not paths:
            return
        added = 0
        for p in paths:
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            for fl in self._coerce_filter_list(data):
                fl["name"] = self._unique_filter_name(fl["name"])
                self.user_filters.append(fl)
                added += 1
        if added:
            self._save_filters()
            self._refresh_filter_count()
            self._refresh_filter_strip()
            self.toast(t("Added {n} filter(s)").format(n=added))
        else:
            self.toast(t("No filters found in the file"))

    def _filter_export(self):
        "Pick a filter to export, or export all into one file."
        if not self.user_filters:
            self.toast(t("No filters saved yet"))
            return
        dlg, body = self._filter_dialog(t("Export filters"))

        if len(self.user_filters) > 1:
            self._filter_action_plain(
                body, "folder-output", t("All in one file"),
                lambda: (self._export_filters(self.user_filters), dlg.destroy()))
            tk.Frame(body, bg="#333333", height=1).pack(fill="x", pady=(6, 6))

        for fl in self.user_filters:
            self._filter_action_plain(
                body, "share-2", fl["name"],
                lambda f=fl: (self._export_filters([f]), dlg.destroy()))

        self._place_filter_dialog(dlg)

    def _export_filters(self, filters):
        "Write the given filters to a .json file the user chooses."
        if len(filters) == 1:
            default = filters[0]["name"] + ".json"
        else:
            default = "manoni-filters.json"
        path = tkfd.asksaveasfilename(
            parent=self.root, title=t("Save filters"),
            defaultextension=".json", initialfile=default,
            filetypes=[(t("Filter file"), "*.json")])
        if not path:
            return
        if len(filters) == 1:
            payload = {"manoni_filter": 1, **filters[0]}
        else:
            payload = {"manoni_filters": 1, "filters": filters}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self.toast(t("Exported {n} filter(s)").format(n=len(filters)))
        except Exception:
            self.toast(t("Could not write the file"))

    def _filter_action_plain(self, parent, icon_name, label, command):
        "A flat full-width row (icon + label) used inside the export dialog."
        row = tk.Frame(parent, bg=BAR, cursor="hand2")
        row.pack(fill="x", pady=2)
        parts = [row]
        img = self.icon(icon_name, size=15)
        if img is not None:
            ic = tk.Label(row, image=img, bg=BAR)
            ic.pack(side="left", padx=(10, 8), pady=7)
            parts.append(ic)
        tx = tk.Label(row, text=label, bg=BAR, fg=FG, anchor="w",
                      font=("Segoe UI", 9))
        tx.pack(side="left", fill="x", expand=True, pady=7)
        parts.append(tx)
        for w in parts:
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: [p.configure(bg=HOVER) for p in parts])
            w.bind("<Leave>", lambda e: [p.configure(bg=BAR) for p in parts])
        return row

    # --- Shared dialog helpers ----------------------------------------------

    def _ask_filter_name(self, title, default=""):
        "Modal dark prompt for a filter name. Returns the trimmed text or None."
        result = {"val": None}
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=BG, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=t("Filter name"), bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))

        e = tk.Entry(wrap, bg=BAR, fg=FG, insertbackground=FG, width=24,
                     relief="flat", font=("Segoe UI", 11))
        e.insert(0, default)
        e.pack(anchor="w", ipady=5, fill="x")

        def confirm():
            txt = e.get().strip()
            if txt:
                result["val"] = txt
            dlg.destroy()

        btnrow = tk.Frame(wrap, bg=BG)
        btnrow.pack(anchor="e", pady=(16, 0))
        self._dialog_btn(btnrow, t("Cancel"), dlg.destroy).pack(side="right",
                                                                  padx=(8, 0))
        self._dialog_btn(btnrow, t("Save"), confirm,
                         primary=True).pack(side="right")

        dlg.bind("<Return>", lambda e: confirm())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        e.focus_set()
        e.select_range(0, "end")
        self._place_filter_dialog(dlg)
        return result["val"]

    def _dialog_btn(self, parent, text, command, primary=False):
        "A small dialog button (accent if primary), matching the crop dialog."
        bg = ACCENT if primary else BAR
        hov = "#5ab0ff" if primary else HOVER
        b = tk.Label(parent, text=text, bg=bg, fg="#0b0b0b" if primary else FG,
                     cursor="hand2", padx=14, pady=7,
                     font=("Segoe UI", 9, "bold" if primary else "normal"))
        b.bind("<Enter>", lambda e: b.configure(bg=hov))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        b.bind("<Button-1>", lambda e: command())
        return b

    def _filter_dialog(self, title):
        "A modal dark dialog with a scrollable body. Returns (dialog, body frame)."
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=BG, padx=16, pady=14)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=title, bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 10))

        # A fixed-height scroll area so a long list can't grow past the screen.
        canvas = tk.Canvas(wrap, bg=BAR, highlightthickness=0,
                           width=self._edit_dpi_w(300), height=self._edit_dpi_w(260))
        sb = self._make_scrollbar(wrap, canvas)
        body = tk.Frame(canvas, bg=BAR)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y", padx=(4, 0))

        def on_body(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win, width=canvas.winfo_width())
        body.bind("<Configure>", on_body)
        canvas.bind("<Configure>", on_body)

        self._dialog_btn(wrap, t("Close"), dlg.destroy).pack(anchor="e",
                                                               pady=(12, 0))
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        return dlg, body

    def _make_scrollbar(self, parent, canvas):
        "The themed slim scrollbar (falls back to a plain one) bound to a canvas."
        import tkinter.ttk as ttk
        try:
            sb = ttk.Scrollbar(parent, orient="vertical",
                               style="Sidebar.Vertical.TScrollbar",
                               command=canvas.yview)
        except tk.TclError:
            sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        return sb

    def _place_filter_dialog(self, dlg):
        "Center a dialog over the main window, then make it modal."
        dlg.update_idletasks()
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        dlg.geometry(f"+{max(0, rx + (rw - dw) // 2)}+{max(0, ry + (rh - dh) // 2)}")
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.grab_set()
        dlg.focus_set()
        self.root.wait_window(dlg)
