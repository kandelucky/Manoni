"""The big preview: show the current image, zoom + pan, rotation, the live
edit render, and the zoom readout.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import math
import queue
import datetime
import threading

from PIL import Image, ImageTk

# FG_DIM/BG/BAR are used only by the preview-canvas draws (letterbox, rulers,
# placeholder) which stay dark in light mode; the zoom-chip / info-bar colours
# now come from self.theme.
from ..config import FG_DIM, BG, BAR
from .. import imaging
from ..i18n import t


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
        self._before_pil = None  # fresh photo → no heal yet, so "before" == current_pil
        self._before_base_key = None
        self._reset_sliders()
        self._rotated = False    # fresh photo → no edits yet, nothing to save
        self._mirrored = False
        self._cropped = False
        self._resized = False
        self._perspd = False     # fresh photo → no pending keystone correction
        self._healed = False     # retouch edits live in current_pil; reloaded photo has none
        self._heal_before_img = None   # drop any half-finished stroke
        self._heal_dirty = self._heal_last = None
        self.clone_src = self.clone_offset = None   # clone anchor was for the old photo
        self.crop_rect = None    # drop any pending crop box from the last photo
        self.crop_ratio = None
        self._filter_anchor = None  # a new photo starts with no filter-trying run
        self._crop_btn_active = None
        self._restyle_crop_chips()
        self._reset_straighten()  # fresh photo → no pending horizon tilt
        self._reset_perspective()  # fresh photo → no pending keystone correction
        self._edits_saved = False
        self._render_preview()
        self._refresh_filter_strip()   # rebuild the filter previews for this photo
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
        if self.straighten and self.active_section == "crop" and self.panel_open:
            return "break"   # the straighten preview needs the photo fully fitted
        if (self.active_section == "perspective" and self.panel_open
                and (self.persp_v or self.persp_h)):
            return "break"   # the perspective preview needs the photo fully fitted
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
        if self.hand_tool:                       # hand tool overrides every tool
            return self._on_pan_start(event)
        if self.compare_mode:                    # split-line drag overrides the edit tools
            return self._compare_drag(event)
        if self._focus_active():
            return self._focus_press(event)
        if self._text_active():
            return self._text_press(event)
        if self._logo_active():
            return self._logo_press(event)
        if self._heal_active():
            return self._heal_press(event)
        return self._crop_press(event)

    def _preview_alt_press(self, event):
        # Alt+click sets the retouch source while the tool is open — mandatory
        # before painting in clone mode, optional (in place of the auto-picked
        # neighbour) in auto heal; otherwise it behaves like a normal press so
        # crop / focus still work.
        if self._heal_active():
            return self._clone_set_source(event)
        return self._preview_press(event)

    def _preview_drag(self, event):
        if self.hand_tool:
            return self._on_pan_move(event)
        if self.compare_mode:
            return self._compare_drag(event)
        if self._focus_active():
            return self._focus_move(event)
        if self._text_active():
            return self._text_move(event)
        if self._logo_active():
            return self._logo_move(event)
        if self._heal_active():
            return self._heal_move(event)
        return self._crop_move(event)

    def _preview_release(self, event):
        if self.hand_tool:
            return self._on_pan_end(event)
        if self.compare_mode:                    # the line moves live on drag; nothing to finalize
            return
        if self._focus_active():
            return self._focus_release(event)
        if self._text_active():
            return self._text_release(event)
        if self._logo_active():
            return self._logo_release(event)
        if self._heal_active():
            return self._heal_release(event)
        return self._crop_release(event)

    def _preview_hover(self, event):
        if self.hand_tool:                       # keep the hand cursor; no tool hover
            return
        if self.compare_mode:                    # keep the resize cursor; no tool hover
            return
        if self._focus_active():
            return self._focus_hover(event)
        if self._text_active():
            return self._text_hover(event)
        if self._logo_active():
            return self._logo_hover(event)
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
        "Release the canvas: restore the cursor (the hand stays armed if its tool is on)."
        self._pan_anchor = None
        self.preview.configure(cursor="hand2" if self.hand_tool else "")

    # --- Before/after compare -----------------------------------------------

    def _compare_drag(self, event):
        "Move the split divider to the pointer (clamped to the photo's on-screen span)."
        if self.current_pil is None:
            return
        vw = max(self.preview.winfo_width(), 1)
        x = event.x
        if self._compare_span:               # keep the line on the photo, not the gutter
            lo, hi = self._compare_span
            x = max(lo, min(hi, x))
        self.compare_frac = max(0.0, min(1.0, x / vw))
        self._render_preview()

    def _compare_peek_on(self):
        "Hold: show the full original (no edits) until the button is released."
        if self.current_pil is None:
            return
        self._compare_peek = True
        self._render_preview()

    def _compare_peek_off(self):
        "Release: drop the peek and re-render with the edits (and split, if on)."
        if not self._compare_peek:
            return
        self._compare_peek = False
        self._render_preview()

    # --- Rotation + mirror --------------------------------------------------

    def rotate_left(self):
        "Rotate the current photo 90° counter-clockwise (preview; saved on Save)."
        self._rotate(Image.ROTATE_90)

    def rotate_right(self):
        "Rotate the current photo 90° clockwise (preview; saved on Save)."
        self._rotate(Image.ROTATE_270)

    def mirror_horizontal(self):
        "Mirror the current photo left↔right (preview; saved on Save)."
        self._rotate(Image.FLIP_LEFT_RIGHT, mirror=True)

    def mirror_vertical(self):
        "Mirror the current photo top↔bottom (preview; saved on Save)."
        self._rotate(Image.FLIP_TOP_BOTTOM, mirror=True)

    def _rotate(self, transpose_op, mirror=False):
        "Losslessly transpose current_pil, refit the view, and refresh the info bar."
        if self.current_pil is None:
            return
        before_geom = self._geometry_snapshot()   # for one-step undo of the turn
        self.current_pil = self.current_pil.transpose(transpose_op)
        if self._before_pil is not None:   # keep the compare "before" aligned to the edit
            self._before_pil = self._before_pil.transpose(transpose_op)
            self._before_base_key = None
        self._reset_straighten()        # a 90° turn invalidates any pending tilt
        if mirror:
            self._mirrored = True       # mirroring is an edit worth offering to save
        else:
            self._rotated = True        # rotation is an edit worth offering to save
        self._clear_focus_for_geometry()  # source-px circle no longer maps after a rotate
        self._clear_text_for_geometry()   # …and the source-px text position no longer maps
        self._clear_logo_for_geometry()   # …and the source-px logo position no longer maps
        self._edits_saved = False
        if not mirror:                  # a 90° turn swaps the aspect ratio; a mirror doesn't
            self.fit_mode = True
            self.pan_x = self.pan_y = 0.0
        self._view_key = None           # pixels changed → drop the cached scaled view
        self._render_preview()
        self._refresh_filter_strip()    # the rotated photo needs fresh thumbnails
        self._update_info(os.path.join(self.folder, self.files[self.index]))
        self._record_geometry(before_geom)   # rotate / mirror is now undoable

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
            brightness=self.brightness, exposure_g=self.exposure_g,
            contrast=self.contrast,
            highlights=self.highlights, shadows=self.shadows,
            whites=self.whites, blacks=self.blacks,
            clarity=self.clarity, texture=self.texture,
            vibrance=self.vibrance, color=self.color, dehaze=self.dehaze,
            temperature=self.temperature, tint=self.tint,
            sat_red=self.sat_red, sat_orange=self.sat_orange,
            sat_yellow=self.sat_yellow, sat_green=self.sat_green,
            sat_aqua=self.sat_aqua, sat_blue=self.sat_blue,
            sat_purple=self.sat_purple, sat_magenta=self.sat_magenta,
            gold_hue=self.gold_hue, gold_sat=self.gold_sat,
            gold_light=self.gold_light,
            skin_hue=self.skin_hue, skin_sat=self.skin_sat,
            skin_light=self.skin_light,
            bw=self.bw, sepia=self.sepia, grain=self.grain,
            denoise=self.denoise,
            split_hi=self.split_hi, split_sh=self.split_sh,
            sharpen=self.sharpen, vignette=self.vignette,
            # Copy the focus dict + each text overlay so the render (which may run
            # on the worker thread) reads a stable snapshot even if the UI thread
            # keeps dragging the shape / caption underneath it.
            focus=dict(self.focus) if self.focus else None,
            texts=[dict(ov) for ov in self.texts],
            logos=[dict(ov) for ov in self.logos])

    def _apply_edits(self, img, scale=1.0, src_box=None, full_size=None, fast=False):
        "Apply the live edit factors via the pure imaging module."
        return imaging.apply_edits(
            img, self._edits(), auto_luts=self._auto_luts, scale=scale,
            src_box=src_box, full_size=full_size, vig_cache=self._vig_cache,
            focus_cache=self._focus_cache, fast=fast)

    def _run_edit(self, req):
        """The heavy edit pass for one render request — the ONLY costly step, and
        the one that runs on the worker thread in async mode.

        Fast preview: while a drag is live the request carries fast=True, dropping
        the heavy filters (clarity, sharpen, denoise, dehaze, focus, grain) so the
        drag stays cheap; the release request brings them back at full quality.
        The edit runs through the incremental cache (apply_edits_cached), so it
        only recomputes the pipeline stages downstream of whatever changed — an
        already-applied heavy effect is reused, not recomputed every slider move.
        The cache lock only matters across an async on/off toggle; uncontended
        otherwise (one worker, or the UI thread alone)."""
        with self._cache_lock:
            return imaging.apply_edits_cached(
                req["base"], req["edits"], self._edit_cache, req["epoch"],
                auto_luts=req["auto_luts"], scale=req["scale"],
                src_box=req["src_box"], full_size=req["full_size"],
                vig_cache=self._vig_cache, focus_cache=self._focus_cache,
                fast=req["fast"])

    def _schedule_preview(self):
        """Coalesce a burst of slider-drag renders into one.

        A drag fires many <B1-Motion> events; rendering synchronously on each let
        them queue up, so the photo trailed behind the slider (the 'jam'). Marking
        'a render is due' and doing it once on the next idle pass collapses the
        burst to a single render of the LATEST values — the photo keeps up instead
        of replaying every stale intermediate frame."""
        if self._preview_scheduled:
            return
        self._preview_scheduled = True
        self.root.after_idle(self._run_scheduled_preview)

    def _run_scheduled_preview(self):
        "Idle callback for _schedule_preview: render once with the latest values."
        self._preview_scheduled = False
        self._render_preview()

    def _render_preview(self, inline=False):
        """Prepare one frame, then hand the heavy edit pass off to be drawn.

        The cheap part — geometry, and re-scaling just the visible viewport (not
        the whole enlarged image) into the cached `_view_base` — runs here on the
        UI thread. The costly part (the edit pass) is packaged into a request and
        either run on the worker thread (async mode: the window stays responsive
        while a heavy effect renders) or run inline; either way `_finish_render`
        draws the result on the UI thread. The cropped+scaled base is cached, so a
        slider drag skips the rescale and only pays the (incremental) edit pass.

        `inline` forces the sync path even in async mode: a heal stroke patches
        `_view_base` in place per dab, so it must not hand that live-mutating
        buffer to the worker thread (which would read it while the next dab writes).
        """
        self._refresh_saved_indicator()   # keep the unsaved ● in step with edits
        if self.current_pil is None:
            if self._message:
                self._draw_message(self._message)
            self._update_zoom_readout(None)
            self._hist_pil = None
            self._update_histogram()
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
            dw = max(1, round((sx1 - sx0) * scale))
            dh = max(1, round((sy1 - sy0) * scale))
            box = (sx0, sy0, sx1, sy1)
            want = "RGBA" if self._has_alpha else "RGB"
            src = self.current_pil
            if src.mode != want:
                # Convert only what is on screen — a full-frame convert of a
                # 24 MP source is waste when the viewport shows a corner of it.
                if box != (0, 0, iw, ih):
                    src = src.crop(box)
                src = src.convert(want)
                box = None                   # `src` is already the region
            # `box=` crops inside the resize, so an unzoomed view needs no
            # full-size copy at all; `reducing_gap` pre-shrinks cheaply before
            # LANCZOS. Preview only — the export path is untouched.
            out = src.resize((dw, dh), Image.LANCZOS, box=box, reducing_gap=2.0)
            if self._has_alpha:
                self._view_base = out.convert("RGB")
                self._view_alpha = out.getchannel("A")
            else:
                self._view_base = out
                self._view_alpha = None
            self._view_key = key
            self._view_epoch += 1    # base pixels rebuilt → retire the edit cache

        # The frame request: the base + a full snapshot of the edit inputs, plus
        # the geometry `_finish_render` needs to place and finish the image. `gen`
        # tags it so a stale worker result (superseded by a newer render) is
        # dropped; `view_key` lets the finish detect the view moved on meanwhile.
        fast = self._interacting and getattr(self, "fast_preview", True)
        self._render_gen += 1
        req = {"base": self._view_base, "edits": self._edits(),
               "auto_luts": self._auto_luts, "epoch": self._view_epoch,
               "scale": scale, "src_box": (sx0, sy0, sx1, sy1),
               "full_size": (iw, ih), "fast": fast, "gen": self._render_gen,
               "off_x": off_x, "off_y": off_y, "sx0": sx0, "sy0": sy0,
               "vw": vw, "vh": vh, "view_key": self._view_key,
               "interacting": self._interacting}

        if not inline and getattr(self, "async_render", True) \
                and self._start_render_worker():
            self._submit_render(req)      # worker renders, then posts _finish_render
        else:
            self._finish_render(self._run_edit(req), req)

    def _finish_render(self, img, req):
        """Composite + draw a finished edit frame on the UI thread.

        Runs either inline (sync mode) or via `root.after` from the worker. It is
        cheap: alpha checker, the straighten / perspective / compare overlays, the
        canvas blit and the tool overlays. Stale frames are dropped — a newer
        render (`gen`) or a view that has since moved (`view_key`) means this
        result no longer matches what should be on screen.
        """
        if req["gen"] != self._render_gen:
            return                        # a newer render has superseded this one
        if self.current_pil is None or req["view_key"] != self._view_key:
            return                        # zoom / pan / new photo moved the view on
        scale, off_x, off_y = req["scale"], req["off_x"], req["off_y"]
        sx0, sy0, vw = req["sx0"], req["sy0"], req["vw"]
        self._hist_pil = img    # edited photo pixels (pre-checker) → live histogram
        if self._view_alpha is not None:
            bg = self._checker_bg(img.width, img.height)
            img = Image.composite(img, bg, self._view_alpha)
        # Horizon straighten preview: with the whole photo fitted, _view_base is
        # the full image scaled, so rotating it here matches rotating the full-res
        # photo on commit. The empty corners fill with the canvas colour so they
        # blend into the letterbox; the crop overlay marks what will be kept.
        if self.straighten and self.active_section == "crop" and self.panel_open:
            img = img.rotate(-self.straighten, resample=Image.BICUBIC,
                             expand=False, fillcolor=BG)
        # Perspective preview: with the whole photo fitted, the warp on the scaled
        # view matches the full-res commit (apply_perspective is scale-free) and
        # fills the frame fully — no empty corners. The crop overlay isn't shown
        # here; the sliders alone drive it.
        if (self.active_section == "perspective" and self.panel_open
                and (self.persp_v or self.persp_h)):
            img = imaging.apply_perspective(
                img, self.persp_v / 100.0, self.persp_h / 100.0)
        # Before/after compare: peek shows the full original; the split shows the
        # unedited photo left of a draggable divider, the edit to its right. The
        # span is recorded so the divider + its drag stay glued to the photo.
        img_left = off_x + sx0 * scale
        self._compare_span = (img_left, img_left + img.width)
        if self._compare_peek or self.compare_mode:
            img = self._compose_compare(img, img_left, vw)
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
        elif self._text_active():
            self._draw_text_overlay()
        elif self._logo_active():
            self._draw_logo_overlay()
        if getattr(self, "show_rulers", True):
            self._draw_rulers(req["vw"], req["vh"], scale, off_x, off_y)
        if self.compare_mode and not self._compare_peek:
            self._draw_compare_divider(req["vw"], req["vh"])
        self._update_zoom_readout(scale)
        if not req["interacting"]:
            self._update_histogram()   # heavy; frozen mid-drag, refreshed on release

    # --- Async render worker ------------------------------------------------
    # The edit pass is the only heavy step; running it here (off the Tk thread)
    # keeps the window responsive while a costly effect renders. Only the newest
    # request is kept — a burst of slider frames collapses to its latest. The
    # worker touches NO Tk (Tkinter is single-thread only): it computes pixels and
    # drops them in a queue that the UI thread drains on a short poll, calling
    # _finish_render there. Toggle it off (Settings) to render inline instead.

    RENDER_POLL_MS = 15    # how often the UI thread checks for a finished frame

    def _start_render_worker(self):
        "Start the worker on first use; return False if a thread can't be created."
        if getattr(self, "_render_thread", None) is not None:
            return True
        try:
            self._render_cv = threading.Condition()
            self._render_req = None      # newest unrendered request (or None)
            self._render_busy = False    # is the worker mid-render right now?
            self._render_result_q = queue.Queue()
            self._poller_on = False      # is the drain callback scheduled?
            self._render_thread = threading.Thread(
                target=self._render_worker, name="manoni-render", daemon=True)
            self._render_thread.start()
            return True
        except Exception:
            self._render_thread = None
            return False

    def _submit_render(self, req):
        "Hand the newest request to the worker; any older pending one is dropped."
        with self._render_cv:
            self._render_req = req
            self._render_cv.notify()
        if not self._poller_on:          # (main thread only — no race with drain)
            self._poller_on = True
            self.root.after(self.RENDER_POLL_MS, self._drain_render_results)

    def _render_worker(self):
        "Background loop: render the newest request, queue the result for the UI."
        while True:
            with self._render_cv:
                while self._render_req is None:
                    self._render_cv.wait()
                req = self._render_req
                self._render_req = None
                self._render_busy = True
            try:
                self._render_result_q.put((self._run_edit(req), req))
            except Exception:
                pass              # a failed frame just skips; the next one draws
            finally:
                with self._render_cv:
                    self._render_busy = False

    def _drain_render_results(self):
        "UI-thread poll: draw the freshest finished frame; keep polling if busy."
        latest = None
        try:
            while True:
                latest = self._render_result_q.get_nowait()   # keep only the newest
        except queue.Empty:
            pass
        if latest is not None:
            self._finish_render(latest[0], latest[1])
        with self._render_cv:
            outstanding = self._render_req is not None or self._render_busy
        # The queue check closes a race: the worker puts a result BEFORE clearing
        # _render_busy, so if we observed busy=False the result is already queued.
        # Without it, a frame that lands between the drain above and this check
        # would be stranded until the next submit.
        if outstanding or latest is not None or not self._render_result_q.empty():
            self.root.after(self.RENDER_POLL_MS, self._drain_render_results)
        else:
            self._poller_on = False       # nothing left in flight → stop polling

    def _render_histogram(self, w, h):
        "Build the panel's live-histogram image from the edited viewport (None if"
        " no photo). Called back by the Histogram widget at its current width."
        src = getattr(self, "_hist_pil", None)
        return imaging.histogram_image(src, w, h) if src is not None else None

    def _update_histogram(self):
        "Refresh the panel histogram from the latest render (no-op before build)."
        hist = getattr(self, "histogram", None)
        if hist is not None:
            hist.refresh()

    def _before_view_base(self):
        """The 'before' scaled viewport: the heal-free `_before_pil` if a stroke
        has diverged it, else the plain `_view_base` (no heal → identical pixels).

        Built at the SAME geometry as `_view_base` (same crop box + display size),
        cached by (view key, before image) so it survives slider drags and divider
        moves and only rebuilds on zoom/pan/heal/crop/rotate.
        """
        if self._before_pil is None or self._view_key is None:
            return self._view_base
        key = (self._view_key, id(self._before_pil))
        if key != self._before_base_key or self._before_base is None:
            _, _, sx0, sy0, sx1, sy1 = self._view_key
            dw, dh = self._view_base.size
            region = self._before_pil.crop((sx0, sy0, sx1, sy1))
            self._before_base = region.convert("RGB").resize((dw, dh), Image.LANCZOS)
            self._before_base_key = key
        return self._before_base

    def _compose_compare(self, img, img_left, vw):
        """Blend the unedited 'before' into the edited `img` for compare.

        "Before" is the photo with NO slider/effect edits AND none of the
        destructive heal/clone strokes — so a retouched blemish shows again on the
        left. Peek replaces the whole frame with it; the split pastes its left part
        over `img`. `img`/`before` may be a shared cache, so copy before pasting.
        """
        before = self._before_view_base()
        if self._view_alpha is not None:        # match the edited frame's backdrop
            before = Image.composite(
                before, self._checker_bg(before.width, before.height),
                self._view_alpha)
        if self._compare_peek:
            return before                       # hold → the full original
        divider = self.compare_frac * vw
        sp = max(0, min(img.width, int(round(divider - img_left))))
        if sp > 0:
            # `img` may be a cached edit-stage output (or _view_base / before) —
            # copy before pasting so the paste never mutates a shared/cached image.
            img = img.copy()
            img.paste(before.crop((0, 0, sp, img.height)), (0, 0))
        return img

    def _draw_compare_divider(self, vw, vh):
        "Draw the split line, a centre grab handle, and the before/after tags."
        x = self.compare_frac * vw
        if self._compare_span:
            lo, hi = self._compare_span
            x = max(lo, min(hi, x))
        c = self.preview
        c.create_line(x, 0, x, vh, fill="#ffffff", width=1)
        r, cy = 10, vh / 2
        c.create_oval(x - r, cy - r, x + r, cy + r, fill=BAR, outline="#ffffff")
        c.create_text(x, cy, text="‹ ›", fill="#ffffff", font=("Segoe UI", 9))
        rw = self.RULER_W if getattr(self, "show_rulers", True) else 0
        self._compare_tag(rw + 8, rw + 8, t("Before"), "nw")
        self._compare_tag(vw - 8, rw + 8, t("After"), "ne")

    def _compare_tag(self, cx, cy, text, anchor):
        "A small white label with a 1px dark shadow, so it reads over any photo."
        c = self.preview
        c.create_text(cx + 1, cy + 1, text=text, fill="#000000", anchor=anchor,
                      font=("Segoe UI", 9, "bold"))
        c.create_text(cx, cy, text=text, fill="#ffffff", anchor=anchor,
                      font=("Segoe UI", 9, "bold"))

    def _patch_view_base(self, box):
        """Refresh just `box` (source px) inside the cached scaled view.

        A heal/clone dab mutates a tiny patch of current_pil. Re-scaling the
        whole viewport for every dab (the old _view_key=None path) makes a
        stroke freeze on a big photo. Instead we re-scale only the dab's box and
        paste it into the cached _view_base, so the per-dab cost tracks the brush
        size, not the image size. Returns False (→ caller forces a full render)
        when the cache can't be patched in place.
        """
        if self._view_base is None or self._view_key is None:
            return False
        vid, scale, sx0, sy0, sx1, sy1 = self._view_key
        if vid != id(self.current_pil):
            return False
        bx0 = max(box[0], sx0); by0 = max(box[1], sy0)
        bx1 = min(box[2], sx1); by1 = min(box[3], sy1)
        if bx1 <= bx0 or by1 <= by0:
            return True                 # dab fell outside the visible region
        dx0 = round((bx0 - sx0) * scale); dy0 = round((by0 - sy0) * scale)
        dx1 = round((bx1 - sx0) * scale); dy1 = round((by1 - sy0) * scale)
        dw = max(1, dx1 - dx0); dh = max(1, dy1 - dy0)
        region = self.current_pil.crop((bx0, by0, bx1, by1))
        if self._view_alpha is not None:
            rgba = region.convert("RGBA").resize((dw, dh), Image.LANCZOS)
            self._view_base.paste(rgba.convert("RGB"), (dx0, dy0))
            self._view_alpha.paste(rgba.getchannel("A"), (dx0, dy0))
        else:
            patch = region.convert("RGB").resize((dw, dh), Image.LANCZOS)
            self._view_base.paste(patch, (dx0, dy0))
        self._view_epoch += 1   # base pixels changed in place → retire the edit cache
        return True

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
        self.show_rulers = not getattr(self, "show_rulers", False)
        self._render_preview()
        self._repaint_view_toggles()      # keep the toolbar toggle in sync
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
        self._zoom_scale = scale          # remembered so a theme switch can restyle
        if not hasattr(self, "lbl_zoom"):
            return
        self.lbl_zoom.configure(text="—" if scale is None else f"{round(scale * 100)}%")
        for chip in self.zoom_presets:
            chip.configure(fg=self.theme["accent"] if self._chip_active(chip)
                           else self.theme["fg_dim"])

    def _chip_active(self, chip):
        "True if this quick-size chip matches the current zoom state."
        if chip._scale is None:          # the 'Fit' chip
            return self.fit_mode
        return (not self.fit_mode) and abs(self.user_scale - chip._scale) < 1e-3

    def _update_info(self, path):
        try:
            w, h = self.current_pil.size if self.current_pil else (0, 0)
            size_kb = os.path.getsize(path) / 1024
            size_txt = f"{size_kb/1024:.1f} MB" if size_kb > 1024 else f"{size_kb:.0f} KB"
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
            date_txt = mtime.strftime("%Y/%m/%d %H:%M")
            folder = os.path.dirname(path)
            # Remember this line so the nav-button hover hints can restore it
            # when the pointer leaves (they borrow the same info bar).
            self._info_text = (f"{self.index+1}/{len(self.files)}   ·   {w}×{h}"
                               f"   ·   {size_txt}   ·   {date_txt}   ·   {folder}")
            self.lbl_info.configure(text=self._info_text, fg=self.theme["fg_dim"])
        except Exception:
            self._info_text = ""
            self.lbl_info.configure(text="", fg=self.theme["fg_dim"])
        # The name label carries the unsaved ● marker, so route it through the
        # indicator (which also refreshes the window title).
        self._refresh_saved_indicator()

    def _refresh_saved_indicator(self):
        """Mark the current photo saved / unsaved in the info-bar name and the
        window title: a leading ● while it has edits not yet written anywhere,
        gone once saved. A change-guard skips redundant work, so it is cheap
        enough to call on every render / edit."""
        lbl = getattr(self, "lbl_name", None)
        if lbl is None:
            return
        file = self.files[self.index] if self.files else None
        dirty = bool(file) and self._has_unsaved_edits()
        key = (file, dirty)
        if key == getattr(self, "_indicator_key", None):
            return
        self._indicator_key = key
        dot = "● " if dirty else ""           # ● when there are unsaved edits
        try:
            if file is None:
                self.root.title("Manoni")
                lbl.configure(text="Manoni")
            else:
                lbl.configure(text=dot + file)
                self.root.title(f"{dot}{file} — Manoni")
        except Exception:
            pass
