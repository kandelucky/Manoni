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

from ..config import (BG, BAR, HOVER, ACCENT, FG, FG_DIM, EDIT_PAD,
                      CHIP_BG, BORDER, DIVIDER)
from ..widgets import Tooltip
from ..i18n import t
from .. import imaging
from .dialogs import make_dialog_button, center_over


class FiltersMixin:
    # The edit factors a filter stores. These mirror _edit_state(): all are live
    # float factors except auto_mode, which is a label (or None). Listed once
    # here so load/import can validate a (possibly hand-edited) file against it.
    FILTER_KEYS = ("brightness", "contrast", "color", "temperature", "tint",
                   "highlights", "shadows", "whites", "blacks", "clarity",
                   "vibrance", "texture", "sharpen", "denoise", "dehaze",
                   "sat_red", "sat_orange", "sat_yellow", "sat_green",
                   "sat_aqua", "sat_blue", "sat_purple", "sat_magenta",
                   "gold_hue", "gold_sat", "gold_light",
                   "skin_hue", "skin_sat", "skin_light",
                   "bw", "sepia", "vignette", "grain", "split_hi", "split_sh")
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

    # --- Filter groups (organising the saved filters) -----------------------
    # A filter belongs to exactly ONE group. Group IDENTITY is stored in a
    # language-stable English form, so switching the UI language can never
    # orphan a filter; the reserved names below are translated only for DISPLAY
    # via t(). Custom group names are free text — stored and shown verbatim.
    GROUP_STANDARD = "Standard"     # the built-in looks (code-defined, never in the store)
    GROUP_MINE     = "My filters"   # default home for filters the user creates
    GROUP_OTHERS   = "Others"       # default home for imported filters with no group
    RESERVED_GROUPS = (GROUP_STANDARD, GROUP_MINE, GROUP_OTHERS)

    # --- Filter store (persisted to FILTERS_FILE) ---------------------------

    def _load_filters(self):
        "Read the saved filters + groups from FILTERS_FILE (migrating older files)."
        from ..config import FILTERS_FILE
        self.user_filters = []
        self.filter_groups = []           # [{"name", "collapsed"}] — user/custom only
        self._standard_collapsed = False  # the built-in 'Standard' group's fold state
        try:
            with open(FILTERS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
        if data is not None:
            for it in self._coerce_filter_list(data):
                # On the user's OWN store a group-less filter (a v1 file) is
                # theirs → home it in 'My filters'.
                it["group"] = it["group"] or self.GROUP_MINE
                self.user_filters.append(it)
            self._load_groups(data)
            if isinstance(data, dict):
                self._standard_collapsed = bool(data.get("standard_collapsed"))
        self._normalize_groups()

    def _load_groups(self, data):
        "Restore the saved group order + fold state (strings or {name,collapsed})."
        raw = data.get("groups") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return
        for g in raw:
            if isinstance(g, str):
                name, collapsed = g.strip(), False
            elif isinstance(g, dict):
                name = str(g.get("name") or "").strip()
                collapsed = bool(g.get("collapsed"))
            else:
                continue
            if name and name != self.GROUP_STANDARD and not self._group(name):
                self.filter_groups.append({"name": name, "collapsed": collapsed})

    def _save_filters(self):
        "Write the filters + group order / fold state back to FILTERS_FILE (v2)."
        from ..config import FILTERS_FILE
        from ..storage import save_json
        ok = save_json(FILTERS_FILE, {"manoni_filters": 2,
                                      "groups": self.filter_groups,
                                      "standard_collapsed": self._standard_collapsed,
                                      "filters": self.user_filters})
        if not ok:
            self.toast(t("Could not save filters"))

    def _coerce_filter_list(self, data):
        "Accept one filter object or a {filters:[…]} bundle → clean list. Each item"
        " is {name, group, values}; group is the stored group name, or None if absent."
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
                grp = str(it.get("group") or "").strip() or None
                out.append({"name": name, "group": grp, "values": vals})
        return out

    # --- Group bookkeeping (order, defaults, fold state) --------------------

    def _group(self, name):
        "The stored group dict with this name, or None."
        for g in self.filter_groups:
            if g["name"] == name:
                return g
        return None

    def _normalize_groups(self):
        "Keep the group list consistent: every filter's group exists, 'My filters'"
        " is present and first, auto 'Others' sits last and only while it is used,"
        " no duplicates."
        used = {fl["group"] for fl in self.user_filters}
        # Any group a filter references but the list is missing → add it.
        for name in used:
            if name != self.GROUP_STANDARD and not self._group(name):
                self.filter_groups.append({"name": name, "collapsed": False})
        # 'Others' is automatic: keep it only while some filter lives there.
        self.filter_groups = [g for g in self.filter_groups
                              if g["name"] != self.GROUP_OTHERS
                              or self.GROUP_OTHERS in used]
        # 'My filters' always exists — it is the default home for new filters.
        if not self._group(self.GROUP_MINE):
            self.filter_groups.insert(0, {"name": self.GROUP_MINE,
                                          "collapsed": False})
        # Display order: My filters first, custom groups in between, Others last.
        mine   = [g for g in self.filter_groups if g["name"] == self.GROUP_MINE]
        others = [g for g in self.filter_groups if g["name"] == self.GROUP_OTHERS]
        custom = [g for g in self.filter_groups
                  if g["name"] not in (self.GROUP_MINE, self.GROUP_OTHERS)]
        self.filter_groups = mine + custom + others

    def _group_collapsed(self, gid):
        "Whether a group (built-in 'Standard' or a user group) is folded."
        if gid == self.GROUP_STANDARD:
            return self._standard_collapsed
        g = self._group(gid)
        return bool(g and g["collapsed"])

    def _set_group_collapsed(self, gid, value):
        "Set a group's fold state and persist it (shared by strip + manager)."
        if gid == self.GROUP_STANDARD:
            self._standard_collapsed = value
        else:
            g = self._group(gid)
            if g is None:
                return
            g["collapsed"] = value
        self._save_filters()

    def _unique_group_name(self, base):
        "A group name not already taken and not a reserved name."
        base = (base or "").strip() or t("Group")
        taken = {g["name"] for g in self.filter_groups} | set(self.RESERVED_GROUPS)
        if base not in taken:
            return base
        i = 2
        while f"{base} {i}" in taken:
            i += 1
        return f"{base} {i}"

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

        tk.Frame(f, bg=DIVIDER, height=1).pack(fill="x", padx=EDIT_PAD,
                                                 pady=(8, 8))

        self._filter_action(f, "folder-input", t("Import"),
                            self._filter_import,
                            t("Load filters from a .json file"))
        self._filter_action(f, "share-2",      t("Export"),
                            self._filter_export,
                            t("Save filters to a .json file to share"))

        tk.Frame(f, bg=DIVIDER, height=1).pack(fill="x", padx=EDIT_PAD,
                                                 pady=(8, 6))
        self._build_filter_list(f)

        self._refresh_filter_count()
        return f

    def _filter_action(self, parent, icon_name, label, command, tip):
        "One full-width filled action button (icon left, label) for the manager."
        NORMAL = CHIP_BG
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

    # --- The grouped filter list (vertical, inside the manager panel) -------
    # A scrollable, name-only list of EVERY filter, split into foldable groups
    # ('Standard' built-ins + the user's groups) — the same groups as the
    # horizontal preview strip, but browsable without the canvas filmstrip.
    # Clicking a name applies that look; clicking a caption folds the group
    # (the fold state is the SAME as the strip's, so they stay in sync).

    def _build_filter_list(self, parent):
        "Scaffold the scrollable grouped list; rows are filled by _refresh_filter_list."
        tk.Label(parent, text=t("All filters"), bg=BAR, fg=FG_DIM, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=EDIT_PAD,
                                                     pady=(0, 4))
        wrap = tk.Frame(parent, bg=BAR)
        wrap.pack(fill="both", expand=True, padx=(EDIT_PAD, 0), pady=(0, 8))

        canvas = tk.Canvas(wrap, bg=BAR, highlightthickness=0)
        sb = self._make_scrollbar(wrap, canvas)
        holder = tk.Frame(canvas, bg=BAR)
        win = canvas.create_window((0, 0), window=holder, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def on_body(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win, width=canvas.winfo_width())
        holder.bind("<Configure>", on_body)
        canvas.bind("<Configure>", on_body)
        canvas.bind("<MouseWheel>", self._flist_wheel)

        self.filter_list_canvas = canvas
        self.filter_list_holder = holder
        self._filter_list_rows = []     # [{frame,label,vals,active}] for the repaint
        self._refresh_filter_list()

    def _flist_wheel(self, e):
        "Vertical wheel scroll for the grouped filter list."
        self.filter_list_canvas.yview_scroll(int(-e.delta / 120), "units")

    def _refresh_filter_list(self):
        "Rebuild the grouped list: 'Standard' built-ins first, then each non-empty"
        " user group, every group under a foldable caption."
        if not hasattr(self, "filter_list_holder"):
            return
        holder = self.filter_list_holder
        for w in holder.winfo_children():
            w.destroy()
        self._filter_list_rows = []
        for grp in self._strip_groups():
            self._add_flist_group(holder, grp)
        self.filter_list_canvas.yview_moveto(0.0)
        self.filter_list_canvas.configure(
            scrollregion=self.filter_list_canvas.bbox("all"))

    def _add_flist_group(self, parent, grp):
        "A foldable caption (chevron + name + count); when open, its filter rows."
        header = tk.Frame(parent, bg=BAR, cursor="hand2")
        header.pack(fill="x", pady=(6, 0))
        parts = [header]
        chev = self.icon("chevron-right" if grp["collapsed"] else "chevron-down",
                         size=12)
        if chev is not None:
            ic = tk.Label(header, image=chev, bg=BAR)
            ic.pack(side="left", padx=(2, 4))
            parts.append(ic)
        tx = tk.Label(header, text=f"{grp['label']}  ({len(grp['items'])})",
                      bg=BAR, fg=FG_DIM, anchor="w", font=("Segoe UI", 8, "bold"))
        tx.pack(side="left", fill="x", expand=True, pady=4)
        parts.append(tx)
        for w in parts:
            w.bind("<Button-1>", lambda e, gid=grp["id"]: self._toggle_group(gid))
            w.bind("<Enter>", lambda e: tx.configure(fg=FG))
            w.bind("<Leave>", lambda e: tx.configure(fg=FG_DIM))
            w.bind("<MouseWheel>", self._flist_wheel)
        if not grp["collapsed"]:
            for label, vals in grp["items"]:
                self._add_flist_row(parent, label, vals)

    def _add_flist_row(self, parent, label, vals):
        "One filter row: an indented name; click applies the look onto the photo."
        active = self._filter_active(vals)
        row = tk.Frame(parent, bg=BAR, cursor="hand2")
        row.pack(fill="x")
        tx = tk.Label(row, text=label, bg=BAR, fg=ACCENT if active else FG,
                      anchor="w", font=("Segoe UI", 9))
        tx.pack(side="left", fill="x", expand=True, padx=(26, 6), pady=4)

        cell = {"frame": row, "label": tx, "vals": vals, "active": active}
        self._filter_list_rows.append(cell)
        parts = (row, tx)

        def enter(_e=None):
            if not cell["active"]:
                for w in parts:
                    w.configure(bg=HOVER)

        def leave(_e=None):
            if not cell["active"]:
                for w in parts:
                    w.configure(bg=BAR)
        for w in parts:
            w.bind("<Button-1>", lambda e, v=vals: self._apply_filter_values(v))
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
            w.bind("<MouseWheel>", self._flist_wheel)
        return row

    # --- The filter preview strip (horizontal, below the editor) ------------
    # A live filmstrip under the preview: each saved filter is rendered onto a
    # small copy of the CURRENT photo, so the look is visible before it is
    # applied. Clicking a cell plays that filter's factors onto the open photo
    # as one undoable step. The whole strip hides itself while there are no
    # saved filters or no photo open, so non-filter users never see it.

    FILTER_THUMB_W = 68       # logical px: the cell image's width budget
    FILTER_THUMB_H = 50       # logical px: the cell image's height budget
    FSTRIP_BORDER  = BORDER  # idle cell border (accent when that look is active)

    def _build_filter_strip(self, body):
        "Scaffold the strip (row 1, col 2). Cells are filled by _refresh_filter_strip."
        strip = tk.Frame(body, bg=BAR)
        strip.grid(row=1, column=2, sticky="ew")
        strip.grid_propagate(False)
        strip.configure(height=round((self.FILTER_THUMB_H + 40) * self.dpi))
        # A 1px divider on top so the strip reads as a band below the canvas.
        tk.Frame(strip, bg=DIVIDER, height=1).pack(side="top", fill="x")
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
        "Rebuild the strip for the current photo: 'Original', then each non-empty"
        " group ('Standard' built-ins + the user's groups) under a foldable caption."
        # The vertical panel list shares the store + fold state, so keep it in
        # sync from the same call (it needs no photo, so refresh it first).
        self._refresh_filter_list()
        if not hasattr(self, "filter_strip"):
            return
        # Turned off in Settings → keep the filmstrip hidden regardless of photo.
        if not getattr(self, "show_filter_strip", True):
            self.filter_strip.grid_remove()
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
        # "Original" is pinned first: a neutral reference and a one-click way to
        # drop the look. Then one labelled section per group; a collapsed group
        # shows just its caption (its cells are skipped to save the row width).
        self._add_filter_cell(holder, t("Original"), {})
        for grp in self._strip_groups():
            self._add_strip_separator(holder)
            self._add_group_caption(holder, grp)
            if not grp["collapsed"]:
                for label, vals in grp["items"]:
                    self._add_filter_cell(holder, label, vals)
        self.filter_strip.grid()
        self.filter_strip_canvas.xview_moveto(0.0)
        self.filter_strip_canvas.configure(
            scrollregion=self.filter_strip_canvas.bbox("all"))

    def _strip_groups(self):
        "Ordered groups for the strip: 'Standard' (built-ins) first, then every"
        " user group that has filters. Each is {id,label,collapsed,items}; items"
        " is a list of (cell_label, values). Empty user groups stay hidden here."
        groups = [{"id": self.GROUP_STANDARD,
                   "label": self._group_display(self.GROUP_STANDARD),
                   "collapsed": self._standard_collapsed,
                   "items": [(t(n), v) for n, v in self.BUILTIN_FILTERS]}]
        for g in self.filter_groups:
            items = [(fl["name"], fl["values"]) for fl in self.user_filters
                     if fl["group"] == g["name"]]
            if not items:
                continue
            groups.append({"id": g["name"],
                           "label": self._group_display(g["name"]),
                           "collapsed": g["collapsed"], "items": items})
        return groups

    def _group_display(self, name):
        "A group's shown name: reserved names translate, custom names stay verbatim."
        return t(name) if name in self.RESERVED_GROUPS else name

    def _add_strip_separator(self, parent):
        "A thin vertical divider that sets one strip group off from the next."
        sep = tk.Frame(parent, bg=DIVIDER, width=1)
        sep.pack(side="left", fill="y", padx=(8, 0), pady=10)
        sep.bind("<MouseWheel>", lambda e: self.filter_strip_canvas.xview_scroll(
            int(-e.delta / 120), "units"))
        return sep

    def _add_group_caption(self, parent, grp):
        "A clickable caption (chevron + group name) that folds / unfolds the group."
        frame = tk.Frame(parent, bg=BAR, cursor="hand2")
        frame.pack(side="left", padx=(6, 2))     # pack centres it vertically
        img = self.icon("chevron-right" if grp["collapsed"] else "chevron-down",
                        size=12)
        parts = [frame]
        if img is not None:
            ic = tk.Label(frame, image=img, bg=BAR)
            ic.pack(side="left", padx=(0, 3))
            parts.append(ic)
        tx = tk.Label(frame, text=grp["label"], bg=BAR, fg=FG_DIM,
                      font=("Segoe UI", 8, "bold"))
        tx.pack(side="left")
        parts.append(tx)
        for w in parts:
            w.bind("<Button-1>", lambda e, gid=grp["id"]: self._toggle_group(gid))
            w.bind("<Enter>", lambda e: tx.configure(fg=FG))
            w.bind("<Leave>", lambda e: tx.configure(fg=FG_DIM))
            w.bind("<MouseWheel>", lambda e: self.filter_strip_canvas.xview_scroll(
                int(-e.delta / 120), "units"))
        return frame

    def _toggle_group(self, gid):
        "Fold / unfold a strip group (built-in 'Standard' or a user group); persist."
        self._set_group_collapsed(gid, not self._group_collapsed(gid))
        self._refresh_filter_strip()

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
        # Mirror the active look onto the vertical panel list (name in accent).
        for cell in getattr(self, "_filter_list_rows", []):
            active = self._filter_active(cell["vals"])
            cell["active"] = active
            bg = BAR
            cell["frame"].configure(bg=bg)
            cell["label"].configure(bg=bg, fg=ACCENT if active else FG)

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
        # New filters land in 'My filters' by default; the manager moves them.
        self.user_filters.append({"name": name,
                                  "group": self.GROUP_MINE,
                                  "values": self._sanitize_filter_values(
                                      self._edit_state())})
        self._save_filters()
        self._refresh_filter_count()
        self._refresh_filter_strip()
        self.toast(t("Filter saved: {name}").format(name=name))

    # --- Edit (rename / refresh / delete) -----------------------------------

    def _filter_edit(self):
        "Open the grouped manager (collapsible groups; … menu on each group/filter)."
        self._open_filter_manager()

    def _open_filter_manager(self):
        "The modeless grouped manager. Modeless so the user can still nudge the"
        " sliders (e.g. before 'Refresh from current edit') with it open."
        existing = getattr(self, "_fmgr_dlg", None)
        if existing is not None and existing.winfo_exists():
            existing.lift(); existing.focus_force(); return
        dlg, body = self._filter_dialog(t("Edit filters"))
        self._fmgr_dlg = dlg

        def redraw():
            self._close_filter_popup()
            for w in body.winfo_children():
                w.destroy()
            # Top action: start a new (empty) group.
            self._filter_action_plain(body, "folder-plus", t("New group"),
                                      lambda: self._do_new_group(redraw))
            tk.Frame(body, bg=DIVIDER, height=1).pack(fill="x", pady=(6, 2))
            # 'Standard' (built-ins, read-only) first, then the user's groups.
            self._manager_group(body, self.GROUP_STANDARD, redraw)
            for g in list(self.filter_groups):
                self._manager_group(body, g["name"], redraw)

        redraw()
        self._place_modeless(dlg)

    def _manager_group(self, parent, name, redraw):
        "One group section: a foldable header (with a … menu) + its filter rows."
        builtin = (name == self.GROUP_STANDARD)
        collapsed = self._group_collapsed(name)
        if builtin:
            rows = [(t(n), None) for n, _ in self.BUILTIN_FILTERS]
        else:
            rows = [(fl["name"], fl) for fl in self.user_filters
                    if fl["group"] == name]

        header = tk.Frame(parent, bg=BAR, cursor="hand2")
        header.pack(fill="x", pady=(8, 0))
        # The … menu sits at the right; pack it first so the title can expand.
        self._kebab(header, lambda anc, gn=name: self._group_menu(anc, gn, redraw))
        chev = self.icon("chevron-right" if collapsed else "chevron-down", size=13)
        hcells = [header]
        if chev is not None:
            ic = tk.Label(header, image=chev, bg=BAR)
            ic.pack(side="left", padx=(8, 4))
            hcells.append(ic)
        title = tk.Label(header,
                         text=f"{self._group_display(name)}  ({len(rows)})",
                         bg=BAR, fg=FG, anchor="w", font=("Segoe UI", 9, "bold"))
        title.pack(side="left", fill="x", expand=True, pady=6)
        hcells.append(title)
        for w in hcells:
            w.bind("<Button-1>", lambda e, gn=name: self._manager_toggle(gn, redraw))

        if collapsed:
            return
        if not rows:
            tk.Label(parent, text=t("No filters in this group"), bg=BAR,
                     fg=FG_DIM, font=("Segoe UI", 8), anchor="w") \
                .pack(fill="x", padx=(32, 8), pady=(1, 1))
            return
        for label, fl in rows:
            self._manager_filter_row(parent, label, fl, redraw, builtin)

    def _manager_toggle(self, name, redraw):
        "Fold / unfold a group from the manager (keeps the strip in sync)."
        self._set_group_collapsed(name, not self._group_collapsed(name))
        self._refresh_filter_strip()
        redraw()

    def _manager_filter_row(self, parent, label, fl, redraw, builtin):
        "One filter row inside a group: indented name + (user filters) a … menu."
        row = tk.Frame(parent, bg=BAR)
        row.pack(fill="x")
        if not builtin:
            self._kebab(row, lambda anc, f=fl: self._filter_menu(anc, f, redraw))
        tk.Label(row, text=label, bg=BAR, fg=FG if not builtin else FG_DIM,
                 anchor="w", font=("Segoe UI", 9)).pack(
            side="left", fill="x", expand=True, padx=(32, 6), pady=5)

    def _kebab(self, parent, open_menu):
        "A small '…' button on the right of a row that opens its popup menu."
        img = self.icon("ellipsis", size=15)
        if img is not None:
            b = tk.Label(parent, image=img, bg=BAR, cursor="hand2")
        else:
            b = tk.Label(parent, text="⋯", bg=BAR, fg=FG, cursor="hand2",
                         font=("Segoe UI", 12, "bold"))
        b.pack(side="right", padx=(0, 8))
        b.bind("<Enter>", lambda e: b.configure(bg=HOVER))
        b.bind("<Leave>", lambda e: b.configure(bg=BAR))
        b.bind("<Button-1>", lambda e, w=b: open_menu(w))
        return b

    # --- The … menus (group / filter / move) --------------------------------

    def _group_menu(self, anchor, name, redraw):
        "The … menu for a group. Reserved groups expose Export only."
        export = ("share-2", t("Export group"), lambda: self._export_group(name))
        if name in self.RESERVED_GROUPS:
            specs = [export]
        else:
            specs = [("pencil", t("Rename group"),
                      lambda: self._do_rename_group(name, redraw)),
                     export, ("sep",),
                     ("trash-2", t("Delete group"),
                      lambda: self._do_delete_group(name, redraw))]
        self._popup_menu(anchor, specs)

    def _filter_menu(self, anchor, fl, redraw):
        "The … menu for one user filter: rename / move / refresh / delete."
        self._popup_menu(anchor, [
            ("pencil", t("Rename"), lambda: self._do_rename_filter(fl, redraw)),
            ("move", t("Move to group"), lambda: self._move_menu(anchor, fl, redraw)),
            ("refresh-cw", t("Refresh from current edit"),
             lambda: self._do_refresh_filter(fl)),
            ("sep",),
            ("trash-2", t("Delete"), lambda: self._do_delete_filter(fl, redraw)),
        ])

    def _move_menu(self, anchor, fl, redraw):
        "A second popup: the groups this filter can move into (+ a new group)."
        specs = []
        for g in self.filter_groups:
            if g["name"] == fl["group"]:
                continue
            specs.append((None, self._group_display(g["name"]),
                          lambda gn=g["name"]: self._do_move_filter(fl, gn, redraw)))
        if specs:
            specs.append(("sep",))
        specs.append(("folder-plus", t("New group…"),
                      lambda: self._do_move_to_new_group(fl, redraw)))
        self._popup_menu(anchor, specs)

    # --- Group / filter operations (called from the menus) ------------------

    def _do_new_group(self, redraw):
        name = self._ask_text(t("New group"), t("Group name"))
        if not name:
            return
        self.filter_groups.append({"name": self._unique_group_name(name),
                                   "collapsed": False})
        self._normalize_groups()
        self._save_filters()
        self._refresh_filter_strip()
        redraw()

    def _do_rename_group(self, name, redraw):
        g = self._group(name)
        if g is None:
            return
        new = self._ask_text(t("Rename group"), t("Group name"), name)
        if not new or new == name:
            return
        new = self._unique_group_name(new)
        for fl in self.user_filters:
            if fl["group"] == name:
                fl["group"] = new
        g["name"] = new
        self._save_filters()
        self._refresh_filter_strip()
        redraw()

    def _do_delete_group(self, name, redraw):
        members = [fl for fl in self.user_filters if fl["group"] == name]
        if not self._confirm(
                t("Delete the group “{name}” and its {n} filter(s)?").format(
                    name=name, n=len(members)), ok_label=t("Delete")):
            return
        self.user_filters = [fl for fl in self.user_filters
                             if fl["group"] != name]
        self.filter_groups = [g for g in self.filter_groups
                              if g["name"] != name]
        self._normalize_groups()
        self._save_filters()
        self._refresh_filter_count()
        self._refresh_filter_strip()
        redraw()

    def _export_group(self, name):
        "Export every filter in a group (built-ins for 'Standard') to a file."
        if name == self.GROUP_STANDARD:
            filters = [{"name": n, "group": self.GROUP_STANDARD, "values": dict(v)}
                       for n, v in self.BUILTIN_FILTERS]
        else:
            filters = [fl for fl in self.user_filters if fl["group"] == name]
        if not filters:
            self.toast(t("No filters in this group"))
            return
        self._export_filters(filters)

    def _do_rename_filter(self, fl, redraw):
        new = self._ask_text(t("Rename"), t("Filter name"), fl["name"])
        if new and new != fl["name"]:
            fl["name"] = self._unique_filter_name(new)
            self._save_filters()
            self._refresh_filter_strip()
            redraw()

    def _do_refresh_filter(self, fl):
        fl["values"] = self._sanitize_filter_values(self._edit_state())
        self._save_filters()
        self._refresh_filter_strip()
        self.toast(t("Filter refreshed: {name}").format(name=fl["name"]))

    def _do_delete_filter(self, fl, redraw):
        if fl in self.user_filters:
            self.user_filters.remove(fl)
        self._normalize_groups()
        self._save_filters()
        self._refresh_filter_count()
        self._refresh_filter_strip()
        redraw()

    def _do_move_filter(self, fl, group_name, redraw):
        fl["group"] = group_name
        self._normalize_groups()
        self._save_filters()
        self._refresh_filter_strip()
        redraw()

    def _do_move_to_new_group(self, fl, redraw):
        name = self._ask_text(t("New group"), t("Group name"))
        if not name:
            return
        name = self._unique_group_name(name)
        self.filter_groups.append({"name": name, "collapsed": False})
        fl["group"] = name
        self._normalize_groups()
        self._save_filters()
        self._refresh_filter_strip()
        redraw()

    # --- Popup menu + confirm + modeless placement --------------------------

    def _popup_menu(self, anchor, specs):
        "A borderless dark dropdown under `anchor`. Each spec is ('sep',) or"
        " (icon_name|None, label, command). Closes on pick / Escape / focus-out."
        self._close_filter_popup()
        pop = tk.Toplevel(self.root)
        pop.overrideredirect(True)
        pop.configure(bg=BORDER)          # 1px hairline border via the inset
        self._filter_popup = pop
        inner = tk.Frame(pop, bg=BAR)
        inner.pack(padx=1, pady=1)

        def add_row(icon_name, label, command):
            r = tk.Frame(inner, bg=BAR, cursor="hand2")
            r.pack(fill="x")
            cells = [r]
            if icon_name:
                img = self.icon(icon_name, size=14)
                if img is not None:
                    ic = tk.Label(r, image=img, bg=BAR)
                    ic.pack(side="left", padx=(10, 8), pady=6)
                    cells.append(ic)
            lab = tk.Label(r, text=label, bg=BAR, fg=FG, anchor="w",
                           font=("Segoe UI", 9))
            lab.pack(side="left", padx=((0 if icon_name else 12), 18), pady=6)
            cells.append(lab)
            for w in cells:
                w.bind("<Enter>", lambda e: [c.configure(bg=HOVER) for c in cells])
                w.bind("<Leave>", lambda e: [c.configure(bg=BAR) for c in cells])
                w.bind("<Button-1>",
                       lambda e, c=command: (self._close_filter_popup(), c()))

        for spec in specs:
            if spec[0] == "sep":
                tk.Frame(inner, bg=BORDER, height=1).pack(fill="x")
            else:
                add_row(*spec)

        pop.update_idletasks()
        x = anchor.winfo_rootx() + anchor.winfo_width() - pop.winfo_width()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 2
        pop.geometry(f"+{max(0, x)}+{y}")
        pop.bind("<Escape>", lambda e: self._close_filter_popup())
        pop.bind("<FocusOut>", lambda e: self._close_filter_popup())
        pop.focus_force()                    # so clicking elsewhere closes it

    def _close_filter_popup(self):
        "Tear down the open … popup, if any."
        pop = getattr(self, "_filter_popup", None)
        if pop is not None:
            self._filter_popup = None
            try:
                pop.destroy()
            except tk.TclError:
                pass

    def _confirm(self, message, ok_label=None):
        "A small modal yes/no over the main window. Returns True if confirmed."
        result = {"ok": False}
        dlg = tk.Toplevel(self.root)
        dlg.title(t("Please confirm"))
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = tk.Frame(dlg, bg=BG, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=message, bg=BG, fg=FG, anchor="w", justify="left",
                 wraplength=self._edit_dpi_w(280),
                 font=("Segoe UI", 10)).pack(anchor="w")

        def ok():
            result["ok"] = True
            dlg.destroy()
        btnrow = tk.Frame(wrap, bg=BG)
        btnrow.pack(anchor="e", pady=(16, 0))
        self._dialog_btn(btnrow, t("Cancel"), dlg.destroy).pack(side="right",
                                                                  padx=(8, 0))
        self._dialog_btn(btnrow, ok_label or t("OK"), ok,
                         primary=True).pack(side="right")
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: ok())
        self._place_filter_dialog(dlg)
        return result["ok"]

    def _place_modeless(self, dlg):
        "Center a NON-modal dialog over the main window (no grab / no wait)."
        dlg.update_idletasks()
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        dlg.geometry(f"+{max(0, rx + (rw - dw) // 2)}+{max(0, ry + (rh - dh) // 2)}")
        dlg.lift()
        dlg.focus_force()

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
                # Keep the group the file carries; a group-less import → 'Others'.
                fl["group"] = fl["group"] or self.GROUP_OTHERS
                self.user_filters.append(fl)
                added += 1
        if added:
            self._normalize_groups()       # surface any new group ('Others' etc.)
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
            tk.Frame(body, bg=DIVIDER, height=1).pack(fill="x", pady=(6, 6))

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
        return self._ask_text(title, t("Filter name"), default)

    def _ask_text(self, title, label, default=""):
        "Modal dark text prompt (title + a labelled field). Trimmed text or None."
        result = {"val": None}
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=BG, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=label, bg=BG, fg=FG,
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
        "Shared flat dialog button (see ui/dialogs.py); kept as a thin alias "
        "because it's called as self._dialog_btn across several mixins."
        return make_dialog_button(parent, text, command, primary)

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
        center_over(self.root, dlg)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.grab_set()
        dlg.focus_set()
        self.root.wait_window(dlg)
