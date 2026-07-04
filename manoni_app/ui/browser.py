"""Folder browsing: the bottom nav bar, loading a folder, the minimalist
sub-folder list (top of the sidebar) and the image thumbnail grid (below it).

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import json
import os
import shutil
import subprocess
import sys
import tkinter as tk
import tkinter.filedialog as tkfd
import tkinter.font as tkfont
from concurrent.futures import ThreadPoolExecutor

import tintkit

from PIL import ImageTk

# Chrome + sidebar cells now read colours from self.theme (via chrome's `_tw`);
# HOVER/ACCENT/FG/FG_DIM stay imported only for the loading overlay, which is a
# deliberate near-black blackout (LOADING_BG) that keeps its fixed colours in
# both schemes. The keep/reject tints are now scheme-aware via self._cull_tint.
from ..config import HOVER, ACCENT, FG, FG_DIM, SUPPORTED
from ..i18n import t
from ..storage import unique_path
# The thumbnail workers call _decode_thumb; it is the disk-cached version, so the
# first decode of a file is stored and every later load / resize / cull / relaunch
# is a cheap blob read (see thumbcache.py — it falls back to a direct decode if the
# cache is unavailable).
from ..thumbcache import cached_thumb as _decode_thumb

# Near-black backdrop for the "please wait" loading screen (darker than the app
# background so it clearly reads as a blocking overlay, not just the sidebar).
LOADING_BG = "#0d0d0d"


class BrowserMixin:
    # --- Bottom navigation --------------------------------------------------

    def _build_bottombar(self):
        # The bottom strip is part of the EDITOR CANVAS, so it spans only the
        # preview column (col 2). In edit mode the full-height tool panels (cols
        # 3-4) sit beside it and clip it on the right. Row 1 above it holds the
        # filter preview strip (when shown); this nav/zoom bar is the last row.
        bar = self._tw(tk.Frame(self.body, height=34), bg="bar")
        bar.grid(row=2, column=2, sticky="ew")
        bar.grid_propagate(False)

        # RIGHT: navigation arrows, then the position counter. The keep / reject
        # cull buttons sit in the MIDDLE of the arrows (between prev and next) —
        # tinted green (keep, folder-up) and red (reject, folder-down) so they
        # read at a glance. Each row is (icon, command, tip, color, hint, sub):
        # color None leaves the arrow white. Hovering a button spells out what it
        # does in the bottom info bar (nav._nav_hint); `sub` is an optional
        # trailing note — keep / reject use it to show where they save (or that
        # no folder is set yet), evaluated fresh so it tracks Settings.
        nav = self._tw(tk.Frame(bar), bg="bar")
        nav.pack(side="right", padx=8)
        # `cull` = "keep"/"reject" (a scheme-aware green/red tint) or None (plain
        # nav button, theme fg). The tint is resolved live so it follows the switch.
        for icon_name, command, tip, cull, hint, sub in [
            ("chevrons-left", self._nav_click_first, t("First"), None,
             t("Jump to the first photo of this folder"), None),
            ("chevron-left", self._nav_click_prev, t("Previous"), None,
             t("Go to the previous photo  ·  ← key"), None),
            ("folder-up", self.move_to_folder, t("Keep (keeper)"), "keep",
             t("Keep — move this photo to the keeper folder  ·  ↑ key"),
             lambda: self._cull_hint_line(self.cull_keep)),
            ("folder-down", self.delete, t("Reject"), "reject",
             t("Reject — move this photo to the discard folder  ·  ↓ key"),
             lambda: self._cull_hint_line(self.cull_reject)),
            ("chevron-right", self._nav_click_next, t("Next"), None,
             t("Go to the next photo  ·  → key"), None),
            ("chevrons-right", self._nav_click_last, t("Last"), None,
             t("Jump to the last photo of this folder"), None),
        ]:
            color = (lambda w=cull: self._cull_tint(w)) if cull else None
            btn = self._tool_button(nav, icon_name, command, tip, color=color)
            btn.bind("<Enter>",
                     lambda e, h=hint, s=sub, w=cull: self._nav_hint(
                         h, s() if callable(s) else "",
                         self._cull_tint(w) if w else None), add="+")
            btn.bind("<Leave>", lambda e: self._nav_hint_clear(), add="+")
            btn.pack(side="left", padx=4, pady=4)
        self.lbl_pos = self._tw(
            tk.Label(nav, text="0 / 0", font=("Segoe UI", 9)),
            bg="bar", fg="fg_dim")
        self.lbl_pos.pack(side="left", padx=10)
        # The thumbnail selection border reads from the theme; repaint the visible
        # cells' borders on a dark<->light switch (this bar is built once).
        self.theme.subscribe(self._highlight_thumb)

        # CENTER: rotate the current photo (truly centered over the strip).
        rot = self._tw(tk.Frame(bar), bg="bar")
        rot.place(relx=0.5, rely=0.5, anchor="center")
        for icon_name, command, tip in [
            ("rotate-ccw", self.rotate_left, t("Rotate left")),
            ("rotate-cw", self.rotate_right, t("Rotate right")),
        ]:
            self._tool_button(rot, icon_name, command, tip).pack(side="left", padx=4)

        # LEFT corner: zoom controls (quick sizes · − · % · +).
        self._build_zoom_controls(bar)

    def _build_zoom_controls(self, bar):
        "Quick-size chips + −/% /+ stepper, packed at the left of the bottom bar."
        zone = self._tw(tk.Frame(bar), bg="bar")
        zone.pack(side="left", padx=10)

        # Quick-size preset chips: Fit · 50% · 100% · 200%. Their fg is state-driven
        # (accent when active, fg_dim otherwise, fg on hover) — owned by
        # _update_zoom_readout / _chip_hover — so `_tw` threads only the bg here.
        self.zoom_presets = []
        for label, scale in self.ZOOM_PRESETS:
            chip = self._tw(
                tk.Label(zone, text=label, fg=self.theme["fg_dim"], cursor="hand2",
                         font=("Segoe UI", 8, "bold"), padx=6, pady=2), bg="bar")
            chip._scale = scale
            if scale is None:
                chip.bind("<Button-1>", lambda e: self.fit_view())
            else:
                chip.bind("<Button-1>", lambda e, s=scale: self.zoom_to(s))
            chip.bind("<Enter>", lambda e, c=chip: self._chip_hover(c, True))
            chip.bind("<Leave>", lambda e, c=chip: self._chip_hover(c, False))
            chip.pack(side="left")
            self.zoom_presets.append(chip)

        self._sep(zone).pack(side="left", fill="y", padx=8, pady=8)

        # Stepper: − [ 49% ] +  (zoom-out / readout / zoom-in).
        self._tool_button(zone, "zoom-out", self.zoom_out,
                          t("Zoom out")).pack(side="left", padx=2)
        self.lbl_zoom = self._tw(
            tk.Label(zone, text="—", width=6, font=("Segoe UI", 9, "bold")),
            bg="bar", fg="fg")
        self.lbl_zoom.pack(side="left")
        self._tool_button(zone, "zoom-in", self.zoom_in,
                          t("Zoom in")).pack(side="left", padx=2)
        # Recolour the chips (accent/fg_dim) + the readout on a dark<->light switch.
        self.theme.subscribe(
            lambda: self._update_zoom_readout(getattr(self, "_zoom_scale", None)))

    def _chip_hover(self, chip, entering):
        "Brighten a quick-size chip on hover; the active one stays accent-colored."
        if self._chip_active(chip):
            return
        chip.configure(fg=self.theme["fg"] if entering else self.theme["fg_dim"])

    # --- Folder + files -----------------------------------------------------

    def load_folder(self, folder, select=None):
        "Load all images in a folder and show the first one (or `select`, if given)."
        folder = os.path.normpath(folder)
        self.folder = folder
        self._subdir_cache = {}          # fresh sub-dir listings for this navigation
        # The folder tree keeps a fixed root: navigating INSIDE it just moves the
        # highlight (and expands down to the new folder); jumping OUTSIDE it (Open
        # folder, a breadcrumb above the root, ↑ past the top) re-roots the tree.
        if not self._within_tree_root(folder):
            self.tree_root = folder
            self.folder_expanded = set()
        self.folder_expanded.add(folder)
        self._expand_ancestors(folder)   # open every level from the root down to here
        self.folder_filter = ""          # a fresh folder clears the live filter
        self._update_breadcrumbs()       # refresh the address bar to the new folder
        try:
            entries = sorted(os.listdir(folder), key=str.lower)
        except OSError:
            entries = []
        self.files = [
            f for f in entries
            if os.path.splitext(f)[1].lower() in SUPPORTED
            and os.path.isfile(os.path.join(folder, f))]
        self.index = self.files.index(select) if select in self.files else 0
        self._refresh_folder_tree(rebuild=True)   # top section: the folder tree
        # A big folder covers the window with a dark, input-blocking "please wait"
        # screen so a stray slider drag or key press can't act on a half-painted
        # strip; it lifts once the visible thumbnails land (overlay=True).
        self._build_thumbs(overlay=True)  # bottom section: photo thumbnail strip
        if self.files:
            self.show_current()
        else:
            self.current_pil = None
            self._message = t("No photos found")
            self._render_preview()
            self.lbl_name.configure(text="Manoni")
            self._info_text = ""
            self.lbl_info.configure(text="")
            self.lbl_pos.configure(text="0 / 0")
            self._refresh_filter_strip()      # no photo → hide the filter strip
            self._save_state()

    def open_folder(self):
        folder = tkfd.askdirectory(parent=self.root,
                                   initialdir=self.folder or os.path.expanduser("~"))
        if folder:
            self.load_folder(folder)

    # --- Loading overlay ("please wait" while a big folder builds) ----------

    def _show_loading_overlay(self, total):
        "Dark, input-blocking screen shown over the whole window while thumbnails load."
        self._hide_loading_overlay()          # never stack two
        dpi = getattr(self, "dpi", 1.0)
        ov = tk.Frame(self.root, bg=LOADING_BG)
        ov.place(relx=0, rely=0, relwidth=1, relheight=1)   # cover everything
        ov.lift()                             # above the toolbar / sidebar / preview
        self._loading_overlay = ov
        # Swallow every mouse / key event that reaches the overlay (the grab below
        # routes them here); this keeps a click or shortcut from leaking through.
        for seq in ("<KeyPress>", "<Button>", "<MouseWheel>", "<B1-Motion>"):
            ov.bind(seq, lambda e: "break")

        box = tk.Frame(ov, bg=LOADING_BG)
        box.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(box, text=t("Please wait…"), bg=LOADING_BG, fg=FG,
                 font=("Segoe UI", 16, "bold")).pack()
        self._loading_sub = tk.Label(box, text="", bg=LOADING_BG, fg=FG_DIM,
                                     font=("Segoe UI", 10))
        self._loading_sub.pack(pady=(8, 14))

        # A thin progress line that fills with an accent bar as the thumbnails load.
        track = tk.Frame(box, bg=HOVER, width=int(320 * dpi),
                         height=max(3, int(4 * dpi)))
        track.pack()
        track.pack_propagate(False)
        self._loading_fill = tk.Frame(track, bg=ACCENT)
        self._loading_fill.place(x=0, y=0, relheight=1, relwidth=0.0)

        self._update_loading_overlay(0, total)
        self._grab_loading()

    def _grab_loading(self, tries=0):
        "Grab all input for the overlay; retry while the window is still unmapped"
        " (e.g. at startup, before mainloop has shown it)."
        ov = self._loading_overlay
        if ov is None:
            return
        try:
            ov.grab_set()                     # local grab: blocks mouse + keyboard
            ov.focus_set()
        except tk.TclError:
            if tries < 20:
                self.root.after(50, lambda: self._grab_loading(tries + 1))

    def _update_loading_overlay(self, done, total):
        "Advance the progress line + counter (no-op when the overlay isn't shown)."
        if self._loading_overlay is None:
            return
        frac = 0.0 if total <= 0 else max(0.0, min(1.0, done / total))
        try:
            self._loading_fill.place_configure(relwidth=frac)
            self._loading_sub.configure(
                text=f"{t('Loading photos…')}   {done} / {total}")
        except tk.TclError:
            pass

    def _hide_loading_overlay(self):
        "Release the grab and tear down the overlay (safe to call when not shown)."
        ov = self._loading_overlay
        if ov is None:
            return
        self._loading_overlay = None
        for action in (ov.grab_release, ov.destroy,
                       lambda: self.preview.focus_set()):
            try:
                action()
            except tk.TclError:
                pass

    # --- Thumbnails ---------------------------------------------------------

    def _build_thumbs(self, overlay=False):
        "(Re)build the virtualized thumbnail strip: lay out the full scroll height up"
        " front, then realize + decode only the cells in (or near) the viewport. Cost"
        " is bound to the screen, not the folder — 50 or 5000 files open the same."
        " `overlay` puts up the blocking 'please wait' screen until the visible cells"
        " fill (folder load + thumb-size/view change pass it; a single cull doesn't)."
        self._shutdown_decode_pool()    # cancels the poll job + any in-flight decodes
        self._clear_cells()             # drop every realized cell from the old build
        self._decode_tsize = self.LIST_THUMB if self.view_mode == "list" \
            else self.thumb_size
        self._thumb_cols = self._calc_cols()
        # Sub-folders are NOT in this strip — they live in the folder tree above
        # it (_refresh_folder_tree), so the strip is pure photos.
        self._layout_strip()            # size the canvas content so the scrollbar is right
        if not self.files:
            self._overlay_active = False
            self._hide_loading_overlay()
            return
        if overlay and len(self.files) >= self.LOADING_OVERLAY_MIN:
            self._overlay_active = True
            self._show_loading_overlay(len(self.files))
        else:
            self._overlay_active = False
        workers = min(8, (os.cpu_count() or 4))
        self._decode_pool = ThreadPoolExecutor(max_workers=workers)
        self._decode_futures = {}
        # Keep the current photo on screen (folder load = index 0 → top); this also
        # realizes + decodes the first visible window via _render_window.
        self._scroll_to_thumb()
        self._ensure_poll()

    # --- Cell geometry (fixed, so any index's x/y is known without a widget) -----

    def _cell_metrics(self):
        "The fixed (cell_w, cell_h, cols) for the current view — the strip's grid is"
        " uniform, so any file index maps to a known row/column and pixel position."
        cols = self._calc_cols()
        if self.view_mode == "list":
            view_w = max(1, self.canvas.winfo_width())
            cell_w = max(self.LIST_COL_MIN, view_w // max(1, cols))
            cell_h = self.LIST_ROW_H
        else:
            cell_w = self.thumb_size + self.THUMB_PAD
            cell_h = self.thumb_size + self.THUMB_NAME_H + self.THUMB_CELL_V
        return cell_w, cell_h, cols

    def _canvas_view_h(self):
        "The strip canvas's current height in px, falling back to a screenful before"
        " the widget has been laid out (e.g. at startup)."
        try:
            self.canvas.update_idletasks()
            h = self.canvas.winfo_height()
        except tk.TclError:
            h = 0
        return h if h > 1 else 600

    def _layout_strip(self):
        "Reset the strip when the folder is empty; otherwise a no-op. _render_window"
        " (below) sizes the canvas for real, to a window bounded by the viewport —"
        " never the full folder — so it stays well under Tk's canvas coordinate"
        " ceiling (~32,767 px; a Frame/window placed past that clips or breaks)"
        " regardless of file count or thumbnail size."
        if self.files:
            return
        view_w = max(1, self.canvas.winfo_width())
        try:
            self.canvas.itemconfigure(self._thumb_window, width=view_w, height=1)
            self.canvas.configure(scrollregion=(0, 0, view_w, 1))
            self._thumb_scrollbar.set(0.0, 1.0)
        except tk.TclError:
            pass

    # --- Realize / recycle the visible window ------------------------------------

    def _render_window(self):
        "Create the cells now in the viewport, destroy those that scrolled out, and"
        " request decodes for the freshly-visible ones. Cheap to call on every scroll."
        " Cells are placed relative to the current row window (self._thumb_row_base),"
        " and the canvas is sized to just that window — NOT to the full folder — so"
        " its scrollregion never approaches Tk's ~32,767 px coordinate ceiling no"
        " matter how many files there are. self._scroll_row (row units, not pixels)"
        " is the single source of truth for scroll position; the scrollbar's thumb is"
        " set by hand from it, since it must track position across every file, not"
        " just the (deliberately tiny) realized window."
        if not hasattr(self, "thumb_holder") or not self.files:
            return
        cell_w, cell_h, cols = self._cell_metrics()
        self._thumb_cols = cols
        n = len(self.files)
        total_rows = (n + cols - 1) // cols
        view_w = max(1, self.canvas.winfo_width())
        visible_rows = max(1.0, self._canvas_view_h() / cell_h)
        max_scroll = max(0.0, total_rows - visible_rows)
        self._scroll_row = max(0.0, min(getattr(self, "_scroll_row", 0.0), max_scroll))

        first_row = max(0, int(self._scroll_row) - self.THUMB_BUFFER_ROWS)
        last_row = min(total_rows - 1,
                       int(self._scroll_row + visible_rows) + self.THUMB_BUFFER_ROWS)
        first = first_row * cols
        last = min(n - 1, (last_row + 1) * cols - 1)
        want = set(range(first, last + 1))

        for i in list(self._cells):
            if i not in want:
                self._destroy_cell(i)
        self._thumb_row_base = first_row     # _make_cell_at places relative to this
        for i in range(first, last + 1):
            if i not in self._cells:
                self._make_cell_at(i, cell_w, cell_h, cols)
            else:
                row, _col = divmod(i, cols)
                try:                          # already realized → just re-seat it
                    self._cells[i].place_configure(y=(row - first_row) * cell_h)
                except tk.TclError:
                    pass
            self._request_decode(i)

        window_h = max(1, (last_row - first_row + 1) * cell_h)
        try:
            self.canvas.itemconfigure(self._thumb_window, width=view_w,
                                      height=window_h)
            self.canvas.configure(scrollregion=(0, 0, view_w, window_h))
            frac = (self._scroll_row - first_row) * cell_h / window_h
            self.canvas.yview_moveto(max(0.0, min(1.0, frac)))
            self._thumb_scrollbar.set(self._scroll_row / total_rows,
                                      min(1.0, (self._scroll_row + visible_rows)
                                          / total_rows))
        except tk.TclError:
            pass
        self._ensure_poll()

    def _clear_cells(self):
        "Destroy every realized cell (keeps the decode pool/futures alive)."
        for cell in self._cells.values():
            try:
                cell.destroy()
            except tk.TclError:
                pass
        self._cells = {}
        self._cell_imgs = {}
        self._cell_failed = set()

    def _destroy_cell(self, i):
        "Recycle one cell that scrolled out of the window (its decode result, if it"
        " arrives later, is discarded — the shared cache keeps it cheap to redo)."
        cell = self._cells.pop(i, None)
        if cell is not None:
            try:
                cell.destroy()
            except tk.TclError:
                pass
        self._cell_imgs.pop(i, None)
        self._cell_failed.discard(i)

    def _make_cell_at(self, i, cell_w, cell_h, cols):
        "Build one placeholder cell for file index i and place it at its slot, relative"
        " to self._thumb_row_base (see _render_window — the strip rebases rather than"
        " placing at the file's true row, which could land past Tk's coordinate limit)."
        file = self.files[i]
        row, col = divmod(i, cols)
        y = (row - self._thumb_row_base) * cell_h
        if self.view_mode == "list":
            cell = self._make_list_cell(i, file)
            cell.place(x=col * cell_w + 2, y=y + 1,
                       width=cell_w - 4, height=cell_h - 2)
        else:
            cell = self._make_grid_cell(i, file)
            cell.place(x=col * cell_w, y=y,
                       width=cell_w, height=cell_h)
        self._cells[i] = cell
        if i in self._cell_imgs:         # survived a relayout → re-show its image
            try:
                cell._img_lbl.configure(image=self._cell_imgs[i])
            except tk.TclError:
                pass

    # --- Decode pool: realize-on-demand, drained by a polling after-job ----------

    def _request_decode(self, i):
        "Submit a decode for file index i unless it is already imaged or in flight."
        pool = self._decode_pool
        if pool is None or i in self._cell_imgs or i in self._decode_futures:
            return
        path = os.path.join(self.folder, self.files[i])
        self._decode_futures[i] = pool.submit(_decode_thumb, path,
                                              self._decode_tsize)

    def _ensure_poll(self):
        "Schedule the decode-draining poll if there is work and none is queued."
        if self._poll_job is not None or self._decode_pool is None:
            return
        if self._decode_futures or self._overlay_active:
            self._poll_job = self.root.after(16, self._poll_decodes)

    def _resolved(self, i):
        "True once cell i has its image (or its decode failed) — nothing left to wait."
        return i in self._cell_imgs or i in self._cell_failed

    def _poll_decodes(self):
        "Drain finished decodes into their (still-visible) cells; drop the overlay once"
        " every visible cell is resolved; keep polling while work remains."
        self._poll_job = None
        if self._decode_pool is None:
            return
        for i in [k for k, f in self._decode_futures.items() if f.done()]:
            fut = self._decode_futures.pop(i)
            try:
                pil = fut.result()
            except Exception:
                pil = None
            if i not in self._cells:     # scrolled away before it landed → discard
                continue
            if pil is None:
                self._cell_failed.add(i)
                continue
            try:
                photo = ImageTk.PhotoImage(pil)
            except Exception:
                self._cell_failed.add(i)
                continue
            self._cell_imgs[i] = photo
            try:
                self._cells[i]._img_lbl.configure(image=photo)
            except tk.TclError:
                pass
        if self._overlay_active:
            vis = list(self._cells)
            done = sum(1 for i in vis if self._resolved(i))
            self._update_loading_overlay(done, len(vis))
            if vis and done >= len(vis):
                self._overlay_active = False
                self._hide_loading_overlay()
        self._ensure_poll()

    def _shutdown_decode_pool(self):
        "Cancel the poll, abandon in-flight decodes, and drop the pool (safe if none)."
        if getattr(self, "_poll_job", None) is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        pool = getattr(self, "_decode_pool", None)
        if pool is None:
            return
        self._decode_pool = None
        for fut in getattr(self, "_decode_futures", {}).values():
            fut.cancel()                # only not-yet-started tasks actually cancel
        self._decode_futures = {}
        pool.shutdown(wait=False)

    # --- Folder tree (tintkit.FolderTree in the top sidebar panel) ----------

    def _within_tree_root(self, folder):
        "True when `folder` is the tree root or lives inside it (so the root stays put)."
        r = self.tree_root
        if not r:
            return False
        r, folder = os.path.normpath(r), os.path.normpath(folder)
        if folder == r:
            return True
        try:                             # commonpath handles drive roots / trailing seps
            return os.path.commonpath([r, folder]) == r
        except ValueError:               # different drives (Windows) → not inside
            return False

    def _expand_ancestors(self, folder):
        "Expand every folder from the tree root down to `folder`, so it's on screen."
        r = self.tree_root
        if not r:
            return
        r, p = os.path.normpath(r), os.path.normpath(folder)
        self.folder_expanded.add(r)
        while p != r:                    # walk up to the root (stops at a drive root)
            self.folder_expanded.add(p)
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent

    def _list_subdirs(self, path):
        "Immediate, non-hidden sub-directories of `path` as (name, full); cached per load."
        hit = self._subdir_cache.get(path)
        if hit is not None:
            return hit
        try:
            entries = sorted(os.listdir(path), key=str.lower)
        except OSError:
            entries = []
        subs = [(n, os.path.join(path, n)) for n in entries
                if not n.startswith(".")
                and os.path.isdir(os.path.join(path, n))]
        self._subdir_cache[path] = subs
        return subs

    def _folder_tree_rows(self):
        "Rows for tintkit.FolderTree: (depth, name, kind, is_current, fullpath)."
        root = self.tree_root
        rows = []
        if not root or not os.path.isdir(root):
            return rows
        root = os.path.normpath(root)
        nm = lambda p: os.path.basename(p) or p
        flt = self.folder_filter.strip().lower()
        if flt:
            # Filter mode: bounded scan for matches; keep matches + their ancestors
            # so the surviving folders stay connected to the root.
            keep, budget = set(), [self.FOLDER_FILTER_BUDGET]

            def scan(path, chain):
                if budget[0] <= 0:
                    return
                budget[0] -= 1
                if flt in nm(path).lower():
                    keep.update(chain)
                    keep.add(path)
                for _n, full in self._list_subdirs(path):
                    scan(full, chain + [path])
            scan(root, [])

            def emit(path, depth):
                shown = [full for _n, full in self._list_subdirs(path)
                         if full in keep]
                kind = "open" if shown else "leaf"
                rows.append((depth, nm(path), kind, path == self.folder, path))
                for full in shown:
                    emit(full, depth + 1)
            emit(root, 0)               # root always shown, for context
        else:
            def emit(path, depth):
                kids = self._list_subdirs(path)
                if kids:
                    kind = "open" if path in self.folder_expanded else "closed"
                else:
                    kind = "leaf"
                rows.append((depth, nm(path), kind, path == self.folder, path))
                if kids and path in self.folder_expanded:
                    for _n, full in kids:
                        emit(full, depth + 1)
            emit(root, 0)
        return rows

    def _refresh_folder_tree(self, rebuild=False):
        "(Re)render the folder tree; hide the whole panel only when the root has no sub-folders."
        rows = self._folder_tree_rows()
        # Show the panel whenever the root actually HAS sub-folders — even when the
        # root row itself is collapsed (then just that one row shows, so it can be
        # re-expanded). Hide only when there's genuinely nothing to browse (and no
        # active filter, which stays on screen so 'no matches' can be cleared).
        root_has_subs = bool(self.tree_root and self._list_subdirs(self.tree_root))
        if not (root_has_subs or self.folder_filter.strip()):
            if rebuild:
                self._destroy_folder_tree()
            self.folder_panel.pack_forget()
            return
        if rebuild:                     # fresh navigation → reset the filter box
            self._destroy_folder_tree()
        if self.folder_tree is None:
            self.folder_tree = tintkit.FolderTree(
                self.folder_holder, self.theme, filter_text=t("Filter folders…"),
                on_row=self._tree_open, on_toggle=self._tree_toggle,
                on_filter=self._tree_filter_changed,
                on_context=self._tree_context_menu)
            self.folder_tree.pack(fill="x")
        self.folder_tree.set_rows(rows)
        self._bind_folder_tree_wheel()       # rows are rebuilt → re-arm wheel scroll
        self.folder_panel.pack(side="top", fill="x", before=self._thumb_scrollbar)
        self.folder_holder.update_idletasks()
        self._on_folder_holder_configure()   # size the list to its content (capped)

    def _bind_folder_tree_wheel(self):
        "Route the mouse wheel over any tree widget (rows included) to the list scroller."
        if self.folder_tree is None:
            return

        def walk(w):
            try:
                w.bind("<MouseWheel>", self._on_folder_wheel)
            except tk.TclError:
                pass
            for c in w.winfo_children():
                walk(c)
        walk(self.folder_tree.box.widget)

    def _destroy_folder_tree(self):
        "Tear down the FolderTree widget (used on navigation so the filter box resets)."
        for w in self.folder_holder.winfo_children():
            w.destroy()
        self.folder_tree = None

    def _tree_open(self, path):
        "Click a folder's name: load its photos and select it (the tree stays rooted)."
        if path and os.path.isdir(path):
            self.load_folder(path)

    def _tree_toggle(self, path):
        "Click a row's chevron: expand / collapse it without changing the open folder."
        if path in self.folder_expanded:
            self.folder_expanded.discard(path)
        else:
            self.folder_expanded.add(path)
        self._refresh_folder_tree()

    def _tree_filter_changed(self, text):
        "Live folder filter: re-render only the rows (the filter box keeps its focus)."
        self.folder_filter = text or ""
        if self.folder_tree is not None:
            self.folder_tree.set_rows(self._folder_tree_rows())
            self._bind_folder_tree_wheel()   # new rows → re-arm wheel scroll
            self.folder_holder.update_idletasks()
            self._on_folder_holder_configure()

    # --- Folder tree right-click menu (open in file manager · rename · delete)

    def _tree_context_menu(self, path, event):
        "Right-click a sidebar folder row."
        if not path or not os.path.isdir(path):
            return
        menu = tk.Menu(self.root, tearoff=0, bg=self.theme["bar"],
                       fg=self.theme["fg"], bd=0,
                       activebackground=self.theme["accent"],
                       activeforeground=self.theme["on_accent"],
                       font=("Segoe UI", 9))
        menu.add_command(label=t("Open in file manager"),
                         command=lambda: self._reveal_path(path))
        menu.add_command(label=t("Rename"),
                         command=lambda: self._rename_tree_folder(path))
        menu.add_separator()
        menu.add_command(label=t("Delete"), foreground="#ff8a8a",
                         command=lambda: self._delete_tree_folder(path))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _reveal_path(self, path, select=False):
        "Show `path` in the OS file manager (Explorer / Finder). `select=True` opens"
        " the CONTAINING folder with `path` itself highlighted, for a file; plain"
        " (select=False) just opens `path`, for a folder row."
        if not os.path.exists(path):
            self.toast(t("File not found") if select else t("Folder not found"))
            return
        try:
            if sys.platform.startswith("win"):
                if select:
                    subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
                else:
                    os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path] if select else ["open", path])
            else:
                subprocess.Popen(["xdg-open",
                                  os.path.dirname(path) if select else path])
        except Exception as e:
            self.toast(t("Error: {e}").format(e=e))

    def _rename_tree_folder(self, path):
        "Rename a sidebar folder on disk, then repoint tree/nav state at the new path."
        old_name = os.path.basename(path)
        new_name = self._ask_text(t("Rename folder"), t("Folder name"), old_name)
        if not new_name or new_name == old_name:
            return
        new_path = os.path.join(os.path.dirname(path), new_name)
        if os.path.exists(new_path):
            self.toast(t("A folder with that name already exists"))
            return
        try:
            os.rename(path, new_path)
        except Exception as e:
            self.toast(t("Error: {e}").format(e=e))
            return
        self._retarget_after_folder_change(path, new_path)
        self.toast(t("Renamed to “{name}”").format(name=new_name))

    def _delete_tree_folder(self, path):
        "Delete a sidebar folder — moved to the Recycle Bin / Trash, never gone for"
        " good (matches the app's non-destructive stance elsewhere: culling only"
        " ever moves files too)."
        name = os.path.basename(path)
        msg = (t("Move “{name}” and everything inside it to the Recycle Bin?")
               if sys.platform.startswith("win") else
               t("Move “{name}” and everything inside it to the Trash?"))
        if not self._confirm(msg.format(name=name), ok_label=t("Delete")):
            return
        try:
            self._trash_path(path)
        except Exception as e:
            self.toast(t("Error: {e}").format(e=e))
            return
        self._retarget_after_folder_change(path, None)
        self.toast(t("Deleted: {name}").format(name=name))

    def _trash_path(self, path):
        "Move `path` to the Recycle Bin (Windows) / Trash (macOS); raises on failure."
        " No plain permanent-delete path on those two — only the 'else' fallback"
        " (an unsupported OS) has no trash convention to call into."
        if sys.platform.startswith("win"):
            import ctypes
            from ctypes import wintypes

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                           ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                           ("fFlags", ctypes.c_uint16),
                           ("fAnyOperationsAborted", wintypes.BOOL),
                           ("hNameMappings", ctypes.c_void_p),
                           ("lpszProgressTitle", wintypes.LPCWSTR)]
            FO_DELETE = 3
            FOF_ALLOWUNDO, FOF_NOCONFIRMATION = 0x40, 0x10
            FOF_SILENT, FOF_NOERRORUI = 0x4, 0x400
            op = SHFILEOPSTRUCTW()
            op.wFunc = FO_DELETE
            # pFrom is a list of NUL-separated names, double-NUL terminated; ctypes
            # appends its own terminator, so one explicit "\0" here gives the required
            # double NUL.
            op.pFrom = os.path.normpath(path) + "\0"
            op.fFlags = (FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
                        | FOF_NOERRORUI)
            if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0:
                raise OSError("SHFileOperationW failed")
        elif sys.platform == "darwin":
            # json.dumps quotes/escapes the path exactly the way an AppleScript
            # string literal needs (both use \" and \\), so it doubles as the
            # AppleScript quoting without a second escaping scheme.
            script = ('tell application "Finder" to delete POSIX file '
                     + json.dumps(os.path.abspath(path)))
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise OSError(r.stderr.strip() or "osascript failed")
        else:
            shutil.rmtree(path)

    def _remap_path(self, p, old, new):
        "`old` -> `new` for `p` (`new=None` when the folder at `old` is gone)."
        p = os.path.normpath(p)
        if p == old:
            return new
        if p.startswith(old + os.sep):
            return None if new is None else new + p[len(old):]
        return p

    def _retarget_after_folder_change(self, old_path, new_path):
        "After a sidebar rename (`new_path` = the new location) or delete"
        " (`new_path` = None): reload only if the OPEN folder itself moved or"
        " vanished, otherwise just drop stale tree state and redraw in place."
        old = os.path.normpath(old_path)
        cur = os.path.normpath(self.folder) if self.folder else None
        target = self._remap_path(cur, old, new_path) if cur else None
        if cur is not None and target != cur:
            self.load_folder(target or os.path.dirname(old))
            return
        self.folder_expanded = {
            q for q in (self._remap_path(p, old, new_path)
                       for p in self.folder_expanded) if q is not None}
        self._subdir_cache = {}
        self._refresh_folder_tree(rebuild=True)

    def _short_name(self, name):
        "Truncate a filename (keeping its extension) to fit roughly under the thumbnail."
        max_chars = max(8, self.thumb_size // 7)
        if len(name) <= max_chars:
            return name
        stem, ext = os.path.splitext(name)
        keep = max(1, max_chars - len(ext) - 1)
        return stem[:keep] + "…" + ext

    def _make_grid_cell(self, i, file):
        "A placeholder grid cell: a fixed square image box (bordered for selection)"
        " + its one-line name. The image lands later, filled in by the decode poll."
        sel = (i == self.index)
        cell = self._tw(tk.Frame(self.thumb_holder), bg="sidebar")
        box = max(1, self.thumb_size)
        holder = self._tw(
            tk.Frame(cell, highlightthickness=2, width=box, height=box,
                     highlightbackground=self.theme["accent"] if sel
                     else self.theme["sidebar"]), bg="sidebar")
        holder.pack_propagate(False)     # fixed square box → uniform rows for windowing
        holder.pack(pady=(2, 0))
        lbl = self._tw(tk.Label(holder, cursor="hand2"), bg="sidebar")
        lbl.place(relx=0.5, rely=0.5, anchor="center")   # center the image in the box
        name = self._tw(tk.Label(cell, text=self._short_name(file),
                                 font=("Segoe UI", 7)), bg="sidebar", fg="fg_dim")
        name.pack()
        cell._holder = holder            # the bordered frame we recolor to select
        cell._img_lbl = lbl              # the label the decode poll fills with the thumb
        for w in (lbl, holder, name, cell):
            w.bind("<MouseWheel>", self._on_wheel)
            w.bind("<Button-1>", lambda e, idx=i: self.go_to(idx))
            w.bind("<Button-3>", lambda e, idx=i: self._thumb_menu(e, idx))
        return cell

    def _make_list_cell(self, i, file):
        "A placeholder list row: a fixed tiny preview box + the (ellipsized) filename."
        sel = (i == self.index)
        cell = self._tw(tk.Frame(self.thumb_holder), bg="sidebar")
        holder = self._tw(
            tk.Frame(cell, highlightthickness=2,
                     highlightbackground=self.theme["accent"] if sel
                     else self.theme["sidebar"]), bg="sidebar")
        holder.pack(fill="both", expand=True)
        box = self._tw(tk.Frame(holder, width=self.LIST_THUMB,
                                height=self.LIST_THUMB), bg="sidebar")
        box.pack_propagate(False)
        box.pack(side="left", padx=(4, 8), pady=2)
        lbl = self._tw(tk.Label(box, cursor="hand2"), bg="sidebar")
        lbl.place(relx=0.5, rely=0.5, anchor="center")
        # The name is ellipsized to the current column width so a long filename fits
        # the row instead of spilling past the right edge (re-fitted by
        # _reflow_list_names on resize). anchor="w" keeps it left-aligned.
        name = self._tw(tk.Label(holder, text=self._fit_name(file), anchor="w",
                                 cursor="hand2", font=("Segoe UI", 9)),
                        bg="sidebar", fg="fg")
        name.pack(side="left", fill="x", expand=True)
        cell._holder = holder            # the bordered frame we recolor to select
        cell._img_lbl = lbl
        cell._name_lbl = name            # re-ellipsized on resize
        cell._file = file
        for w in (cell, holder, box, lbl, name):
            w.bind("<MouseWheel>", self._on_wheel)
            w.bind("<Button-1>", lambda e, idx=i: self.go_to(idx))
            w.bind("<Button-3>", lambda e, idx=i: self._thumb_menu(e, idx))
        return cell

    # --- Thumbnail right-click menu (open in folder · duplicate · delete) -----

    def _thumb_menu(self, event, idx):
        "Right-click a thumbnail: reveal it in Explorer, duplicate it, or delete it."
        if not (0 <= idx < len(self.files)):
            return
        # Transient popup menu: read the live theme once at build time. The active
        # item sits on the accent fill, so its text uses on_accent (light in both
        # schemes) rather than fg (which is dark in light mode).
        menu = tk.Menu(self.root, tearoff=0, bg=self.theme["bar"],
                       fg=self.theme["fg"], bd=0,
                       activebackground=self.theme["accent"],
                       activeforeground=self.theme["on_accent"],
                       font=("Segoe UI", 9))
        menu.add_command(label=t("Open in folder"),
                         command=lambda: self._reveal_in_explorer(idx))
        menu.add_command(label=t("Make a duplicate"),
                         command=lambda: self._duplicate_photo(idx))
        menu.add_separator()
        menu.add_command(label=t("Delete permanently"), foreground="#ff8a8a",
                         command=lambda: self._delete_permanently(idx))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _thumb_target(self, idx):
        "The (file, absolute path) a thumbnail action acts on, or (None, None)."
        if not self.folder or not (0 <= idx < len(self.files)):
            return None, None
        file = self.files[idx]
        return file, os.path.join(self.folder, file)

    def _reveal_in_explorer(self, idx):
        "Open the file's folder in the OS file manager with the file itself selected."
        file, path = self._thumb_target(idx)
        if path is None:
            return
        self._reveal_path(path, select=True)

    def _duplicate_photo(self, idx):
        "Copy the file next to itself ('name (1).jpg') without leaving the open photo."
        file, path = self._thumb_target(idx)
        if path is None or not os.path.isfile(path):
            self.toast(t("File not found"))
            return
        dest = unique_path(path)
        try:
            shutil.copy2(path, dest)
        except Exception as e:
            self.toast(t("Error: {e}").format(e=e))
            return
        newname = os.path.basename(dest)
        # Slot the copy into the list but keep the currently-shown photo selected, so
        # an unsaved edit in the preview is never silently discarded.
        cur = self.files[self.index] if self.files else newname
        self.files.append(newname)
        self.files.sort(key=str.lower)       # match load_folder's ordering
        self.index = self.files.index(cur)
        self._build_thumbs()                 # strip only; the editor preview is untouched
        self.toast(t("Duplicated → {name}").format(name=newname))

    def _delete_permanently(self, idx):
        "Delete the file from disk for good (no undo) after a confirm."
        file, path = self._thumb_target(idx)
        if path is None:
            return
        if not self._confirm(
                t("Permanently delete “{name}”? This cannot be undone.").format(
                    name=file),
                ok_label=t("Delete")):
            return
        try:
            os.remove(path)
        except Exception as e:
            self.toast(t("Error: {e}").format(e=e))
            return
        cur = self.files[self.index] if self.files else None
        del self.files[idx]
        if cur is not None and cur in self.files:
            # Deleted some OTHER photo → keep the open one shown (preview untouched).
            self.index = self.files.index(cur)
            self._build_thumbs()
        else:
            # Deleted the open photo → fall to a neighbour and reload the preview.
            self.index = max(0, min(idx, len(self.files) - 1))
            self._build_thumbs()
            if self.files:
                self.show_current()
            else:
                self.load_folder(self.folder)
        self.toast(t("Deleted: {name}").format(name=file))

    # --- List-view name fitting (truncate filenames to the sidebar width) -----

    def _list_font(self):
        "Cached Font matching the list rows — used to measure text for ellipsizing."
        if getattr(self, "_list_font_obj", None) is None:
            self._list_font_obj = tkfont.Font(family="Segoe UI", size=9)
        return self._list_font_obj

    def _list_name_avail(self):
        "Pixels available for a list filename: the per-column width minus the thumb + pads."
        cols = max(1, getattr(self, "_thumb_cols", 1))
        return int(self.canvas.winfo_width() / cols) - self.LIST_THUMB - self.LIST_NAME_PAD

    def _fit_name(self, file):
        "Shorten `file` with a trailing '…' so it fits the available list width."
        return self._ellipsize(file, self._list_font(), self._list_name_avail())

    def _ellipsize(self, text, font, avail):
        "Return `text` trimmed with a trailing '…' so it measures <= avail px."
        if avail <= 0 or font.measure(text) <= avail:
            return text
        ell = "…"
        lo, hi = 0, len(text)
        while lo < hi:                       # binary-search the longest prefix that fits
            mid = (lo + hi + 1) // 2
            if font.measure(text[:mid] + ell) <= avail:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + ell

    def _reflow_list_names(self):
        "Re-fit every visible list filename to the current column width (after resize)."
        if self.view_mode != "list":
            return
        avail = self._list_name_avail()
        font = self._list_font()
        for cell in self._cells.values():
            lbl = getattr(cell, "_name_lbl", None)
            if lbl is None:
                continue
            try:
                lbl.configure(text=self._ellipsize(cell._file, font, avail))
            except tk.TclError:
                pass

    def _highlight_thumb(self):
        "Accent-border the current photo's cell; clear the rest (only visible cells exist)."
        for i, cell in self._cells.items():
            try:
                cell._holder.configure(
                    highlightbackground=self.theme["accent"] if i == self.index
                    else self.theme["sidebar"])
            except tk.TclError:
                pass

    def _scroll_to_thumb(self):
        "Scroll so the current photo's row is visible, then realize the new window."
        " Works in row units (self._scroll_row), never raw pixels — see"
        " _render_window for why the strip can't track a giant folder by pixel."
        n = len(self.files)
        if not (0 <= self.index < n):
            self._render_window()
            return
        cell_w, cell_h, cols = self._cell_metrics()
        total_rows = (n + cols - 1) // cols
        row = self.index // max(1, cols)
        visible_rows = max(1.0, self._canvas_view_h() / cell_h)
        scroll_row = getattr(self, "_scroll_row", 0.0)
        if row < scroll_row:                          # above the viewport → scroll up
            scroll_row = float(row)
        elif row >= scroll_row + visible_rows:        # below → scroll down
            scroll_row = row - visible_rows + 1
        max_scroll = max(0.0, total_rows - visible_rows)
        self._scroll_row = max(0.0, min(scroll_row, max_scroll))
        self._render_window()
