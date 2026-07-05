"""Logo / sticker overlays for Manoni.

A transparent PNG laid over the photo — the picture sibling of the text tool.
Like the text overlay (and unlike crop / heal, which bake into current_pil),
logos are LIVE, non-destructive effects: each logo's centre and its width live
in SOURCE-image pixels, so it stays glued to the photo through zoom + pan and
the small preview composites exactly like the full-res save (the imaging module
multiplies position AND size by the same `scale`).

The photo can hold MANY logos: `self.logos` is the list, `self.logo_sel` the
selected index, and the `logo_overlay` property exposes the selected element so
every per-control method stays single-overlay-simple. A logo appears ONLY by
clicking a preset thumbnail or picking a PNG file (nothing is auto-inserted);
'Delete logo' drops the selected one and 'Delete all' wipes them. Each gesture
rides one undo entry, shared with the slider-edit machinery.

Presets come from two folders (see config): the bundled LOGO_PRESET_DIR and the
user's LOGO_DIR, into which 'Choose PNG…' copies an imported file so it is
offered again next launch. Click a logo to select it, drag to move it, drag its
bottom-right handle to resize. The panel offers size, opacity, a flat-colour
tint and horizontal / vertical flip, plus one-click corner placement. Mixin on
the Manoni window — every method uses the shared `self`.
"""

import math
import os
import shutil
import tkinter as tk
from tkinter import colorchooser

from PIL import Image, ImageTk

import tintkit

from ..config import ACCENT, FG_DIM, ON_ACCENT, EDIT_PAD, LOGO_DIR, LOGO_PRESET_DIR
from ..i18n import t
from ..storage import unique_path
from .. import imaging


