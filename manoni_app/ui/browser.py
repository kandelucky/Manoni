"""Folder browsing: the bottom nav bar, loading a folder, the minimalist
sub-folder list (top of the sidebar) and the image thumbnail grid (below it).

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import tkinter as tk
import tkinter.filedialog as tkfd
import tkinter.font as tkfont
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageTk

from ..config import BAR, SIDEBAR, HOVER, ACCENT, FG, FG_DIM, SUPPORTED, ICON_DIR
from ..i18n import t
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
        bar = tk.Frame(self.body, bg=BAR, height=34)
        bar.grid(row=2, column=2, sticky="ew")
        bar.grid_propagate(False)

        # RIGHT: navigation arrows, then the position counter.
        nav = tk.Frame(bar, bg=BAR)
        nav.pack(side="right", padx=8)
        for icon_name, command, tip in [
            ("chevrons-left", self.first, t("First")),
            ("chevron-left", self.prev, t("Previous")),
            ("chevron-right", self.next, t("Next")),
            ("chevrons-right", self.last, t("Last")),
        ]:
            self._tool_button(nav, icon_name, command, tip).pack(side="left", padx=4, pady=4)
        self.lbl_pos = tk.Label(nav, text="0 / 0", bg=BAR, fg=FG_DIM,
                                font=("Segoe UI", 9))
        self.lbl_pos.pack(side="left", padx=10)

        # CENTER: rotate the current photo (truly centered over the strip).
        rot = tk.Frame(bar, bg=BAR)
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
        zone = tk.Frame(bar, bg=BAR)
        zone.pack(side="left", padx=10)

        # Quick-size preset chips: Fit · 50% · 100% · 200%.
        self.zoom_presets = []
        for label, scale in self.ZOOM_PRESETS:
            chip = tk.Label(zone, text=label, bg=BAR, fg=FG_DIM, cursor="hand2",
                            font=("Segoe UI", 8, "bold"), padx=6, pady=2)
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
        self.lbl_zoom = tk.Label(zone, text="—", bg=BAR, fg=FG, width=6,
                                 font=("Segoe UI", 9, "bold"))
        self.lbl_zoom.pack(side="left")
        self._tool_button(zone, "zoom-in", self.zoom_in,
                          t("Zoom in")).pack(side="left", padx=2)

    def _chip_hover(self, chip, entering):
        "Brighten a quick-size chip on hover; the active one stays accent-colored."
        if self._chip_active(chip):
            return
        chip.configure(fg=FG if entering else FG_DIM)

    # --- Folder + files -----------------------------------------------------

    def load_folder(self, folder, select=None):
        "Load all images in a folder and show the first one (or `select`, if given)."
        self.folder = folder
        self._update_breadcrumbs()       # refresh the address bar to the new folder
        try:
            entries = sorted(os.listdir(folder), key=str.lower)
        except OSError:
            entries = []
        # Sub-folders shown as tiles atop the grid so you can browse into them;
        # hidden (dot-prefixed) folders are skipped.
        self.subfolders = [
            (name, os.path.join(folder, name))
            for name in entries
            if not name.startswith(".")
            and os.path.isdir(os.path.join(folder, name))]
        self.files = [
            f for f in entries
            if os.path.splitext(f)[1].lower() in SUPPORTED
            and os.path.isfile(os.path.join(folder, f))]
        self.index = self.files.index(select) if select in self.files else 0
        self._build_folder_list()        # top section: minimalist sub-folder list
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
        # Sub-folders are NOT in this strip — they live in the auto-height list above
        # it (_build_folder_list), so the strip is pure photos.
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

    def _layout_strip(self):
        "Size the inner holder to the full content height so the scrollbar reflects all"
        " files even though only the visible cells exist."
        cell_w, cell_h, cols = self._cell_metrics()
        n = len(self.files)
        rows = (n + cols - 1) // cols if cols else 0
        content_h = max(1, rows * cell_h)
        view_w = max(1, self.canvas.winfo_width())
        try:
            self.canvas.itemconfigure(self._thumb_window, width=view_w,
                                      height=content_h)
            self.canvas.configure(scrollregion=(0, 0, view_w, content_h))
        except tk.TclError:
            pass

    def _visible_range(self, cell_h, cols):
        "First/last file index inside the viewport, padded by THUMB_BUFFER_ROWS rows."
        n = len(self.files)
        if n == 0 or cols <= 0:
            return 0, -1
        try:
            self.canvas.update_idletasks()
            view_h = self.canvas.winfo_height()
            top = self.canvas.canvasy(0)
        except tk.TclError:
            view_h, top = 0, 0
        if view_h <= 1:
            view_h = 600                 # canvas not laid out yet → assume a screenful
        first_row = max(0, int(top // cell_h) - self.THUMB_BUFFER_ROWS)
        last_row = int((top + view_h) // cell_h) + self.THUMB_BUFFER_ROWS
        first = first_row * cols
        last = min(n - 1, (last_row + 1) * cols - 1)
        return first, max(first - 1, last)

    # --- Realize / recycle the visible window ------------------------------------

    def _render_window(self):
        "Create the cells now in the viewport, destroy those that scrolled out, and"
        " request decodes for the freshly-visible ones. Cheap to call on every scroll."
        if not hasattr(self, "thumb_holder") or not self.files:
            return
        cell_w, cell_h, cols = self._cell_metrics()
        self._thumb_cols = cols
        first, last = self._visible_range(cell_h, cols)
        want = set(range(first, last + 1))
        for i in list(self._cells):
            if i not in want:
                self._destroy_cell(i)
        for i in range(first, last + 1):
            if i not in self._cells:
                self._make_cell_at(i, cell_w, cell_h, cols)
            self._request_decode(i)
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
        "Build one placeholder cell for file index i and place it at its fixed slot."
        file = self.files[i]
        row, col = divmod(i, cols)
        if self.view_mode == "list":
            cell = self._make_list_cell(i, file)
            cell.place(x=col * cell_w + 2, y=row * cell_h + 1,
                       width=cell_w - 4, height=cell_h - 2)
        else:
            cell = self._make_grid_cell(i, file)
            cell.place(x=col * cell_w, y=row * cell_h,
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

    def _build_folder_list(self):
        "Fill the top folder section with one compact row per sub-folder; hide it"
        " entirely when the open folder has none (see chrome._build_folder_panel)."
        for w in self.folder_holder.winfo_children():
            w.destroy()
        self.folder_widgets = []
        self._folder_name_labels = []        # (name Label, full name) for width-reflow
        if not self.subfolders:
            self.folder_panel.pack_forget()
            return
        for name, full in self.subfolders:
            self._add_folder_row(name, full)
        self._folder_cols = self._calc_folder_cols()
        self._place_folder_rows()            # 1 or 2 columns, by sidebar width
        self.folder_panel.pack(side="top", fill="x", before=self._thumb_scrollbar)
        self.folder_holder.update_idletasks()
        self._on_folder_holder_configure()   # size the list to its content (capped)
        self._fit_folder_names()             # ellipsize names to the column width

    def _folder_glyph(self):
        "A small white folder glyph for a list row (cached; falls back to an emoji)."
        if "list" in self._folder_imgs:
            return self._folder_imgs["list"]
        img = None
        path = os.path.join(ICON_DIR, "folder.png")
        if os.path.exists(path):
            try:
                im = Image.open(path).convert("RGBA").resize((14, 14), Image.LANCZOS)
                img = ImageTk.PhotoImage(im)
            except Exception:
                img = None
        self._folder_imgs["list"] = img
        return img

    def _add_folder_row(self, name, fullpath):
        "Build one minimalist folder cell (glyph + name, hover, click to open). It is"
        " placed into the 1- or 2-column grid later by _place_folder_rows."
        img = self._folder_glyph()
        row = tk.Frame(self.folder_holder, bg=SIDEBAR, cursor="hand2")
        if img is not None:
            icon = tk.Label(row, image=img, bg=SIDEBAR)
        else:
            icon = tk.Label(row, text="📁", bg=SIDEBAR, fg=FG_DIM,
                            font=("Segoe UI", 9))
        icon.pack(side="left", padx=(10, 6), pady=3)
        lbl = tk.Label(row, text=self._fit_folder(name), bg=SIDEBAR, fg=FG,
                       anchor="w", font=("Segoe UI", 9))
        lbl.pack(side="left", fill="x", expand=True, pady=3)
        self._folder_name_labels.append((lbl, name))
        cells = (row, icon, lbl)

        def enter(_e):
            for w in cells:
                w.configure(bg=HOVER)

        def leave(_e):
            for w in cells:
                w.configure(bg=SIDEBAR)
        for w in cells:
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)
            w.bind("<Button-1>", lambda e, p=fullpath: self._navigate_to(p))
            w.bind("<MouseWheel>", self._on_folder_wheel)
        self.folder_widgets.append(row)

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
        cell = tk.Frame(self.thumb_holder, bg=SIDEBAR)
        box = max(1, self.thumb_size)
        holder = tk.Frame(cell, bg=SIDEBAR, highlightthickness=2,
                          highlightbackground=ACCENT if sel else SIDEBAR,
                          width=box, height=box)
        holder.pack_propagate(False)     # fixed square box → uniform rows for windowing
        holder.pack(pady=(2, 0))
        lbl = tk.Label(holder, bg=SIDEBAR, cursor="hand2")
        lbl.place(relx=0.5, rely=0.5, anchor="center")   # center the image in the box
        name = tk.Label(cell, text=self._short_name(file), bg=SIDEBAR,
                        fg=FG_DIM, font=("Segoe UI", 7))
        name.pack()
        cell._holder = holder            # the bordered frame we recolor to select
        cell._img_lbl = lbl              # the label the decode poll fills with the thumb
        for w in (lbl, holder, name, cell):
            w.bind("<MouseWheel>", self._on_wheel)
            w.bind("<Button-1>", lambda e, idx=i: self.go_to(idx))
        return cell

    def _make_list_cell(self, i, file):
        "A placeholder list row: a fixed tiny preview box + the (ellipsized) filename."
        sel = (i == self.index)
        cell = tk.Frame(self.thumb_holder, bg=SIDEBAR)
        holder = tk.Frame(cell, bg=SIDEBAR,
                          highlightthickness=2,
                          highlightbackground=ACCENT if sel else SIDEBAR)
        holder.pack(fill="both", expand=True)
        box = tk.Frame(holder, bg=SIDEBAR, width=self.LIST_THUMB,
                       height=self.LIST_THUMB)
        box.pack_propagate(False)
        box.pack(side="left", padx=(4, 8), pady=2)
        lbl = tk.Label(box, bg=SIDEBAR, cursor="hand2")
        lbl.place(relx=0.5, rely=0.5, anchor="center")
        # The name is ellipsized to the current column width so a long filename fits
        # the row instead of spilling past the right edge (re-fitted by
        # _reflow_list_names on resize). anchor="w" keeps it left-aligned.
        name = tk.Label(holder, text=self._fit_name(file), bg=SIDEBAR, fg=FG,
                        anchor="w", cursor="hand2", font=("Segoe UI", 9))
        name.pack(side="left", fill="x", expand=True)
        cell._holder = holder            # the bordered frame we recolor to select
        cell._img_lbl = lbl
        cell._name_lbl = name            # re-ellipsized on resize
        cell._file = file
        for w in (cell, holder, box, lbl, name):
            w.bind("<MouseWheel>", self._on_wheel)
            w.bind("<Button-1>", lambda e, idx=i: self.go_to(idx))
        return cell

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

    # --- Folder-name fitting (truncate sub-folder names to the column width) ---

    def _folder_name_avail(self):
        "Pixels available for a folder name: the canvas width per column minus the glyph."
        cols = max(1, getattr(self, "_folder_cols", 1))
        return int(self.folder_canvas.winfo_width() / cols) - self.FOLDER_NAME_PAD

    def _fit_folder(self, name):
        "Shorten a sub-folder `name` with a trailing '…' so it fits its column width."
        return self._ellipsize(name, self._list_font(), self._folder_name_avail())

    def _fit_folder_names(self):
        "Re-fit every sub-folder name to the current column width (after resize/reflow)."
        if not getattr(self, "_folder_name_labels", None):
            return
        avail = self._folder_name_avail()
        font = self._list_font()
        for lbl, full in self._folder_name_labels:
            try:
                lbl.configure(text=self._ellipsize(full, font, avail))
            except tk.TclError:
                pass

    def _highlight_thumb(self):
        "Accent-border the current photo's cell; clear the rest (only visible cells exist)."
        for i, cell in self._cells.items():
            try:
                cell._holder.configure(
                    highlightbackground=ACCENT if i == self.index else SIDEBAR)
            except tk.TclError:
                pass

    def _scroll_to_thumb(self):
        "Scroll so the current photo's row is visible, then realize the new window."
        n = len(self.files)
        if not (0 <= self.index < n):
            self._render_window()
            return
        cell_w, cell_h, cols = self._cell_metrics()
        rows = (n + cols - 1) // cols if cols else 0
        total = max(1, rows * cell_h)
        y = (self.index // max(1, cols)) * cell_h
        try:
            self.canvas.update_idletasks()
            view_h = self.canvas.winfo_height()
            if view_h <= 1:
                view_h = 600
            top = self.canvas.canvasy(0)
            if y < top:                              # row above the viewport → scroll up
                self.canvas.yview_moveto(max(0.0, y / total))
            elif y + cell_h > top + view_h:          # below → scroll down
                self.canvas.yview_moveto(max(0.0, (y + cell_h - view_h) / total))
        except tk.TclError:
            pass
        self._render_window()
