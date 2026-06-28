"""Grid view: a full-area, scrollable grid of LARGE thumbnails over the preview
column, for fast culling and side-by-side comparison.

Unlike the sidebar thumbnail strip (a narrow 1–2 column navigator), this fills
the whole central preview area with big tiles so several near-duplicate shots
can be judged at a glance. A toolbar toggle (grid-2x2) shows/hides it.

  • single click  → select that photo (loads it, honours the unsaved-edit guard)
  • double click  → open it in the big single view (grid closes)
  • keep / reject  (toolbar or ↑/↓) act on the selected photo, as usual.

Decoded tiles are cached per filename for the open folder, so culling (which
rebuilds the grid after a file moves out) reuses them instead of re-decoding the
whole folder — keeping it snappy on a weak laptop.

Mixin on the Manoni window — every method uses the shared `self`.
"""

import os
import time
import tkinter as tk
import tkinter.ttk as ttk
from concurrent.futures import ThreadPoolExecutor

from PIL import ImageTk

from ..config import BG, BAR, HOVER, ACCENT, FG, FG_DIM, ON_ACCENT, BORDER
from ..widgets import Tooltip
from ..i18n import t
from .browser import _decode_thumb

# Drop-zone colours (dark theme): keep = green, reject = red; brighter on hover.
KEEP_BG, KEEP_HOVER, KEEP_FG = "#1e3a2a", "#2c5740", "#86e3a8"
REJECT_BG, REJECT_HOVER, REJECT_FG = "#3a1e1e", "#572c2c", "#e89090"
DRAG_THRESHOLD = 6     # px the pointer must move before a click becomes a drag


