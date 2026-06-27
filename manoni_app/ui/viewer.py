"""The big preview: show the current image, zoom + pan, rotation, the live
edit render, and the zoom readout.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import math
import datetime

from PIL import Image, ImageTk

from ..config import ACCENT, FG_DIM, BG, BAR
from .. import imaging


class ViewerMixin:
    RULER_W = 16    # ruler bar thickness, in screen px
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
        self._message = None
        self.fit_mode = True     # each photo starts fitted, un-panned
        self.pan_x = self.pan_y = 0.0
        self._view_key = None    # new photo → drop the cached scaled image
        self._reset_sliders()
        self._rotated = False    # fresh photo → no edits yet, nothing to save
        self._cropped = False
        self._healed = False     # retouch edits live in current_pil; reloaded photo has none
        self._heal_before_img = None   # drop any half-finished stroke
        self._heal_dirty = self._heal_last = None
        self.clone_src = self.clone_offset = None   # clone anchor was for the old photo
        self.crop_rect = None    # drop any pending crop box from the last photo
        self.crop_ratio = None
        self._crop_btn_active = None
        self._restyle_crop_chips()
        self._edits_saved = False
        self._render_preview()
        self._update_info(path)
        self._highlight_thumb()
        self._scroll_to_thumb()
        self.lbl_pos.configure(text=f"{self.index + 1} / {len(self.files)}")
        self._save_state()

    # --- Zoom + pan ---------------------------------------------------------

    def _fit_scale(self, vw, vh):
        "Pixels-per-source-pixel that fits the photo in the viewport (never upscales)."
        iw, ih = self.current_pil.size
        return min(vw / iw, vh / ih, 1.0)

    def _eff_scale(self, vw, vh):
        "The scale actually drawn now: the fit scale in fit mode, else user_scale."
        return self._fit_scale(vw, vh) if self.fit_mode else self.user_scale

    def fit_view(self):
        "Fit the photo to the window and recenter. Bound to the ⤢ button + 'Fit'."
        self.fit_mode = True
        self.pan_x = self.pan_y = 0.0
        self._render_preview()

    def zoom_to(self, scale):
        "Jump to an absolute zoom (e.g. 1.0 = 100%) from a preset, around center."
        self._set_scale(scale)

    def zoom_in(self):
        "− / + buttons and wheel share one step; here, one step in, around center."
        vw = max(self.preview.winfo_width(), 1)
        vh = max(self.preview.winfo_height(), 1)
        self._set_scale(self._eff_scale(vw, vh) * self.ZOOM_STEP)

    def zoom_out(self):
        vw = max(self.preview.winfo_width(), 1)
        vh = max(self.preview.winfo_height(), 1)
        self._set_scale(self._eff_scale(vw, vh) / self.ZOOM_STEP)

    def _set_scale(self, new_scale, cx=None, cy=None):
        "Set an absolute zoom, keeping the point (cx, cy) — or the center — fixed."
        if self.current_pil is None:
            return
        vw = max(self.preview.winfo_width(), 1)
        vh = max(self.preview.winfo_height(), 1)
        new_scale = max(self.MIN_SCALE, min(self.MAX_SCALE, new_scale))
        iw, ih = self.current_pil.size
        s0 = self._eff_scale(vw, vh)
        if cx is None:
            cx = vw / 2
        if cy is None:
            cy = vh / 2
        # Source pixel under (cx, cy) must stay under (cx, cy) after the zoom.
        sx = (cx - ((vw - iw * s0) / 2 + self.pan_x)) / s0
        sy = (cy - ((vh - ih * s0) / 2 + self.pan_y)) / s0
        self.fit_mode = False
        self.user_scale = new_scale
        self.pan_x = cx - sx * new_scale - (vw - iw * new_scale) / 2
        self.pan_y = cy - sy * new_scale - (vh - ih * new_scale) / 2
        self._render_preview()

    def _clamp_pan(self, vw, vh, scale):
        "Keep the photo covering the viewport (no empty gaps); center it if smaller."
        iw, ih = self.current_pil.size
        mx = max(0.0, (iw * scale - vw) / 2)
        my = max(0.0, (ih * scale - vh) / 2)
        self.pan_x = max(-mx, min(mx, self.pan_x))
        self.pan_y = max(-my, min(my, self.pan_y))

    def _on_zoom(self, event):
        "Mouse wheel: zoom toward/away from the cursor, keeping that point fixed."
        if self.current_pil is None:
            return "break"
        vw = max(self.preview.winfo_width(), 1)
        vh = max(self.preview.winfo_height(), 1)
        factor = self.ZOOM_STEP if event.delta > 0 else 1 / self.ZOOM_STEP
        self._set_scale(self._eff_scale(vw, vh) * factor, event.x, event.y)
        return "break"

    # --- Preview mouse dispatch (the tools share the left button + wheel) -----
    # One set of bindings on the canvas routes to whichever tool is open: heal
    # takes over while its section is active, otherwise crop (which itself only
    # acts when the crop box is live), and the wheel zooms unless heal claims it.

    def _preview_press(self, event):
        if self._focus_active():
            return self._focus_press(event)
        if self._heal_active():
            return self._heal_press(event)
        return self._crop_press(event)

    def _preview_alt_press(self, event):
        # Alt+click sets the clone source while clone mode is open; otherwise it
        # behaves like a normal press so crop / heal / focus still work.
        if self._heal_active() and self.heal_mode == "clone":
            return self._clone_set_source(event)
        return self._preview_press(event)

    def _preview_drag(self, event):
        if self._focus_active():
            return self._focus_move(event)
        if self._heal_active():
            return self._heal_move(event)
        return self._crop_move(event)

    def _preview_release(self, event):
        if self._focus_active():
            return self._focus_release(event)
        if self._heal_active():
            return self._heal_release(event)
        return self._crop_release(event)

    def _preview_hover(self, event):
        if self._focus_active():
            return self._focus_hover(event)
        if self._heal_active():
            return self._heal_hover(event)
        return self._crop_hover(event)

    def _preview_wheel(self, event):
        if self._heal_active():
            return self._heal_wheel(event)
        return self._on_zoom(event)

    def _on_pan_start(self, event):
        "Middle-button press: grab the canvas (hand) and remember the start point."
        if self.current_pil is None:
            return
        self._pan_anchor = (event.x, event.y, self.pan_x, self.pan_y)
        self.preview.configure(cursor="fleur")

    def _on_pan_move(self, event):
        "Middle-button drag: shift the view by how far the mouse has moved."
        if self._pan_anchor is None:
            return
        ax, ay, px, py = self._pan_anchor
        self.pan_x = px + (event.x - ax)
        self.pan_y = py + (event.y - ay)
        self._render_preview()

    def _on_pan_end(self, event):
        "Release the canvas: restore the normal cursor."
        self._pan_anchor = None
        self.preview.configure(cursor="")

    # --- Rotation -----------------------------------------------------------

    def rotate_left(self):
        "Rotate the current photo 90° counter-clockwise (preview; saved on შენახვა)."
        self._rotate(Image.ROTATE_90)

    def rotate_right(self):
        "Rotate the current photo 90° clockwise (preview; saved on შენახვა)."
        self._rotate(Image.ROTATE_270)

    def _rotate(self, transpose_op):
        "Losslessly transpose current_pil, refit the view, and refresh the info bar."
        if self.current_pil is None:
            return
        self.current_pil = self.current_pil.transpose(transpose_op)
        self._rotated = True            # rotation is an edit worth offering to save
        self._clear_focus_for_geometry()  # source-px circle no longer maps after a rotate
        self._edits_saved = False
        self.fit_mode = True            # aspect ratio swapped → refit to window
        self.pan_x = self.pan_y = 0.0
        self._view_key = None           # size changed → drop the cached scaled view
        self._render_preview()
        self._update_info(os.path.join(self.folder, self.files[self.index]))

    def _draw_message(self, text):
        "Clear the canvas and show centered placeholder text (e.g. 'no photos')."
        c = self.preview
        c.delete("all")
        c.image = None
        vw = max(c.winfo_width(), 1)
        vh = max(c.winfo_height(), 1)
        c.create_text(vw / 2, vh / 2, text=text, fill=FG_DIM,
                      font=("Segoe UI", 12))

    def _edits(self):
        "Snapshot the live slider values as a plain imaging.Edits object."
        return imaging.Edits(
            brightness=self.brightness, contrast=self.contrast,
            highlights=self.highlights, shadows=self.shadows,
            whites=self.whites, blacks=self.blacks,
            clarity=self.clarity, texture=self.texture,
            vibrance=self.vibrance, color=self.color,
            temperature=self.temperature, tint=self.tint,
            bw=self.bw, sepia=self.sepia,
            sharpen=self.sharpen, vignette=self.vignette, focus=self.focus)

    def _apply_edits(self, img, scale=1.0, src_box=None, full_size=None):
        "Apply the live edit factors via the pure imaging module."
        return imaging.apply_edits(
            img, self._edits(), auto_luts=self._auto_luts, scale=scale,
            src_box=src_box, full_size=full_size, vig_cache=self._vig_cache,
            focus_cache=self._focus_cache)


    def _render_preview(self):
        """Render only the visible part of the photo at the current zoom + pan.

        Re-scaling just the viewport (not the whole enlarged image) keeps zoom
        fast on a weak laptop. The cropped+scaled base is cached so slider edits
        only re-apply the cheap colour pass.
        """
        if self.current_pil is None:
            if self._message:
                self._draw_message(self._message)
            self._update_zoom_readout(None)
            return
        vw = max(self.preview.winfo_width(), 1)
        vh = max(self.preview.winfo_height(), 1)
        if vw <= 1 or vh <= 1:
            return

        iw, ih = self.current_pil.size
        scale = self._eff_scale(vw, vh)
        self._clamp_pan(vw, vh, scale)
        off_x = (vw - iw * scale) / 2 + self.pan_x
        off_y = (vh - ih * scale) / 2 + self.pan_y
        self._disp = (scale, off_x, off_y)   # for crop ↔ screen coordinate maps

        # Source-pixel box visible in the viewport (clipped to the image).
        sx0 = max(0, int((0 - off_x) / scale))
        sy0 = max(0, int((0 - off_y) / scale))
        sx1 = min(iw, int(math.ceil((vw - off_x) / scale)))
        sy1 = min(ih, int(math.ceil((vh - off_y) / scale)))
        if sx1 <= sx0 or sy1 <= sy0:
            self.preview.delete("all")
            return

        # Transparent images (PNG/WebP/…) get a checkerboard backdrop so the
        # see-through areas read as transparent. The alpha mask rides alongside
        # the cached RGB base so edits stay a pure colour pass on the photo.
        self._has_alpha = imaging.has_alpha(self.current_pil)
        key = (id(self.current_pil), round(scale, 5), sx0, sy0, sx1, sy1)
        if key != self._view_key or self._view_base is None:
            region = self.current_pil.crop((sx0, sy0, sx1, sy1))
            dw = max(1, round((sx1 - sx0) * scale))
            dh = max(1, round((sy1 - sy0) * scale))
            if self._has_alpha:
                rgba = region.convert("RGBA").resize((dw, dh), Image.LANCZOS)
                self._view_base = rgba.convert("RGB")
                self._view_alpha = rgba.getchannel("A")
            else:
                self._view_base = region.convert("RGB").resize((dw, dh), Image.LANCZOS)
                self._view_alpha = None
            self._view_key = key

        img = self._apply_edits(self._view_base, scale, (sx0, sy0, sx1, sy1), (iw, ih))
        if self._view_alpha is not None:
            bg = self._checker_bg(img.width, img.height)
            img = Image.composite(img, bg, self._view_alpha)
        photo = ImageTk.PhotoImage(img)
        self.preview.delete("all")
        self.preview.create_image(off_x + sx0 * scale, off_y + sy0 * scale,
                                  anchor="nw", image=photo)
        self.preview.image = photo   # keep a reference alive
        if self._crop_active():
            self._draw_crop_overlay()
        elif self._heal_active():
            self._draw_heal_cursor()
        elif self._focus_active():
            self._draw_focus_overlay()
        if getattr(self, "show_rulers", True):
            self._draw_rulers(vw, vh, scale, off_x, off_y)
        self._update_zoom_readout(scale)

    # --- Transparency checkerboard ------------------------------------------

    def _checker_bg(self, w, h):
        "A cached checkerboard at least (w, h); rebuilt only when the view grows."
        cw, ch = getattr(self, "_checker_size", (0, 0))
        if getattr(self, "_checker_img", None) is None or cw < w or ch < h:
            cw, ch = max(w, cw), max(h, ch)
            self._checker_img = imaging.checkerboard(cw, ch)
            self._checker_size = (cw, ch)
        return self._checker_img.crop((0, 0, w, h))

    # --- Rulers -------------------------------------------------------------

    def toggle_rulers(self):
        "Show/hide the top + left rulers (Ctrl+R). Remembered across sessions."
        self.show_rulers = not getattr(self, "show_rulers", True)
        self._render_preview()
        self._save_state()

    @staticmethod
    def _ruler_step(scale):
        "Source px between labeled ticks, a 1/2/5×10ⁿ 'nice' number ≥ ~64 screen px."
        raw = 64.0 / scale
        mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
        for m in (1, 2, 5):
            if m * mag >= raw:
                return m * mag
        return 10 * mag

    def _draw_rulers(self, vw, vh, scale, off_x, off_y):
        """Top + left rulers in source-pixel units, tracking the live zoom + pan.

        Drawn last, over the photo, so they frame the canvas like a real editor.
        `_render_preview` clears the canvas every frame, so the ticks re-derive
        from the current transform and stay glued to the image as it moves.
        """
        c = self.preview
        rw = self.RULER_W
        font = ("Segoe UI", 7)
        # Opaque bars + a 1px inner seam so the strips read as a frame.
        c.create_rectangle(0, 0, vw, rw, fill=BAR, width=0)
        c.create_rectangle(0, 0, rw, vh, fill=BAR, width=0)
        c.create_line(0, rw + 0.5, vw, rw + 0.5, fill=BG)
        c.create_line(rw + 0.5, 0, rw + 0.5, vh, fill=BG)

        step = self._ruler_step(scale)
        minor = step / 5.0

        # Top ruler: a tick per minor step; the multiples of `step` get a label.
        n = int(math.floor(((rw - off_x) / scale) / minor))
        while True:
            sx = n * minor
            x = off_x + sx * scale
            if x > vw:
                break
            if x >= rw:
                major = (n % 5 == 0)
                c.create_line(x, rw - (8 if major else 4), x, rw, fill=FG_DIM)
                if major:
                    c.create_text(x + 2, rw / 2, text=str(int(round(sx))),
                                  anchor="w", fill=FG_DIM, font=font)
            n += 1

        # Left ruler: the same, with the labels rotated to fit the narrow bar.
        n = int(math.floor(((rw - off_y) / scale) / minor))
        while True:
            sy = n * minor
            y = off_y + sy * scale
            if y > vh:
                break
            if y >= rw:
                major = (n % 5 == 0)
                c.create_line(rw - (8 if major else 4), y, rw, y, fill=FG_DIM)
                if major:
                    label = str(int(round(sy)))
                    c.create_text(rw / 2, y + 2 + len(label) * 3, text=label,
                                  anchor="center", angle=90, fill=FG_DIM, font=font)
            n += 1
        # A filled corner square caps where the two bars meet.
        c.create_rectangle(0, 0, rw, rw, fill=BAR, width=0)
        c.create_line(0, rw + 0.5, rw + 0.5, rw + 0.5, fill=BG)
        c.create_line(rw + 0.5, 0, rw + 0.5, rw + 0.5, fill=BG)

    # --- Zoom readout (bottom bar) ------------------------------------------

    def _update_zoom_readout(self, scale):
        "Refresh the '%' label and highlight the matching quick-size chip."
        if not hasattr(self, "lbl_zoom"):
            return
        self.lbl_zoom.configure(text="—" if scale is None else f"{round(scale * 100)}%")
        for chip in self.zoom_presets:
            chip.configure(fg=ACCENT if self._chip_active(chip) else FG_DIM)

    def _chip_active(self, chip):
        "True if this quick-size chip matches the current zoom state."
        if chip._scale is None:          # the 'Fit' chip
            return self.fit_mode
        return (not self.fit_mode) and abs(self.user_scale - chip._scale) < 1e-3

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