class LogoMixin:
    # --- Logo overlay (col 3 panel + interactive box on the preview) ---------

    LOGO_HANDLE   = 5      # half-size of the resize handle square, screen px
    LOGO_HIT_PAD  = 4      # click slack around a logo box for selection, screen px
    LOGO_MIN_SIZE = 8.0    # smallest logo width, source px
    LOGO_MARGIN   = 0.04   # corner-placement inset, as a fraction of the short side
    LOGO_PRESET_PX = 46    # preset thumbnail square, logical px
    LOGO_PRESET_COLS = 4   # thumbnails per row in the preset strip

    # --- Panel --------------------------------------------------------------

    def _build_logo_section(self, parent):
        "Logo panel: presets + import, then size / opacity / tint / flip / place."
        f = self._tw(tk.Frame(parent), bg="bar")

        self._tw(tk.Label(f, text=t("Pick a saved logo or choose a PNG, then drag it "
                           "on the photo to place it. The corner handle resizes it."),
                 font=("Segoe UI", 8), justify="left",
                 anchor="w", wraplength=self._edit_dpi_w(190)),
                 bg="bar", fg="fg_dim").pack(fill="x", padx=EDIT_PAD, pady=(10, 6))

        # Top row: ‘Choose PNG…’ (import a file — it is copied into the user logo
        # folder so it is offered again next time) and a trash icon that removes
        # the selected logo.
        addrow = self._tw(tk.Frame(f), bg="bar")
        addrow.pack(fill="x", padx=EDIT_PAD, pady=(0, 8))
        add = tintkit.Button(addrow, self.theme, t("Choose PNG…"), role="primary",
                             variant="filled", stretch=True, bg="bar",
                             command=self._import_logo)
        add.pack(side="left", fill="x", expand=True)
        tintkit.HoverTip(add.canvas, self.theme,
                         t("Add your own transparent PNG logo"))
        self._logo_del_btn = tintkit.IconButton(
            addrow, self.theme, "trash-2", w=36, h=36, icon_px=15, bg="bar",
            command=self._delete_logo)
        self._logo_del_btn.pack(side="left", padx=(6, 0))
        tintkit.HoverTip(self._logo_del_btn.canvas, self.theme,
                         t("Remove the selected logo from the photo"))

        # Preset strip: a grid of clickable thumbnails from the bundled + user
        # logo folders. Rebuilt when a PNG is imported.
        self._group_header(f, t("Saved logos"))
        self._logo_preset_host = self._tw(tk.Frame(f), bg="bar")
        self._logo_preset_host.pack(fill="x", padx=EDIT_PAD, pady=2)
        self._logo_preset_thumbs = []          # PhotoImages kept alive
        self._refresh_logo_presets()

        # Size (as % of the photo's short side) and opacity, each a TitledSlider
        # with its own reset. The press/release hooks fold a whole drag into one
        # undo step.
        self.s_logo_size = tintkit.TitledSlider(
            f, self.theme, t("Size"), value=30, lo=2, hi=100, neutral=30, bg="bar",
            command=self._set_logo_size, on_press=self._edit_gesture_start,
            on_release=self._edit_gesture_end, reset_tip=t("Reset this slider"),
            value_fmt=lambda v, n: str(v),
            on_reset=lambda: self._reset_logo_slider("size"))
        self.s_logo_size.pack(fill="x", padx=EDIT_PAD, pady=(8, 2))
        self.s_logo_opacity = tintkit.TitledSlider(
            f, self.theme, t("Opacity"), value=100, lo=0, hi=100, neutral=100,
            bg="bar", command=self._set_logo_opacity,
            on_press=self._edit_gesture_start, on_release=self._edit_gesture_end,
            reset_tip=t("Reset this slider"), value_fmt=lambda v, n: str(v),
            on_reset=lambda: self._reset_logo_slider("opacity"))
        self.s_logo_opacity.pack(fill="x", padx=EDIT_PAD, pady=2)
        # Rotation: −180…180° (0 = upright). Positive turns clockwise.
        self.s_logo_rotation = tintkit.TitledSlider(
            f, self.theme, t("Rotation"), value=0, lo=-180, hi=180, neutral=0,
            bg="bar", command=self._set_logo_rotation,
            on_press=self._edit_gesture_start, on_release=self._edit_gesture_end,
            reset_tip=t("Reset this slider"), value_fmt=lambda v, n: f"{v}°",
            on_reset=lambda: self._reset_logo_slider("rotation"))
        self.s_logo_rotation.pack(fill="x", padx=EDIT_PAD, pady=2)

        # Tint: a checkbox that recolours the whole logo to the swatch colour
        # (turns a black logo white, etc.), with the colour swatch beside it.
        row = self._tw(tk.Frame(f), bg="bar")
        row.pack(fill="x", padx=EDIT_PAD, pady=(10, 2))
        self._logo_tint_chk = tintkit.Checkbox(
            row, self.theme, t("Tint"), state="off", bg="bar",
            command=lambda _st: self._toggle_logo_tint())
        self._logo_tint_chk.pack(side="left")
        tintkit.HoverTip(self._logo_tint_chk.canvas, self.theme,
                         t("Recolour the whole logo to one flat colour"))
        self._logo_swatch = self._tw(tk.Frame(row, bg="#ffffff", cursor="hand2",
                                     width=self._edit_dpi_w(28),
                                     height=self._edit_dpi_w(16),
                                     highlightthickness=1), hl="border")
        self._logo_swatch.pack(side="right")
        self._logo_swatch.pack_propagate(False)
        self._logo_swatch.bind("<Button-1>", lambda e: self._pick_logo_color())
        tintkit.HoverTip(self._logo_swatch, self.theme, t("Pick the tint colour"))

        # Flip: two independent toggles (horizontal / vertical mirror).
        self._group_header(f, t("Flip"))
        fliprow = self._tw(tk.Frame(f), bg="bar")
        fliprow.pack(fill="x", padx=EDIT_PAD, pady=2)
        self._logo_fliph_chk = tintkit.Checkbox(
            fliprow, self.theme, t("Horizontal"), state="off", bg="bar",
            command=lambda _st: self._toggle_logo_flip("flip_h"))
        self._logo_fliph_chk.pack(side="left")
        self._logo_flipv_chk = tintkit.Checkbox(
            fliprow, self.theme, t("Vertical"), state="off", bg="bar",
            command=lambda _st: self._toggle_logo_flip("flip_v"))
        self._logo_flipv_chk.pack(side="right")

        # One-click placement: a 3×3 grid snapping the logo to a corner / edge /
        # centre with a small margin — the watermark staple.
        self._group_header(f, t("Position"))
        self._build_logo_position_grid(f)

        # Footer: Done closes the tool (the logos stay live on the photo); Delete
        # all wipes every logo. 'Delete logo' (the selected one) is the trash icon
        # up by 'Choose PNG…'. Delete all dims to disabled while there's nothing.
        done = tintkit.Button(
            f, self.theme, t("Done"), role="primary", variant="filled",
            stretch=True, bg="bar", command=lambda: self.set_section("basic"))
        done.pack(fill="x", padx=EDIT_PAD, pady=(14, 0))
        self._logo_delall_btn = tintkit.Button(
            f, self.theme, t("Delete all"), role="neutral", variant="outline",
            icon="x", stretch=True, bg="bar", command=self._delete_all_logo)
        self._logo_delall_btn.pack(fill="x", padx=EDIT_PAD, pady=(8, 8))
        tintkit.HoverTip(self._logo_delall_btn.canvas, self.theme,
                         t("Remove every logo from the photo"))
        self._refresh_logo_buttons()           # start Delete-all disabled if empty
        return f

    def _build_logo_position_grid(self, parent):
        "A 3×3 grid of buttons; each snaps the logo to that anchor with a margin."
        grid = self._tw(tk.Frame(parent), bg="bar")
        grid.pack(padx=EDIT_PAD, pady=2)
        for r, v in enumerate(("t", "m", "b")):
            for c, h in enumerate(("l", "c", "r")):
                cell = self._tw(tk.Frame(grid, cursor="hand2",
                                width=self._edit_dpi_w(34),
                                height=self._edit_dpi_w(22)), bg="chip")
                cell.grid(row=r, column=c, padx=2, pady=2)
                cell.pack_propagate(False)
                dot = self._tw(tk.Frame(cell,
                               width=self._edit_dpi_w(6), height=self._edit_dpi_w(6)),
                               bg="fg_dim")
                dot.place(relx={"l": 0.18, "c": 0.5, "r": 0.82}[h],
                          rely={"t": 0.22, "m": 0.5, "b": 0.78}[v], anchor="center")
                for w in (cell, dot):
                    w.bind("<Button-1>", lambda e, hh=h, vv=v: self._place_logo(hh, vv))
                    w.bind("<Enter>", lambda e, cc=cell, dd=dot:
                           (cc.configure(bg=self.theme["hover"]),
                            dd.configure(bg=self.theme["fg"])))
                    w.bind("<Leave>", lambda e, cc=cell, dd=dot:
                           (cc.configure(bg=self.theme["chip"]),
                            dd.configure(bg=self.theme["fg_dim"])))

    # --- Preset strip -------------------------------------------------------

    def _logo_preset_paths(self):
        "Every PNG in the bundled + user logo folders (user ones last), sorted."
        paths = []
        for d in (LOGO_PRESET_DIR, LOGO_DIR):
            try:
                names = sorted(os.listdir(d))
            except OSError:
                continue
            for name in names:
                if name.lower().endswith(".png"):
                    paths.append(os.path.join(d, name))
        return paths

    def _is_user_logo(self, path):
        "True if `path` sits in the user's writable my_logos folder — those can be"
        " deleted from the library; the bundled read-only presets cannot."
        try:
            return (os.path.normcase(os.path.abspath(os.path.dirname(path)))
                    == os.path.normcase(os.path.abspath(LOGO_DIR)))
        except (OSError, ValueError):
            return False

    def _logo_thumb(self, path):
        "A PhotoImage of `path` fitted into a light tile so light AND dark logos"
        " both read (a transparent logo on the dark chip could vanish otherwise)."
        px = round(self.LOGO_PRESET_PX * getattr(self, "dpi", 1.0))
        try:
            im = Image.open(path).convert("RGBA")
        except Exception:
            return None
        im.thumbnail((px, px), Image.LANCZOS)
        tile = Image.new("RGBA", (px, px), (200, 200, 200, 255))
        tile.paste(im, ((px - im.width) // 2, (px - im.height) // 2), im)
        return ImageTk.PhotoImage(tile.convert("RGB"))

    def _refresh_logo_presets(self):
        "Rebuild the preset thumbnail grid from the two logo folders."
        host = getattr(self, "_logo_preset_host", None)
        if host is None:
            return
        for w in host.winfo_children():
            w.destroy()
        self._logo_preset_thumbs = []
        paths = self._logo_preset_paths()
        if not paths:
            self._tw(tk.Label(host, text=t("No saved logos yet — use Choose PNG…"),
                     font=("Segoe UI", 8), justify="left", anchor="w",
                     wraplength=self._edit_dpi_w(190)),
                     bg="bar", fg="fg_dim").pack(fill="x", pady=2)
            return
        grid = self._tw(tk.Frame(host), bg="bar")
        grid.pack(anchor="w")
        for i, path in enumerate(paths):
            thumb = self._logo_thumb(path)
            self._logo_preset_thumbs.append(thumb)   # keep the ref alive
            cell = self._tw(tk.Frame(grid, cursor="hand2", highlightthickness=1),
                            bg="chip", hl="border")
            cell.grid(row=i // self.LOGO_PRESET_COLS,
                      column=i % self.LOGO_PRESET_COLS, padx=2, pady=2)
            if thumb is not None:
                lbl = tk.Label(cell, image=thumb, bg=self.theme["chip"], bd=0)
            else:
                lbl = self._tw(tk.Label(cell, text="?", width=4, height=2),
                               bg="chip", fg="fg_dim")
            lbl.pack()
            for w in (cell, lbl):
                w.bind("<Button-1>", lambda e, p=path: self._add_logo(p))
                w.bind("<Enter>", lambda e, c=cell: c.configure(
                    highlightbackground=self.theme["accent"]))
                w.bind("<Leave>", lambda e, c=cell: c.configure(
                    highlightbackground=self.theme["border"]))
            tintkit.HoverTip(lbl, self.theme, os.path.basename(path))
            # User-imported logos carry a small ✕ badge to delete them from the
            # library; the bundled read-only presets don't (nothing to delete).
            if self._is_user_logo(path):
                x = tk.Label(cell, text="✕", font=("Segoe UI", 8, "bold"),
                             bg=self.theme["bg"], fg="#ff8a8a", cursor="hand2",
                             padx=2, bd=0)
                x.place(relx=1.0, rely=0.0, anchor="ne")
                x.bind("<Button-1>",
                       lambda e, p=path: (self._delete_saved_logo(p), "break")[1])
                tintkit.HoverTip(x, self.theme, t("Remove from your saved logos"))

    def _import_logo(self):
        "‘Choose PNG…’: pick a PNG, copy it into the user logo folder (so it is"
        " remembered) and drop it on the photo."
        if self.current_pil is None:
            return
        import tkinter.filedialog as tkfd
        path = tkfd.askopenfilename(
            parent=self.root, title=t("Choose a logo PNG"),
            filetypes=[(t("PNG image"), "*.png"), (t("All files"), "*.*")])
        if not path:
            return
        try:
            os.makedirs(LOGO_DIR, exist_ok=True)
            dest = unique_path(os.path.join(LOGO_DIR, os.path.basename(path)))
            shutil.copyfile(path, dest)
        except OSError:
            dest = path                        # copy failed → use the file in place
        self._refresh_logo_presets()
        self._add_logo(dest)

    def _delete_saved_logo(self, path):
        "Delete a user-imported logo PNG from the library (confirmed), then refresh"
        " the strip. Bundled read-only presets are never deletable (no ✕ badge)."
        if not self._is_user_logo(path):
            return
        if not self._confirm(
                t("Remove “{name}” from your saved logos?\n"
                  "The PNG file will be deleted from disk.")
                .format(name=os.path.basename(path)),
                ok_label=t("Remove")):
            return
        try:
            os.remove(path)
        except OSError:
            self.toast(t("Could not remove the logo"))
            return
        self._refresh_logo_presets()
        self.toast(t("Removed from your saved logos"))

    # --- State + presets ----------------------------------------------------

    @property
    def logo_overlay(self):
        "The selected logo element (or None). Every per-element control reads and"
        " writes THIS, so the editing code stays single-overlay-simple while the"
        " photo can hold many logos in `self.logos`."
        ls = getattr(self, "logos", None)
        i = getattr(self, "logo_sel", None)
        if ls and i is not None and 0 <= i < len(ls):
            return ls[i]
        return None

    @logo_overlay.setter
    def logo_overlay(self, value):
        "A dict replaces the selected element (or becomes the first one); None is"
        " the 'clear everything' used by reset / geometry changes. Always rebinds"
        " `self.logos` to a NEW list so undo snapshots are never aliased."
        if value is None:
            self.logos = []
            self.logo_sel = None
            return
        if self.logo_sel is not None and 0 <= self.logo_sel < len(self.logos):
            new = list(self.logos)
            new[self.logo_sel] = value
            self.logos = new
        else:
            self.logos = self.logos + [value]
            self.logo_sel = len(self.logos) - 1

    def _default_logo_overlay(self, path):
        "A centred logo sized to ~30% of the photo's short side."
        iw, ih = self.current_pil.size
        return {"path": path, "cx": iw / 2.0, "cy": ih / 2.0,
                "size": max(self.LOGO_MIN_SIZE, min(iw, ih) * 0.3),
                "opacity": 1.0, "flip_h": False, "flip_v": False,
                "angle": 0.0, "tint": None}

    def _add_logo(self, path):
        "Drop ONE new logo on the photo from `path` and select it (undoable)."
        if self.current_pil is None or not path:
            return
        before = self._edit_state()
        ov = self._default_logo_overlay(path)
        # Cascade each new logo down-right of the centre so several don't pile up
        # exactly on top of each other (leaving only the topmost clickable).
        n = len(self.logos)
        if n:
            iw, ih = self.current_pil.size
            step = min(iw, ih) * 0.05
            k = n % 10
            ov["cx"] = min(max(0.0, ov["cx"] + step * k), float(iw))
            ov["cy"] = min(max(0.0, ov["cy"] + step * k), float(ih))
        self.logos = self.logos + [ov]         # rebind (never alias an undo snapshot)
        self.logo_sel = len(self.logos) - 1
        self._edits_saved = False
        self._sync_logo_controls()
        self._render_preview()
        self._record_edit(before)

    def _delete_logo(self):
        "‘Delete logo’: remove the SELECTED element from the photo (undoable)."
        if self.logo_sel is None or not (0 <= self.logo_sel < len(self.logos)):
            return
        before = self._edit_state()
        self.logos = [o for j, o in enumerate(self.logos) if j != self.logo_sel]
        self.logo_sel = (len(self.logos) - 1) if self.logos else None
        self._logo_drag = None
        self._edits_saved = False
        self._sync_logo_controls()
        self._render_preview()
        self._record_edit(before)

    def _delete_all_logo(self):
        "‘Delete all’: remove every logo element from the photo (undoable)."
        if not self.logos:
            return
        before = self._edit_state()
        self.logos = []
        self.logo_sel = None
        self._logo_drag = None
        self._edits_saved = False
        self._sync_logo_controls()
        self._render_preview()
        self._record_edit(before)

    def _enter_logo(self):
        "Open the logo tool: refresh presets + controls and fit the photo. Adds NO"
        " logo on its own — the user clicks a preset or ‘Choose PNG…’ for that."
        if self.current_pil is None:
            self._render_preview()
            return
        self._refresh_logo_presets()
        self._sync_logo_controls()
        self.preview.configure(cursor="")
        self.fit_view()                        # fit so the whole photo is visible

    def _logo_active(self):
        "True whenever the logo tool is open (so clicks can select / place logos)."
        return (self.panel_open and self.active_section == "logo"
                and self.current_pil is not None)

    def _sync_logo_controls(self):
        "Push the selected element's values into the sliders, checkboxes + swatch."
        if not hasattr(self, "s_logo_size"):
            return
        # Keep the selection index valid after deletes / undo.
        if self.logo_sel is not None and not (0 <= self.logo_sel < len(self.logos)):
            self.logo_sel = (len(self.logos) - 1) if self.logos else None
        ov = self.logo_overlay
        has = ov is not None
        if self.current_pil is not None and has:
            short = max(1, min(self.current_pil.size))
            self.s_logo_size.set(round(ov.get("size", 0.0) / short * 100))
        self.s_logo_opacity.set(round((ov.get("opacity", 1.0) if has else 1.0) * 100))
        if hasattr(self, "s_logo_rotation"):
            self.s_logo_rotation.set(round(ov.get("angle", 0.0)) if has else 0)
        tint = ov.get("tint") if has else None
        self._logo_swatch.configure(bg=tint or "#ffffff")
        if hasattr(self, "_logo_tint_chk"):
            self._logo_tint_chk.state = "on" if tint else "off"
            self._logo_tint_chk.repaint()
        if hasattr(self, "_logo_fliph_chk"):
            self._logo_fliph_chk.state = "on" if (has and ov.get("flip_h")) else "off"
            self._logo_fliph_chk.repaint()
        if hasattr(self, "_logo_flipv_chk"):
            self._logo_flipv_chk.state = "on" if (has and ov.get("flip_v")) else "off"
            self._logo_flipv_chk.repaint()
        self._refresh_logo_buttons()

    def _refresh_logo_buttons(self):
        "Disable ‘Delete all’ while there's no logo to wipe."
        if hasattr(self, "_logo_delall_btn"):
            want = not bool(self.logos)
            if self._logo_delall_btn.disabled != want:
                self._logo_delall_btn.disabled = want
                self._logo_delall_btn.repaint()

    def _clear_logo_for_geometry(self):
        "Drop ALL logos when the image geometry changes (rotate / crop / resize /"
        " perspective): the source-px positions no longer map to the new pixels."
        " No separate undo entry — it rides along with the geometry action's own"
        " undo, which snapshots and restores the logos (see nav._geometry_snapshot)."
        if not self.logos:
            return
        self.logos = []
        self.logo_sel = None
        self._logo_drag = None
        self._sync_logo_controls()

    # --- Panel controls -----------------------------------------------------

    def _set_logo_size(self, v):
        "Slider: logo width as a % of the photo's short side (live, no undo step)."
        if self.logo_overlay is None or self.current_pil is None:
            return
        short = max(1, min(self.current_pil.size))
        self.logo_overlay = {**self.logo_overlay,
                             "size": max(self.LOGO_MIN_SIZE, int(v) / 100.0 * short)}
        self._edits_saved = False
        self._schedule_preview()

    def _set_logo_opacity(self, v):
        "Slider: logo opacity 0..100 → 0..1 (live, no undo step)."
        if self.logo_overlay is None:
            return
        self.logo_overlay = {**self.logo_overlay,
                             "opacity": max(0.0, min(1.0, int(v) / 100.0))}
        self._edits_saved = False
        self._schedule_preview()

    def _set_logo_rotation(self, v):
        "Slider: logo rotation in degrees, −180..180 (live, no undo step)."
        if self.logo_overlay is None:
            return
        self.logo_overlay = {**self.logo_overlay, "angle": float(int(v))}
        self._edits_saved = False
        self._schedule_preview()

    def _reset_logo_slider(self, which):
        "Return one logo slider to neutral on the selected element (one undo step)."
        if self.logo_overlay is None or self.current_pil is None:
            return
        before = self._edit_state()
        if which == "size":
            short = max(1, min(self.current_pil.size))
            self.logo_overlay = {**self.logo_overlay,
                                 "size": max(self.LOGO_MIN_SIZE, 30 / 100.0 * short)}
            self.s_logo_size.set(30)
        elif which == "rotation":
            self.logo_overlay = {**self.logo_overlay, "angle": 0.0}
            self.s_logo_rotation.set(0)
        else:
            self.logo_overlay = {**self.logo_overlay, "opacity": 1.0}
            self.s_logo_opacity.set(100)
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    def _toggle_logo_flip(self, which):
        "Flip the logo horizontally / vertically (undoable)."
        if self.logo_overlay is None:
            return
        before = self._edit_state()
        self.logo_overlay = {**self.logo_overlay,
                             which: not self.logo_overlay.get(which)}
        self._sync_logo_controls()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    def _toggle_logo_tint(self):
        "Turn the flat-colour tint on / off (undoable). On uses the swatch colour."
        if self.logo_overlay is None:
            return
        before = self._edit_state()
        if self.logo_overlay.get("tint"):
            self.logo_overlay = {**self.logo_overlay, "tint": None}
        else:
            colour = self._logo_swatch.cget("bg") or "#ffffff"
            self.logo_overlay = {**self.logo_overlay, "tint": colour}
        self._sync_logo_controls()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    def _pick_logo_color(self):
        "Open the colour chooser; apply the picked tint colour (undoable)."
        if self.logo_overlay is None:
            return
        cur = self.logo_overlay.get("tint") or "#ffffff"
        _rgb, hexv = colorchooser.askcolor(color=cur, parent=self.root,
                                           title=t("Tint colour"))
        if not hexv:
            return
        before = self._edit_state()
        self.logo_overlay = {**self.logo_overlay, "tint": hexv}
        self._sync_logo_controls()
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    def _place_logo(self, h, v):
        "Snap the logo to a 3×3 anchor (h in l/c/r, v in t/m/b) with a margin. Undoable."
        if self.logo_overlay is None or self.current_pil is None:
            return
        before = self._edit_state()
        iw, ih = self.current_pil.size
        lw, lh = imaging.logo_extent(self.logo_overlay)
        margin = min(iw, ih) * self.LOGO_MARGIN
        cx = {"l": margin + lw / 2, "c": iw / 2, "r": iw - margin - lw / 2}[h]
        cy = {"t": margin + lh / 2, "m": ih / 2, "b": ih - margin - lh / 2}[v]
        self.logo_overlay = {**self.logo_overlay, "cx": cx, "cy": cy}
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    # --- Canvas geometry + hit testing --------------------------------------

    def _logo_box_screen(self, ov):
        "Screen box for ONE overlay: centre (cxs, cys) and half-extent (hw, hh)."
        scale = self._disp[0] or 1.0
        cxs, cys = self._src_to_scr(ov["cx"], ov["cy"])
        lw, lh = imaging.logo_extent(ov)
        if lw <= 0 or lh <= 0:                 # unreadable PNG → a placeholder box
            return cxs, cys, 24.0, 24.0
        return cxs, cys, lw * scale / 2.0, lh * scale / 2.0

    def _logo_at(self, x, y):
        "Topmost logo under screen (x, y): (index, 'resize'|'move') or (None, None)."
        if self.logo_sel is not None and 0 <= self.logo_sel < len(self.logos):
            cxs, cys, hw, hh = self._logo_box_screen(self.logos[self.logo_sel])
            if math.hypot(x - (cxs + hw), y - (cys + hh)) <= self.LOGO_HANDLE + 5:
                return self.logo_sel, "resize"
        pad = self.LOGO_HIT_PAD
        for i in range(len(self.logos) - 1, -1, -1):
            cxs, cys, hw, hh = self._logo_box_screen(self.logos[i])
            if abs(x - cxs) <= hw + pad and abs(y - cys) <= hh + pad:
                return i, "move"
        return None, None

    # --- Mouse interaction --------------------------------------------------

    def _logo_press(self, event):
        "Click a logo to select it, then drag to move it / its corner to resize."
        if not self._logo_active():
            return
        i, hit = self._logo_at(event.x, event.y)
        if hit is None:
            return "break"                     # empty click: keep the selection
        if i != self.logo_sel:
            self.logo_sel = i                  # clicking a box selects it
            self._sync_logo_controls()
        self._edit_gesture_start()             # snapshot so the whole drag is one undo
        sx, sy = self._scr_to_src(event.x, event.y)
        ov = self.logo_overlay
        if hit == "move":
            self._logo_drag = ("move", sx, sy, ov["cx"], ov["cy"])
        else:
            d0 = max(1.0, math.hypot(sx - ov["cx"], sy - ov["cy"]))
            self._logo_drag = ("resize", d0, ov["size"], None, None)
        return "break"

    def _logo_move(self, event):
        "Drag in progress: move the box or scale the logo, then repaint."
        if self._logo_drag is None:
            return
        iw, ih = self.current_pil.size
        sx, sy = self._scr_to_src(event.x, event.y)
        mode = self._logo_drag[0]
        if mode == "move":
            _, psx, psy, ocx, ocy = self._logo_drag
            cx = min(max(0.0, ocx + (sx - psx)), float(iw))
            cy = min(max(0.0, ocy + (sy - psy)), float(ih))
            self.logo_overlay = {**self.logo_overlay, "cx": cx, "cy": cy}
        else:                                  # resize: scale width by the distance ratio
            _, d0, s0, _, _ = self._logo_drag
            d = max(1.0, math.hypot(sx - self.logo_overlay["cx"],
                                    sy - self.logo_overlay["cy"]))
            size = max(self.LOGO_MIN_SIZE, min(s0 * d / d0, float(max(iw, ih))))
            self.logo_overlay = {**self.logo_overlay, "size": size}
            short = max(1, min(iw, ih))
            self.s_logo_size.set(round(size / short * 100))
        self._edits_saved = False
        self._render_preview()
        return "break"

    def _logo_release(self, event):
        "End the drag: record one undo entry if the overlay actually changed."
        if self._logo_drag is None:
            return
        self._logo_drag = None
        self._edit_gesture_end()
        return "break"

    def _logo_hover(self, event):
        "Show a move / resize cursor over a box while idle."
        if not self._logo_active() or self._logo_drag is not None:
            return
        _, hit = self._logo_at(event.x, event.y)
        cur = {"resize": "bottom_right_corner", "move": "fleur"}.get(hit, "")
        self.preview.configure(cursor=cur)

    # --- Overlay ------------------------------------------------------------

    def _draw_logo_overlay(self):
        "Chrome for the SELECTED logo only (a bright box + resize handle); the"
        " other logos show as their plain composited pixels, with no outline."
        c = self.preview
        for i, ov in enumerate(self.logos):
            cxs, cys, hw, hh = self._logo_box_screen(ov)
            if i == self.logo_sel:
                x0, y0, x1, y1 = cxs - hw, cys - hh, cxs + hw, cys + hh
                c.create_rectangle(x0, y0, x1, y1,
                                   outline=ACCENT, dash=(4, 3), width=1)
                r = self.LOGO_HANDLE
                c.create_rectangle(x1 - r, y1 - r, x1 + r, y1 + r,
                                   fill=ACCENT, outline=ON_ACCENT)
