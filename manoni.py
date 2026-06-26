"""Manoni - a fast, simple dark photo browser + culler.

Runs on a weak laptop. Pure Python + Tkinter + Pillow (MIT-friendly stack).
Built fresh (NOT on Blurry's keyboard engine) so the code is ours and easy to extend.

Current state (first increment): the interface shell (ImageGlass-style, dark theme)
with working browsing, folder open, delete (safe, reversible) and move-to-folder.
Editing (resize / brightness / filter) is stubbed - that is the next work.

Run:  python manoni.py [optional_folder]
See:  spec/00-START-HERE.md
"""

import os
import sys
import shutil
import datetime
import tkinter as tk
import tkinter.ttk as ttk
import tkinter.filedialog as tkfd

from PIL import Image, ImageTk, ImageEnhance

# --- Config -----------------------------------------------------------------

# Icons live next to this file in ./icons (Lucide, white strokes on transparent)
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}

# Dark theme colors
BG        = "#1b1b1b"   # main background
BAR       = "#262626"   # toolbar / info bar
SIDEBAR   = "#1e1e1e"   # sidebar background
HOVER     = "#3a3a3a"   # button hover
ACCENT    = "#4aa3ff"   # selection / highlight
FG        = "#e6e6e6"   # primary text
FG_DIM    = "#9a9a9a"   # secondary text

ICON_SIZE = 22
THUMB_W   = 150


class Slider:
    """A clean, dark, custom-drawn horizontal slider (Canvas-based).

    Layout per slider:  label (top-left)            value (top-right)
                        ───────────●───────────────  (track + knob)
    The fill runs from the neutral point to the knob, so you can see at a
    glance how far an edit deviates from "unchanged".
    """
    W       = 220   # widget width
    H       = 50    # widget height
    PAD     = 10    # left/right inset for the track
    TRACK_Y = 38    # track baseline
    KNOB_R  = 7     # knob radius
    TRACK   = "#3a3a3a"
    KNOB    = "#f0f0f0"

    def __init__(self, parent, label, command, lo=0, hi=200, neutral=100):
        self.label = label
        self.command = command          # called with the int value on change
        self.lo, self.hi = lo, hi
        self.neutral = neutral
        self.value = neutral
        self.x0 = self.PAD
        self.x1 = self.W - self.PAD
        self.canvas = tk.Canvas(parent, width=self.W, height=self.H, bg=BAR,
                                highlightthickness=0, cursor="hand2")
        self.canvas.bind("<Button-1>", self._on_drag)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self._draw()

    def pack(self, **kw):
        self.canvas.pack(**kw)
        return self

    def _val_to_x(self, v):
        frac = (v - self.lo) / (self.hi - self.lo)
        return self.x0 + frac * (self.x1 - self.x0)

    def _x_to_val(self, x):
        frac = (x - self.x0) / (self.x1 - self.x0)
        frac = min(1.0, max(0.0, frac))
        return round(self.lo + frac * (self.hi - self.lo))

    def _on_drag(self, event):
        v = self._x_to_val(event.x)
        if v != self.value:
            self.value = v
            self._draw()
            self.command(v)

    def set(self, v):
        "Set the value and redraw, WITHOUT firing the command (for resets)."
        self.value = max(self.lo, min(self.hi, v))
        self._draw()

    def get(self):
        return self.value

    def _draw(self):
        c = self.canvas
        c.delete("all")
        c.create_text(self.x0, 11, text=self.label, anchor="w",
                      fill=FG, font=("Segoe UI", 9))
        d = self.value - self.neutral
        dtxt = f"+{d}" if d > 0 else str(d)
        c.create_text(self.x1, 11, text=dtxt, anchor="e",
                      fill=FG_DIM, font=("Segoe UI", 9))
        y = self.TRACK_Y
        c.create_line(self.x0, y, self.x1, y, fill=self.TRACK,
                      width=4, capstyle="round")
        nx = self._val_to_x(self.neutral)
        kx = self._val_to_x(self.value)
        if abs(kx - nx) > 1:
            c.create_line(nx, y, kx, y, fill=ACCENT, width=4, capstyle="round")
        r = self.KNOB_R
        c.create_oval(kx - r, y - r, kx + r, y + r,
                      fill=self.KNOB, outline=ACCENT, width=2)


