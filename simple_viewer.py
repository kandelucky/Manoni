"""A dead-simple dark photo viewer.

Two panels — a thumbnail strip down the LEFT and a control bar along the
BOTTOM — with the selected photo opening in the MIDDLE. Nothing else: no
editing, no culling, no menus. Just look at photos.

Run:   python simple_viewer.py [folder]
Stack: standard library + Pillow (same as Manoni).
"""

import os
import sys
import tkinter as tk
import tkinter.filedialog as tkfd

from PIL import Image, ImageTk

from manoni_app.scaling import set_dpi_awareness, apply_tk_scaling

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}

# Dark theme.
BG     = "#1b1b1b"   # photo background
PANEL  = "#1e1e1e"   # side strip
BAR    = "#262626"   # bottom bar
HOVER  = "#3a3a3a"
ACCENT = "#4aa3ff"   # selected thumbnail border
FG     = "#e6e6e6"
FG_DIM = "#9a9a9a"

THUMB = 92           # thumbnail size in the side strip (px)


class SimpleViewer:
    def __init__(self, folder=None):
        # Declare DPI awareness BEFORE the first window so Windows draws at the
        # monitor's true pixels (crisp) instead of bitmap-stretching (blurry at
        # 150 % scaling); then tell Tk the real DPI so fonts stay correctly sized.
        set_dpi_awareness()
        self.root = tk.Tk()
        self.dpi = apply_tk_scaling(self.root)
        self.root.title("Viewer")
        self.root.configure(bg=BG)
        self.root.geometry("1100x720")

        self.folder = None
        self.files = []
        self.index = 0
        self.current = None       # PhotoImage of the centre photo (kept alive)
        self.thumbs = []          # thumbnail PhotoImages (kept alive)
        self.thumb_rows = []      # the row frame per file (for selection); may be None
        self._thumb_job = None    # incremental thumbnail-loader handle

        self._build_ui()

        # Keyboard: arrows to move, Esc to quit.
        self.root.bind("<Left>", lambda e: self.show(self.index - 1))
        self.root.bind("<Right>", lambda e: self.show(self.index + 1))
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        if folder and os.path.isdir(folder):
            self.load(folder)

    # --- Layout: side strip (left) · photo (centre) · control bar (bottom) ---

    def _build_ui(self):
        self.root.rowconfigure(0, weight=1)     # content row expands
        self.root.rowconfigure(1, weight=0)     # bottom bar fixed
        self.root.columnconfigure(0, weight=0)  # side strip fixed width
        self.root.columnconfigure(1, weight=1)  # photo expands

        # LEFT panel: a scrollable vertical strip of thumbnails.
        side = tk.Frame(self.root, bg=PANEL, width=THUMB + 34)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        self.canvas = tk.Canvas(side, bg=PANEL, highlightthickness=0)
        sb = tk.Scrollbar(side, orient="vertical", command=self.canvas.yview)
        self.strip = tk.Frame(self.canvas, bg=PANEL)
        self.strip.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.strip, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        for w in (self.canvas, self.strip):
            w.bind("<MouseWheel>", self._wheel)

        # CENTRE: the photo, fit to the area and re-fit on resize.
        self.photo = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.photo.grid(row=0, column=1, sticky="nsew")
        self.photo.bind("<Configure>", lambda e: self._render())

        # BOTTOM panel: open · ‹ prev · name · next › · counter.
        bar = tk.Frame(self.root, bg=BAR, height=44)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        self._btn(bar, "გახსნა", self.open_folder).pack(side="left", padx=(10, 14), pady=7)
        self._btn(bar, "‹", lambda: self.show(self.index - 1)).pack(side="left", padx=2)
        self._btn(bar, "›", lambda: self.show(self.index + 1)).pack(side="left", padx=2)
        self.lbl_count = tk.Label(bar, text="0 / 0", bg=BAR, fg=FG_DIM,
                                  font=("Segoe UI", 9))
        self.lbl_count.pack(side="right", padx=14)
        self.lbl_name = tk.Label(bar, text="← გახსენი ფოლდერი", bg=BAR, fg=FG_DIM,
                                 font=("Segoe UI", 9))
        self.lbl_name.pack(side="left", padx=12)

    def _btn(self, parent, text, command):
        "A flat text button with a hover highlight."
        b = tk.Label(parent, text=text, bg=BAR, fg=FG, cursor="hand2",
                     font=("Segoe UI", 11), padx=10, pady=4)
        b.bind("<Enter>", lambda e: b.configure(bg=HOVER))
        b.bind("<Leave>", lambda e: b.configure(bg=BAR))
        b.bind("<Button-1>", lambda e: command())
        return b

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    # --- Loading a folder ---------------------------------------------------

    def open_folder(self):
        folder = tkfd.askdirectory(initialdir=self.folder or os.path.expanduser("~"))
        if folder:
            self.load(folder)

    def load(self, folder):
        "Read the images in a folder, build the strip, show the first photo."
        self.folder = folder
        try:
            entries = sorted(os.listdir(folder), key=str.lower)
        except OSError:
            entries = []
        self.files = [f for f in entries
                      if os.path.splitext(f)[1].lower() in SUPPORTED
                      and os.path.isfile(os.path.join(folder, f))]
        self.index = 0
        self._build_thumbs()
        if self.files:
            self.show(0)
        else:
            self._clear()

    def _build_thumbs(self):
        "Clear the strip and (re)start loading thumbnails incrementally."
        if self._thumb_job is not None:
            self.root.after_cancel(self._thumb_job)
            self._thumb_job = None
        for w in self.strip.winfo_children():
            w.destroy()
        self.thumbs = []
        self.thumb_rows = []
        self._ti = 0
        self._thumb_job = self.root.after(1, self._add_thumb)

    def _add_thumb(self):
        "Load one thumbnail per tick so a big folder never freezes the window."
        if self._ti >= len(self.files):
            self._thumb_job = None
            self._highlight()
            return
        i, file = self._ti, self.files[self._ti]
        try:
            with Image.open(os.path.join(self.folder, file)) as im:
                im.thumbnail((THUMB, THUMB))
                im = im.convert("RGB")
                ph = ImageTk.PhotoImage(im)
            self.thumbs.append(ph)
            row = tk.Frame(self.strip, bg=PANEL, cursor="hand2",
                           highlightthickness=2, highlightbackground=PANEL)
            row.pack(fill="x", padx=6, pady=4)
            lbl = tk.Label(row, image=ph, bg=PANEL, cursor="hand2")
            lbl.pack(padx=2, pady=2)
            for w in (row, lbl):
                w.bind("<Button-1>", lambda e, idx=i: self.show(idx))
                w.bind("<MouseWheel>", self._wheel)
            self.thumb_rows.append(row)
        except Exception:
            self.thumb_rows.append(None)
        self._ti += 1
        self._thumb_job = self.root.after(1, self._add_thumb)

    # --- Showing the centre photo -------------------------------------------

    def show(self, index):
        "Select an image: render it in the centre and highlight its thumbnail."
        if not self.files:
            return
        self.index = index % len(self.files)
        self._render()
        self._highlight()
        self._scroll_to()
        self.lbl_name.configure(text=self.files[self.index], fg=FG)
        self.lbl_count.configure(text=f"{self.index + 1} / {len(self.files)}")
        self.root.title(f"{self.files[self.index]} — Viewer")

    def _render(self):
        "Fit the current photo to the centre canvas (preserve aspect, centred)."
        if not self.files:
            return
        cw, ch = self.photo.winfo_width(), self.photo.winfo_height()
        if cw <= 1 or ch <= 1:
            return
        try:
            with Image.open(os.path.join(self.folder, self.files[self.index])) as im:
                im = im.convert("RGB")
                scale = min(cw / im.width, ch / im.height)
                w = max(1, int(im.width * scale))
                h = max(1, int(im.height * scale))
                self.current = ImageTk.PhotoImage(im.resize((w, h), Image.LANCZOS))
        except Exception:
            return
        self.photo.delete("all")
        self.photo.create_image(cw // 2, ch // 2, image=self.current, anchor="center")

    def _highlight(self):
        "Mark the selected thumbnail with an accent border."
        for i, row in enumerate(self.thumb_rows):
            if row is None:
                continue
            try:
                row.configure(highlightbackground=ACCENT if i == self.index else PANEL)
            except tk.TclError:
                pass

    def _scroll_to(self):
        "Scroll the strip so the selected thumbnail stays visible."
        if not (0 <= self.index < len(self.thumb_rows)):
            return
        row = self.thumb_rows[self.index]
        if row is None:
            return
        try:
            self.canvas.update_idletasks()
            total = self.strip.winfo_height()
            view = self.canvas.winfo_height()
            if total <= 1 or view <= 1:
                return
            y, h = row.winfo_y(), row.winfo_height()
            top = self.canvas.canvasy(0)
            if y < top:
                self.canvas.yview_moveto(max(0.0, y / total))
            elif y + h > top + view:
                self.canvas.yview_moveto(max(0.0, (y + h - view) / total))
        except tk.TclError:
            pass

    def _clear(self):
        "No images in the folder: blank the centre and the labels."
        self.current = None
        self.photo.delete("all")
        self.lbl_name.configure(text="ფოტო ვერ მოიძებნა", fg=FG_DIM)
        self.lbl_count.configure(text="0 / 0")

    def run(self):
        self.root.mainloop()


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    SimpleViewer(folder).run()


if __name__ == "__main__":
    main()
