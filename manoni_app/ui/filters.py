"""Filters: a manager for user-made presets (saved slider/effect values).

A "filter" here is NOT a baked colour table — it is a named snapshot of the
edit factors (temperature, contrast, vignette, …). Creating one captures the
current sliders; applying one (later, from the horizontal strip below the
editor) just plays those factors back onto the open photo.

This panel is the MANAGER only — it never lists the filters as clickable looks.
It offers four actions: create (from the current edit), edit (rename / refresh
/ delete), import and export. The clickable filter strip lives elsewhere.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import json
import tkinter as tk
import tkinter.filedialog as tkfd

from ..config import BG, BAR, HOVER, ACCENT, FG, FG_DIM, EDIT_PAD
from ..widgets import Tooltip
from ..i18n import t


class FiltersMixin:
    # The edit factors a filter stores. These mirror _edit_state(): all are live
    # float factors except auto_mode, which is a label (or None). Listed once
    # here so load/import can validate a (possibly hand-edited) file against it.
    FILTER_KEYS = ("brightness", "contrast", "color", "temperature", "tint",
                   "highlights", "shadows", "whites", "blacks", "clarity",
                   "vibrance", "texture", "sharpen", "bw", "sepia", "vignette")
    AUTO_MODES = (None, "levels", "contrast")

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

        tk.Label(f, text=t("შენ შეგიძლია მიმდინარე ედიტი ფილტრად შეინახო, "
                           "ან მზა ფილტრები ფაილიდან ჩამოამატო."),
                 bg=BAR, fg=FG_DIM, anchor="w", justify="left",
                 font=("Segoe UI", 8), wraplength=self._edit_dpi_w(210)) \
            .pack(fill="x", padx=EDIT_PAD, pady=(12, 2))

        self.lbl_filter_count = tk.Label(f, text="", bg=BAR, fg=FG, anchor="w",
                                         font=("Segoe UI", 8, "bold"))
        self.lbl_filter_count.pack(fill="x", padx=EDIT_PAD, pady=(2, 8))

        self._filter_action(f, "plus",         t("ფილტრის შექმნა"),
                            self._filter_create,
                            t("მიმდინარე სლაიდერების მნიშვნელობებს ფილტრად შეინახავს"))
        self._filter_action(f, "pencil",       t("რედაქტირება"),
                            self._filter_edit,
                            t("შენახული ფილტრების გადარქმევა / განახლება / წაშლა"))

        tk.Frame(f, bg="#333333", height=1).pack(fill="x", padx=EDIT_PAD,
                                                 pady=(8, 8))

        self._filter_action(f, "folder-input", t("იმპორტი"),
                            self._filter_import,
                            t("ფილტრების ჩამოტვირთვა .json ფაილიდან"))
        self._filter_action(f, "share-2",      t("ექსპორტი"),
                            self._filter_export,
                            t("ფილტრების შენახვა .json ფაილში გასაზიარებლად"))

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
            text=t("შენახული ფილტრები: {n}").format(n=n))

    # --- Create -------------------------------------------------------------

    def _filter_create(self):
        "Save the current edit factors as a new named filter."
        default = self._unique_filter_name(t("ჩემი ფილტრი"))
        name = self._ask_filter_name(t("ახალი ფილტრი"), default)
        if name is None:
            return
        name = self._unique_filter_name(name)
        self.user_filters.append({"name": name,
                                  "values": self._sanitize_filter_values(
                                      self._edit_state())})
        self._save_filters()
        self._refresh_filter_count()
        self.toast(t("ფილტრი შენახულია: {name}").format(name=name))

    # --- Edit (rename / refresh / delete) -----------------------------------

    def _filter_edit(self):
        "Open the manage dialog: rename, refresh-from-current, or delete filters."
        if not self.user_filters:
            self.toast(t("ჯერ ფილტრი არ შენახულა"))
            return
        self._open_filter_manager()

    def _open_filter_manager(self):
        dlg, body = self._filter_dialog(t("ფილტრების რედაქტირება"))

        def redraw():
            for w in body.winfo_children():
                w.destroy()
            if not self.user_filters:
                tk.Label(body, text=t("ფილტრები აღარ არის"), bg=BG, fg=FG_DIM,
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
            new = self._ask_filter_name(t("გადარქმევა"), fl["name"])
            if new and new != fl["name"]:
                fl["name"] = self._unique_filter_name(new)
                self._save_filters()
                self._refresh_filter_count()
                redraw()

        def refresh():
            fl["values"] = self._sanitize_filter_values(self._edit_state())
            self._save_filters()
            self.toast(t("ფილტრი განახლდა: {name}").format(name=fl["name"]))

        def delete():
            self.user_filters.remove(fl)
            self._save_filters()
            self._refresh_filter_count()
            redraw()

        self._row_icon(row, "pencil",     rename,
                       t("სახელის გადარქმევა"))
        self._row_icon(row, "refresh-cw", refresh,
                       t("მიმდინარე ედიტით განახლება"))
        self._row_icon(row, "trash-2",    delete, t("წაშლა"))

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
            parent=self.root, title=t("ფილტრების იმპორტი"),
            filetypes=[(t("ფილტრის ფაილი"), "*.json"), (t("ყველა ფაილი"), "*.*")])
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
            self.toast(t("დაიმატა {n} ფილტრი").format(n=added))
        else:
            self.toast(t("ფაილში ფილტრები ვერ მოიძებნა"))

    def _filter_export(self):
        "Pick a filter to export, or export all into one file."
        if not self.user_filters:
            self.toast(t("ჯერ ფილტრი არ შენახულა"))
            return
        dlg, body = self._filter_dialog(t("ფილტრების ექსპორტი"))

        if len(self.user_filters) > 1:
            self._filter_action_plain(
                body, "folder-output", t("ყველას ერთ ფაილში"),
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
            parent=self.root, title=t("ფილტრების შენახვა"),
            defaultextension=".json", initialfile=default,
            filetypes=[(t("ფილტრის ფაილი"), "*.json")])
        if not path:
            return
        if len(filters) == 1:
            payload = {"manoni_filter": 1, **filters[0]}
        else:
            payload = {"manoni_filters": 1, "filters": filters}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self.toast(t("ექსპორტი დასრულდა: {n} ფილტრი").format(n=len(filters)))
        except Exception:
            self.toast(t("ფაილის ჩაწერა ვერ მოხერხდა"))

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
        tk.Label(wrap, text=t("ფილტრის სახელი"), bg=BG, fg=FG,
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
        self._dialog_btn(btnrow, t("გაუქმება"), dlg.destroy).pack(side="right",
                                                                  padx=(8, 0))
        self._dialog_btn(btnrow, t("შენახვა"), confirm,
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

        self._dialog_btn(wrap, t("დახურვა"), dlg.destroy).pack(anchor="e",
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
