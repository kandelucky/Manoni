"""Folder browsing: the bottom nav bar, loading a folder, the minimalist
sub-folder list (top of the sidebar) and the image thumbnail grid (below it).

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import time
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
# cache is unavailable). Re-exported here so gridview, which does
# `from .browser import _decode_thumb`, shares the same cached path.
from ..thumbcache import cached_thumb as _decode_thumb  # noqa: F401

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
        # A big folder takes a while to thumbnail; cover the window with a dark,
        # input-blocking "please wait" screen so a stray slider drag or key press
        # can't corrupt the half-loaded grid. It lifts as the last thumbnail lands.
        if len(self.files) >= self.LOADING_OVERLAY_MIN:
            self._show_loading_overlay(len(self.files))
        self._build_folder_list()        # top section: minimalist sub-folder list
        self._build_thumbs()             # bottom section: photo thumbnail grid
        self._refresh_grid_if_open()     # rebuild the full-area grid for the new folder
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

    def _build_thumbs(self):
        "Rebuild the sidebar thumbnail grid: decode in parallel worker threads,"
        " build the Tk cells on the main thread in time-budgeted batches."
        if self._thumb_job is not None:
            self.root.after_cancel(self._thumb_job)
            self._thumb_job = None
        self._shutdown_decode_pool()    # abandon any in-flight decodes from a prior load
        for w in self.thumb_holder.winfo_children():
            w.destroy()
        self.thumb_images = []
        self.thumb_widgets = []         # cell frame per file index (None on failure)
        self._list_name_labels = []     # (name Label, full filename) for width-reflow
        self._thumb_idx = 0             # next file to turn into a cell (main thread)
        self._submit_idx = 0            # next file handed to the decode pool
        self._thumb_pos = 0
        self._decode_tsize = self.LIST_THUMB if self.view_mode == "list" \
            else self.thumb_size
        self._thumb_cols = self._calc_cols()
        # Set the column weights for this view: list columns stretch equally (so the
        # rows fill the panel and tile into 2/3/4…); grid cells stay fixed + centered.
        self._config_thumb_columns(self._thumb_cols)
        # Sub-folders are NOT in this grid anymore — they live in the auto-height
        # list above it (_build_folder_list), so the grid is pure photos.
        if self.files:
            workers = min(8, (os.cpu_count() or 4))
            self._decode_pool = ThreadPoolExecutor(max_workers=workers)
            self._decode_futures = {}
            self._top_up_decodes()      # prime the decode window before the first cell
        self._thumb_job = self.root.after(1, self._add_thumb)

    # --- Parallel thumbnail decode (worker pool) ----------------------------

    def _top_up_decodes(self):
        "Keep the decode pipeline a fixed distance ahead of the cells we've built —"
        " bounds memory (only ~DECODE_WINDOW thumbnails are ever held decoded)."
        pool = self._decode_pool
        if pool is None:
            return
        target = min(len(self.files), self._thumb_idx + self.DECODE_WINDOW)
        while self._submit_idx < target:
            i = self._submit_idx
            path = os.path.join(self.folder, self.files[i])
            self._decode_futures[i] = pool.submit(
                _decode_thumb, path, self._decode_tsize)
            self._submit_idx += 1

    def _shutdown_decode_pool(self):
        "Cancel pending decodes and drop the pool (safe when there is none)."
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

    def _add_thumb(self):
        "Drain freshly-decoded thumbnails (in file order) into grid cells, for up to"
        " THUMB_BUDGET seconds, then yield so the progress bar repaints; repeat."
        try:
            if not self.thumb_holder.winfo_exists():
                return
        except tk.TclError:
            return

        deadline = time.perf_counter() + self.THUMB_BUDGET
        while self._thumb_idx < len(self.files):
            self._top_up_decodes()       # keep the workers fed as we consume
            fut = self._decode_futures.get(self._thumb_idx)
            if fut is None or not fut.done():
                break                    # next-in-order not decoded yet → yield, retry
            pil = fut.result()           # None if the file couldn't be read
            del self._decode_futures[self._thumb_idx]
            i = self._thumb_idx
            file = self.files[i]
            try:
                if pil is None:
                    raise ValueError("decode failed")
                photo = ImageTk.PhotoImage(pil)
                self.thumb_images.append(photo)
                if self.view_mode == "list":
                    cell = self._add_list_row(i, file, photo)
                else:
                    cell = self._add_grid_cell(i, file, photo)
                self.thumb_widgets.append(cell)
                self._thumb_pos += 1
            except Exception:
                self.thumb_widgets.append(None)
            self._thumb_idx += 1
            if time.perf_counter() >= deadline:
                break

        self._update_loading_overlay(self._thumb_idx, len(self.files))
        if self._thumb_idx >= len(self.files):
            self._thumb_job = None
            self._shutdown_decode_pool()
            self._highlight_thumb()      # re-mark the current image once loaded
            self._hide_loading_overlay()  # grid is built → drop the "please wait" screen
            return
        self._thumb_job = self.root.after(1, self._add_thumb)

    def _add_grid_cell(self, i, file, photo):
        "Build one grid cell: a bordered image (for selection) + its name below."
        cell = tk.Frame(self.thumb_holder, bg=SIDEBAR)
        holder = tk.Frame(cell, bg=SIDEBAR,
                          highlightthickness=2, highlightbackground=SIDEBAR)
        holder.pack()
        lbl = tk.Label(holder, image=photo, bg=SIDEBAR, cursor="hand2")
        lbl.pack()
        name = tk.Label(cell, text=self._short_name(file), bg=SIDEBAR,
                        fg=FG_DIM, font=("Segoe UI", 7),
                        wraplength=self.thumb_size)
        name.pack()
        cell._holder = holder            # the bordered frame we recolor to select
        pos, cols = self._thumb_pos, self._thumb_cols
        cell.grid(row=pos // cols, column=pos % cols, padx=4, pady=4, sticky="n")
        for w in (lbl, holder, name, cell):
            w.bind("<MouseWheel>", self._on_wheel)
            w.bind("<Button-1>", lambda e, idx=i: self.go_to(idx))
        return cell

    def _add_list_row(self, i, file, photo):
        "Build one list row: a tiny preview + the filename, truncated to fit the width."
        cell = tk.Frame(self.thumb_holder, bg=SIDEBAR)
        holder = tk.Frame(cell, bg=SIDEBAR,
                          highlightthickness=2, highlightbackground=SIDEBAR)
        holder.pack(fill="x")
        thumb = tk.Label(holder, image=photo, bg=SIDEBAR, cursor="hand2")
        thumb.pack(side="left", padx=(4, 8), pady=2)
        # The name is ellipsized to the current sidebar width so a long filename
        # fits the row instead of spilling past the right edge (and is re-fitted on
        # resize by _reflow_list_names). anchor="w" keeps it left-aligned.
        name = tk.Label(holder, text=self._fit_name(file), bg=SIDEBAR, fg=FG,
                        anchor="w", cursor="hand2", font=("Segoe UI", 9))
        name.pack(side="left", fill="x", expand=True)
        self._list_name_labels.append((name, file))
        cell._holder = holder            # the bordered frame we recolor to select
        pos, cols = self._thumb_pos, self._thumb_cols
        cell.grid(row=pos // cols, column=pos % cols, padx=2, pady=1, sticky="ew")
        for w in (cell, holder, thumb, name):
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
        "Re-fit every list filename to the current sidebar width (after a resize)."
        if self.view_mode != "list" or not getattr(self, "_list_name_labels", None):
            return
        avail = self._list_name_avail()
        font = self._list_font()
        for lbl, full in self._list_name_labels:
            try:
                lbl.configure(text=self._ellipsize(full, font, avail))
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
        for i, cell in enumerate(self.thumb_widgets):
            if cell is None:
                continue
            try:
                cell._holder.configure(
                    highlightbackground=ACCENT if i == self.index else SIDEBAR)
            except tk.TclError:
                pass

    def _scroll_to_thumb(self):
        "Scroll the grid so the selected thumbnail is visible (no-op if not loaded yet)."
        if not (0 <= self.index < len(self.thumb_widgets)):
            return
        cell = self.thumb_widgets[self.index]
        if cell is None:
            return
        try:
            self.canvas.update_idletasks()
            total = self.thumb_holder.winfo_height()
            view_h = self.canvas.winfo_height()
            if total <= 1 or view_h <= 1:
                return
            y, h = cell.winfo_y(), cell.winfo_height()
            top = self.canvas.canvasy(0)
            if y < top:                              # above the viewport → scroll up
                self.canvas.yview_moveto(max(0.0, y / total))
            elif y + h > top + view_h:               # below → scroll down
                self.canvas.yview_moveto(max(0.0, (y + h - view_h) / total))
        except tk.TclError:
            pass
