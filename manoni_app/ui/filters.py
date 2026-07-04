"""Filters: a manager for user-made presets (saved slider/effect values).

A "filter" here is NOT a baked colour table — it is a named snapshot of the
edit factors (temperature, contrast, vignette, …). Creating one captures the
current sliders; applying one just plays those factors back onto the open
photo (replacing whatever was on the sliders, not blending with it).

Two parts live here. The MANAGER panel (in the edit panel's "filters" section)
is a full-width Import button pinned above the grouped "All filters" list
(Lasha found the old small header icon too easy to miss, 2026-07-04), then the
list itself: each group/filter row is clickable (applies the look) and carries
a … menu (rename / move / delete / export-group, plus Move up/down for a
custom group) and, for a filter, a grip to drag-reorder it within its group.
Create + Undo (undo a run of filter-trying, back to whatever
was there before) live in a PINNED FOOTER (_build_filters_footer) — built once
in editpanel._build_edit_panel, outside the scrolling section content, so they
stay reachable no matter how long the list grows; shown only while the filters
tool is open, Undo only once a filter-trying run is live. The PREVIEW STRIP
(_build_filter_strip) is a second, optional way to browse: a horizontal
filmstrip under the preview that renders each saved filter onto a fixed
showcase image (Filter_Show.jpg), so a filter's look reads the same whatever
photo is open (toggled in Settings; the manager's list works with or without
it).

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import json
import tkinter as tk
import tkinter.filedialog as tkfd
import tkinter.font as tkfont

from PIL import Image, ImageTk

import tintkit

# Colours now come from self.theme (dark<->light). The persistent panel + strip
# scaffolding uses chrome's `_tw`; the heavily-rebuilt rows/cells read the live
# theme at build time and are rebuilt on a switch (via _refresh_filter_strip,
# subscribed). Only EDIT_PAD (a layout inset, not a colour) stays a config const.
from ..config import EDIT_PAD, FILTER_SHOW_IMG
from ..widgets import Tooltip
from ..i18n import t
from .. import imaging
from .dialogs import center_over


class FiltersMixin:
    # The edit factors a filter stores. These mirror _edit_state(): all are live
    # float factors except auto_mode, which is a label (or None). Listed once
    # here so load/import can validate a (possibly hand-edited) file against it.
    FILTER_KEYS = ("brightness", "exposure_g", "contrast", "color", "temperature", "tint",
                   "highlights", "shadows", "whites", "blacks", "clarity",
                   "vibrance", "texture", "sharpen", "denoise", "dehaze",
                   "sat_red", "sat_orange", "sat_yellow", "sat_green",
                   "sat_aqua", "sat_blue", "sat_purple", "sat_magenta",
                   "gold_hue", "gold_sat", "gold_light",
                   "skin_hue", "skin_sat", "skin_light",
                   "bw", "sepia", "vignette", "grain", "split_hi", "split_sh")
    AUTO_MODES = (None, "levels", "contrast", "tone")

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
        "Filter MANAGER: the pinned Import button + clickable grouped list (see"
        " _build_filter_list). Create / Undo live in the panel's pinned filters"
        " footer (_build_filters_footer)."
        f = self._tw(tk.Frame(parent), bg="bar")
        self._build_filter_list(f)
        return f

    # --- The pinned filters footer (Create / Undo) --------------------------
    # Unlike the per-tool footers other tools build inline at the bottom of
    # their own section (Done/Remove — see focus.py, perspective.py), the
    # filters list can grow arbitrarily long, so its actions can't live at the
    # bottom of the scrolling content — they'd scroll out of reach. This footer
    # instead sits OUTSIDE the scroll canvas, pinned directly above the panel's
    # universal Save/Restore footer (same trick as editpanel._build_panel_actions),
    # built once in editpanel._build_edit_panel and shown only while the filters
    # tool is open (see editpanel.set_section / _enter_filters).

    def _build_filters_footer(self, panel):
        "Scaffold the pinned Create/Undo row; hidden until the filters tool opens."
        wrap = self._tw(tk.Frame(panel), bg="bar")
        # before=_sec_host: same trick as the universal footer (_build_panel_actions)
        # — without it, the scroll canvas's fill=both/expand=True claims the cavity
        # before this footer gets a slice, and it never shows.
        wrap.pack(side="bottom", fill="x", before=self._sec_host)
        self._tw(tk.Frame(wrap, height=1), bg="divider").pack(side="top", fill="x")
        row = self._tw(tk.Frame(wrap), bg="bar")
        row.pack(fill="x", padx=EDIT_PAD, pady=8)
        self._filters_footer, self._filters_footer_row = wrap, row

        self._filters_create_btn = tintkit.Button(
            row, self.theme, t("Create filter"), role="primary", variant="filled",
            icon="plus", stretch=True, bg="bar", command=self._filter_create)
        tintkit.HoverTip(self._filters_create_btn.canvas, self.theme,
                         t("Saves the current slider values as a filter"))

        # "Undo filter", not "Remove filter" — this only undoes a filter TRY,
        # it never touches the saved list, and "Remove" read like the list's
        # own Delete to Lasha (2026-07-04). Icon is 'x' per the footer-secondary
        # standard (rotate-ccw is reserved for the per-slider reset).
        self._filters_undo_btn = tintkit.Button(
            row, self.theme, t("Undo filter"), role="neutral", variant="outline",
            icon="x", stretch=True, bg="bar", command=self._filter_remove)
        tintkit.HoverTip(self._filters_undo_btn.canvas, self.theme,
                         t("Undoes whatever filter(s) you've tried, back to"
                           " before the first one"))

        self._layout_filters_footer()
        wrap.pack_forget()
        return wrap

    def _layout_filters_footer(self):
        "Show Undo next to Create only while a filter-trying run is live."
        if not hasattr(self, "_filters_create_btn"):
            return
        self._filters_create_btn.canvas.pack_forget()
        self._filters_undo_btn.canvas.pack_forget()
        if getattr(self, "_filter_anchor", None) is not None:
            self._filters_create_btn.pack(side="left", fill="x", expand=True,
                                          padx=(0, 6))
            self._filters_undo_btn.pack(side="left", fill="x", expand=True)
        else:
            self._filters_create_btn.pack(fill="x")

    def _enter_filters(self):
        "Open the filters tool: show the pinned footer, then repaint normally."
        self._filters_footer.pack(side="bottom", fill="x", before=self._sec_host)
        self._layout_filters_footer()
        self.preview.configure(cursor="")
        self._render_preview()

    def _filter_action(self, parent, icon_name, label, command, tip):
        "One full-width filled action button (icon left, label) for the manager."
        btn = self._tw(tk.Frame(parent, cursor="hand2"), bg="chip")
        btn.pack(fill="x", padx=EDIT_PAD, pady=3)
        inner = self._tw(tk.Frame(btn), bg="chip")
        inner.pack(side="left", padx=12, pady=8)
        parts = [btn, inner]
        img = self.icon(icon_name, size=16)
        if img is not None:
            ic = self._tw(tk.Label(inner, image=img), bg="chip")
            ic.pack(side="left", padx=(0, 8))
            parts.append(ic)
        tx = self._tw(tk.Label(inner, text=label, font=("Segoe UI", 9, "bold")),
                      bg="chip", fg="fg")
        tx.pack(side="left")
        parts.append(tx)
        for w in parts:
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>",
                   lambda e: [p.configure(bg=self.theme["hover"]) for p in parts])
            w.bind("<Leave>",
                   lambda e: [p.configure(bg=self.theme["chip"]) for p in parts])
        btn._tip = Tooltip(btn, tip)
        return btn

    # --- The grouped filter list (vertical, inside the manager panel) -------
    # A scrollable, name-only list of EVERY filter, split into foldable groups
    # ('Standard' built-ins + the user's groups) — the same groups as the
    # horizontal preview strip, but browsable without the canvas filmstrip.
    # Clicking a name applies that look; clicking a caption folds the group
    # (the fold state is the SAME as the strip's, so they stay in sync).

    def _build_filter_list(self, parent):
        "Scaffold the grouped list (scrolls with the rest of the section, like the"
        " Actions list); rows (+ the header) are filled by _refresh_filter_list."
        " A pinned full-width Import button sits above it — Lasha found the old"
        " small header icon too easy to miss (2026-07-04)."
        self._filter_action(parent, "folder-input", t("Import filters"),
                            self._filter_import,
                            t("Load filters from a .json file"))
        holder = self._tw(tk.Frame(parent), bg="bar")
        holder.pack(fill="x", padx=(EDIT_PAD, 0), pady=(12, 8))

        self.filter_list_holder = holder
        self._filter_list_rows = []     # [{frame,label,vals,active}] for the repaint
        self._drag = None               # active grip-drag, if any (see _drag_start)
        self._refresh_filter_list()

    def _refresh_filter_list(self):
        "Rebuild the grouped list: a header (running total + Import), then"
        " 'Standard' built-ins, then each non-empty user group, every group"
        " under a foldable caption."
        if not hasattr(self, "filter_list_holder"):
            return
        holder = self.filter_list_holder
        for w in holder.winfo_children():
            w.destroy()
        self._filter_list_rows = []
        self._filter_rows_by_group = {} # group name -> [{key,widget}], per-group band
        self._filter_list_thumbs = []   # row preview PhotoImages, kept alive
        self._add_flist_header(holder)
        if getattr(self, "_last_filter", None) is not None:
            self._add_last_row(holder)     # the pinned session slot, above all groups
        for grp in self._strip_groups():
            self._add_flist_group(holder, grp)

    def _add_flist_header(self, parent):
        "The list's own caption: just the running total (Import is the pinned"
        " full-width button above the list — see _build_filter_list)."
        bar, fg_dim = self.theme["bar"], self.theme["fg_dim"]
        total = len(self.user_filters) + len(self.BUILTIN_FILTERS)
        row = tk.Frame(parent, bg=bar)
        row.pack(fill="x", pady=(0, 4))
        tk.Label(row, text=f"{t('All filters')}  ({total})", bg=bar, fg=fg_dim,
                 anchor="w", font=("Segoe UI", 8, "bold")).pack(
                     side="left", fill="x", expand=True)

    def _add_flist_group(self, parent, grp):
        "A foldable caption (chevron + name + count + … menu); when open, its rows."
        bar, fg, fg_dim = self.theme["bar"], self.theme["fg"], self.theme["fg_dim"]
        builtin = grp["id"] == self.GROUP_STANDARD
        header = tk.Frame(parent, bg=bar, cursor="hand2")
        header.pack(fill="x", pady=(6, 0))
        # The … menu sits at the right; pack it first so the title can expand.
        self._kebab(header, lambda anc, gid=grp["id"]:
                    self._group_menu(anc, gid, lambda: None),
                    icon_name="folder-cog", size=13)
        parts = [header]
        chev = self.icon("chevron-right" if grp["collapsed"] else "chevron-down",
                         size=12)
        if chev is not None:
            ic = tk.Label(header, image=chev, bg=bar)
            ic.pack(side="left", padx=(2, 4))
            parts.append(ic)
        tx = tk.Label(header, text=f"{grp['label']}  ({len(grp['items'])})",
                      bg=bar, fg=fg_dim, anchor="w", font=("Segoe UI", 8, "bold"))
        tx.pack(side="left", fill="x", expand=True, pady=4)
        parts.append(tx)
        for w in parts:
            w.bind("<Button-1>", lambda e, gid=grp["id"]: self._toggle_group(gid))
            w.bind("<Enter>", lambda e: tx.configure(fg=fg))
            w.bind("<Leave>", lambda e: tx.configure(fg=fg_dim))
        if not grp["collapsed"]:
            for label, vals in grp["items"]:
                fl = None if builtin else self._filter_by_name(label)
                self._add_flist_row(parent, label, vals, fl, grp["id"])

    def _filter_by_name(self, name):
        "The stored user filter dict with this name, or None (built-ins aren't stored)."
        for fl in self.user_filters:
            if fl["name"] == name:
                return fl
        return None

    def _add_flist_row(self, parent, label, vals, fl=None, group_id=None):
        "One filter row: a grip + a small preview + indented name (+ … menu for"
        " user filters, not built-ins); click applies the look onto the photo."
        active = self._filter_active(vals)
        bar = self.theme["bar"]
        row = tk.Frame(parent, bg=bar, cursor="hand2")
        row.pack(fill="x")
        if fl is not None:
            self._grip(row, fl, group_id)
            self._filter_rows_by_group.setdefault(group_id, []).append(
                {"key": fl, "widget": row})
            self._kebab(row, lambda anc, f=fl: self._filter_menu(anc, f, lambda: None))
        # A small square preview (Filter_Show.jpg under this filter), left of the
        # name. Built-ins have no grip, so they take a left indent that lines the
        # preview up with the grip'd rows.
        pic = None
        thumb = self._list_thumb_image(vals)
        if thumb is not None:
            self._filter_list_thumbs.append(thumb)
            pic = tk.Label(row, image=thumb, bg=bar)
            pic.pack(side="left", padx=(2 if fl is not None else 24, 6))
        tx = tk.Label(row, text=label, bg=bar,
                      fg=self.theme["accent"] if active else self.theme["fg"],
                      anchor="w", font=("Segoe UI", 9))
        name_lpad = 0 if pic is not None else (4 if fl is not None else 26)
        tx.pack(side="left", fill="x", expand=True, padx=(name_lpad, 6), pady=4)

        cell = {"frame": row, "label": tx, "vals": vals, "active": active}
        self._filter_list_rows.append(cell)
        parts = (row, tx) if pic is None else (row, pic, tx)

        def enter(_e=None):
            if not cell["active"]:
                for w in parts:
                    w.configure(bg=self.theme["hover"])

        def leave(_e=None):
            if not cell["active"]:
                for w in parts:
                    w.configure(bg=self.theme["bar"])
        for w in parts:
            w.bind("<Button-1>", lambda e, v=vals: self._apply_filter_values(v))
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
        return row

    # --- The filter preview strip (horizontal, below the editor) ------------
    # A live filmstrip under the preview: each saved filter is rendered onto a
    # small copy of the CURRENT photo, so the look is visible before it is
    # applied. Clicking a cell plays that filter's factors onto the open photo
    # as one undoable step. The whole strip hides itself while there are no
    # saved filters or no photo open, so non-filter users never see it.

    FILTER_THUMB_W = 68       # logical px: the cell image's width budget
    FILTER_THUMB_H = 50       # logical px: the cell image's height budget
    FILTER_LIST_THUMB = 30    # logical px: the panel-list row's square preview
    # Idle cell border is the theme "border" token (accent when the look is
    # active); read live in _add_filter_cell / _repaint_filter_strip.

    def _build_filter_strip(self, body):
        "Scaffold the strip (row 1, col 2). Cells are filled by _refresh_filter_strip."
        strip = self._tw(tk.Frame(body), bg="bar")
        strip.grid(row=1, column=2, sticky="ew")
        strip.grid_propagate(False)
        strip.configure(height=round((self.FILTER_THUMB_H + 40) * self.dpi))
        # A 1px divider on top so the strip reads as a band below the canvas.
        self._tw(tk.Frame(strip, height=1), bg="divider").pack(side="top", fill="x")
        self.filter_strip = strip

        # Horizontal scroll area: a canvas holding a left-packed row of cells.
        canvas = self._tw(
            tk.Canvas(strip, highlightthickness=0,
                      height=round((self.FILTER_THUMB_H + 34) * self.dpi)), bg="bar")
        canvas.pack(side="top", fill="both", expand=True)
        holder = self._tw(tk.Frame(canvas), bg="bar")
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
        # cached small RGB copy of the showcase image; keep any copy the panel
        # list already loaded (it builds before this strip scaffold).
        self._fstrip_base = getattr(self, "_fstrip_base", None)

        strip.grid_remove()            # hidden until there are filters + a photo
        # The strip + panel-list cells read the live theme at build time; rebuild
        # them (in the new scheme) on a dark<->light switch. One subscription
        # covers both, since _refresh_filter_strip also refreshes the panel list.
        self.theme.subscribe(self._refresh_filter_strip)

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
        # The strip stays photo-gated (its clicks edit the OPEN photo); the panel
        # list, already refreshed above, shows its previews with or without one.
        base = self._filter_thumb_base()
        if base is None or self.current_pil is None:
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
        lf = getattr(self, "_last_filter", None)
        if lf is not None:
            self._add_strip_separator(holder)
            self._add_filter_cell(holder, t("Last"), lf["values"])
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
        sep = tk.Frame(parent, bg=self.theme["divider"], width=1)
        sep.pack(side="left", fill="y", padx=(8, 0), pady=10)
        sep.bind("<MouseWheel>", lambda e: self.filter_strip_canvas.xview_scroll(
            int(-e.delta / 120), "units"))
        return sep

    def _add_group_caption(self, parent, grp):
        "A clickable caption (chevron + group name) that folds / unfolds the group."
        bar, fg, fg_dim = self.theme["bar"], self.theme["fg"], self.theme["fg_dim"]
        frame = tk.Frame(parent, bg=bar, cursor="hand2")
        frame.pack(side="left", padx=(6, 2))     # pack centres it vertically
        img = self.icon("chevron-right" if grp["collapsed"] else "chevron-down",
                        size=12)
        parts = [frame]
        if img is not None:
            ic = tk.Label(frame, image=img, bg=bar)
            ic.pack(side="left", padx=(0, 3))
            parts.append(ic)
        tx = tk.Label(frame, text=grp["label"], bg=bar, fg=fg_dim,
                      font=("Segoe UI", 8, "bold"))
        tx.pack(side="left")
        parts.append(tx)
        for w in parts:
            w.bind("<Button-1>", lambda e, gid=grp["id"]: self._toggle_group(gid))
            w.bind("<Enter>", lambda e: tx.configure(fg=fg))
            w.bind("<Leave>", lambda e: tx.configure(fg=fg_dim))
            w.bind("<MouseWheel>", lambda e: self.filter_strip_canvas.xview_scroll(
                int(-e.delta / 120), "units"))
        return frame

    def _toggle_group(self, gid):
        "Fold / unfold a strip group (built-in 'Standard' or a user group); persist."
        self._set_group_collapsed(gid, not self._group_collapsed(gid))
        self._refresh_filter_strip()

    def _filter_thumb_base(self):
        "A small RGB copy of the fixed showcase image (Filter_Show.jpg), cached"
        " once. None only when the image is missing/unreadable. Photo-independent"
        " so the strip AND the panel list can render previews from it."
        # getattr: the panel list is built (and first refreshed) before the strip
        # scaffold runs, so this can be called before _fstrip_base is assigned.
        if getattr(self, "_fstrip_base", None) is not None:
            return self._fstrip_base
        try:
            im = Image.open(FILTER_SHOW_IMG).convert("RGB")
        except (OSError, ValueError):
            return None
        box = (round(self.FILTER_THUMB_W * self.dpi),
               round(self.FILTER_THUMB_H * self.dpi))
        im.thumbnail(box, Image.LANCZOS)
        self._fstrip_base = im
        return im

    def _thumb_key(self, vals):
        "A hashable identity for one filter's render (its factors + auto mode),"
        " so the strip and the list reuse a single rendered image per look."
        keys = tuple(sorted((k, round(float(vals[k]), 4))
                            for k in self.FILTER_KEYS if k in vals))
        return keys + (("auto_mode", vals.get("auto_mode")),)

    def _thumb_render(self, vals):
        "The showcase base rendered through one filter (PIL, base size), cached"
        " by filter identity so the same look is never rendered twice (the base"
        " is fixed, so the cache stays valid for the whole session)."
        base = self._filter_thumb_base()
        if base is None:
            return None
        cache = self.__dict__.setdefault("_thumb_cache", {})
        key = self._thumb_key(vals)
        im = cache.get(key)
        if im is None:
            fields = {k: float(vals[k]) for k in self.FILTER_KEYS if k in vals}
            e = imaging.Edits(**fields)
            auto_luts = imaging.build_auto_luts(base, vals.get("auto_mode"))
            im = imaging.apply_edits(base, e, auto_luts=auto_luts)
            cache[key] = im
        return im

    def _filter_thumb_image(self, vals):
        "A strip cell image: the (cached) showcase render at full strip size."
        im = self._thumb_render(vals)
        return ImageTk.PhotoImage(im) if im is not None else None

    def _list_thumb_image(self, vals):
        "A panel-list row image: the same render, downscaled to a small square."
        im = self._thumb_render(vals)
        if im is None:
            return None
        s = round(self.FILTER_LIST_THUMB * self.dpi)
        small = im.copy()          # copy: thumbnail() mutates, base is shared
        small.thumbnail((s, s), Image.LANCZOS)
        return ImageTk.PhotoImage(small)

    def _strip_name_h(self):
        "Fixed pixel height for a cell's name box — one line of the strip's font."
        if getattr(self, "_strip_name_height", None) is None:
            self._strip_name_height = (self._strip_font(8).metrics("linespace")
                                       + round(4 * self.dpi))
        return self._strip_name_height

    def _strip_font(self, size):
        "A cached 'Segoe UI' Font at the given point size (for measuring names)."
        fonts = self.__dict__.setdefault("_strip_fonts", {})
        if size not in fonts:
            fonts[size] = tkfont.Font(font=("Segoe UI", size))
        return fonts[size]

    def _strip_name_fit(self, label, max_w):
        "Fit a name into max_w px: pick the largest font (8 down to a 6 floor)"
        " that holds the whole name; if it still overflows at the floor, elide"
        " the MIDDLE so head + tail stay visible. Returns (font, display_text)."
        for size in (8, 7, 6):
            if self._strip_font(size).measure(label) <= max_w:
                return ("Segoe UI", size), label
        return ("Segoe UI", 6), self._middle_elide(label, self._strip_font(6),
                                                    max_w)

    def _middle_elide(self, text, font, max_w):
        "Drop characters from the centre of `text` (keeping head + tail, joined"
        " by '...') until it fits max_w px. Falls back to '...' if nothing fits."
        ell = "..."
        if font.measure(text) <= max_w:
            return text
        n = len(text)
        # Cut a growing chunk from the middle; keep the split near-even so both
        # ends survive, favouring the tail by one char (the end matters most).
        for keep in range(n - 1, 0, -1):
            tail = (keep + 1) // 2
            head = keep - tail
            cand = text[:head] + ell + text[n - tail:]
            if font.measure(cand) <= max_w:
                return cand
        return ell

    def _add_filter_cell(self, parent, label, vals):
        "One filmstrip cell: the filtered thumbnail + its name; click applies the look."
        photo = self._filter_thumb_image(vals)
        self._filter_thumb_imgs.append(photo)
        active = self._filter_active(vals)
        bar, border = self.theme["bar"], self.theme["border"]
        frame = tk.Frame(parent, bg=self.theme["accent"] if active else border,
                         cursor="hand2")
        frame.pack(side="left", padx=(8, 0), pady=7)
        inner = tk.Frame(frame, bg=bar)
        inner.pack(padx=2, pady=2)
        pic = tk.Label(inner, image=photo, bg=bar)
        pic.pack()
        # The name lives in a box locked to the thumbnail's width, so a long
        # name can't widen the cell — every cell stays the same size. The font
        # shrinks to fit; if it still overflows at the floor, the middle is
        # elided ("My f...r 34") so both the start AND the end stay visible. The
        # full name is always on the hover tooltip.
        namebox = tk.Frame(inner, bg=bar, width=photo.width(),
                           height=self._strip_name_h())
        namebox.pack(fill="x", pady=(2, 1))
        namebox.pack_propagate(False)
        font, display = self._strip_name_fit(label, photo.width())
        name = tk.Label(namebox, text=display, bg=bar,
                        fg=self.theme["accent"] if active else self.theme["fg_dim"],
                        font=font, anchor="center")
        name.pack(fill="both", expand=True)

        cell = {"frame": frame, "name": name, "vals": vals, "active": active}
        self._filter_cells.append(cell)
        parts = (frame, inner, pic, namebox, name)

        def enter(_e=None):
            if not cell["active"]:
                frame.configure(bg=self.theme["hover"])
                name.configure(fg=self.theme["fg"])

        def leave(_e=None):
            if not cell["active"]:
                frame.configure(bg=self.theme["border"])
                name.configure(fg=self.theme["fg_dim"])
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
        accent, fg_dim = self.theme["accent"], self.theme["fg_dim"]
        border, bar, fg = self.theme["border"], self.theme["bar"], self.theme["fg"]
        for cell in getattr(self, "_filter_cells", []):
            active = self._filter_active(cell["vals"])
            cell["active"] = active
            cell["frame"].configure(bg=accent if active else border)
            cell["name"].configure(fg=accent if active else fg_dim)
        # Mirror the active look onto the vertical panel list (name in accent).
        for cell in getattr(self, "_filter_list_rows", []):
            active = self._filter_active(cell["vals"])
            cell["active"] = active
            cell["frame"].configure(bg=bar)
            cell["label"].configure(bg=bar, fg=accent if active else fg)
        self._layout_filters_footer()   # Undo shows/hides with the live anchor

    def _apply_filter_values(self, vals):
        "Play a filter's factors (FILTER_KEYS + auto mode) onto the photo, undoably."
        " The first application in a run remembers the pre-filter state, so trying"
        " several filters in a row can all be undone at once via 'Undo filter'."
        if self.current_pil is None:
            return
        before = self._edit_state()
        if self._filter_anchor is None:
            self._filter_anchor = before
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
        self._record_edit(before, is_filter=True)
        self._repaint_filter_strip()

    def _filter_remove(self):
        "Undo whatever effect trying filters had this run — back to the state from"
        " right before the first one, no matter how many were tried since."
        if self.current_pil is None or self._filter_anchor is None:
            self.toast(t("No filter to undo"))
            return
        before = self._edit_state()
        anchor = self._filter_anchor
        for k in self.FILTER_KEYS:
            v = float(anchor.get(k, self._slider_neutral(k)))
            setattr(self, k, v)
            s = self.sliders.get(k)
            if s is not None:
                s.set(round(v * 100))
        auto = anchor.get("auto_mode")
        self.auto_mode = auto if auto in self.AUTO_MODES else None
        self._recompute_auto()
        self._refresh_auto_buttons()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)      # is_filter=False → also clears the anchor
        self._repaint_filter_strip()
        self.toast(t("Filter undone"))

    # --- Create -------------------------------------------------------------

    def _filter_create(self):
        "Save the current edit factors as a new named filter, into a chosen group."
        default = self._unique_filter_name(t("My filter"))
        picked = self._ask_new_filter(t("New filter"), default)
        if picked is None:
            return
        name, group = picked
        name = self._unique_filter_name(name)
        self._last_new_filter_group = group   # remembered as next time's default
        self.user_filters.append({"name": name, "group": group,
                                  "values": self._sanitize_filter_values(
                                      self._edit_state())})
        self._save_filters()
        self._refresh_filter_strip()
        self.toast(t("Filter saved: {name}").format(name=name))

    # --- The "Last" filter (session-only slot) ------------------------------
    # After every save, the slider look that was written is remembered as a
    # single pinned "Last" slot (in the strip + panel list), so it can be
    # replayed on the next photo without first turning it into a named filter.
    # It lives only in memory (self._last_filter), so a new session starts
    # empty. A save that carried NO slider adjustment (only a crop / rotate)
    # leaves the previous slot untouched — there is nothing new worth keeping.
    # The slot's … menu can promote it into a permanent named filter, or clear it.

    def _values_neutral(self, vals):
        "True when every factor sits at its neutral rest value (no real adjustment)."
        for k in self.FILTER_KEYS:
            if abs(float(vals.get(k, self._slider_neutral(k)))
                   - self._slider_neutral(k)) > 1e-6:
                return False
        return (vals.get("auto_mode") or None) is None

    def _capture_last_filter(self):
        "Called after a successful save: remember the saved slider look as 'Last',"
        " unless the sliders were all neutral (a geometry-only save keeps the"
        " previous slot). Session-only — never written to the filters store."
        vals = self._sanitize_filter_values(self._edit_state())
        if vals is None or self._values_neutral(vals):
            return
        self._last_filter = {"values": vals}
        self._refresh_filter_strip()

    def _add_last_row(self, parent):
        "The pinned 'Last' row (session slot): the last saved photo's slider look."
        " Click applies it; the … menu saves it as a permanent filter or clears it."
        vals = self._last_filter["values"]
        active = self._filter_active(vals)
        bar = self.theme["bar"]
        row = tk.Frame(parent, bg=bar, cursor="hand2")
        row.pack(fill="x")
        self._kebab(row, lambda anc: self._last_menu(anc))
        # No grip (like the built-ins), so take their left indent to line the
        # preview up with the grip'd user rows.
        pic = None
        thumb = self._list_thumb_image(vals)
        if thumb is not None:
            self._filter_list_thumbs.append(thumb)
            pic = tk.Label(row, image=thumb, bg=bar)
            pic.pack(side="left", padx=(24, 6))
        tx = tk.Label(row, text=t("Last"), bg=bar,
                      fg=self.theme["accent"] if active else self.theme["fg"],
                      anchor="w", font=("Segoe UI", 9))
        name_lpad = 0 if pic is not None else 26
        tx.pack(side="left", fill="x", expand=True, padx=(name_lpad, 6), pady=4)

        cell = {"frame": row, "label": tx, "vals": vals, "active": active}
        self._filter_list_rows.append(cell)
        parts = (row, tx) if pic is None else (row, pic, tx)

        def enter(_e=None):
            if not cell["active"]:
                for w in parts:
                    w.configure(bg=self.theme["hover"])

        def leave(_e=None):
            if not cell["active"]:
                for w in parts:
                    w.configure(bg=self.theme["bar"])
        for w in parts:
            w.bind("<Button-1>", lambda e, v=vals: self._apply_filter_values(v))
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
        return row

    def _last_menu(self, anchor):
        "The 'Last' slot's … menu: save it permanently, or clear the session slot."
        self._popup_menu(anchor, [
            ("save", t("Save as filter…"), self._save_last_filter),
            ("sep",),
            ("x", t("Clear last filter"), self._clear_last_filter),
        ])

    def _save_last_filter(self):
        "Promote the 'Last' slot into a permanent, named filter (in a chosen group)."
        lf = getattr(self, "_last_filter", None)
        if lf is None:
            return
        default = self._unique_filter_name(t("My filter"))
        picked = self._ask_new_filter(t("New filter"), default)
        if picked is None:
            return
        name, group = picked
        name = self._unique_filter_name(name)
        self._last_new_filter_group = group
        self.user_filters.append({"name": name, "group": group,
                                  "values": dict(lf["values"])})
        self._save_filters()
        self._refresh_filter_strip()
        self.toast(t("Filter saved: {name}").format(name=name))

    def _clear_last_filter(self):
        "Drop the session 'Last' slot (it comes back on the next meaningful save)."
        self._last_filter = None
        self._refresh_filter_strip()

    def _kebab(self, parent, open_menu, icon_name="ellipsis", size=15):
        "A small '…' button on the right of a row that opens its popup menu."
        " Groups use 'folder-cog' (smaller, since it reads heavier than the plain"
        " dots) so they look distinct from filter rows."
        img = self.icon(icon_name, size=size)
        if img is not None:
            b = tk.Label(parent, image=img, bg=self.theme["bar"], cursor="hand2")
        else:
            b = tk.Label(parent, text="⋯", bg=self.theme["bar"],
                         fg=self.theme["fg"], cursor="hand2",
                         font=("Segoe UI", 12, "bold"))
        b.pack(side="right", padx=(0, 8))
        b.bind("<Enter>", lambda e: b.configure(bg=self.theme["hover"]))
        b.bind("<Leave>", lambda e: b.configure(bg=self.theme["bar"]))
        b.bind("<Button-1>", lambda e, w=b: open_menu(w))
        return b

    # --- Grip drag-to-reorder (filters only, panel list) ---------------------
    # A grip on a filter row's left drags it among its own group's filters
    # (built-ins have no grip; cross-group moves are still "Move to group").
    # Groups reorder via the … menu's Move up/down instead — a drag grip there
    # looked identical to a filter's, so the two were hard to tell apart.
    # No live reflow while dragging — just an accent drop-line — the actual move
    # (list splice + save + rebuild) happens once, on release.

    def _grip(self, parent, key, band_id):
        "A drag handle; `band_id` is the group name this filter reorders within."
        img = self.icon("grip-vertical", size=13)
        if img is not None:
            g = tk.Label(parent, image=img, bg=self.theme["bar"], cursor="fleur")
        else:
            g = tk.Label(parent, text="::", bg=self.theme["bar"],
                         fg=self.theme["fg_dim"], cursor="fleur",
                         font=("Segoe UI", 9, "bold"))
        g.pack(side="left", padx=(6, 4))
        g.bind("<ButtonPress-1>",
               lambda e, key=key, b=band_id: self._drag_start(e, key, b))
        g.bind("<B1-Motion>", self._drag_motion)
        g.bind("<ButtonRelease-1>", self._drag_release)
        return g

    def _drag_start(self, e, key, band_id):
        "Arm a drag: remember the dragged filter's band + starting index."
        band = self._filter_rows_by_group.get(band_id, [])
        idx = next((i for i, r in enumerate(band) if r["key"] is key), None)
        if idx is None or len(band) < 2:
            self._drag = None
            return
        line = tk.Frame(self.filter_list_holder, bg=self.theme["accent"], height=2)
        self._drag = {"key": key, "band_id": band_id,
                      "band": band, "start": idx, "target": idx, "line": line}

    def _drag_motion(self, _e):
        "Track the pointer; show an accent drop-line at the prospective landing."
        d = self._drag
        if d is None:
            return
        band = d["band"]
        idx = len(band)
        for i, r in enumerate(band):
            w = r["widget"]
            if _e.y_root < w.winfo_rooty() + w.winfo_height() // 2:
                idx = i
                break
        d["target"] = idx
        if idx < len(band):
            y = band[idx]["widget"].winfo_y()
        else:
            last = band[-1]["widget"]
            y = last.winfo_y() + last.winfo_height()
        d["line"].place(x=0, y=max(0, y - 1), relwidth=1.0, height=2)

    def _drag_release(self, _e):
        "Commit the reorder (if the drop landed somewhere new) and clean up."
        d = self._drag
        self._drag = None
        if d is None:
            return
        d["line"].destroy()
        start, target = d["start"], d["target"]
        if target > start:
            target -= 1      # removing the dragged row shifts later indices down
        if target == start:
            return
        self._reorder_filter(d["key"], d["band_id"], target)

    def _reorder_group(self, gid, target_idx):
        "Move a custom group to `target_idx` among the other custom groups"
        " ('My filters' stays first, 'Others' stays last)."
        reorderable = [g for g in self.filter_groups
                       if g["name"] not in self.RESERVED_GROUPS]
        moved = next(g for g in reorderable if g["name"] == gid)
        reorderable = [g for g in reorderable if g is not moved]
        reorderable.insert(target_idx, moved)
        mine = [g for g in self.filter_groups if g["name"] == self.GROUP_MINE]
        others = [g for g in self.filter_groups if g["name"] == self.GROUP_OTHERS]
        self.filter_groups = mine + reorderable + others
        self._save_filters()
        self._refresh_filter_strip()

    def _reorder_filter(self, fl, group_name, target_idx):
        "Move a filter to `target_idx` among its own group's filters."
        siblings = [f for f in self.user_filters
                    if f["group"] == group_name and f is not fl]
        others = [f for f in self.user_filters if f["group"] != group_name]
        siblings.insert(target_idx, fl)
        self.user_filters = others + siblings
        self._save_filters()
        self._refresh_filter_strip()

    # --- The … menus (group / filter / move) --------------------------------

    def _group_menu(self, anchor, name, redraw):
        "The … menu for a group. Reserved groups expose Export only; a custom"
        " group also gets Move up/down (omitted at either end of the custom band)."
        export = ("share-2", t("Export group"), lambda: self._export_group(name))
        if name in self.RESERVED_GROUPS:
            specs = [export]
        else:
            custom = [g["name"] for g in self.filter_groups
                      if g["name"] not in self.RESERVED_GROUPS]
            idx = custom.index(name)
            specs = [("pencil", t("Rename group"),
                      lambda: self._do_rename_group(name, redraw)), export]
            moves = []
            if idx > 0:
                moves.append(("chevron-up", t("Move up"),
                              lambda: self._do_move_group(name, -1, redraw)))
            if idx < len(custom) - 1:
                moves.append(("chevron-down", t("Move down"),
                              lambda: self._do_move_group(name, 1, redraw)))
            if moves:
                specs.append(("sep",))
                specs.extend(moves)
            specs.append(("sep",))
            specs.append(("trash-2", t("Delete group"),
                          lambda: self._do_delete_group(name, redraw)))
        self._popup_menu(anchor, specs)

    def _do_move_group(self, name, direction, redraw):
        "Swap a custom group with its neighbor (direction -1 up / +1 down); persist."
        custom_names = [g["name"] for g in self.filter_groups
                        if g["name"] not in self.RESERVED_GROUPS]
        idx = custom_names.index(name)
        j = idx + direction
        if not (0 <= j < len(custom_names)):
            return
        self._reorder_group(name, j)
        redraw()

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
        bar, border, fg, hover = (self.theme["bar"], self.theme["border"],
                                   self.theme["fg"], self.theme["hover"])
        pop = tk.Toplevel(self.root)
        pop.overrideredirect(True)
        pop.configure(bg=border)          # 1px hairline border via the inset
        self._filter_popup = pop
        inner = tk.Frame(pop, bg=bar)
        inner.pack(padx=1, pady=1)

        def add_row(icon_name, label, command):
            r = tk.Frame(inner, bg=bar, cursor="hand2")
            r.pack(fill="x")
            cells = [r]
            if icon_name:
                img = self.icon(icon_name, size=14)
                if img is not None:
                    ic = tk.Label(r, image=img, bg=bar)
                    ic.pack(side="left", padx=(10, 8), pady=6)
                    cells.append(ic)
            lab = tk.Label(r, text=label, bg=bar, fg=fg, anchor="w",
                           font=("Segoe UI", 9))
            lab.pack(side="left", padx=((0 if icon_name else 12), 18), pady=6)
            cells.append(lab)
            for w in cells:
                w.bind("<Enter>", lambda e: [c.configure(bg=hover) for c in cells])
                w.bind("<Leave>", lambda e: [c.configure(bg=bar) for c in cells])
                w.bind("<Button-1>",
                       lambda e, c=command: (self._close_filter_popup(), c()))

        for spec in specs:
            if spec[0] == "sep":
                tk.Frame(inner, bg=border, height=1).pack(fill="x")
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
        bg, fg = self.theme["bg"], self.theme["fg"]
        dlg = tk.Toplevel(self.root)
        dlg.title(t("Please confirm"))
        dlg.configure(bg=bg)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = tk.Frame(dlg, bg=bg, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=message, bg=bg, fg=fg, anchor="w", justify="left",
                 wraplength=self._edit_dpi_w(280),
                 font=("Segoe UI", 10)).pack(anchor="w")

        def ok():
            result["ok"] = True
            dlg.destroy()
        btnrow = tk.Frame(wrap, bg=bg)
        btnrow.pack(anchor="e", pady=(16, 0))
        self._dialog_btn(btnrow, t("Cancel"), dlg.destroy).pack(side="right",
                                                                  padx=(8, 0))
        self._dialog_btn(btnrow, ok_label or t("OK"), ok,
                         primary=True).pack(side="right")
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: ok())
        self._place_filter_dialog(dlg)
        return result["ok"]

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
            self._refresh_filter_strip()
            self.toast(t("Added {n} filter(s)").format(n=added))
        else:
            self.toast(t("No filters found in the file"))

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
        bar = self.theme["bar"]
        row = tk.Frame(parent, bg=bar, cursor="hand2")
        row.pack(fill="x", pady=2)
        parts = [row]
        img = self.icon(icon_name, size=15)
        if img is not None:
            ic = tk.Label(row, image=img, bg=bar)
            ic.pack(side="left", padx=(10, 8), pady=7)
            parts.append(ic)
        tx = tk.Label(row, text=label, bg=bar, fg=self.theme["fg"], anchor="w",
                      font=("Segoe UI", 9))
        tx.pack(side="left", fill="x", expand=True, pady=7)
        parts.append(tx)
        for w in parts:
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>",
                   lambda e: [p.configure(bg=self.theme["hover"]) for p in parts])
            w.bind("<Leave>",
                   lambda e: [p.configure(bg=self.theme["bar"]) for p in parts])
        return row

    # --- Shared dialog helpers ----------------------------------------------

    def _ask_new_filter(self, title, default_name):
        "Modal dialog for creating a filter: a name field + a group dropdown"
        " (with 'New group…' inline) — defaults to the last group a filter"
        " was created into. Returns (name, group) or None if cancelled."
        result = {"val": None}
        bg, fg, bar = self.theme["bg"], self.theme["fg"], self.theme["bar"]
        names = [g["name"] for g in self.filter_groups]   # 'Standard' excluded
        default_group = getattr(self, "_last_new_filter_group", None)
        if default_group not in names:
            default_group = self.GROUP_MINE
        state = {"group": default_group}

        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=bg)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=bg, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=t("Filter name"), bg=bg, fg=fg,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))

        e = tk.Entry(wrap, bg=bar, fg=fg, insertbackground=fg, width=24,
                     relief="flat", font=("Segoe UI", 11))
        e.insert(0, default_name)
        e.pack(anchor="w", ipady=5, fill="x")

        tk.Label(wrap, text=t("Group"), bg=bg, fg=fg,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(14, 4))

        # A dropdown-style field: current group + chevron, opening the same
        # popup-menu widget the … menus use (see _popup_menu), plus an inline
        # "New group…" row so a brand-new group needs no separate trip.
        picker = tk.Frame(wrap, bg=bar, cursor="hand2")
        picker.pack(fill="x")
        glabel = tk.Label(picker, text=self._group_display(state["group"]),
                          bg=bar, fg=fg, anchor="w", font=("Segoe UI", 10))
        glabel.pack(side="left", fill="x", expand=True, padx=(10, 4), pady=8)
        chev = self.icon("chevron-down", size=13)
        if chev is not None:
            gchev = tk.Label(picker, image=chev, bg=bar)
        else:
            gchev = tk.Label(picker, text="▾", bg=bar, fg=fg)
        gchev.pack(side="right", padx=(0, 10))

        def set_group(name):
            state["group"] = name
            glabel.configure(text=self._group_display(name))

        def new_group():
            name = self._ask_text(t("New group"), t("Group name"))
            if not name:
                return
            name = self._unique_group_name(name)
            self.filter_groups.append({"name": name, "collapsed": False})
            names.append(name)
            set_group(name)

        def open_picker():
            specs = [(None, self._group_display(n), lambda gn=n: set_group(gn))
                     for n in names]
            specs.append(("sep",))
            specs.append(("folder-plus", t("New group…"), new_group))
            self._popup_menu(picker, specs)

        for w in (picker, glabel, gchev):
            w.bind("<Button-1>", lambda e: open_picker())

        def confirm():
            txt = e.get().strip()
            if txt:
                result["val"] = (txt, state["group"])
            dlg.destroy()

        btnrow = tk.Frame(wrap, bg=bg)
        btnrow.pack(anchor="e", pady=(16, 0))
        self._dialog_btn(btnrow, t("Cancel"), dlg.destroy).pack(side="right",
                                                                  padx=(8, 0))
        self._dialog_btn(btnrow, t("Save"), confirm,
                         primary=True).pack(side="right")

        dlg.bind("<Return>", lambda e: confirm())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        e.focus_set()
        e.select_range(0, "end")
        # No hard grab here (unlike _place_filter_dialog): the group dropdown
        # opens its own popup Toplevel, which a grab on this dialog would starve
        # of clicks. transient() still keeps it on top of / closing with root.
        center_over(self.root, dlg)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.focus_set()
        self.root.wait_window(dlg)
        return result["val"]

    def _ask_text(self, title, label, default=""):
        "Modal dark text prompt (title + a labelled field). Trimmed text or None."
        result = {"val": None}
        bg, fg, bar = self.theme["bg"], self.theme["fg"], self.theme["bar"]
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=bg)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=bg, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=label, bg=bg, fg=fg,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))

        e = tk.Entry(wrap, bg=bar, fg=fg, insertbackground=fg, width=24,
                     relief="flat", font=("Segoe UI", 11))
        e.insert(0, default)
        e.pack(anchor="w", ipady=5, fill="x")

        def confirm():
            txt = e.get().strip()
            if txt:
                result["val"] = txt
            dlg.destroy()

        btnrow = tk.Frame(wrap, bg=bg)
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
        "Shared dialog button — a tintkit.Button reading self.theme (primary = "
        "filled accent, else neutral outline). Called as self._dialog_btn across "
        "several mixins (chrome + filters dialogs)."
        return tintkit.Button(parent, self.theme, text,
                              role="primary" if primary else "neutral",
                              variant="filled" if primary else "outline",
                              command=command)

    def _filter_dialog(self, title):
        "A modal dark dialog with a scrollable body. Returns (dialog, body frame)."
        dlg = self._tw(tk.Toplevel(self.root), bg="bg")
        dlg.title(title)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = self._tw(tk.Frame(dlg, padx=16, pady=14), bg="bg")
        wrap.pack(fill="both", expand=True)
        self._tw(tk.Label(wrap, text=title, font=("Segoe UI", 11, "bold")),
                 bg="bg", fg="fg").pack(anchor="w", pady=(0, 10))

        # A fixed-height scroll area so a long list can't grow past the screen.
        canvas = self._tw(
            tk.Canvas(wrap, highlightthickness=0, width=self._edit_dpi_w(300),
                      height=self._edit_dpi_w(260)), bg="bar")
        sb = self._make_scrollbar(wrap, canvas)
        body = self._tw(tk.Frame(canvas), bg="bar")
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
