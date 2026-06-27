"""Folder browsing: the bottom nav bar, loading a folder, the minimalist
sub-folder list (top of the sidebar) and the image thumbnail grid (below it).

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import tkinter as tk
import tkinter.filedialog as tkfd
import tkinter.font as tkfont

from PIL import Image, ImageTk

from ..config import BAR, SIDEBAR, HOVER, ACCENT, FG, FG_DIM, SUPPORTED, ICON_DIR
from ..i18n import t


class BrowserMixin:
    # --- Bottom navigation --------------------------------------------------

    def _build_bottombar(self):
        # The bottom strip is part of the EDITOR CANVAS, so it spans only the
        # preview column (col 2). In edit mode the full-height tool panels (cols
        # 3-4) sit beside it and clip it on the right.
        bar = tk.Frame(self.body, bg=BAR, height=34)
        bar.grid(row=1, column=2, sticky="ew")
        bar.grid_propagate(False)

        # RIGHT: navigation arrows, then the position counter.
        nav = tk.Frame(bar, bg=BAR)
        nav.pack(side="right", padx=8)
        for icon_name, command, tip in [
            ("chevrons-left", self.first, t("პირველი")),
            ("chevron-left", self.prev, t("წინა")),
            ("chevron-right", self.next, t("შემდეგი")),
            ("chevrons-right", self.last, t("ბოლო")),
        ]:
            self._tool_button(nav, icon_name, command, tip).pack(side="left", padx=4, pady=4)
        self.lbl_pos = tk.Label(nav, text="0 / 0", bg=BAR, fg=FG_DIM,
                                font=("Segoe UI", 9))
        self.lbl_pos.pack(side="left", padx=10)

        # CENTER: rotate the current photo (truly centered over the strip).
        rot = tk.Frame(bar, bg=BAR)
        rot.place(relx=0.5, rely=0.5, anchor="center")
        for icon_name, command, tip in [
            ("rotate-ccw", self.rotate_left, t("მარცხნივ ამოტრიალება")),
            ("rotate-cw", self.rotate_right, t("მარჯვნივ ამოტრიალება")),
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
                          t("დაპატარავება")).pack(side="left", padx=2)
        self.lbl_zoom = tk.Label(zone, text="—", bg=BAR, fg=FG, width=6,
                                 font=("Segoe UI", 9, "bold"))
        self.lbl_zoom.pack(side="left")
        self._tool_button(zone, "zoom-in", self.zoom_in,
                          t("გადიდება")).pack(side="left", padx=2)

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
        self._build_thumbs()             # bottom section: photo thumbnail grid
        if self.files:
            self.show_current()
        else:
            self.current_pil = None
            self._message = t("ფოტოები ვერ მოიძებნა")
            self._render_preview()
            self.lbl_name.configure(text="Manoni")
            self.lbl_info.configure(text="")
            self.lbl_pos.configure(text="0 / 0")
            self._save_state()

    def open_folder(self):
        folder = tkfd.askdirectory(parent=self.root,
                                   initialdir=self.folder or os.path.expanduser("~"))
        if folder:
            self.load_folder(folder)

    # --- Thumbnails ---------------------------------------------------------

    def _build_thumbs(self):
        "Rebuild the sidebar thumbnail grid (loaded incrementally so UI stays responsive)."
        if self._thumb_job is not None:
            self.root.after_cancel(self._thumb_job)
            self._thumb_job = None
        for w in self.thumb_holder.winfo_children():
            w.destroy()
        self.thumb_images = []
        self.thumb_widgets = []         # cell frame per file index (None on failure)
        self._list_name_labels = []     # (name Label, full filename) for width-reflow
        self._thumb_idx = 0
        self._thumb_pos = 0
        self._thumb_cols = self._calc_cols()
        # Set the column weights for this view: list columns stretch equally (so the
        # rows fill the panel and tile into 2/3/4…); grid cells stay fixed + centered.
        self._config_thumb_columns(self._thumb_cols)
        # Sub-folders are NOT in this grid anymore — they live in the auto-height
        # list above it (_build_folder_list), so the grid is pure photos.
        self._thumb_job = self.root.after(1, self._add_thumb)

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
        try:
            if not self.thumb_holder.winfo_exists():
                return
        except tk.TclError:
            return
        if self._thumb_idx >= len(self.files):
            self._thumb_job = None
            self._highlight_thumb()      # re-mark the current image once loaded
            return

        i = self._thumb_idx
        file = self.files[i]
        # List view shows a tiny preview beside the name; grid view a big icon.
        tsize = self.LIST_THUMB if self.view_mode == "list" else self.thumb_size
        try:
            with Image.open(os.path.join(self.folder, file)) as im:
                im.thumbnail((tsize, tsize))
                im = im.convert("RGB")
                photo = ImageTk.PhotoImage(im)
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
