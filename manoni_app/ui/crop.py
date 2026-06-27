"""Interactive crop tool for Manoni: ratio presets, the on-preview overlay,
and apply. Split out of the Manoni class as a mixin — every method uses the
shared `self`, so behaviour is identical to when it lived on the class.
"""

import os
import math
import tkinter as tk

from ..config import (ACCENT, BAR, BG, FG, FG_DIM, HOVER,
                      EDIT_PANEL_W, EDIT_PAD, CHIP_GAP)
from ..widgets import Tooltip
from ..i18n import t


class CropMixin:
    # --- Crop tool (col 3 panel + interactive overlay on the preview) --------

    # Aspect-ratio presets. ratio: None = free, "orig" = the photo's own ratio,
    # "custom" = ask the user for a width:height, else a width/height float. Every
    # ratio is listed once — platforms that share a ratio share one chip.
    CROP_COMMON = [("თავისუფ.", None), ("ორიგინ.", "orig"), ("საკუთარი", "custom"),
                   ("1:1", 1.0), ("4:3", 4 / 3), ("3:2", 3 / 2), ("5:4", 5 / 4)]
    CROP_SOCIAL = [("IG პორტრ. 4:5", 4 / 5), ("Story·Reels·TikTok 9:16", 9 / 16),
                   ("YouTube·X 16:9", 16 / 9), ("FB·LinkedIn 1.91", 1.91)]

    def _build_crop_section(self, parent):
        "Crop tool panel: a hint, ratio presets (common + social), flip + apply."
        f = tk.Frame(parent, bg=BAR)
        self._crop_chips = []
        wrap = self._edit_dpi_w(EDIT_PANEL_W - 2 * EDIT_PAD)
        tk.Label(f, text=t("ჩავათრიე კუთხეები; აირჩიე ფორმა ან სოც. ქსელი"),
                 bg=BAR, fg=FG_DIM, font=("Segoe UI", 8), justify="left",
                 anchor="w", wraplength=wrap).pack(fill="x", padx=EDIT_PAD,
                                                   pady=(10, 4))

        self._crop_chip_grid(f, "ფორმა", self.CROP_COMMON)
        self._crop_chip_grid(f, "სოციალური ქსელები", self.CROP_SOCIAL)

        flip = tk.Label(f, text=t("⇄ გადატრიალება (3:4 ⇄ 4:3)"), bg=BAR, fg=FG_DIM,
                        cursor="hand2", anchor="w", font=("Segoe UI", 9))
        flip.bind("<Enter>", lambda e: flip.configure(fg=FG))
        flip.bind("<Leave>", lambda e: flip.configure(fg=FG_DIM))
        flip.bind("<Button-1>", lambda e: self._flip_crop_ratio())
        flip.pack(fill="x", padx=EDIT_PAD, pady=(12, 4))
        flip._tip = Tooltip(flip, t("მონიშვნის 90°-ით გადატრიალება"))

        apply_btn = tk.Label(f, text=t("მოჭრა"), bg=ACCENT, fg="#0b0b0b",
                             cursor="hand2", font=("Segoe UI", 10, "bold"),
                             padx=14, pady=8)
        apply_btn.bind("<Enter>", lambda e: apply_btn.configure(bg="#5ab0ff"))
        apply_btn.bind("<Leave>", lambda e: apply_btn.configure(bg=ACCENT))
        apply_btn.bind("<Button-1>", lambda e: self.apply_crop())
        apply_btn.pack(side="top", fill="x", padx=EDIT_PAD, pady=(6, 4))

        reset = tk.Label(f, text=t("გაუქმება"), bg=BAR, fg=FG_DIM, cursor="hand2",
                         anchor="w", font=("Segoe UI", 9))
        reset.bind("<Enter>", lambda e: reset.configure(fg=FG))
        reset.bind("<Leave>", lambda e: reset.configure(fg=FG_DIM))
        reset.bind("<Button-1>", lambda e: self._reset_crop())
        reset.pack(fill="x", padx=EDIT_PAD, pady=(2, 8))
        reset._tip = Tooltip(reset, t("მონიშვნის სრულ სურათზე დაბრუნება"))
        return f

    def _crop_chip_grid(self, parent, title, presets):
        "A titled 2-column grid of crop-ratio preset chips."
        tk.Label(parent, text=t(title), bg=BAR, fg=FG_DIM, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=EDIT_PAD,
                                                    pady=(8, 2))
        grid = tk.Frame(parent, bg=BAR)
        grid.pack(side="top", fill="x", padx=EDIT_PAD)
        grid.columnconfigure(0, weight=1, uniform="crop")
        grid.columnconfigure(1, weight=1, uniform="crop")
        for i, (label, ratio) in enumerate(presets):
            chip = tk.Label(grid, text=t(label), bg="#2f2f2f", fg=FG, cursor="hand2",
                            font=("Segoe UI", 8), padx=4, pady=5)
            chip._ratio = ratio
            chip.bind("<Button-1>", lambda e, c=chip: self._pick_crop_ratio(c))
            chip.bind("<Enter>", lambda e, c=chip: self._crop_chip_hover(c, True))
            chip.bind("<Leave>", lambda e, c=chip: self._crop_chip_hover(c, False))
            colpad = (0, CHIP_GAP // 2) if i % 2 == 0 else (CHIP_GAP // 2, 0)
            chip.grid(row=i // 2, column=i % 2, sticky="ew", padx=colpad, pady=2)
            self._crop_chips.append(chip)

    def _crop_chip_hover(self, chip, entering):
        "Brighten a preset chip on hover; the active one keeps its accent fill."
        if chip is self._crop_btn_active:
            return
        chip.configure(bg=HOVER if entering else "#2f2f2f")

    def _restyle_crop_chips(self):
        "Repaint the preset chips so the active one is accent-filled, rest neutral."
        for c in self._crop_chips:
            active = c is self._crop_btn_active
            c.configure(bg=ACCENT if active else "#2f2f2f",
                        fg="#0b0b0b" if active else FG)

    def _pick_crop_ratio(self, chip):
        "A preset chip was clicked: lock the box to its ratio and highlight it."
        if self.current_pil is None:
            return
        ratio = chip._ratio
        if ratio == "custom":
            wh = self._ask_custom_ratio()
            if wh is None:
                return                       # cancelled → keep the current box
            w, h = wh
            ratio = w / h
            chip.configure(text=self._fmt_ratio_label(w, h))
        elif ratio == "orig":
            iw, ih = self.current_pil.size
            ratio = iw / ih
        self._crop_btn_active = chip
        self._restyle_crop_chips()
        self._set_crop_ratio(ratio)

    def _fmt_ratio_label(self, w, h):
        "Compact chip label for a custom ratio, reduced to lowest terms if whole."
        if abs(w - round(w)) < 1e-6 and abs(h - round(h)) < 1e-6:
            iw, ih = int(round(w)), int(round(h))
            g = math.gcd(iw, ih) or 1
            return f"{t('საკ.')} {iw // g}:{ih // g}"
        return f"{t('საკ.')} {w:g}:{h:g}"

    def _ask_custom_ratio(self):
        "Modal dark dialog: ask for a custom width:height. Returns (w, h) or None."
        result = {"val": None}
        dlg = tk.Toplevel(self.root)
        dlg.title(t("საკუთარი ზომა"))
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = tk.Frame(dlg, bg=BG, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=t("საკუთარი პროპორცია"), bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(wrap, text=t("სიგანე : სიმაღლე  (მაგ. 4:5 ან 1200:800)"), bg=BG,
                 fg=FG_DIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 12))

        row = tk.Frame(wrap, bg=BG)
        row.pack(anchor="w")

        def mkentry(value):
            e = tk.Entry(row, bg=BAR, fg=FG, insertbackground=FG, width=6,
                         relief="flat", justify="center", font=("Segoe UI", 12))
            e.insert(0, value)
            return e

        # Prefill with the current box size, so the dialog doubles as "type the
        # size you want" and hints that pixel values work too.
        w0 = h0 = ""
        if self.crop_rect is not None:
            w0 = str(int(round(self.crop_rect[2] - self.crop_rect[0])))
            h0 = str(int(round(self.crop_rect[3] - self.crop_rect[1])))
        e_w = mkentry(w0); e_w.pack(side="left", ipady=4)
        tk.Label(row, text=":", bg=BG, fg=FG,
                 font=("Segoe UI", 13, "bold")).pack(side="left", padx=8)
        e_h = mkentry(h0); e_h.pack(side="left", ipady=4)

        err = tk.Label(wrap, text="", bg=BG, fg="#ff6b6b", font=("Segoe UI", 8))
        err.pack(anchor="w", pady=(8, 0))

        def confirm():
            try:
                cw = float(e_w.get().replace(",", "."))
                ch = float(e_h.get().replace(",", "."))
            except ValueError:
                err.configure(text=t("შეიყვანე ორი დადებითი რიცხვი"))
                return
            if cw <= 0 or ch <= 0:
                err.configure(text=t("რიცხვები დადებითი უნდა იყოს"))
                return
            result["val"] = (cw, ch)
            dlg.destroy()

        btnrow = tk.Frame(wrap, bg=BG)
        btnrow.pack(anchor="e", pady=(14, 0))

        def mkbtn(text, command, primary=False):
            bg = ACCENT if primary else BAR
            hov = "#5ab0ff" if primary else HOVER
            b = tk.Label(btnrow, text=text, bg=bg, fg="#0b0b0b" if primary else FG,
                         cursor="hand2", padx=14, pady=7,
                         font=("Segoe UI", 9, "bold" if primary else "normal"))
            b.bind("<Enter>", lambda e: b.configure(bg=hov))
            b.bind("<Leave>", lambda e: b.configure(bg=bg))
            b.bind("<Button-1>", lambda e: command())
            return b

        mkbtn(t("გაუქმება"), dlg.destroy).pack(side="right", padx=(8, 0))
        mkbtn(t("არჩევა"), confirm, primary=True).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Return>", lambda e: confirm())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        e_w.focus_set()
        e_w.select_range(0, "end")

        dlg.update_idletasks()
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        dlg.geometry(f"+{max(0, rx + (rw - dw) // 2)}+{max(0, ry + (rh - dh) // 2)}")
        dlg.grab_set()
        dlg.focus_set()
        self.root.wait_window(dlg)
        return result["val"]

    def _set_crop_ratio(self, ratio):
        "Lock the crop box to an aspect ratio (None = free) and reshape it to fit."
        self.crop_ratio = ratio
        if self.current_pil is None:
            return
        iw, ih = self.current_pil.size
        if ratio is None:
            if self.crop_rect is None:
                self.crop_rect = [0.0, 0.0, float(iw), float(ih)]
            self._render_preview()
            return
        # Largest box of this ratio, centered in the image.
        if iw / ih > ratio:
            h = float(ih); w = h * ratio
        else:
            w = float(iw); h = w / ratio
        x0 = (iw - w) / 2.0
        y0 = (ih - h) / 2.0
        self.crop_rect = [x0, y0, x0 + w, y0 + h]
        self._render_preview()

    def _flip_crop_ratio(self):
        "Rotate the crop 90°: swap its width↔height (and any locked ratio) in place."
        if self.current_pil is None or self.crop_rect is None:
            return
        if self.crop_ratio:
            self.crop_ratio = 1.0 / self.crop_ratio
        iw, ih = self.current_pil.size
        x0, y0, x1, y1 = self.crop_rect
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        nw, nh = (y1 - y0), (x1 - x0)            # swapped dimensions
        nw = min(nw, float(iw))                  # fit inside the image...
        nh = min(nh, float(ih))
        if self.crop_ratio:                      # ...while keeping the locked ratio
            if nw / nh > self.crop_ratio:
                nw = nh * self.crop_ratio
            else:
                nh = nw / self.crop_ratio
        nx0 = max(0.0, min(cx - nw / 2.0, iw - nw))
        ny0 = max(0.0, min(cy - nh / 2.0, ih - nh))
        self.crop_rect = [nx0, ny0, nx0 + nw, ny0 + nh]
        # The shown ratio changed, so a named preset chip no longer matches it.
        self._crop_btn_active = None
        self._restyle_crop_chips()
        self._render_preview()

    def _reset_crop(self):
        "Clear the selection back to the whole image (free ratio)."
        if self.current_pil is None:
            return
        iw, ih = self.current_pil.size
        self.crop_rect = [0.0, 0.0, float(iw), float(ih)]
        self.crop_ratio = None
        self._crop_btn_active = None
        self._restyle_crop_chips()
        self._render_preview()

    def _enter_crop(self):
        "Open the crop tool: start a full-image box and fit the photo to see it all."
        if self.current_pil is None:
            self._render_preview()
            return
        if self.crop_rect is None:
            iw, ih = self.current_pil.size
            self.crop_rect = [0.0, 0.0, float(iw), float(ih)]
        self.preview.configure(cursor="crosshair")
        self.fit_view()          # fit + recenter + render (shows the overlay)

    def apply_crop(self):
        "Crop current_pil to the selection (in memory; written out via შენახვა)."
        if self.current_pil is None or self.crop_rect is None:
            return
        iw, ih = self.current_pil.size
        x0, y0, x1, y1 = self.crop_rect
        box = (max(0, int(round(x0))), max(0, int(round(y0))),
               min(iw, int(round(x1))), min(ih, int(round(y1))))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            self.toast(t("მოსაჭრელი არე ძალიან პატარაა"))
            return
        if box == (0, 0, iw, ih):
            self.toast(t("მთელი სურათია მონიშნული — არაფერი იცვლება"))
            return
        self.current_pil = self.current_pil.crop(box)
        self._cropped = True
        self._clear_focus_for_geometry()  # source-px circle no longer maps after a crop
        self._edits_saved = False
        nw, nh = self.current_pil.size
        # Reset the box to the new full image; ready for a second crop.
        self.crop_rect = [0.0, 0.0, float(nw), float(nh)]
        self.crop_ratio = None
        self._crop_btn_active = None
        self._restyle_crop_chips()
        self.fit_mode = True
        self.pan_x = self.pan_y = 0.0
        self._view_key = None       # size changed → drop the cached scaled view
        self._render_preview()
        self._update_info(os.path.join(self.folder, self.files[self.index]))
        self.toast(t("მოიჭრა → {w}×{h}px  ·  შენახვა ფაილში ჩასაწერად").format(w=nw, h=nh))

    # --- Crop overlay geometry + mouse interaction --------------------------

    CROP_HANDLE = 6    # half-size of a handle square, in screen px
    CROP_MIN    = 16   # smallest crop side, in source px
    _CROP_CURSORS = {"nw": "top_left_corner", "se": "bottom_right_corner",
                     "ne": "top_right_corner", "sw": "bottom_left_corner",
                     "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
                     "w": "sb_h_double_arrow", "e": "sb_h_double_arrow",
                     "move": "fleur"}

    def _crop_active(self):
        "True when the crop tool is open and a box exists (drives overlay + clicks)."
        return (self.panel_open and self.active_section == "crop"
                and self.current_pil is not None and self.crop_rect is not None)

    def _src_to_scr(self, sx, sy):
        "Source-pixel (sx, sy) → screen (x, y), using the last render transform."
        scale, ox, oy = self._disp
        return ox + sx * scale, oy + sy * scale

    def _scr_to_src(self, x, y):
        "Screen (x, y) → source-pixel (sx, sy), using the last render transform."
        scale, ox, oy = self._disp
        scale = scale or 1.0
        return (x - ox) / scale, (y - oy) / scale

    def _crop_handles(self):
        "Map handle name → screen (x, y). Corners always; edges only when free."
        x0, y0 = self._src_to_scr(self.crop_rect[0], self.crop_rect[1])
        x1, y1 = self._src_to_scr(self.crop_rect[2], self.crop_rect[3])
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        h = {"nw": (x0, y0), "ne": (x1, y0), "se": (x1, y1), "sw": (x0, y1)}
        if self.crop_ratio is None:
            h.update({"n": (mx, y0), "s": (mx, y1), "w": (x0, my), "e": (x1, my)})
        return h

    def _crop_hit(self, x, y):
        "Handle/'move' under screen (x, y), or None. Handles take priority."
        tol = self.CROP_HANDLE + 4
        for mode, (hx, hy) in self._crop_handles().items():
            if abs(x - hx) <= tol and abs(y - hy) <= tol:
                return mode
        x0, y0 = self._src_to_scr(self.crop_rect[0], self.crop_rect[1])
        x1, y1 = self._src_to_scr(self.crop_rect[2], self.crop_rect[3])
        if x0 <= x <= x1 and y0 <= y <= y1:
            return "move"
        return None

    def _crop_anchor_for(self, mode):
        "The fixed corner a corner-handle drag pivots around (the opposite corner)."
        x0, y0, x1, y1 = self.crop_rect
        return {"nw": (x1, y1), "ne": (x0, y1),
                "se": (x0, y0), "sw": (x1, y0)}[mode]

    def _corner_box(self, ax, ay, mx, my):
        "Box from fixed anchor corner (ax,ay) toward moving point (mx,my)."
        iw, ih = self.current_pil.size
        r = self.crop_ratio
        if r:
            dirx = 1.0 if mx >= ax else -1.0
            diry = 1.0 if my >= ay else -1.0
            maxw = (iw - ax) if dirx > 0 else ax
            maxh = (ih - ay) if diry > 0 else ay
            w = max(abs(mx - ax), abs(my - ay) * r)   # follow the dominant axis
            w = min(w, maxw, maxh * r)
            w = max(w, self.CROP_MIN)
            h = w / r
            xo, yo = ax + dirx * w, ay + diry * h
        else:
            xo, yo = mx, my
            if abs(xo - ax) < self.CROP_MIN:
                xo = ax + (self.CROP_MIN if xo >= ax else -self.CROP_MIN)
            if abs(yo - ay) < self.CROP_MIN:
                yo = ay + (self.CROP_MIN if yo >= ay else -self.CROP_MIN)
        x0, x1 = sorted((ax, xo))
        y0, y1 = sorted((ay, yo))
        return [max(0.0, x0), max(0.0, y0),
                min(float(iw), x1), min(float(ih), y1)]

    def _edge_resize(self, mode, sx, sy):
        "Free-ratio edge drag: move one edge to (sx, sy), keeping a minimum size."
        x0, y0, x1, y1 = self.crop_rect
        if mode == "n":
            y0 = min(sy, y1 - self.CROP_MIN)
        elif mode == "s":
            y1 = max(sy, y0 + self.CROP_MIN)
        elif mode == "w":
            x0 = min(sx, x1 - self.CROP_MIN)
        elif mode == "e":
            x1 = max(sx, x0 + self.CROP_MIN)
        self.crop_rect = [x0, y0, x1, y1]

    def _crop_press(self, event):
        "Begin a crop drag: grab a handle, the box body (move), or draw a fresh box."
        if not self._crop_active():
            return
        hit = self._crop_hit(event.x, event.y)
        sx, sy = self._scr_to_src(event.x, event.y)
        if hit == "move":
            self._crop_drag = ("move", event.x, event.y, list(self.crop_rect))
        elif hit in ("nw", "ne", "se", "sw"):
            self._crop_drag = (hit, self._crop_anchor_for(hit))
        elif hit in ("n", "s", "w", "e"):
            self._crop_drag = (hit, None)
        else:
            iw, ih = self.current_pil.size
            if 0 <= sx <= iw and 0 <= sy <= ih:     # rubber-band a new box
                self._crop_drag = ("se", (sx, sy))
                self.crop_rect = [sx, sy, sx, sy]
                self._render_preview()
        return "break"

    def _crop_move(self, event):
        "Drag in progress: move/resize the box, then repaint the overlay."
        if self._crop_drag is None:
            return
        mode = self._crop_drag[0]
        iw, ih = self.current_pil.size
        sx, sy = self._scr_to_src(event.x, event.y)
        sx = max(0.0, min(float(iw), sx))
        sy = max(0.0, min(float(ih), sy))
        if mode == "move":
            _, px, py, base = self._crop_drag
            opx, opy = self._scr_to_src(px, py)
            csx, csy = self._scr_to_src(event.x, event.y)
            dx, dy = csx - opx, csy - opy
            w, h = base[2] - base[0], base[3] - base[1]
            nx0 = min(max(0.0, base[0] + dx), iw - w)
            ny0 = min(max(0.0, base[1] + dy), ih - h)
            self.crop_rect = [nx0, ny0, nx0 + w, ny0 + h]
        elif mode in ("nw", "ne", "se", "sw"):
            ax, ay = self._crop_drag[1]
            self.crop_rect = self._corner_box(ax, ay, sx, sy)
        else:
            self._edge_resize(mode, sx, sy)
        self._render_preview()
        return "break"

    def _crop_release(self, event):
        "End the drag (the box stays as drawn; nothing is committed until მოჭრა)."
        if self._crop_drag is None:
            return
        self._crop_drag = None
        return "break"

    def _crop_hover(self, event):
        "Show the right resize/move cursor while hovering over the crop box."
        if not self._crop_active() or self._crop_drag is not None:
            return
        hit = self._crop_hit(event.x, event.y)
        self.preview.configure(cursor=self._CROP_CURSORS.get(hit, "crosshair"))

    def _draw_crop_overlay(self):
        "Dim outside the crop box; draw its border, thirds grid and handles."
        c = self.preview
        iw, ih = self.current_pil.size
        ix0, iy0 = self._src_to_scr(0, 0)
        ix1, iy1 = self._src_to_scr(iw, ih)
        x0, y0 = self._src_to_scr(self.crop_rect[0], self.crop_rect[1])
        x1, y1 = self._src_to_scr(self.crop_rect[2], self.crop_rect[3])
        dim = dict(fill="#000000", stipple="gray50", outline="")
        c.create_rectangle(ix0, iy0, ix1, y0, **dim)   # above the box
        c.create_rectangle(ix0, y1, ix1, iy1, **dim)   # below the box
        c.create_rectangle(ix0, y0, x0, y1, **dim)     # left of the box
        c.create_rectangle(x1, y0, ix1, y1, **dim)     # right of the box
        for k in (1, 2):                               # rule-of-thirds guides
            gx = x0 + (x1 - x0) * k / 3
            gy = y0 + (y1 - y0) * k / 3
            c.create_line(gx, y0, gx, y1, fill="#ffffff", stipple="gray25")
            c.create_line(x0, gy, x1, gy, fill="#ffffff", stipple="gray25")
        c.create_rectangle(x0, y0, x1, y1, outline="#ffffff", width=1)
        r = self.CROP_HANDLE
        for hx, hy in self._crop_handles().values():
            c.create_rectangle(hx - r, hy - r, hx + r, hy + r,
                               fill=ACCENT, outline="#0b0b0b")
