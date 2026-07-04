"""Resize tool for Manoni: scale the photo down (or up) keeping — or breaking —
its aspect ratio, by explicit width×height or by a percentage.

Like crop / rotate this is a DESTRUCTIVE in-memory bake into current_pil — the
original file on disk is never touched; Save writes the resized copy. The
compare "before" image is resized in lockstep, the source-px crop box / focus
shape are dropped (their coordinates no longer map), and the photo refits the
window. Reversed by leaving the photo (discard), exactly like crop.

Panel layout (approved "variant A"):
  * a Dimensions | Percent mode toggle;
  * Dimensions = a W and an H field with an aspect LOCK (locked = the pair
    stays proportional to the photo; unlocked = a free, possibly-distorting
    W×H);
  * Percent = one field scaling both sides;
  * Quick sizes = long-side px chips that jump to Dimensions, proportionally;
  * a foldable Quality group (resample filter + strength);
  * Resize / Reset live in a PINNED footer (like crop's Crop/Cancel) so they
    never scroll out of reach.

Mixin on the Manoni window — every method uses the shared `self`, so behaviour
is identical to when it lived directly on the class.
"""

import os
import tkinter as tk
import tkinter.filedialog as tkfd

from PIL import Image, ImageFilter

import tintkit

from ..config import EDIT_PANEL_W, EDIT_PAD, SUPPORTED
from ..i18n import t


