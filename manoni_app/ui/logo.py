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
import tkinter.ttk as ttk
from tkinter import colorchooser

from PIL import Image, ImageDraw, ImageTk

import tintkit

from ..config import (ACCENT, FG_DIM, ON_ACCENT, EDIT_PAD, CHIP_GAP,
                      LOGO_DIR, LOGO_PRESET_DIR)
from ..i18n import t
from ..storage import unique_path
from .. import imaging


class LogoMixin:
    # --- Logo overlay (col 3 panel + interactive box on the preview) ---------

    LOGO_HANDLE   = 5      # half-size of the resize handle square, logical px (×DPI)
    LOGO_HIT_PAD  = 4      # click slack around a logo box for selection, logical px
    LOGO_MIN_SIZE = 8.0    # smallest logo width, source px
    LOGO_MARGIN   = 0.04   # corner-placement inset, as a fraction of the short side
    LOGO_PRESET_PX = 46    # preset thumbnail square, logical px
    LOGO_PRESET_COLS = 4   # thumbnails per row in the preset strip
    LOGO_GROUP_MAX_H = 150 # a preset group's height before its own scrollbar shows

    # --- Panel --------------------------------------------------------------

    def _build_logo_section(self, parent):
        "Logo panel: presets + import, then Appearance + Flip cards, then footer."
        f = self._tw(tk.Frame(parent), bg="bar")

        # Top row: ‘Choose PNG…’ (import a file — it is copied into the user logo
        # folder so it is offered again next time) and a trash icon that removes
        # the selected logo.
        addrow = self._tw(tk.Frame(f), bg="bar")
        addrow.pack(fill="x", padx=EDIT_PAD, pady=(12, 8))
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

        # Presets live in TWO collapsible, independently scrollable groups: the
        # shapes bundled with the app and the user's own imported PNGs. Each has a
        # click-to-fold header and a height-capped scroll body (rebuilt on import).
        self._logo_preset_thumbs = []          # PhotoImages kept alive (both groups)
        self._logo_groups = {}                 # key -> {header, body, canvas, inner…}
        self._logo_collapsed = {"preset": False, "user": False}
        self._build_logo_group(f, "preset", t("Built-in"))
        self._build_logo_group(f, "user", t("Your logos"))
        self._refresh_logo_presets()

        # Appearance card: size / opacity / rotation, then tint + colour swatch.
        # Controls pack WITHOUT EDIT_PAD — the card's own inset aligns them.
        ap = self._panel_card(f, t("Appearance"))
        self.s_logo_size = tintkit.TitledSlider(
            ap, self.theme, t("Size"), value=30, lo=2, hi=100, neutral=30,
            bg="bar", compact=True, command=self._set_logo_size,
            on_press=self._edit_gesture_start, on_release=self._edit_gesture_end,
            reset_tip=t("Reset this slider"), value_fmt=lambda v, n: str(v),
            on_reset=lambda: self._reset_logo_slider("size"))
        self.s_logo_size.pack(fill="x", pady=(3, 0))
        self.s_logo_opacity = tintkit.TitledSlider(
            ap, self.theme, t("Opacity"), value=100, lo=0, hi=100, neutral=100,
            bg="bar", compact=True, command=self._set_logo_opacity,
            on_press=self._edit_gesture_start, on_release=self._edit_gesture_end,
            reset_tip=t("Reset this slider"), value_fmt=lambda v, n: str(v),
            on_reset=lambda: self._reset_logo_slider("opacity"))
        self.s_logo_opacity.pack(fill="x", pady=(3, 0))
        # Rotation: −180…180° (0 = upright). Positive turns clockwise.
        self.s_logo_rotation = tintkit.TitledSlider(
            ap, self.theme, t("Rotation"), value=0, lo=-180, hi=180, neutral=0,
            bg="bar", compact=True, command=self._set_logo_rotation,
            on_press=self._edit_gesture_start, on_release=self._edit_gesture_end,
            reset_tip=t("Reset this slider"), value_fmt=lambda v, n: f"{v}°",
            on_reset=lambda: self._reset_logo_slider("rotation"))
        self.s_logo_rotation.pack(fill="x", pady=(3, 0))

        # Tint: a checkbox that recolours the whole logo to the swatch colour
        # (turns a black logo white, etc.), with the colour swatch beside it —
        # two equal halves.
        row = self._tw(tk.Frame(ap), bg="bar")
        row.pack(fill="x", pady=(8, 0))
        row.grid_columnconfigure(0, weight=1, uniform="lg")
        row.grid_columnconfigure(1, weight=1, uniform="lg")
        self._logo_tint_chk = tintkit.Checkbox(
            row, self.theme, t("Tint"), state="off", bg="bar",
            command=lambda _st: self._toggle_logo_tint())
        self._logo_tint_chk.grid(row=0, column=0, sticky="w")
        tintkit.HoverTip(self._logo_tint_chk.canvas, self.theme,
                         t("Recolour the whole logo to one flat colour"))
        self._logo_swatch = self._tw(tk.Frame(row, bg="#ffffff", cursor="hand2",
                                     width=self._edit_dpi_w(40),
                                     height=self._edit_dpi_w(20),
                                     highlightthickness=1), hl="border")
        self._logo_swatch.grid(row=0, column=1, sticky="e")
        self._logo_swatch.bind("<Button-1>", lambda e: self._pick_logo_color())
        tintkit.HoverTip(self._logo_swatch, self.theme, t("Pick the tint colour"))

        # Flip card: two equal icon-only tiles (mirror horizontally / vertically),
        # each lit accent while on. No corner-placement grid — a logo is dragged
        # straight onto the photo, so snapping it to an anchor is redundant.
        fl = self._panel_card(f, t("Flip"))
        self._build_logo_flip_tiles(fl)

        # Footer: Done + Delete all on one row, two equal halves. Done closes the
        # tool (logos stay live); Delete all wipes every logo and dims to disabled
        # while there's nothing. ('Delete logo' is the trash icon above.)
        foot = self._tw(tk.Frame(f), bg="bar")
        foot.pack(fill="x", padx=EDIT_PAD, pady=(12, 10))
        foot.grid_columnconfigure(0, weight=1, uniform="ft")
        foot.grid_columnconfigure(1, weight=1, uniform="ft")
        tintkit.Button(foot, self.theme, t("Done"), role="primary",
                       variant="filled", stretch=True, bg="bar",
                       command=lambda: self.set_section("basic")).grid(
                           row=0, column=0, sticky="ew", padx=(0, CHIP_GAP))
        self._logo_delall_btn = tintkit.Button(
            foot, self.theme, t("Delete all"), role="neutral", variant="outline",
            icon="x", stretch=True, bg="bar", command=self._delete_all_logo)
        self._logo_delall_btn.grid(row=0, column=1, sticky="ew", padx=(CHIP_GAP, 0))
        tintkit.HoverTip(self._logo_delall_btn.canvas, self.theme,
                         t("Remove every logo from the photo"))
        self._refresh_logo_buttons()           # start Delete-all disabled if empty
        return f

    # (icon, overlay-key, tooltip) for the two mirror tiles.
    _LOGO_FLIP_TILES = [
        ("flip-horizontal-2", "flip_h", "Mirror the logo horizontally"),
        ("flip-vertical-2", "flip_v", "Mirror the logo vertically"),
    ]

    def _build_logo_flip_tiles(self, parent):
        "Two equal icon-only tiles that mirror the logo; each lights accent while"
        " its flip is on (repainted by _paint_logo_flip_tiles on select / theme)."
        " Fixed to the standard button height so they match the footer buttons —"
        " the grid gives them equal width, the icon is centred with place()."
        grid = self._tw(tk.Frame(parent), bg="bar")
        grid.pack(fill="x")
        self._logo_flip_widgets = {}           # key -> (tile, icon-label, icon-name)
        h = self._edit_dpi_w(36)               # = a tintkit Button's height
        for i, (icon_name, key, tip) in enumerate(self._LOGO_FLIP_TILES):
            grid.columnconfigure(i, weight=1, uniform="lf")
            tile = self._tw(tk.Frame(grid, cursor="hand2", highlightthickness=1,
                            height=h), bg="chip", hl="border")
            tile.grid(row=0, column=i, sticky="ew", padx=2)
            tile.grid_propagate(False)         # hold the height; width fills the cell
            ic = tk.Label(tile, bd=0)
            ic.place(relx=0.5, rely=0.5, anchor="center")
            self._logo_flip_widgets[key] = (tile, ic, icon_name)
            for w in (tile, ic):
                w.bind("<Button-1>", lambda e, k=key: self._toggle_logo_flip(k))
                w.bind("<Enter>", lambda e, k=key: self._logo_flip_hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._logo_flip_hover(k, False))
            tintkit.HoverTip(tile, self.theme, t(tip))
        self.theme.subscribe(self._paint_logo_flip_tiles)   # panel built once → safe
        self._paint_logo_flip_tiles()

    def _logo_flip_hover(self, key, on):
        "Hover a flip tile — but leave an active (accent) tile alone."
        ov = self.logo_overlay
        if ov is not None and ov.get(key):
            return
        tile, ic, _ = self._logo_flip_widgets[key]
        bg = self.theme["hover"] if on else self.theme["chip"]
        tile.configure(bg=bg)
        ic.configure(bg=bg)

    def _paint_logo_flip_tiles(self):
        "Colour each flip tile by the selected logo's flip state (accent = on) and"
        " tint its icon to match. Re-tints on the dark<->light switch too."
        if not hasattr(self, "_logo_flip_widgets"):
            return
        ov = self.logo_overlay
        for key, (tile, ic, icon_name) in self._logo_flip_widgets.items():
            active = bool(ov is not None and ov.get(key))
            base = self.theme["accent"] if active else self.theme["chip"]
            col = self.theme["on_accent"] if active else self.theme["fg"]
            tile.configure(bg=base)
            ic.configure(bg=base)
            img = self.icon(icon_name, 16, col)
            ic.configure(image=img or "")
            ic.image = img

    # --- Preset strip -------------------------------------------------------

    LOGO_GROUP_DIRS = {"preset": LOGO_PRESET_DIR, "user": LOGO_DIR}

    def _logo_paths_in(self, folder):
        "Every PNG in one logo folder, name-sorted (empty list if unreadable)."
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return []
        return [os.path.join(folder, n) for n in names if n.lower().endswith(".png")]

    def _build_logo_group(self, parent, key, title):
        "One collapsible + scrollable preset group: a fold header over a canvas +"
        " inner grid + auto-hiding slim scrollbar (same nested-scroll recipe as the"
        " crop size list). Bodies are rebuilt by _populate_logo_group."
        sec = self._tw(tk.Frame(parent), bg="bar")
        sec.pack(fill="x", padx=EDIT_PAD, pady=(8, 0))
        self._tw(tk.Frame(sec, height=1), bg="divider").pack(fill="x", pady=(0, 3))

        header = self._tw(tk.Frame(sec, cursor="hand2"), bg="bar")
        header.pack(fill="x")
        chev = self._tw(tk.Label(header, text="▾", font=("Segoe UI", 8)),
                        bg="bar", fg="fg_dim")
        chev.pack(side="left")
        cap = self._tw(tk.Label(header, text=title, anchor="w",
                       font=("Segoe UI", 8, "bold")), bg="bar", fg="fg_dim")
        cap.pack(side="left", padx=(4, 0))
        cnt = self._tw(tk.Label(header, text="", font=("Segoe UI", 8)),
                       bg="bar", fg="fg_dim")
        cnt.pack(side="right")

        maxh = self._edit_dpi_w(self.LOGO_GROUP_MAX_H)
        body = self._tw(tk.Frame(sec), bg="bar")
        body.pack(fill="x", pady=(4, 0))
        cv = self._tw(tk.Canvas(body, highlightthickness=0, bd=0, height=maxh), bg="bar")
        sb = ttk.Scrollbar(body, orient="vertical", command=cv.yview,
                           style="Sidebar.Vertical.TScrollbar")
        cv.configure(yscrollcommand=sb.set)
        inner = self._tw(tk.Frame(cv), bg="bar")
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.pack(side="left", fill="x", expand=True)

        def on_inner(_e=None, cv=cv, inner=inner, sb=sb, maxh=maxh):
            cv.configure(scrollregion=cv.bbox("all"))
            need = inner.winfo_reqheight()
            cv.configure(height=min(need, maxh))
            if need > maxh:
                if not sb.winfo_ismapped():
                    sb.pack(side="right", fill="y", before=cv)
            else:
                sb.pack_forget()
                cv.yview_moveto(0)

        inner.bind("<Configure>", on_inner)
        cv.bind("<Configure>", lambda e, cv=cv, win=win: cv.itemconfigure(win, width=e.width))
        self._logo_groups[key] = {"sec": sec, "chev": chev, "count": cnt,
                                  "body": body, "canvas": cv, "inner": inner,
                                  "on_inner": on_inner}
        for w in (header, chev, cap, cnt):
            w.bind("<Button-1>", lambda e, k=key: self._toggle_logo_group(k))
        self._bind_logo_group_wheel(key, cv)

    def _toggle_logo_group(self, key):
        "Fold / unfold one preset group, then refresh the outer panel's scroll extent."
        g = self._logo_groups.get(key)
        if not g:
            return
        collapsed = not self._logo_collapsed.get(key, False)
        self._logo_collapsed[key] = collapsed
        if collapsed:
            g["body"].pack_forget()
            g["chev"].configure(text="▸")
        else:
            g["body"].pack(fill="x", pady=(4, 0))    # re-packs after the header
            g["chev"].configure(text="▾")
            g["on_inner"]()
        self.root.after_idle(self._sync_section_scroll)

    def _bind_logo_group_wheel(self, key, widget):
        "Arm the wheel on a group's canvas + every descendant so it scrolls that"
        " group (not the outer panel or the photo)."
        widget.bind("<MouseWheel>", lambda e, k=key: self._logo_group_wheel(k, e))
        for c in widget.winfo_children():
            self._bind_logo_group_wheel(key, c)

    def _logo_group_wheel(self, key, e):
        "Scroll one preset group if it overflows its cap; swallow the event either way."
        g = self._logo_groups.get(key)
        if g is not None:
            cv = g["canvas"]
            if g["inner"].winfo_reqheight() > int(cv["height"]):
                cv.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

    def _is_user_logo(self, path):
        "True if `path` sits in the user's writable my_logos folder — those can be"
        " deleted from the library; the bundled read-only presets cannot."
        try:
            return (os.path.normcase(os.path.abspath(os.path.dirname(path)))
                    == os.path.normcase(os.path.abspath(LOGO_DIR)))
        except (OSError, ValueError):
            return False

    @staticmethod
    def _checker_tile(px):
        "A px×px checkerboard in two mid greys — a neutral backdrop that reads a"
        " white shape, a black shape and the transparent hole of an outline alike."
        cell = max(4, px // 8)
        tile = Image.new("RGBA", (px, px), (120, 120, 120, 255))
        d = ImageDraw.Draw(tile)
        for y in range(0, px, cell):
            for x in range(0, px, cell):
                if (x // cell + y // cell) % 2:
                    d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(165, 165, 165, 255))
        return tile

    def _logo_thumb(self, path):
        "A PhotoImage of `path` on a soft checkerboard so light AND dark logos both"
        " read — a white shape (or an outline's see-through centre) would vanish on"
        " a flat tile, and a dark one vanishes on the dark chip."
        px = round(self.LOGO_PRESET_PX * getattr(self, "dpi", 1.0))
        try:
            im = Image.open(path).convert("RGBA")
        except Exception:
            return None
        im.thumbnail((px, px), Image.LANCZOS)
        tile = self._checker_tile(px)
        tile.paste(im, ((px - im.width) // 2, (px - im.height) // 2), im)
        return ImageTk.PhotoImage(tile.convert("RGB"))

    def _refresh_logo_presets(self):
        "Rebuild BOTH preset groups from their folders, then resettle the scroll."
        if not getattr(self, "_logo_groups", None):
            return
        self._logo_preset_thumbs = []          # both groups share one keep-alive list
        for key, folder in self.LOGO_GROUP_DIRS.items():
            self._populate_logo_group(key, folder)
        self.root.after_idle(self._sync_section_scroll)

    def _populate_logo_group(self, key, folder):
        "Fill one group's inner grid with its folder's PNG thumbnails (or a hint)."
        g = self._logo_groups.get(key)
        if g is None:
            return
        inner = g["inner"]
        for w in inner.winfo_children():
            w.destroy()
        paths = self._logo_paths_in(folder)
        g["count"].configure(text=str(len(paths)) if paths else "")
        if not paths:
            msg = (t("No saved logos yet — use Choose PNG…") if key == "user"
                   else t("No built-in shapes found"))
            self._tw(tk.Label(inner, text=msg, font=("Segoe UI", 8), justify="left",
                     anchor="w", wraplength=self._edit_dpi_w(180)),
                     bg="bar", fg="fg_dim").pack(fill="x", pady=2)
        else:
            grid = self._tw(tk.Frame(inner), bg="bar")
            grid.pack(anchor="w")
            for i, path in enumerate(paths):
                self._logo_preset_cell(grid, i, path)
        self._bind_logo_group_wheel(key, g["canvas"])   # re-arm wheel on fresh rows
        inner.update_idletasks()
        g["on_inner"]()                                  # cap height + toggle scrollbar

    def _logo_preset_cell(self, grid, i, path):
        "One clickable preset thumbnail; user PNGs also get a ✕ delete badge."
        thumb = self._logo_thumb(path)
        self._logo_preset_thumbs.append(thumb)           # keep the ref alive
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
        ov["z"] = self._layer_next_z()         # a new logo lands on top of everything
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
        self._paint_logo_flip_tiles()          # recolour the flip tiles by state
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

    # --- Canvas geometry + hit testing --------------------------------------

    def _logo_box_screen(self, ov):
        "Screen box for ONE overlay: centre (cxs, cys) and half-extent (hw, hh)."
        scale = self._disp[0] or 1.0
        cxs, cys = self._src_to_scr(ov["cx"], ov["cy"])
        lw, lh = imaging.logo_extent(ov)
        if lw <= 0 or lh <= 0:                 # unreadable PNG → a placeholder box
            r = float(self._edit_dpi_w(24))
            return cxs, cys, r, r
        return cxs, cys, lw * scale / 2.0, lh * scale / 2.0

    def _logo_at(self, x, y):
        "Topmost logo under screen (x, y): (index, 'resize'|'move'|'layer_up'|"
        "'layer_down') or (None, None)."
        # The layer chips + resize handle belong to the selected element only.
        if self.logo_sel is not None and 0 <= self.logo_sel < len(self.logos):
            chip = self._layer_chip_at(x, y)
            if chip is not None:
                return self.logo_sel, chip
            cxs, cys, hw, hh = self._logo_box_screen(self.logos[self.logo_sel])
            if math.hypot(x - (cxs + hw), y - (cys + hh)) \
                    <= self._edit_dpi_w(self.LOGO_HANDLE + 5):
                return self.logo_sel, "resize"
        # Otherwise the front-most box, walking the LAYER order top-down — what
        # the eye sees on top is what a click lands on.
        pad = self._edit_dpi_w(self.LOGO_HIT_PAD)
        order = [i for k, i in self._layer_seq() if k == "logo"]
        for i in reversed(order):
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
        if hit in ("layer_up", "layer_down"):
            self._layer_move("logo", 1 if hit == "layer_up" else -1)
            return "break"                     # a chip click reorders, no drag
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
        cur = {"resize": "bottom_right_corner", "move": "fleur",
               "layer_up": "hand2", "layer_down": "hand2"}.get(hit, "")
        self.preview.configure(cursor=cur)

    # --- Overlay ------------------------------------------------------------

    def _draw_logo_overlay(self):
        "Chrome for the SELECTED logo only (a bright box + resize handle + layer"
        " chips); the other logos show as their plain composited pixels, with no"
        " outline. All chrome is DPI-scaled so it reads the same at 100% / 150%."
        c = self.preview
        self._layer_chips = {}                 # no selection drawn → no chip hits
        lw = max(1, self._edit_dpi_w(1.4))
        dash = (self._edit_dpi_w(4), self._edit_dpi_w(3))
        for i, ov in enumerate(self.logos):
            cxs, cys, hw, hh = self._logo_box_screen(ov)
            if i == self.logo_sel:
                x0, y0, x1, y1 = cxs - hw, cys - hh, cxs + hw, cys + hh
                c.create_rectangle(x0, y0, x1, y1,
                                   outline=ACCENT, dash=dash, width=lw)
                r = self._edit_dpi_w(self.LOGO_HANDLE)
                c.create_rectangle(x1 - r, y1 - r, x1 + r, y1 + r,
                                   fill=ACCENT, outline=ON_ACCENT)
                self._draw_layer_chips("logo", x0, y0, x1, y1)