class Manoni:
    "Main application window"

    def __init__(self, folder=None):
        self.root = tk.Tk()
        self.root.title("Manoni")
        self.root.configure(bg=BG)
        self.root.geometry("1280x800")

        self.folder = None
        self.files = []          # image filenames in the folder
        self.index = 0           # current image index
        self.current_pil = None  # PIL image currently shown (full res)
        self.brightness = 1.0    # live edit factors (1.0 = unchanged)
        self.contrast = 1.0
        self.color = 1.0
        self.temperature = 1.0   # >1.0 warmer (more red), <1.0 cooler (more blue)
        self._fit_pil = None     # current photo pre-scaled to the preview size
        self._fit_size = None    # (w, h) the fit image was scaled for
        self.icons = {}          # name -> PhotoImage (kept alive)
        self.thumb_images = []   # thumbnail PhotoImages (kept alive)
        self.thumb_widgets = []  # frame per thumbnail (for highlight); may be None
        self._thumb_job = None

        self._build_infobar()
        self._build_toolbar()
        self._build_body()
        self._build_bottombar()

        self.root.rowconfigure(2, weight=1)      # body row expands
        self.root.columnconfigure(0, weight=1)

        # Re-fit the preview when the window resizes
        self.preview.bind("<Configure>", lambda e: self._render_preview())

        if folder:
            self.load_folder(folder)

    # --- Icons --------------------------------------------------------------

    def icon(self, name):
        "Load a Lucide icon (white) scaled to ICON_SIZE, cached. None if missing."
        if name in self.icons:
            return self.icons[name]
        path = os.path.join(ICON_DIR, name + ".png")
        img = None
        if os.path.exists(path):
            try:
                im = Image.open(path).convert("RGBA")
                im = im.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
                img = ImageTk.PhotoImage(im)
            except Exception:
                img = None
        self.icons[name] = img
        return img

    def _tool_button(self, parent, icon_name, command, tooltip=""):
        "A flat icon button with hover effect (falls back to text if no icon)."
        img = self.icon(icon_name)
        if img is not None:
            btn = tk.Label(parent, image=img, bg=BAR, cursor="hand2")
        else:
            btn = tk.Label(parent, text=tooltip or "?", bg=BAR, fg=FG,
                           cursor="hand2", font=("Segoe UI", 10))
        btn.bind("<Enter>", lambda e: btn.configure(bg=HOVER))
        btn.bind("<Leave>", lambda e: btn.configure(bg=BAR))
        btn.bind("<Button-1>", lambda e: command())
        btn._tooltip = tooltip
        return btn

    def _sep(self, parent):
        "Vertical separator in a bar."
        return tk.Frame(parent, bg="#3a3a3a", width=1)

    # --- Top info bar -------------------------------------------------------

    def _build_infobar(self):
        self.infobar = tk.Frame(self.root, bg=BAR, height=30)
        self.infobar.grid(row=0, column=0, sticky="ew")
        self.infobar.grid_propagate(False)

        self.lbl_name = tk.Label(self.infobar, text="Manoni", bg=BAR, fg=FG,
                                 font=("Segoe UI", 9, "bold"))
        self.lbl_name.pack(side="left", padx=12)

        self.lbl_info = tk.Label(self.infobar, text="", bg=BAR, fg=FG_DIM,
                                 font=("Segoe UI", 9))
        self.lbl_info.pack(side="left", padx=8)

    # --- Toolbar ------------------------------------------------------------

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=BAR, height=46)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)

        # (icon, command, tooltip)
        groups = [
            [("chevron-left", self.prev, "წინა"),
             ("chevron-right", self.next, "შემდეგი")],
            [("maximize", self._render_preview, "Fit"),
             ("grid-2x2", lambda: self.toast("ბადე — მალე"), "ბადე")],
            [("scaling", lambda: self.toast("Resize — მალე"), "Resize"),
             ("sun", lambda: self.toast("განათება — მალე"), "განათება"),
             ("palette", lambda: self.toast("ფილტრი — მალე"), "ფილტრი")],
            [("folder-check", self.move_to_folder, "შენახვა ფოლდერში"),
             ("trash-2", self.delete, "წაშლა")],
            [("folder-open", self.open_folder, "ფოლდერის გახსნა"),
             ("menu", lambda: self.toast("მენიუ — მალე"), "მენიუ")],
        ]

        for gi, group in enumerate(groups):
            for icon_name, command, tip in group:
                btn = self._tool_button(bar, icon_name, command, tip)
                btn.pack(side="left", padx=4, pady=8)
            if gi < len(groups) - 1:
                self._sep(bar).pack(side="left", fill="y", padx=6, pady=10)

    # --- Body: sidebar + preview -------------------------------------------

    def _build_body(self):
        body = tk.Frame(self.root, bg=BG)
        body.grid(row=2, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=0)   # thumbnail sidebar fixed
        body.columnconfigure(1, weight=1)   # preview expands
        body.columnconfigure(2, weight=0)   # edit panel fixed

        # Sidebar (scrollable thumbnails)
        side = tk.Frame(body, bg=SIDEBAR, width=THUMB_W + 30)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)

        self.canvas = tk.Canvas(side, bg=SIDEBAR, highlightthickness=0,
                                width=THUMB_W + 30)
        sb = ttk.Scrollbar(side, orient="vertical", command=self.canvas.yview)
        self.thumb_holder = tk.Frame(self.canvas, bg=SIDEBAR)
        self.thumb_holder.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.thumb_holder, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        for w in (self.canvas, self.thumb_holder):
            w.bind("<MouseWheel>", self._on_wheel)

        # Big preview fills the center
        self.preview = tk.Label(body, bg=BG)
        self.preview.grid(row=0, column=1, sticky="nsew")

        # ACR-style edit panel on the right
        self._build_edit_panel(body)

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    # --- Edit panel (below the preview) -------------------------------------

    def _build_edit_panel(self, parent):
        "Vertical ACR-style edit panel on the right: stacked live sliders + reset."
        panel = tk.Frame(parent, bg=BAR, width=252)
        panel.grid(row=0, column=2, sticky="ns")
        panel.grid_propagate(False)

        tk.Label(panel, text="რედაქტირება", bg=BAR, fg=FG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16,
                                                     pady=(16, 10))

        self.s_brightness = self._slider(panel, "განათება", "brightness")
        self.s_contrast   = self._slider(panel, "კონტრასტი", "contrast")
        self.s_color      = self._slider(panel, "ფერი", "color")
        self.sliders = {"brightness": self.s_brightness,
                        "contrast": self.s_contrast,
                        "color": self.s_color}

        reset = tk.Label(panel, text="ხელახლა", bg=BAR, fg=FG_DIM,
                         cursor="hand2", font=("Segoe UI", 9))
        reset.bind("<Enter>", lambda e: reset.configure(fg=FG))
        reset.bind("<Leave>", lambda e: reset.configure(fg=FG_DIM))
        reset.bind("<Button-1>", lambda e: self._reset_edits())
        reset.pack(anchor="w", padx=16, pady=(14, 0))

    def _slider(self, parent, label, attr):
        "A labeled live slider (0–200 → factor 0.0–2.0) bound to an attribute."
        s = Slider(parent, label, lambda v, a=attr: self._on_slider(a, v))
        s.pack(anchor="w", padx=16, pady=6)
        return s

    def _on_slider(self, attr, val):
        setattr(self, attr, val / 100.0)
        self._render_preview()

    def _reset_sliders(self):
        "Put every slider back to neutral (factor 1.0). set() does not re-render."
        for attr, s in self.sliders.items():
            setattr(self, attr, 1.0)
            s.set(100)

    def _reset_edits(self):
        self._reset_sliders()
        self._render_preview()

    # --- Bottom navigation --------------------------------------------------

    def _build_bottombar(self):
        bar = tk.Frame(self.root, bg=BAR, height=34)
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_propagate(False)

        wrap = tk.Frame(bar, bg=BAR)
        wrap.pack(expand=True)

        self.lbl_pos = tk.Label(wrap, text="0 / 0", bg=BAR, fg=FG_DIM,
                                font=("Segoe UI", 9))
        self.lbl_pos.pack(side="left", padx=14)

        for icon_name, command, tip in [
            ("chevrons-left", self.first, "პირველი"),
            ("chevron-left", self.prev, "წინა"),
            ("chevron-right", self.next, "შემდეგი"),
            ("chevrons-right", self.last, "ბოლო"),
        ]:
            self._tool_button(wrap, icon_name, command, tip).pack(side="left", padx=4, pady=4)

    # --- Folder + files -----------------------------------------------------

    def load_folder(self, folder):
        "Load all images in a folder and show the first one."
        self.folder = folder
        self.files = sorted(
            f for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f))
            and os.path.splitext(f)[1].lower() in SUPPORTED)
        self.index = 0
        self._build_thumbs()
        if self.files:
            self.show_current()
        else:
            self.preview.configure(image="", text="ფოტოები ვერ მოიძებნა",
                                   fg=FG_DIM, font=("Segoe UI", 12))
            self.lbl_name.configure(text="Manoni")
            self.lbl_info.configure(text="")
            self.lbl_pos.configure(text="0 / 0")

    def open_folder(self):
        folder = tkfd.askdirectory(parent=self.root,
                                   initialdir=self.folder or os.path.expanduser("~"))
        if folder:
            self.load_folder(folder)

    # --- Thumbnails ---------------------------------------------------------

    def _build_thumbs(self):
        "Rebuild the sidebar thumbnail list (loaded incrementally so UI stays responsive)."
        if self._thumb_job is not None:
            self.root.after_cancel(self._thumb_job)
            self._thumb_job = None
        for w in self.thumb_holder.winfo_children():
            w.destroy()
        self.thumb_images = []
        self.thumb_widgets = []
        self._thumb_idx = 0
        self._thumb_job = self.root.after(1, self._add_thumb)

    def _add_thumb(self):
        try:
            if not self.thumb_holder.winfo_exists():
                return
        except tk.TclError:
            return
        if self._thumb_idx >= len(self.files):
            self._thumb_job = None
            return

        i = self._thumb_idx
        file = self.files[i]
        try:
            with Image.open(os.path.join(self.folder, file)) as im:
                im.thumbnail((THUMB_W, THUMB_W))
                im = im.convert("RGB")
                photo = ImageTk.PhotoImage(im)
            self.thumb_images.append(photo)

            frame = tk.Frame(self.thumb_holder, bg=SIDEBAR,
                             highlightthickness=2, highlightbackground=SIDEBAR)
            frame.pack(pady=4)
            lbl = tk.Label(frame, image=photo, bg=SIDEBAR, cursor="hand2")
            lbl.pack()
            name = tk.Label(self.thumb_holder, text=file, bg=SIDEBAR, fg=FG_DIM,
                            font=("Segoe UI", 7), wraplength=THUMB_W)
            name.pack()
            for w in (lbl, frame, name):
                w.bind("<MouseWheel>", self._on_wheel)
                w.bind("<Button-1>", lambda e, idx=i: self.go_to(idx))
            self.thumb_widgets.append(frame)
        except Exception:
            self.thumb_widgets.append(None)

        self._thumb_idx += 1
        self._thumb_job = self.root.after(1, self._add_thumb)

    def _highlight_thumb(self):
        for i, frame in enumerate(self.thumb_widgets):
            if frame is None:
                continue
            try:
                frame.configure(highlightbackground=ACCENT if i == self.index else SIDEBAR)
            except tk.TclError:
                pass

    # --- Show current image -------------------------------------------------

    def show_current(self):
        if not self.files:
            return
        path = os.path.join(self.folder, self.files[self.index])
        try:
            self.current_pil = Image.open(path)
            self.current_pil.load()
        except Exception:
            self.current_pil = None
        self._fit_pil = None     # new photo → drop the cached scaled image
        self._reset_sliders()
        self._render_preview()
        self._update_info(path)
        self._highlight_thumb()
        self.lbl_pos.configure(text=f"{self.index + 1} / {len(self.files)}")

    def _fit_current(self, aw, ah):
        "Downscale the full-res photo to the preview size, once. Expensive."
        img = self.current_pil.copy()
        img.thumbnail((aw, ah), Image.LANCZOS)
        self._fit_pil = img.convert("RGB")
        self._fit_size = (aw, ah)

    def _apply_edits(self, img):
        "Apply the live edit factors. Cheap on the small preview, exact on full-res."
        if self.brightness != 1.0:
            img = ImageEnhance.Brightness(img).enhance(self.brightness)
        if self.contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(self.contrast)
        if self.color != 1.0:
            img = ImageEnhance.Color(img).enhance(self.color)
        return img

    def _render_preview(self):
        "Apply live edits to the cached fit image and show it. Cheap on the slider."
        if self.current_pil is None:
            return
        aw = max(self.preview.winfo_width(), 1)
        ah = max(self.preview.winfo_height(), 1)
        if aw <= 1 or ah <= 1:
            return
        # Re-scale only when the photo changed or the window was resized.
        if self._fit_pil is None or self._fit_size != (aw, ah):
            self._fit_current(aw, ah)
        img = self._apply_edits(self._fit_pil)
        photo = ImageTk.PhotoImage(img)
        self.preview.configure(image=photo, text="")
        self.preview.image = photo   # keep reference

    def _update_info(self, path):
        file = self.files[self.index]
        try:
            w, h = self.current_pil.size if self.current_pil else (0, 0)
            size_kb = os.path.getsize(path) / 1024
            size_txt = f"{size_kb/1024:.1f} MB" if size_kb > 1024 else f"{size_kb:.0f} KB"
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
            date_txt = mtime.strftime("%Y/%m/%d %H:%M")
            self.lbl_name.configure(text=file)
            self.lbl_info.configure(
                text=f"{self.index+1}/{len(self.files)}   ·   {w}×{h}   ·   "
                     f"{size_txt}   ·   {date_txt}")
        except Exception:
            self.lbl_name.configure(text=file)
            self.lbl_info.configure(text="")

    # --- Navigation ---------------------------------------------------------

    def go_to(self, index):
        if 0 <= index < len(self.files):
            self.index = index
            self.show_current()

    def prev(self):
        if self.files:
            self.go_to((self.index - 1) % len(self.files))

    def next(self):
        if self.files:
            self.go_to((self.index + 1) % len(self.files))

    def first(self):
        self.go_to(0)

    def last(self):
        self.go_to(len(self.files) - 1)

    # --- Cull: delete + move ------------------------------------------------

    def delete(self):
        "Move the current file into a _deleted subfolder (safe, reversible)."
        if not self.files:
            return
        trash = os.path.join(self.folder, "_deleted")
        os.makedirs(trash, exist_ok=True)
        self._move_current_to(trash)
        self.toast("გადატანილია _deleted-ში")

    def move_to_folder(self):
        "Move the current file into a folder you choose (keep the good ones)."
        if not self.files:
            return
        dest = tkfd.askdirectory(parent=self.root, title="აირჩიე ფოლდერი",
                                 initialdir=self.folder)
        if dest:
            self._move_current_to(dest)
            self.toast(f"გადატანილია → {os.path.basename(dest)}")

    def _move_current_to(self, dest):
        file = self.files[self.index]
        src = os.path.join(self.folder, file)
        try:
            shutil.move(src, os.path.join(dest, file))
        except Exception as e:
            self.toast(f"შეცდომა: {e}")
            return
        # Remove from list and refresh
        del self.files[self.index]
        if self.index >= len(self.files):
            self.index = max(0, len(self.files) - 1)
        self._build_thumbs()
        if self.files:
            self.show_current()
        else:
            self.load_folder(self.folder)

    # --- Misc ---------------------------------------------------------------

    def toast(self, message):
        "Show a short status message in the info bar."
        self.lbl_info.configure(text=message)

    def run(self):
        self.root.mainloop()


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    app = Manoni(folder)
    app.run()


if __name__ == "__main__":
    main()