class StretchTabs(tintkit.SegmentedTabs):
    """A SegmentedTabs that fills its parent's width, splitting the segments
    equally — so every toggle row spans the panel like the full-width buttons
    instead of shrinking to its text (which made rows look mismatched)."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._lastw = 0
        self.canvas.bind("<Configure>", self._on_cfg, add="+")

    def _on_cfg(self, e):
        if e.width <= 4 or e.width == self._lastw:
            return
        self._lastw = e.width
        n = len(self.options)
        inner = e.width - tintkit.s(6)
        base = inner // n
        self._widths = [base] * (n - 1) + [inner - base * (n - 1)]
        self.w = e.width
        self.repaint()


class ResizeMixin:
    # --- Resize tool (col 3 panel) ------------------------------------------

    # Quick-target long sides in px (web-friendly). Clicking one jumps to the
    # Dimensions mode with a proportional W×H.
    RESIZE_PX_PRESETS = [1080, 1600, 2000, 2560]

    # Pixel quality = which resampling filter the resize uses (and, for "sharp",
    # a light output-sharpen afterwards). Shared by the single photo + folder
    # batch via _resize_pixels, so both paths render pixels identically.
    #   soft   — BICUBIC + a small Gaussian blur (smoother, gentler on noise)
    #   normal — LANCZOS: the default; sharpest clean downscale (no post-pass)
    #   sharp  — LANCZOS + an UnsharpMask (web "output sharpening")
    # Soft and sharp each carry a 3-step strength (light/medium/strong); normal
    # has none. The chosen strength is remembered per quality in _resize_strength.
    RESIZE_QUALITIES = ("soft", "normal", "sharp")
    RESIZE_RESAMPLE  = {"soft": Image.BICUBIC, "normal": Image.LANCZOS,
                        "sharp": Image.LANCZOS}
    RESIZE_STRENGTHS = ("light", "medium", "strong")
    # Sharp: UnsharpMask percent per strength (radius + threshold fixed, so only
    # real edges crisp up while flat areas / noise stay clean).
    RESIZE_SHARP_RADIUS = 0.8
    RESIZE_SHARP_THRESH = 2
    RESIZE_SHARP_PCT    = {"light": 50, "medium": 90, "strong": 150}
    # Soft: an extra Gaussian blur (full-res px) on top of the BICUBIC resample.
    RESIZE_SOFT_BLUR    = {"light": 0.5, "medium": 0.9, "strong": 1.4}

    def _resize_pixels(self, img, size, post=True):
        """Resize `img` to `size` with the chosen quality + strength.

        `post`=False skips the soft/sharp pass — used for the compare "before",
        which stays the plain reference so the slider shows the effect."""
        q = self._resize_quality
        out = img.resize(size, self.RESIZE_RESAMPLE[q])
        if not post or q == "normal":
            return out
        lvl = self._resize_strength[q]
        if q == "sharp":
            out = out.filter(ImageFilter.UnsharpMask(
                radius=self.RESIZE_SHARP_RADIUS, percent=self.RESIZE_SHARP_PCT[lvl],
                threshold=self.RESIZE_SHARP_THRESH))
        else:   # soft
            out = out.filter(ImageFilter.GaussianBlur(self.RESIZE_SOFT_BLUR[lvl]))
        return out

    # --- Panel build --------------------------------------------------------

    def _build_resize_section(self, parent):
        "Resize panel content (Resize/Reset are a separate pinned footer)."
        f = self._tw(tk.Frame(parent), bg="bar")
        self._resize_modes = ["dim", "pct"]  # tab order for the mode toggle
        self._resize_mode = "dim"            # "dim" = W×H, "pct" = percent
        self._resize_lock = True             # Dimensions: keep W:H proportional
        self._resize_quality = "normal"      # soft / normal / sharp (resample)
        self._resize_strength = {"soft": "medium", "sharp": "medium"}  # per quality
        self._resize_w_var = tk.StringVar()
        self._resize_h_var = tk.StringVar()
        self._resize_pct_var = tk.StringVar()

        self._resize_group(f, t("Size"))
        # Current dimensions, refreshed on enter and after every resize.
        self._resize_current = self._tw(tk.Label(f, text="", anchor="w",
                                        font=("Segoe UI", 9)), bg="bar", fg="fg_dim")
        self._resize_current.pack(fill="x", padx=EDIT_PAD, pady=(0, 8))

        # Mode toggle: explicit dimensions or a percentage — exclusive, so a
        # full-width segmented control.
        self._resize_mode_tabs = StretchTabs(
            f, self.theme, [t("Dimensions"), t("Percent")], selected=0, bg="bar",
            command=lambda i, _l: self._set_resize_mode(self._resize_modes[i]))
        self._resize_mode_tabs.pack(fill="x", padx=EDIT_PAD, pady=(0, 8))

        # --- Dimensions body: W · lock · H --------------------------------
        self._resize_dim_body = self._tw(tk.Frame(f), bg="bar")
        self._resize_w_entry = self._resize_field(
            self._resize_dim_body, "W", self._resize_w_var, self._resize_on_w)
        lockrow = self._tw(tk.Frame(self._resize_dim_body), bg="bar")
        lockrow.pack(fill="x", padx=EDIT_PAD, pady=(2, 4))
        self._resize_lock_chk = tintkit.Checkbox(
            lockrow, self.theme, t("Lock aspect ratio"), state="on",
            command=self._resize_set_lock, bg="bar")
        self._resize_lock_chk.pack(anchor="w")
        self._resize_h_entry = self._resize_field(
            self._resize_dim_body, "H", self._resize_h_var, self._resize_on_h)

        # --- Percent body -------------------------------------------------
        self._resize_pct_body = self._tw(tk.Frame(f), bg="bar")
        self._resize_pct_entry = self._resize_field(
            self._resize_pct_body, "%", self._resize_pct_var, self._resize_on_pct,
            unit_only=True)

        # Live result of the current input ("→ W × H"), under whichever body.
        self._resize_result = self._tw(tk.Label(f, text="", anchor="w",
                                       font=("Segoe UI", 10, "bold")),
                                       bg="bar", fg="accent")
        self._resize_result.pack(fill="x", padx=EDIT_PAD, pady=(6, 0))

        # Quick long-side targets — each jumps to Dimensions with a proportional
        # W×H. Equal-width columns so the four always fit the panel.
        self._resize_group(f, t("Quick sizes (long side)"))
        qs = self._tw(tk.Frame(f), bg="bar")
        qs.pack(fill="x", padx=EDIT_PAD, pady=(0, 2))
        for i in range(len(self.RESIZE_PX_PRESETS)):
            qs.columnconfigure(i, weight=1, uniform="rp")
        for i, p in enumerate(self.RESIZE_PX_PRESETS):
            tintkit.Button(qs, self.theme, str(p), role="neutral", variant="outline",
                           min_w=40, h=30, stretch=True, bg="bar",
                           command=lambda v=p: self._resize_apply_preset(v)).grid(
                               row=0, column=i, sticky="ew", padx=2)

        self._tw(tk.Label(f, text=t("The original stays untouched — Save writes the resized copy."),
                 anchor="w", justify="left", font=("Segoe UI", 8),
                 wraplength=self._edit_dpi_w(EDIT_PANEL_W - 2 * EDIT_PAD)),
                 bg="bar", fg="fg_dim").pack(fill="x", padx=EDIT_PAD, pady=(10, 2))

        # Pixel quality — secondary, so it folds away (collapsed by default).
        self._build_foldable_group(f, t("Quality"), "_resize_quality_open",
                                   self._build_resize_quality_body)

        # --- Whole-folder batch (same size rule applied to every photo) ---
        self._resize_group(f, t("Whole folder"))
        self._tw(tk.Label(f, text=t("Resize every photo in a folder with the size above — "
                           "pick the folder, subfolders and where the copies go. "
                           "Originals are untouched."),
                 anchor="w", justify="left", font=("Segoe UI", 8),
                 wraplength=self._edit_dpi_w(EDIT_PANEL_W - 2 * EDIT_PAD)),
                 bg="bar", fg="fg_dim").pack(fill="x", padx=EDIT_PAD, pady=(0, 6))
        tintkit.Button(f, self.theme, t("Resize the whole folder"), role="neutral",
                       variant="outline", icon="folder-output", stretch=True, bg="bar",
                       command=self._resize_folder).pack(
                           fill="x", padx=EDIT_PAD, pady=(0, 8))

        self._set_resize_quality(self._resize_quality)   # paints tabs + str block
        self._resize_dim_body.pack(fill="x", before=self._resize_result)  # default mode
        return f

    def _resize_group(self, parent, text):
        "A thin divider + small bold caption titling a resize sub-section."
        self._tw(tk.Frame(parent, height=1), bg="divider").pack(
            fill="x", padx=EDIT_PAD, pady=(12, 0))
        self._tw(tk.Label(parent, text=text, anchor="w",
                 font=("Segoe UI", 8, "bold")), bg="bar", fg="fg_dim").pack(
                     fill="x", padx=EDIT_PAD, pady=(4, 6))

    def _resize_field(self, parent, tag, var, on_change, unit_only=False):
        """A [tag] [entry] [unit] row. For W/H the tag is the leading letter and
        the unit is "px"; for percent pass unit_only=True so the tag ("%") is the
        trailing unit and the leading column is blank — keeping every field's
        left edge aligned."""
        row = self._tw(tk.Frame(parent), bg="bar")
        row.pack(fill="x", padx=EDIT_PAD, pady=(0, 4))
        unit = tag if unit_only else "px"
        self._tw(tk.Label(row, text=unit, font=("Segoe UI", 9)),
                 bg="bar", fg="fg_dim").pack(side="right", padx=(6, 0))
        self._tw(tk.Label(row, text="" if unit_only else tag, width=2, anchor="w",
                 font=("Segoe UI", 10)), bg="bar", fg="fg_dim").pack(side="left")
        ent = self._tw(tk.Entry(row, textvariable=var, relief="flat",
                       justify="center", font=("Segoe UI", 11)),
                       bg="chip", fg="fg", insert="fg")
        ent.pack(side="left", fill="x", expand=True, ipady=5)
        ent.bind("<Return>", lambda e: self.apply_resize())
        ent.bind("<KeyRelease>", lambda e: on_change())
        return ent

    def _build_resize_quality_body(self, parent):
        "Foldable Quality body: resample filter + a strength row for soft/sharp."
        qlabels = {"soft": t("Soft"), "normal": t("Normal"), "sharp": t("Sharp")}
        self._resize_q_tabs = StretchTabs(
            parent, self.theme, [qlabels[k] for k in self.RESIZE_QUALITIES],
            selected=self.RESIZE_QUALITIES.index(self._resize_quality), bg="bar",
            command=lambda i, _l: self._set_resize_quality(self.RESIZE_QUALITIES[i]))
        self._resize_q_tabs.pack(fill="x", padx=EDIT_PAD, pady=(0, 2))

        # Strength (a whole block, shown only for soft/sharp). Packed before the
        # hint by _refresh_resize_strength.
        self._resize_str_block = self._tw(tk.Frame(parent), bg="bar")
        self._tw(tk.Label(self._resize_str_block, text=t("Strength"),
                 anchor="w", font=("Segoe UI", 8, "bold")),
                 bg="bar", fg="fg_dim").pack(fill="x", pady=(8, 4))
        slabels = {"light": t("Light"), "medium": t("Medium"), "strong": t("Strong")}
        self._resize_str_tabs = StretchTabs(
            self._resize_str_block, self.theme,
            [slabels[k] for k in self.RESIZE_STRENGTHS], selected=0, bg="bar",
            command=lambda i, _l: self._set_resize_strength(self.RESIZE_STRENGTHS[i]))
        self._resize_str_tabs.pack(fill="x")

        self._resize_q_hint = self._tw(tk.Label(
            parent, text=t("Soft = smoother · Sharp adds web output-sharpening."),
            anchor="w", justify="left", font=("Segoe UI", 8),
            wraplength=self._edit_dpi_w(EDIT_PANEL_W - 2 * EDIT_PAD)),
            bg="bar", fg="fg_dim")
        self._resize_q_hint.pack(fill="x", padx=EDIT_PAD, pady=(5, 0))

    def _build_resize_footer(self, panel):
        "Scaffold the pinned Resize/Reset row; hidden until the resize tool opens."
        wrap = self._tw(tk.Frame(panel), bg="bar")
        wrap.pack(side="bottom", fill="x", before=self._sec_host)
        self._tw(tk.Frame(wrap, height=1), bg="divider").pack(side="top", fill="x")

        apply_btn = tintkit.Button(
            wrap, self.theme, t("Resize"), role="primary", variant="filled",
            stretch=True, bg="bar", command=self.apply_resize)
        apply_btn.pack(fill="x", padx=EDIT_PAD, pady=(8, 6))

        reset_btn = tintkit.Button(
            wrap, self.theme, t("Reset"), role="neutral", variant="outline",
            icon="x", stretch=True, bg="bar", command=self._reset_resize)
        reset_btn.pack(fill="x", padx=EDIT_PAD, pady=(0, 8))
        tintkit.HoverTip(reset_btn.canvas, self.theme,
                         t("Reset the size to the current photo"))

        self._resize_footer = wrap
        wrap.pack_forget()
        return wrap

    # --- Mode + lock --------------------------------------------------------

    def _set_resize_mode(self, mode):
        "Switch between explicit dimensions and percent; reseed the fields."
        if mode == self._resize_mode:
            return
        self._resize_mode = mode
        self._refresh_resize_mode()
        self._reset_resize_input()
        self._update_resize_display()

    def _refresh_resize_mode(self):
        "Sync the mode toggle and show the matching body (dimensions / percent)."
        if not hasattr(self, "_resize_mode_tabs"):
            return
        idx = self._resize_modes.index(self._resize_mode)
        if self._resize_mode_tabs.selected != idx:
            self._resize_mode_tabs.selected = idx
            self._resize_mode_tabs.repaint()
        self._resize_dim_body.pack_forget()
        self._resize_pct_body.pack_forget()
        body = (self._resize_dim_body if self._resize_mode == "dim"
                else self._resize_pct_body)
        body.pack(fill="x", before=self._resize_result)

    def _resize_set_lock(self, state):
        "Aspect-lock checkbox: on = keep W:H proportional (re-tie H to W now)."
        self._resize_lock = (state == "on")
        if self._resize_lock:
            self._resize_sync("w")
        self._update_resize_display()

    def _resize_on_w(self):
        "W changed: under lock recompute H from the photo aspect, then refresh."
        if self._resize_lock:
            self._resize_sync("w")
        self._update_resize_display()

    def _resize_on_h(self):
        "H changed: under lock recompute W from the photo aspect, then refresh."
        if self._resize_lock:
            self._resize_sync("h")
        self._update_resize_display()

    def _resize_on_pct(self):
        self._update_resize_display()

    def _resize_sync(self, src):
        "Under lock: set the OTHER dimension from the current photo's aspect."
        if self.current_pil is None:
            return
        iw, ih = self.current_pil.size
        if src == "w":
            w = self._resize_num(self._resize_w_var)
            if w:
                self._resize_h_var.set(str(max(1, round(w * ih / iw))))
        else:
            h = self._resize_num(self._resize_h_var)
            if h:
                self._resize_w_var.set(str(max(1, round(h * iw / ih))))

    # --- Presets + reset ----------------------------------------------------

    def _resize_apply_preset(self, long_side):
        "Quick long-side chip: jump to Dimensions with a proportional W×H."
        if self._resize_mode != "dim":
            self._set_resize_mode("dim")
        if self.current_pil is None:
            return
        iw, ih = self.current_pil.size
        scale = long_side / max(iw, ih)
        self._resize_w_var.set(str(max(1, round(iw * scale))))
        self._resize_h_var.set(str(max(1, round(ih * scale))))
        self._update_resize_display()

    def _reset_resize(self):
        "Footer secondary: return the fields to the current photo's size."
        self._reset_resize_input()
        self._update_resize_display()

    def _reset_resize_input(self):
        "Seed the fields: the photo's W×H (dimensions) and 100 (percent)."
        if self.current_pil is None:
            self._resize_w_var.set("")
            self._resize_h_var.set("")
            self._resize_pct_var.set("")
            return
        iw, ih = self.current_pil.size
        self._resize_w_var.set(str(iw))
        self._resize_h_var.set(str(ih))
        self._resize_pct_var.set("100")

    # --- Quality + strength -------------------------------------------------

    def _set_resize_quality(self, q):
        "Pick the resample quality; sync the toggle + show/hide the strength block."
        self._resize_quality = q
        if not hasattr(self, "_resize_q_tabs"):
            return
        idx = self.RESIZE_QUALITIES.index(q)
        if self._resize_q_tabs.selected != idx:
            self._resize_q_tabs.selected = idx
            self._resize_q_tabs.repaint()
        self._refresh_resize_strength()

    def _set_resize_strength(self, level):
        "Set the active quality's effect strength; remembered per quality."
        if self._resize_quality == "normal":
            return
        self._resize_strength[self._resize_quality] = level
        self._refresh_resize_strength()

    def _refresh_resize_strength(self):
        "Show the strength toggle for soft/sharp (hidden for normal) + sync it."
        if self._resize_quality == "normal":
            self._resize_str_block.pack_forget()
            return
        self._resize_str_block.pack(fill="x", padx=EDIT_PAD,
                                    before=self._resize_q_hint)
        active = self._resize_strength[self._resize_quality]
        idx = self.RESIZE_STRENGTHS.index(active)
        if self._resize_str_tabs.selected != idx:
            self._resize_str_tabs.selected = idx
            self._resize_str_tabs.repaint()

    # --- Value reading ------------------------------------------------------

    def _resize_num(self, var):
        "One field as a float (>0), or None if blank / invalid."
        try:
            val = float(var.get().strip().replace(",", "."))
        except (ValueError, AttributeError):
            return None
        return val if val > 0 else None

    def _resize_wh(self):
        "The Dimensions (w, h) as positive ints, or None if either is invalid."
        w = self._resize_num(self._resize_w_var)
        h = self._resize_num(self._resize_h_var)
        if w is None or h is None:
            return None
        return (max(1, int(round(w))), max(1, int(round(h))))

    def _resize_pct(self):
        "The Percent value as a float (>0), or None."
        return self._resize_num(self._resize_pct_var)

    def _resize_ready(self):
        "True when the active mode has a valid value to apply."
        if self._resize_mode == "pct":
            return self._resize_pct() is not None
        return self._resize_wh() is not None

    def _resize_target_size(self):
        """Target (w, h) for the OPEN photo — the exact fields in Dimensions,
        a proportional scale in Percent. None if the input is invalid."""
        if self.current_pil is None:
            return None
        iw, ih = self.current_pil.size
        if self._resize_mode == "pct":
            p = self._resize_pct()
            if p is None:
                return None
            return (max(1, round(iw * p / 100)), max(1, round(ih * p / 100)))
        return self._resize_wh()

    def _resize_target_for(self, iw, ih):
        """Target (w, h) for ONE image of the folder batch (per-image, so a
        percent or a locked box scales each photo by its own size). None if
        the input is invalid.

        Percent    → scale both sides.
        Dimensions, locked   → fit INSIDE the W×H box, keeping each photo's aspect.
        Dimensions, unlocked → the exact W×H (may distort a different-aspect photo)."""
        if self._resize_mode == "pct":
            p = self._resize_pct()
            if p is None:
                return None
            return (max(1, round(iw * p / 100)), max(1, round(ih * p / 100)))
        wh = self._resize_wh()
        if wh is None:
            return None
        tw, th = wh
        if self._resize_lock:
            scale = min(tw / iw, th / ih)
            return (max(1, round(iw * scale)), max(1, round(ih * scale)))
        return (tw, th)

    def _update_resize_display(self):
        "Refresh the current-size and live-result labels (cheap; on every keystroke)."
        if not hasattr(self, "_resize_current"):
            return
        if self.current_pil is None:
            self._resize_current.configure(text="—")
            self._resize_result.configure(text="")
            return
        iw, ih = self.current_pil.size
        self._resize_current.configure(
            text=t("Current: {w} × {h}").format(w=iw, h=ih))
        target = self._resize_target_size()
        if target is None:
            self._resize_result.configure(text="")
        else:
            self._resize_result.configure(text=f"→  {target[0]} × {target[1]} px")

    # --- Enter + apply ------------------------------------------------------

    def _enter_resize(self):
        "Open the resize tool: pin the footer, refresh the panel, plain view."
        self.preview.configure(cursor="")
        self._resize_footer.pack(side="bottom", fill="x", before=self._sec_host)
        if hasattr(self, "_resize_mode_tabs"):
            self._refresh_resize_mode()
            self._reset_resize_input()
            self._update_resize_display()
        self._render_preview()

    def apply_resize(self):
        "Resize current_pil to the target (in memory; written out via Save)."
        if self.current_pil is None:
            return
        target = self._resize_target_size()
        if target is None:
            self.toast(t("Enter a valid size"))
            return
        nw, nh = target
        iw, ih = self.current_pil.size
        if (nw, nh) == (iw, ih):
            self.toast(t("That's already the current size"))
            return
        self.current_pil = self._resize_pixels(self.current_pil, (nw, nh))
        if self._before_pil is not None:   # keep the compare "before" aligned
            # Same resample, but no soft/sharp pass — "before" is the reference.
            self._before_pil = self._resize_pixels(self._before_pil, (nw, nh),
                                                   post=False)
            self._before_base_key = None
        self._resized = True
        self._clear_focus_for_geometry()   # source-px focus shape no longer maps
        self._clear_text_for_geometry()    # …and the source-px text position no longer maps
        self._reset_straighten()           # pending tilt was for the old size
        self.clone_src = self.clone_offset = None   # clone anchor was for the old size
        # The crop box was in old source px — reset it to the new full image.
        self.crop_rect = [0.0, 0.0, float(nw), float(nh)]
        self.crop_ratio = None
        self._crop_btn_active = None
        self._restyle_crop_chips()
        self._edits_saved = False
        self.fit_mode = True
        self.pan_x = self.pan_y = 0.0
        self._view_key = None              # size changed → drop the cached view
        self._render_preview()
        self._update_info(os.path.join(self.folder, self.files[self.index]))
        self._refresh_filter_strip()       # the resized photo needs fresh thumbnails
        self._refresh_resize_mode()
        self._reset_resize_input()
        self._update_resize_display()
        self.toast(t("Resized → {w}×{h}px  ·  Save to write it to a file").format(
            w=nw, h=nh))

    # --- Whole-folder batch -------------------------------------------------

    @staticmethod
    def _batch_export_meta(im):
        """ICC profile + EXIF from a just-opened source image, as save() kwargs.

        A resized web copy that silently dropped the colour profile is the same
        bug we fixed for single saves — so the batch carries it across too. The
        EXIF orientation is left as-is: the pixels aren't rotated, so the original
        tag still describes them correctly."""
        extra = {}
        icc = im.info.get("icc_profile")
        if icc:
            extra["icc_profile"] = icc
        try:
            exif = im.getexif()
            if exif:
                extra["exif"] = exif.tobytes()
        except Exception:
            pass
        return extra

    def _gather_batch_images(self, src, recurse, skip_name=None, skip_dir=None):
        """List (dirpath, filename) for every supported image under `src`.

        recurse   → walk the whole tree; else only `src`'s top level.
        skip_name → prune any sub-folder with this name (the in-place output
                    sub-folder, so a re-run never re-processes its own copies).
        skip_dir  → prune this one absolute directory subtree (the flat/mirror
                    output folder when it sits inside the source)."""
        out = []
        skip_dir = os.path.normcase(os.path.abspath(skip_dir)) if skip_dir else None
        if not src or not os.path.isdir(src):
            return out
        if recurse:
            for dpath, dnames, fnames in os.walk(src):
                dnames[:] = [d for d in dnames
                             if d != skip_name and
                             (skip_dir is None or
                              os.path.normcase(os.path.abspath(os.path.join(dpath, d)))
                              != skip_dir)]
                for f in sorted(fnames):
                    if os.path.splitext(f)[1].lower() in SUPPORTED:
                        out.append((dpath, f))
        else:
            try:
                for f in sorted(os.listdir(src)):
                    p = os.path.join(src, f)
                    if os.path.isfile(p) and os.path.splitext(f)[1].lower() in SUPPORTED:
                        out.append((src, f))
            except OSError:
                pass
        return out

    @staticmethod
    def _batch_dest_dir(cfg, src_dir):
        "Output directory for one source file living in `src_dir`, per the mode."
        mode = cfg["out_mode"]
        if mode == "inplace":                         # a sub-folder beside each photo
            return os.path.join(src_dir, cfg["sub_name"])
        if mode == "mirror":                          # rebuild the tree under out_dir
            rel = os.path.relpath(src_dir, cfg["src"])
            return cfg["out_dir"] if rel == "." else os.path.join(cfg["out_dir"], rel)
        return cfg["out_dir"]                          # flat — everything together

    def _resize_folder(self):
        "Resize images in a chosen folder by the current size rule, saving copies."
        if not self._resize_ready():
            self.toast(t("Enter a valid size"))
            return
        cfg = self._ask_resize_batch_config(self.folder or "")
        if cfg is None:
            return
        # Never re-read our own output: prune the in-place sub-folder, and the
        # flat/mirror output folder when it lives inside the source.
        skip_name = cfg["sub_name"] if cfg["out_mode"] == "inplace" else None
        skip_dir = None
        if cfg["out_mode"] != "inplace":
            od = os.path.normcase(os.path.abspath(cfg["out_dir"]))
            sd = os.path.normcase(os.path.abspath(cfg["src"]))
            if od.startswith(sd + os.sep) or od == sd:
                skip_dir = cfg["out_dir"]
        images = self._gather_batch_images(cfg["src"], cfg["recurse"],
                                           skip_name=skip_name, skip_dir=skip_dir)
        if not images:
            self.toast(t("No images in that folder"))
            return
        from ..storage import unique_path
        ext = self.FMT_EXT[cfg["fmt"]]
        total, ok, fail = len(images), 0, 0
        # Blocking "please wait" screen with a filling bar + i/n counter — a long
        # batch shouldn't leave the window looking frozen or half-drawn. Cancel
        # stops between photos (each already-written copy is kept).
        self._show_loading_overlay(total, sub=t("Resizing…"), cancelable=True)
        self.root.update()
        cancelled = False
        try:
            for i, (dpath, fname) in enumerate(images):
                self._update_loading_overlay(i, total)
                self.root.update()                    # repaint the bar, stay alive
                if getattr(self, "_loading_cancelled", False):
                    cancelled = True
                    break
                try:
                    with Image.open(os.path.join(dpath, fname)) as im:
                        im.load()
                        target = self._resize_target_for(*im.size)
                        if target is None:            # value went blank mid-run
                            fail += 1
                            continue
                        out = self._resize_pixels(im, target)
                        extra = self._batch_export_meta(im)
                    dest_dir = self._batch_dest_dir(cfg, dpath)
                    os.makedirs(dest_dir, exist_ok=True)
                    # Don't let two sources (a.jpg + a.png) or a re-run overwrite
                    # each other — number a clashing name instead.
                    dest = unique_path(os.path.join(dest_dir,
                                                    os.path.splitext(fname)[0] + ext))
                    if cfg["fmt"] == "PNG":
                        out.save(dest, "PNG", **extra)
                    else:
                        out.convert("RGB").save(dest, cfg["fmt"],
                                                quality=int(cfg["quality"]), **extra)
                    ok += 1
                except Exception:
                    fail += 1
        finally:
            self._hide_loading_overlay()              # always tear the screen down
        where = cfg["sub_name"] if cfg["out_mode"] == "inplace" else cfg["out_dir"]
        short = os.path.basename(where.rstrip("\\/")) or where
        if cancelled:
            self.toast(t("Cancelled — {ok} resized, {fail} failed  ·  {dir}").format(
                ok=ok, fail=fail, dir=short))
        else:
            self.toast(t("Done — {ok} resized, {fail} failed  ·  {dir}").format(
                ok=ok, fail=fail, dir=short))

    # --- The whole-folder resize dialog -------------------------------------

    def _ask_resize_batch_config(self, start_dir):
        """Dialog for the whole-folder resize: source folder (+ sub-folders),
        output layout (flat / mirror tree / in-place sub-folder), format +
        quality. Returns a config dict, or None on cancel."""
        seed = self.quick_save_cfg or self.last_save or {}
        st = {"src": start_dir, "recurse": False, "out_mode": "flat",
              "out_dir": os.path.join(start_dir, "_resized") if start_dir else "_resized",
              "sub_name": "resized",
              "fmt": seed.get("fmt") or "JPEG",
              "quality": int(seed.get("quality", 95)), "ok": False}

        dlg = tk.Toplevel(self.root)
        dlg.title(t("Resize whole folder"))
        self._tw(dlg, bg="bg")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = self._tw(tk.Frame(dlg, padx=22, pady=16), bg="bg")
        wrap.pack(fill="both", expand=True)

        def heading(text):
            self._tw(tk.Label(wrap, text=text, font=("Segoe UI", 8)),
                     bg="bg", fg="fg_dim").pack(anchor="w", pady=(10, 2))

        # --- Source folder + browse + a live image count ---
        heading(t("Source folder"))
        src_var = tk.StringVar(value=st["src"])

        def pick_src():
            dlg.grab_release()
            d = tkfd.askdirectory(parent=dlg, title=t("Choose a folder"),
                                  initialdir=src_var.get() or start_dir or None)
            dlg.grab_set()
            if d:
                src_var.set(d)
                recount()

        frow = self._tw(tk.Frame(wrap), bg="bg"); frow.pack(fill="x")
        tintkit.Button(frow, self.theme, t("Select"), role="neutral",
                       variant="outline", command=pick_src, bg="bg").pack(
                           side="right", padx=(6, 0))
        src_field = tintkit.TextField(frow, self.theme, bg="bg")
        src_field.entry.configure(textvariable=src_var)
        src_field.pack(side="left", fill="x", expand=True)

        count_lbl = self._tw(tk.Label(wrap, text="", anchor="w",
                             font=("Segoe UI", 8)), bg="bg", fg="accent")
        count_lbl.pack(fill="x", pady=(4, 0))

        def recount():
            src = src_var.get().strip()
            n = len(self._gather_batch_images(src, recurse_chk.state == "on"))
            count_lbl.configure(text=t("{n} images found").format(n=n))

        recurse_chk = tintkit.Checkbox(
            wrap, self.theme, t("Include subfolders"), state="off",
            command=lambda _s: recount(), bg="bg")
        recurse_chk.pack(anchor="w", pady=(8, 0))
        recount()

        # --- Where to save: flat / mirror tree / in-place sub-folder ---
        heading(t("Where to save"))
        grp = tintkit.RadioGroup(self.theme, command=lambda v: set_mode(v))
        grp.add(wrap, t("One folder (all together)"), "flat",
                selected=True, bg="bg").pack(anchor="w", pady=2)
        grp.add(wrap, t("Same subfolder structure"), "mirror", bg="bg").pack(
            anchor="w", pady=2)
        grp.add(wrap, t("A new subfolder in each folder"), "inplace", bg="bg").pack(
            anchor="w", pady=2)

        # A host that swaps between the output-folder picker and the name field.
        ctx_host = self._tw(tk.Frame(wrap), bg="bg"); ctx_host.pack(fill="x")

        outdir_box = self._tw(tk.Frame(ctx_host), bg="bg")
        odir_var = tk.StringVar(value=st["out_dir"])

        def pick_out():
            dlg.grab_release()
            d = tkfd.askdirectory(parent=dlg, title=t("Choose a folder"),
                                  initialdir=odir_var.get() or src_var.get() or None)
            dlg.grab_set()
            if d:
                odir_var.set(d)
        orow = self._tw(tk.Frame(outdir_box), bg="bg"); orow.pack(fill="x", pady=(6, 0))
        tintkit.Button(orow, self.theme, t("Select"), role="neutral",
                       variant="outline", command=pick_out, bg="bg").pack(
                           side="right", padx=(6, 0))
        odir_field = tintkit.TextField(orow, self.theme, bg="bg")
        odir_field.entry.configure(textvariable=odir_var)
        odir_field.pack(side="left", fill="x", expand=True)

        subname_box = self._tw(tk.Frame(ctx_host), bg="bg")
        sub_var = tk.StringVar(value=st["sub_name"])
        self._tw(tk.Label(subname_box, text=t("Subfolder name"),
                 font=("Segoe UI", 8)), bg="bg", fg="fg_dim").pack(
                     anchor="w", pady=(6, 2))
        sub_field = tintkit.TextField(subname_box, self.theme, bg="bg")
        sub_field.entry.configure(textvariable=sub_var)
        sub_field.pack(fill="x")

        def set_mode(v):
            st["out_mode"] = v
            outdir_box.pack_forget(); subname_box.pack_forget()
            (subname_box if v == "inplace" else outdir_box).pack(fill="x")
        set_mode("flat")

        # --- Format (drives quality visibility) + Quality ---
        q_opts = (80, 90, 95, 100)
        st["quality"] = min(q_opts, key=lambda q: abs(q - st["quality"]))
        heading(t("Format"))
        fmt_row = self._tw(tk.Frame(wrap), bg="bg"); fmt_row.pack(anchor="w")
        fmt_opts = ("JPEG", "PNG", "WEBP")

        qbox = self._tw(tk.Frame(wrap), bg="bg")
        self._tw(tk.Label(qbox, text=t("Quality"), font=("Segoe UI", 8)),
                 bg="bg", fg="fg_dim").pack(anchor="w", pady=(10, 2))

        def pick_q(i, _label):
            st["quality"] = q_opts[i]
        tintkit.SegmentedTabs(qbox, self.theme, [str(q) for q in q_opts],
                              selected=q_opts.index(st["quality"]),
                              command=pick_q, bg="bg").pack(anchor="w")

        def apply_fmt(f):
            st["fmt"] = f
            if f == "PNG":
                qbox.pack_forget()                 # PNG is lossless — no quality
            else:
                qbox.pack(fill="x", anchor="w", after=fmt_row)
        tintkit.SegmentedTabs(fmt_row, self.theme, list(fmt_opts),
                              selected=fmt_opts.index(st["fmt"]),
                              command=lambda i, label: apply_fmt(label),
                              bg="bg").pack(anchor="w")
        apply_fmt(st["fmt"])                        # initial quality visibility

        # --- Confirm / cancel ---
        def confirm():
            src = src_var.get().strip()
            if not src or not os.path.isdir(src):
                self.toast(t("Choose a source folder"))
                return
            st["src"] = src
            st["recurse"] = recurse_chk.state == "on"
            if st["out_mode"] == "inplace":
                st["sub_name"] = sub_var.get().strip() or "resized"
            else:
                st["out_dir"] = odir_var.get().strip() or \
                    (os.path.join(src, "_resized"))
            st["ok"] = True
            dlg.destroy()

        brow = self._tw(tk.Frame(wrap), bg="bg"); brow.pack(anchor="e", pady=(16, 0))
        tintkit.Button(brow, self.theme, t("Cancel"), role="neutral",
                       variant="outline", command=dlg.destroy, bg="bg").pack(
                           side="right", padx=(8, 0))
        tintkit.Button(brow, self.theme, t("Resize"), role="primary",
                       variant="filled", command=confirm, bg="bg").pack(
                           side="right")

        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: confirm())
        self._place_filter_dialog(dlg)
        if not st["ok"]:
            return None
        return {"src": st["src"], "recurse": st["recurse"],
                "out_mode": st["out_mode"], "out_dir": st["out_dir"],
                "sub_name": st["sub_name"], "fmt": st["fmt"],
                "quality": st["quality"]}
