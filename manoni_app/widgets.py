"""Small reusable Tk widgets for Manoni (no app state, no `self` from Manoni).

These are generic building blocks — a custom dark slider and a hover tooltip —
that the main window composes. Kept separate so the window code stays focused.
"""

import tkinter as tk

from PIL import ImageTk

from .config import ACCENT, BAR, FG, FG_DIM, HOVER


class Slider:
    """A clean, dark, custom-drawn horizontal slider (Canvas-based).

    Layout per slider:  label (top-left)            value (top-right)
                        ───────────●───────────────  (track + knob)
    The fill runs from the neutral point to the knob, so you can see at a
    glance how far an edit deviates from "unchanged".
    """
    W       = 220   # widget width
    H       = 34    # widget height (compact — fits many sliders without scrolling)
    PAD     = 10    # left/right inset for the track
    TRACK_Y = 26    # track baseline
    KNOB_R  = 5     # knob radius (small, minimal)
    TRACK   = "#333333"   # thin dark track
    KNOB    = ACCENT      # accent dot, not a white ball

    def __init__(self, parent, label, command, lo=0, hi=200, neutral=100,
                 on_press=None, on_release=None):
        self.label = label
        self.command = command          # called with the int value on change
        self.on_press = on_press        # called once (no args) when a drag begins
        self.on_release = on_release    # called once (no args) when a drag ends
        self.lo, self.hi = lo, hi
        self.neutral = neutral
        self.value = neutral
        self.x0 = self.PAD
        self.x1 = self.W - self.PAD
        self.canvas = tk.Canvas(parent, width=self.W, height=self.H, bg=BAR,
                                highlightthickness=0, cursor="hand2")
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        # Packed with fill="x", so the canvas grows to the panel width. Track the
        # real width and rescale the track + readout to it on every resize.
        self.canvas.bind("<Configure>", self._on_configure)
        self._draw()

    def _on_configure(self, event):
        "Stretched to the panel width: re-anchor the right edge and redraw."
        new_x1 = event.width - self.PAD
        if new_x1 > self.x0 and new_x1 != self.x1:
            self.x1 = new_x1
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

    def _on_press(self, event):
        "Drag begins: snapshot for undo (via on_press), then apply the click."
        if self.on_press:
            self.on_press()
        self._on_drag(event)

    def _on_release(self, event):
        "Drag ends: let the app commit one undo entry for the whole gesture."
        if self.on_release:
            self.on_release()

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
                      width=3, capstyle="round")
        nx = self._val_to_x(self.neutral)
        kx = self._val_to_x(self.value)
        if abs(kx - nx) > 1:
            c.create_line(nx, y, kx, y, fill=ACCENT, width=3, capstyle="round")
        # Small accent knob; the bg-colored outline cuts a thin halo so the dot
        # stays readable against the accent fill without any bright white.
        r = self.KNOB_R
        c.create_oval(kx - r, y - r, kx + r, y + r,
                      fill=self.KNOB, outline=BAR, width=2)


class Histogram:
    """A live RGB histogram strip (a Canvas showing a PIL-rendered image).

    Holds no image state of its own: on every `refresh()` (and on resize) it
    asks `render(w, h)` for a fresh histogram image at the current width, so the
    app can hand back the edited preview's histogram each frame. `render` returns
    a PIL RGB image of that size, or None when there is no photo.
    """

    def __init__(self, parent, render, height=92, bg=BAR):
        self.render = render
        self.height = height
        self.canvas = tk.Canvas(parent, height=height, bg=bg,
                                highlightthickness=0)
        self.canvas.bind("<Configure>", self._on_configure)
        self._w = 0
        self._photo = None         # keep a reference alive or Tk drops the image

    def pack(self, **kw):
        self.canvas.pack(**kw)
        return self

    def _on_configure(self, event):
        "Stretched to the panel width: re-render at the new width."
        if event.width != self._w:
            self._w = event.width
            self.refresh()

    def refresh(self):
        "Re-pull the histogram image from `render` and repaint (None → clear)."
        w = self._w or self.canvas.winfo_width()
        if w <= 1:
            return
        img = self.render(w, self.height)
        self.canvas.delete("all")
        if img is None:
            self._photo = None
            return
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)


class Tooltip:
    "A small delayed dark hover tooltip, attachable to any widget."
    DELAY = 450   # ms to hover before the tip appears

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        self._job = None
        # add="+" so we never clobber the widget's own hover / click bindings.
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<Button>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        if self.text:
            self._job = self.widget.after(self.DELAY, self._show)

    def _cancel(self):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _show(self):
        self._job = None
        if self.tip is not None or not self.text:
            return
        try:
            if not self.widget.winfo_exists():
                return
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.configure(bg=HOVER)            # thin border via 1px inset
        lbl = tk.Label(self.tip, text=self.text, bg="#0f0f0f", fg=FG,
                       font=("Segoe UI", 9), padx=8, pady=3)
        lbl.pack(padx=1, pady=1)
        self.tip.update_idletasks()
        w = self.tip.winfo_width()
        self.tip.wm_geometry(f"+{x - w // 2}+{y}")

    def _on_leave(self, event=None):
        # A <Leave> also fires when the pointer merely crosses onto a CHILD of
        # the widget (e.g. a cell's thumbnail or name label) — it is still
        # "inside" the cell, so don't dismiss the tip then. Only hide once the
        # pointer has truly left the widget's subtree. Without this the tip is
        # cancelled the instant you move off the frame's own pixels, so it
        # barely ever shows (looks like "hover works only once").
        if event is not None and self._still_inside(event):
            return
        self._hide()

    def _hide(self, _event=None):
        self._cancel()
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None

    def _still_inside(self, event):
        "True when the pointer (at this <Leave>) is over the widget or a child."
        try:
            under = self.widget.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return False
        while under is not None:
            if under is self.widget:
                return True
            under = getattr(under, "master", None)
        return False