class GridViewMixin:
    # Tile geometry (logical px; scaled by DPI when decoding/measuring). The tile
    # box is user-zoomable (Ctrl+wheel or the −/+ buttons) between MIN and MAX.
    GRID_TILE_DEFAULT = 190  # default tile box size (px)
    GRID_TILE_MIN = 110
    GRID_TILE_MAX = 360
    GRID_TILE_STEP = 30      # +/- per zoom notch / button click
    GRID_TILE_PAD = 26     # a cell's footprint beyond the image (padding + name)
    GRID_BUDGET = 0.03     # seconds of cell-building per main-thread slice
    DROP_ZONE_H = 72       # height of the კარგი / ცუდი drop bar (logical px)

    # --- Toolbar toggle button ---------------------------------------------

    def _build_gridview_button(self, parent):
        "A toggle icon button for the grid (culling) view — accent-filled while on."
        img = self.icon("grid-2x2")
        if img is not None:
            btn = tk.Label(parent, image=img, bg=BAR, cursor="hand2")
        else:
            btn = tk.Label(parent, text="▦", bg=BAR, fg=FG_DIM,
                           cursor="hand2", font=("Segoe UI", 11))
        btn.bind("<Enter>", lambda e: self._grid_btn_paint(hover=True))
        btn.bind("<Leave>", lambda e: self._grid_btn_paint(hover=False))
        btn.bind("<Button-1>", lambda e: self.toggle_grid_view())
        btn._tip = Tooltip(btn, t("Grid view — see many photos at once (for culling)"))
        self.btn_grid = btn
        return btn

    def _grid_btn_paint(self, hover=False):
        "Repaint the grid toggle: accent fill while on, hover tint otherwise."
        if not hasattr(self, "btn_grid"):
            return
        if self.grid_view:
            self.btn_grid.configure(bg=ACCENT)
        else:
            self.btn_grid.configure(bg=HOVER if hover else BAR)

    # --- Build the (initially hidden) grid surface --------------------------

    def _build_grid_view(self, body):
        "Scrollable big-thumbnail grid overlaying the preview column (rows 0–2 of"
        " column 2), with a კარგი / ცუდი drop bar pinned to its foot. Built once,"
        " kept hidden with grid_remove() until the toolbar toggle shows it."
        frame = tk.Frame(body, bg=BG)
        frame.grid(row=0, column=2, rowspan=3, sticky="nsew")
        frame.grid_remove()                  # hidden until the toolbar toggle shows it
        self.grid_frame = frame

        # Thin header strip: photo count (left) + tile zoom −/+ (right).
        self._build_grid_topbar(frame)

        # Drop bar at the foot: two zones to drag photos onto (Good / Bad). Packed
        # first (side="bottom") so the scrolling grid fills the space above it.
        self._build_drop_bar(frame)

        canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview,
                           style="Sidebar.Vertical.TScrollbar")
        self.grid_canvas = canvas
        self.grid_holder = tk.Frame(canvas, bg=BG)
        self.grid_holder.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        self._grid_window = canvas.create_window((0, 0), window=self.grid_holder,
                                                 anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.bind("<Configure>", self._on_grid_configure)
        for w in (canvas, self.grid_holder):
            w.bind("<MouseWheel>", self._on_grid_wheel)

    # --- Header strip: photo count + tile zoom ------------------------------

    def _build_grid_topbar(self, parent):
        "A thin header above the grid: photo count on the left, tile zoom −/+ right."
        top = tk.Frame(parent, bg=BAR)
        top.pack(side="top", fill="x")
        tk.Frame(top, bg=BORDER, height=1).pack(side="bottom", fill="x")

        zoom = tk.Frame(top, bg=BAR)
        zoom.pack(side="right", padx=8, pady=4)
        self._tool_button(zoom, "zoom-out", lambda: self._grid_zoom(-1),
                          t("Smaller tiles")).pack(side="left", padx=2)
        self._tool_button(zoom, "zoom-in", lambda: self._grid_zoom(1),
                          t("Larger tiles")).pack(side="left", padx=2)

        self._grid_count_lbl = tk.Label(top, bg=BAR, fg=FG_DIM,
                                        font=("Segoe UI", 9))
        self._grid_count_lbl.pack(side="left", padx=12, pady=4)

    def _update_grid_count(self):
        "Refresh the header photo count (no-op before the strip is built)."
        if not hasattr(self, "_grid_count_lbl"):
            return
        n = len(self.files)
        txt = t("1 photo") if n == 1 else t("{n} photos").format(n=n)
        try:
            self._grid_count_lbl.configure(text=txt)
        except tk.TclError:
            pass

    # --- Tile zoom (Ctrl+wheel or the −/+ buttons) --------------------------

    def _grid_zoom(self, direction):
        "Grow (+1) / shrink (−1) the tile size; rebuild at the new size (debounced)."
        new = self.grid_tile + direction * self.GRID_TILE_STEP
        new = max(self.GRID_TILE_MIN, min(self.GRID_TILE_MAX, new))
        if new == self.grid_tile:
            return
        self.grid_tile = new
        # Cached tiles are size-specific → drop them so they re-decode at the new
        # size. (Cull rebuilds still reuse the cache; only a zoom invalidates it.)
        self._grid_cache = {}
        self._grid_cache_folder = None
        self._save_state()
        # Coalesce a fast wheel spin into a single rebuild.
        if getattr(self, "_grid_zoom_job", None) is not None:
            try:
                self.root.after_cancel(self._grid_zoom_job)
            except tk.TclError:
                pass
        self._grid_zoom_job = self.root.after(120, self._grid_zoom_rebuild)

    def _grid_zoom_rebuild(self):
        "Fire the debounced rebuild after a tile-size change."
        self._grid_zoom_job = None
        if getattr(self, "grid_view", False):
            self._build_grid_thumbs()

    # --- Drop bar: drag photos onto Good / Bad to sort them -----------------

    def _build_drop_bar(self, parent):
        "Two coloured drop zones (Good = keep, Bad = reject) along the grid's foot."
        bar = tk.Frame(parent, bg=BORDER, height=round(self.DROP_ZONE_H * getattr(self, "dpi", 1.0)))
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        self._drop_bar = bar

        self._zone_keep = self._make_drop_zone(
            bar, "keep", t("Good"), "folder-check", KEEP_BG, KEEP_FG, side="left")
        self._zone_reject = self._make_drop_zone(
            bar, "reject", t("Bad"), "folder-x", REJECT_BG, REJECT_FG, side="right")

    def _make_drop_zone(self, bar, kind, title, icon_name, bg, fg, side):
        "One half of the drop bar: a titled, coloured panel. Highlights while a drag"
        " hovers it; a plain click opens its folder (or the ⚙ window when unset)."
        zone = tk.Frame(bar, bg=bg, cursor="hand2")
        zone.pack(side=side, fill="both", expand=True, padx=2, pady=2)
        zone.pack_propagate(False)
        inner = tk.Frame(zone, bg=bg)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        cells = [zone, inner]
        img = self.icon(icon_name)           # same keep / reject icons as the toolbar
        if img is not None:
            ico = tk.Label(inner, image=img, bg=bg)
            ico.pack(side="left", padx=(0, 8))
            cells.append(ico)
        head = tk.Label(inner, text=title, bg=bg, fg=fg,
                        font=("Segoe UI", 12, "bold"))
        head.pack(side="left")
        sub = tk.Label(zone, text="", bg=bg, fg=fg, font=("Segoe UI", 8))
        sub.place(relx=0.5, rely=0.5, anchor="center", y=18)
        cells += [head, sub]
        zone._kind, zone._bg, zone._sub = kind, bg, sub
        zone._hover = KEEP_HOVER if kind == "keep" else REJECT_HOVER
        zone._cells = cells
        # Click the zone (no drag) → open that folder, or pop ⚙ if it isn't set.
        for w in cells:
            w.bind("<Button-1>", lambda e, k=kind: self._open_cull_folder(k))
        return zone

    def _open_cull_folder(self, kind):
        "Click a drop zone: open its folder in the file manager — or, if it isn't"
        " configured yet, pop the sorting-folders window to set it (no auto-create)."
        dest = self.cull_keep if kind == "keep" else self.cull_reject
        if not dest:
            self._cull_options_dialog()      # let the user choose the folder first
            self._update_drop_zones()
            return
        try:
            os.makedirs(dest, exist_ok=True)
            os.startfile(dest)               # Windows: reveal in Explorer
        except Exception as e:
            self.toast(t("Couldn't open the folder: {e}").format(e=e))

    def _update_drop_zones(self):
        "Refresh each zone's subtitle to the destination folder it sorts into."
        if not hasattr(self, "_zone_keep"):
            return
        for zone, dest in ((self._zone_keep, self.cull_keep),
                           (self._zone_reject, self.cull_reject)):
            name = os.path.basename(dest.rstrip("\\/")) if dest else t("(set a folder)")
            try:
                zone._sub.configure(text=name)
            except tk.TclError:
                pass

    def _paint_zone(self, kind, hovered):
        "Tint a drop zone brighter while a drag hovers it, else its resting colour."
        zone = self._zone_keep if kind == "keep" else self._zone_reject
        bg = zone._hover if hovered else zone._bg
        for w in zone._cells:
            try:
                w.configure(bg=bg)
            except tk.TclError:
                pass

    def _drop_zone_at(self, x_root, y_root):
        "Which drop zone ('keep' / 'reject') the screen point is over, else None."
        for zone in (getattr(self, "_zone_keep", None), getattr(self, "_zone_reject", None)):
            if zone is None or not zone.winfo_ismapped():
                continue
            zx, zy = zone.winfo_rootx(), zone.winfo_rooty()
            if zx <= x_root < zx + zone.winfo_width() \
                    and zy <= y_root < zy + zone.winfo_height():
                return zone._kind
        return None

    # --- Toggle on/off ------------------------------------------------------

    def toggle_grid_view(self):
        "Toolbar action: flip the grid (culling) view on/off."
        self._set_grid_view(not self.grid_view)

    def _set_grid_view(self, on):
        "Show or hide the grid surface and (re)build its tiles when shown."
        if on == self.grid_view:
            return
        if on and not self.files:
            self.toast(t("No photos to show"))
            return
        self.grid_view = on
        self._grid_btn_paint()
        if on:
            self._grid_sel = set()           # nothing selected yet (current tile just gets a focus ring)
            self._update_drop_zones()        # show where each zone sorts to
            self.grid_frame.grid()           # restore into its cell …
            self.grid_frame.lift()           # … above the preview / strips
            self._build_grid_thumbs()
        else:
            self._stop_grid_build()
            self._end_drag()                 # drop any half-finished drag
            self._grid_sel = set()
            self.grid_frame.grid_remove()
            self._render_preview()           # the big view is in sync with the selection

    # --- Tile loading (parallel decode, cached per filename) ----------------

    def _build_grid_thumbs(self):
        "Rebuild the grid: reuse cached tiles, decode the rest in worker threads,"
        " and drain them into cells on the main thread in time-budgeted slices."
        if not hasattr(self, "grid_holder"):
            return
        # A new folder invalidates the per-filename tile cache.
        if getattr(self, "_grid_cache_folder", None) != self.folder:
            self._grid_cache = {}
            self._grid_cache_folder = self.folder
        self._stop_grid_build()
        for w in self.grid_holder.winfo_children():
            w.destroy()
        self.grid_images = []
        self.grid_cells = []                 # cell per file index (None on failure)
        self._grid_idx = 0                   # next file to turn into a cell
        self._grid_submit = 0                # next file handed to the decode pool
        self._grid_pos = 0                   # next free grid slot
        self._grid_tsize = round(self.grid_tile * getattr(self, "dpi", 1.0))
        self._grid_cols = self._calc_grid_cols()
        self._update_grid_count()
        if self.files:
            workers = min(8, (os.cpu_count() or 4))
            self._grid_pool = ThreadPoolExecutor(max_workers=workers)
            self._grid_futures = {}
            self._top_up_grid()
            self._grid_job = self.root.after(1, self._grid_drain)

    def _top_up_grid(self):
        "Keep the decode pool a bounded distance ahead of the cells being built;"
        " files already in the tile cache need no decode."
        pool = getattr(self, "_grid_pool", None)
        if pool is None:
            return
        target = min(len(self.files), self._grid_idx + 64)
        while self._grid_submit < target:
            i = self._grid_submit
            file = self.files[i]
            if file not in self._grid_cache:
                path = os.path.join(self.folder, file)
                self._grid_futures[i] = pool.submit(
                    _decode_thumb, path, self._grid_tsize)
            self._grid_submit += 1

    def _grid_drain(self):
        "Turn freshly-decoded (or cached) tiles into cells, in file order, for up to"
        " GRID_BUDGET seconds, then yield and repeat until the folder is built."
        try:
            if not self.grid_holder.winfo_exists():
                return
        except tk.TclError:
            return

        deadline = time.perf_counter() + self.GRID_BUDGET
        while self._grid_idx < len(self.files):
            self._top_up_grid()
            i = self._grid_idx
            file = self.files[i]
            if file in self._grid_cache:
                pil = self._grid_cache[file]
            else:
                fut = self._grid_futures.get(i)
                if fut is None or not fut.done():
                    break                    # next-in-order not ready → yield, retry
                pil = fut.result()           # None if the file couldn't be read
                del self._grid_futures[i]
                if pil is not None:
                    self._grid_cache[file] = pil
            try:
                if pil is None:
                    raise ValueError("decode failed")
                photo = ImageTk.PhotoImage(pil)
                self.grid_images.append(photo)
                cell = self._grid_make_cell(i, file, photo)
                self.grid_cells.append(cell)
                self._grid_pos += 1
            except Exception:
                self.grid_cells.append(None)
            self._grid_idx += 1
            if time.perf_counter() >= deadline:
                break

        if self._grid_idx >= len(self.files):
            self._grid_job = None
            self._shutdown_grid_pool()
            self._highlight_grid()
            self._scroll_to_grid()
            return
        self._grid_job = self.root.after(1, self._grid_drain)

    def _stop_grid_build(self):
        "Cancel an in-flight grid build (pending after-job + decode pool)."
        if getattr(self, "_grid_job", None) is not None:
            try:
                self.root.after_cancel(self._grid_job)
            except tk.TclError:
                pass
            self._grid_job = None
        self._shutdown_grid_pool()

    def _shutdown_grid_pool(self):
        "Cancel pending grid decodes and drop the pool (safe when there is none)."
        pool = getattr(self, "_grid_pool", None)
        if pool is None:
            return
        self._grid_pool = None
        for fut in getattr(self, "_grid_futures", {}).values():
            fut.cancel()
        self._grid_futures = {}
        pool.shutdown(wait=False)

    # --- Cells --------------------------------------------------------------

    def _grid_make_cell(self, i, file, photo):
        "One grid cell: a bordered image (the border marks selection) + its name."
        cell = tk.Frame(self.grid_holder, bg=BG)
        holder = tk.Frame(cell, bg=BG, highlightthickness=2, highlightbackground=BG)
        holder.pack()
        lbl = tk.Label(holder, image=photo, bg=BG, cursor="hand2")
        lbl.pack()
        name = tk.Label(cell, text=self._short_name(file), bg=BG, fg=FG_DIM,
                        font=("Segoe UI", 8))
        name.pack()
        cell._holder = holder
        pos, cols = self._grid_pos, self._grid_cols
        cell.grid(row=pos // cols, column=pos % cols, padx=6, pady=6)
        for w in (lbl, holder, name, cell):
            w.bind("<MouseWheel>", self._on_grid_wheel)
            w.bind("<ButtonPress-1>", lambda e, idx=i: self._grid_press(idx, e))
            w.bind("<B1-Motion>", self._grid_motion)
            w.bind("<ButtonRelease-1>", lambda e, idx=i: self._grid_release(idx, e))
            w.bind("<Double-Button-1>", lambda e, idx=i: self._grid_double(idx))
        return cell

    # --- Selection (single · Ctrl-toggle · Shift-range) ---------------------

    def _grid_set_sel(self, indices):
        "Replace the selection set and repaint the tile borders."
        self._grid_sel = set(indices)
        self._highlight_grid()

    def _grid_toggle(self, i):
        "Ctrl+click: add/remove one tile from the selection."
        self._grid_sel.symmetric_difference_update({i})
        self._highlight_grid()

    def _grid_range_to(self, i):
        "Shift+click: select the inclusive range between the current photo and i."
        a, b = sorted((self.index, i))
        self._grid_sel = set(range(a, b + 1))
        self._highlight_grid()

    # --- Press / drag / release (click vs drag, drag = sort) ----------------

    def _grid_press(self, i, event):
        "Tile pressed: resolve modifier selection now; arm a possible drag."
        self._grid_press_xy = (event.x_root, event.y_root)
        self._grid_dragging = False
        ctrl = bool(event.state & 0x0004)
        shift = bool(event.state & 0x0001)
        if ctrl:
            self._grid_toggle(i)
        elif shift:
            self._grid_range_to(i)
        elif i not in self._grid_sel:
            self._grid_set_sel({i})          # plain press on a new tile → select just it
        self._grid_press_idx = i

    def _grid_motion(self, event):
        "Once the pointer moves past the threshold, drag the selection; track the zone."
        if self._grid_press_xy is None:
            return
        x0, y0 = self._grid_press_xy
        if not self._grid_dragging:
            if abs(event.x_root - x0) < DRAG_THRESHOLD \
                    and abs(event.y_root - y0) < DRAG_THRESHOLD:
                return
            self._grid_dragging = True
            self._start_drag_chip()
        self._move_drag_chip(event.x_root, event.y_root)
        zone = self._drop_zone_at(event.x_root, event.y_root)
        self._paint_zone("keep", zone == "keep")
        self._paint_zone("reject", zone == "reject")

    def _grid_release(self, i, event):
        "Release: a drag drops onto a zone (sort); a plain click just loads the photo."
        was_drag = self._grid_dragging
        self._grid_press_xy = None
        if was_drag:
            zone = self._drop_zone_at(event.x_root, event.y_root)
            self._end_drag()
            if zone:
                self._grid_drop(zone)
            return
        # Not a drag → a click. Ctrl/Shift already set the selection on press;
        # a plain click loads that photo into the (hidden) big view.
        if event.state & 0x0004 or event.state & 0x0001:
            return
        self.go_to(i)

    def _grid_double(self, i):
        "Double click: open the photo in the big single view (grid closes)."
        self._end_drag()
        self.go_to(i)
        self._set_grid_view(False)

    # --- Floating drag chip --------------------------------------------------

    def _start_drag_chip(self):
        "Create the little '{n} photos' label that follows the cursor during a drag."
        self._end_drag_chip()
        n = max(1, len(self._grid_sel))
        txt = t("1 photo") if n == 1 else t("{n} photos").format(n=n)
        chip = tk.Label(self.root, text=txt, bg=ACCENT, fg=ON_ACCENT,
                        font=("Segoe UI", 9, "bold"), padx=10, pady=6)
        self._drag_chip = chip

    def _move_drag_chip(self, x_root, y_root):
        "Position the drag chip just below-right of the cursor."
        if self._drag_chip is None:
            return
        x = x_root - self.root.winfo_rootx() + 14
        y = y_root - self.root.winfo_rooty() + 14
        self._drag_chip.place(x=x, y=y)
        self._drag_chip.lift()

    def _end_drag_chip(self):
        if self._drag_chip is not None:
            try:
                self._drag_chip.destroy()
            except tk.TclError:
                pass
            self._drag_chip = None

    def _end_drag(self):
        "Tear down any in-progress drag (chip + zone highlights)."
        self._grid_dragging = False
        self._end_drag_chip()
        if hasattr(self, "_zone_keep"):
            self._paint_zone("keep", False)
            self._paint_zone("reject", False)

    # --- Drop = sort the selection into the keep / reject folder ------------

    def _grid_drop(self, zone):
        "Move every selected photo into the zone's folder (keep or reject)."
        if not self._require_cull():         # both sort folders must be set first
            self._update_drop_zones()        # they may have just been configured
            return
        dest = self.cull_keep if zone == "keep" else self.cull_reject
        files = [self.files[i] for i in sorted(self._grid_sel)
                 if 0 <= i < len(self.files)]
        if not files:
            return
        os.makedirs(dest, exist_ok=True)
        moved = []
        for f in files:
            if self._fs_move(f, self.folder, dest):
                self._push_undo({"kind": "move", "file": f,
                                 "src": self.folder, "dest": dest})
                moved.append(f)
        if not moved:
            return
        for f in moved:
            if f in self.files:
                self.files.remove(f)
        self.index = min(self.index, max(0, len(self.files) - 1))
        self._grid_sel = set()
        self._build_thumbs()
        self._refresh_grid_if_open()
        if self.files:
            self.show_current()
        else:
            self.load_folder(self.folder)
        self.toast(t("Moved {n} → {name}  ·  Ctrl+Z").format(
            n=len(moved), name=os.path.basename(dest.rstrip("\\/"))))

    # --- Layout (columns, reflow, scroll, highlight) ------------------------

    def _calc_grid_cols(self, width=None):
        "How many tile columns fit the grid's current width (at least 1)."
        if width is None:
            width = self.grid_canvas.winfo_width()
        cell = round((self.grid_tile + self.GRID_TILE_PAD) * getattr(self, "dpi", 1.0))
        return max(1, int(max(width, 1) // cell))

    def _on_grid_configure(self, event):
        "Match the inner frame to the viewport and reflow if the column count changed."
        self.grid_canvas.itemconfigure(self._grid_window, width=event.width)
        cols = self._calc_grid_cols(event.width)
        if cols != getattr(self, "_grid_cols", 1) and getattr(self, "grid_cells", None):
            self._grid_cols = cols
            self._reflow_grid()

    def _reflow_grid(self):
        "Re-place every loaded tile into the current column count."
        cols = self._grid_cols
        pos = 0
        for cell in self.grid_cells:
            if cell is None:
                continue
            cell.grid_configure(row=pos // cols, column=pos % cols)
            pos += 1

    def _on_grid_wheel(self, event):
        "Ctrl+wheel zooms the tile size; a plain wheel scrolls the grid."
        if event.state & 0x0004:             # Ctrl held → zoom the tiles
            self._grid_zoom(1 if event.delta > 0 else -1)
            return "break"
        self.grid_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _highlight_grid(self):
        "Accent-border every selected tile; clear the rest. No-op when grid is off."
        if not getattr(self, "grid_view", False) or not getattr(self, "grid_cells", None):
            return
        sel = self._grid_sel or {self.index}
        for i, cell in enumerate(self.grid_cells):
            if cell is None:
                continue
            try:
                cell._holder.configure(
                    highlightbackground=ACCENT if i in sel else BG)
            except tk.TclError:
                pass

    def _grid_on_navigate(self):
        "After the current photo changes (arrow / click / cull), collapse the grid"
        " selection onto it and refresh the highlight + scroll. No-op when grid off."
        if not getattr(self, "grid_view", False):
            return
        self._grid_sel = {self.index}
        self._highlight_grid()
        self._scroll_to_grid()

    def _scroll_to_grid(self):
        "Scroll the grid so the selected tile is visible (no-op if not built yet)."
        if not getattr(self, "grid_view", False):
            return
        if not (0 <= self.index < len(getattr(self, "grid_cells", []))):
            return
        cell = self.grid_cells[self.index]
        if cell is None:
            return
        try:
            self.grid_canvas.update_idletasks()
            total = self.grid_holder.winfo_height()
            view_h = self.grid_canvas.winfo_height()
            if total <= 1 or view_h <= 1:
                return
            y, h = cell.winfo_y(), cell.winfo_height()
            top = self.grid_canvas.canvasy(0)
            if y < top:
                self.grid_canvas.yview_moveto(max(0.0, y / total))
            elif y + h > top + view_h:
                self.grid_canvas.yview_moveto(max(0.0, (y + h - view_h) / total))
        except tk.TclError:
            pass

    def _refresh_grid_if_open(self):
        "Rebuild the grid after the file set changed (cull / undo / folder load)."
        if getattr(self, "grid_view", False):
            self._build_grid_thumbs()
