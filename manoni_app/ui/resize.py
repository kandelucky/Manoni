"""Resize tool for Manoni: scale the photo down (or up) keeping its aspect
ratio, by a target long-side in pixels or by a percentage.

Like crop / rotate this is a DESTRUCTIVE in-memory bake into current_pil — the
original file on disk is never touched; Save writes the resized copy. The
compare "before" image is resized in lockstep, the source-px crop box / focus
shape are dropped (their coordinates no longer map), and the photo refits the
window. Reversed by leaving the photo (discard), exactly like crop.

Mixin on the Manoni window — every method uses the shared `self`, so behaviour
is identical to when it lived directly on the class.
"""

import os
import tkinter as tk

from PIL import Image, ImageFilter

from ..config import (BAR, ACCENT, FG, FG_DIM, HOVER, EDIT_PANEL_W, EDIT_PAD,
                      CHIP_GAP, ON_ACCENT, ACCENT_HOVER, CHIP_BG, DIVIDER)
from ..i18n import t
from .dialogs import set_chip_active, make_panel_chip


class ResizeMixin:
    # --- Resize tool (col 3 panel) ------------------------------------------

    # Quick targets per mode: a long-side in px (web-friendly sizes) or a percent.
    RESIZE_PX_PRESETS  = [1080, 1600, 2000, 2560]
    RESIZE_PCT_PRESETS = [25, 50, 75]

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

    def _build_resize_section(self, parent):
        "Resize panel: current size, mode toggle, a value entry + presets, apply."
        f = tk.Frame(parent, bg=BAR)
        self._resize_mode = "px"             # "px" = long side, "pct" = percent
        self._resize_quality = "normal"      # soft / normal / sharp (resample)
        self._resize_strength = {"soft": "medium", "sharp": "medium"}  # per quality
        self._resize_var = tk.StringVar()

        self._resize_group(f, t("Size"))
        # Current dimensions, refreshed on enter and after every resize.
        self._resize_current = tk.Label(f, text="", bg=BAR, fg=FG_DIM, anchor="w",
                                        font=("Segoe UI", 9))
        self._resize_current.pack(fill="x", padx=EDIT_PAD, pady=(0, 8))

        # Mode toggle: scale by the long side (px) or by a percentage.
        self._resize_mode_chips = {}
        modes = tk.Frame(f, bg=BAR)
        modes.pack(fill="x", padx=EDIT_PAD, pady=(0, 8))
        modes.columnconfigure(0, weight=1, uniform="rm")
        modes.columnconfigure(1, weight=1, uniform="rm")
        self._resize_mode_chips["px"] = make_panel_chip(
            modes, t("Long side"), lambda: self._set_resize_mode("px"), 0, CHIP_GAP)
        self._resize_mode_chips["pct"] = make_panel_chip(
            modes, t("Percent"), lambda: self._set_resize_mode("pct"), 1, CHIP_GAP)

        # Value entry + a live unit suffix (px / %). Enter applies.
        erow = tk.Frame(f, bg=BAR)
        erow.pack(fill="x", padx=EDIT_PAD)
        self._resize_unit = tk.Label(erow, text="px", bg=BAR, fg=FG_DIM,
                                     font=("Segoe UI", 9))
        self._resize_unit.pack(side="right", padx=(6, 0))
        ent = tk.Entry(erow, textvariable=self._resize_var, bg=CHIP_BG, fg=FG,
                       insertbackground=FG, relief="flat", justify="center",
                       font=("Segoe UI", 11))
        ent.pack(side="left", fill="x", expand=True, ipady=5)
        ent.bind("<Return>", lambda e: self.apply_resize())
        self._resize_entry = ent

        # Quick-target chips (rebuilt when the mode changes).
        self._resize_presets = tk.Frame(f, bg=BAR)
        self._resize_presets.pack(fill="x", padx=EDIT_PAD, pady=(8, 2))

        # Live result of the current input ("→ W × H").
        self._resize_result = tk.Label(f, text="", bg=BAR, fg=ACCENT, anchor="w",
                                       font=("Segoe UI", 10, "bold"))
        self._resize_result.pack(fill="x", padx=EDIT_PAD, pady=(6, 0))

        # Pixel quality (resample filter). One setting drives the single photo
        # AND the whole-folder batch.
        tk.Label(f, text=t("Pixels"), bg=BAR, fg=FG_DIM, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=EDIT_PAD,
                                                    pady=(12, 4))
        self._resize_q_chips = {}
        qrow = tk.Frame(f, bg=BAR)
        qrow.pack(fill="x", padx=EDIT_PAD)
        for i in range(len(self.RESIZE_QUALITIES)):
            qrow.columnconfigure(i, weight=1, uniform="rq")
        qlabels = {"soft": t("Soft"), "normal": t("Normal"), "sharp": t("Sharp")}
        for i, key in enumerate(self.RESIZE_QUALITIES):
            self._resize_q_chips[key] = self._resize_quality_chip(
                qrow, qlabels[key], key, i)

        # Strength of the soft/sharp effect (a whole block, shown only for those
        # two — "normal" has no effect to dial). Packed before the hint label.
        self._resize_str_block = tk.Frame(f, bg=BAR)
        tk.Label(self._resize_str_block, text=t("Strength"), bg=BAR, fg=FG_DIM,
                 anchor="w", font=("Segoe UI", 8, "bold")).pack(fill="x",
                                                                pady=(8, 4))
        self._resize_str_chips = {}
        srow = tk.Frame(self._resize_str_block, bg=BAR)
        srow.pack(fill="x")
        for i in range(len(self.RESIZE_STRENGTHS)):
            srow.columnconfigure(i, weight=1, uniform="rs")
        slabels = {"light": t("Light"), "medium": t("Medium"), "strong": t("Strong")}
        for i, key in enumerate(self.RESIZE_STRENGTHS):
            self._resize_str_chips[key] = self._resize_strength_chip(
                srow, slabels[key], key, i)

        self._resize_q_hint = tk.Label(
            f, text=t("Soft = smoother · Sharp adds web output-sharpening."),
            bg=BAR, fg=FG_DIM, anchor="w", justify="left", font=("Segoe UI", 8),
            wraplength=self._edit_dpi_w(EDIT_PANEL_W - 2 * EDIT_PAD))
        self._resize_q_hint.pack(fill="x", padx=EDIT_PAD, pady=(5, 0))
        self._set_resize_quality(self._resize_quality)   # paints chips + str block

        # Apply (accent, full width).
        apply_btn = tk.Frame(f, bg=ACCENT, cursor="hand2")
        apply_btn.pack(fill="x", padx=EDIT_PAD, pady=(14, 6))
        atx = tk.Label(apply_btn, text=t("Resize"), bg=ACCENT, fg=ON_ACCENT,
                       font=("Segoe UI", 10, "bold"))
        atx.pack(expand=True, pady=10)
        for w in (apply_btn, atx):
            w.bind("<Button-1>", lambda e: self.apply_resize())
            w.bind("<Enter>", lambda e: [x.configure(bg=ACCENT_HOVER)
                                         for x in (apply_btn, atx)])
            w.bind("<Leave>", lambda e: [x.configure(bg=ACCENT)
                                         for x in (apply_btn, atx)])

        tk.Label(f, text=t("The original stays untouched — Save writes the resized copy."),
                 bg=BAR, fg=FG_DIM, anchor="w", justify="left",
                 font=("Segoe UI", 8),
                 wraplength=self._edit_dpi_w(EDIT_PANEL_W - 2 * EDIT_PAD)).pack(
                     fill="x", padx=EDIT_PAD, pady=(2, 6))

        # --- Whole-folder batch (same size rule applied to every photo) -------
        self._resize_group(f, t("Whole folder"))
        tk.Label(f, text=t("Resize every photo in the folder with the size above. "
                           "Originals are untouched; the copies go to a new folder."),
                 bg=BAR, fg=FG_DIM, anchor="w", justify="left",
                 font=("Segoe UI", 8),
                 wraplength=self._edit_dpi_w(EDIT_PANEL_W - 2 * EDIT_PAD)).pack(
                     fill="x", padx=EDIT_PAD, pady=(0, 6))

        btn = tk.Frame(f, bg=CHIP_BG, cursor="hand2")
        btn.pack(fill="x", padx=EDIT_PAD, pady=(0, 8))
        inner = tk.Frame(btn, bg=CHIP_BG)
        inner.pack(pady=9)
        bparts = [btn, inner]
        bimg = self.icon("folder-output", size=16)
        if bimg is not None:
            bic = tk.Label(inner, image=bimg, bg=CHIP_BG)
            bic.pack(side="left", padx=(0, 8))
            bparts.append(bic)
        btx = tk.Label(inner, text=t("Resize the whole folder"), bg=CHIP_BG, fg=FG,
                       font=("Segoe UI", 9, "bold"))
        btx.pack(side="left")
        bparts.append(btx)
        for w in bparts:
            w.bind("<Button-1>", lambda e: self._resize_folder())
            w.bind("<Enter>", lambda e: [p.configure(bg=HOVER) for p in bparts])
            w.bind("<Leave>", lambda e: [p.configure(bg=CHIP_BG) for p in bparts])

        # Recompute the result label live as the value changes (typing or preset).
        self._resize_var.trace_add("write", lambda *_: self._update_resize_display())
        return f

    def _resize_group(self, parent, text):
        "A thin divider + small bold caption titling the resize panel."
        tk.Frame(parent, bg=DIVIDER, height=1).pack(fill="x", padx=EDIT_PAD,
                                                    pady=(12, 0))
        tk.Label(parent, text=text, bg=BAR, fg=FG_DIM, anchor="w",
                 font=("Segoe UI", 8, "bold")).pack(fill="x", padx=EDIT_PAD,
                                                    pady=(4, 6))

    # --- Mode + presets -----------------------------------------------------

    def _set_resize_mode(self, mode):
        "Switch between long-side-px and percent; reset the value to a sane default."
        if mode == self._resize_mode:
            return
        self._resize_mode = mode
        self._refresh_resize_mode()
        self._reset_resize_input()

    def _refresh_resize_mode(self):
        "Repaint the mode chips, the unit suffix, and rebuild the preset chips."
        for m, chip in self._resize_mode_chips.items():
            set_chip_active(chip, m == self._resize_mode, CHIP_BG)
        px = self._resize_mode == "px"
        self._resize_unit.configure(text="px" if px else "%")
        pf = self._resize_presets
        for w in pf.winfo_children():
            w.destroy()
        presets = self.RESIZE_PX_PRESETS if px else self.RESIZE_PCT_PRESETS
        suffix = "px" if px else "%"
        # Equal-width columns so the chips always fit the panel (4 px / 3 percent).
        for i in range(max(len(self.RESIZE_PX_PRESETS), len(self.RESIZE_PCT_PRESETS))):
            pf.columnconfigure(i, weight=1 if i < len(presets) else 0, uniform="rp")
        for i, p in enumerate(presets):
            self._resize_preset_chip(pf, f"{p}{suffix}", p, i)

    def _resize_preset_chip(self, parent, label, value, col):
        "One quick-target chip; click fills the value entry."
        chip = tk.Label(parent, text=label, bg=CHIP_BG, fg=FG, cursor="hand2",
                        font=("Segoe UI", 8, "bold"), pady=6)
        chip.grid(row=0, column=col, sticky="ew", padx=2)
        chip.bind("<Button-1>", lambda e: self._resize_var.set(str(value)))
        chip.bind("<Enter>", lambda e: chip.configure(bg=HOVER))
        chip.bind("<Leave>", lambda e: chip.configure(bg=CHIP_BG))
        return chip

    def _resize_quality_chip(self, parent, label, key, col):
        "One pixel-quality chip (soft/normal/sharp); click selects it, like the mode chips."
        chip = tk.Label(parent, text=label, bg=CHIP_BG, fg=FG, cursor="hand2",
                        font=("Segoe UI", 8, "bold"), pady=6)
        chip.grid(row=0, column=col, sticky="ew", padx=2)
        chip.bind("<Button-1>", lambda e: self._set_resize_quality(key))
        return chip

    def _set_resize_quality(self, q):
        "Pick the resample quality; light up its chip + show/hide the strength block."
        self._resize_quality = q
        for k, chip in self._resize_q_chips.items():
            set_chip_active(chip, k == q, CHIP_BG)
        self._refresh_resize_strength()

    def _resize_strength_chip(self, parent, label, key, col):
        "One strength chip (light/medium/strong) for the active soft/sharp effect."
        chip = tk.Label(parent, text=label, bg=CHIP_BG, fg=FG, cursor="hand2",
                        font=("Segoe UI", 8, "bold"), pady=6)
        chip.grid(row=0, column=col, sticky="ew", padx=2)
        chip.bind("<Button-1>", lambda e: self._set_resize_strength(key))
        return chip

    def _set_resize_strength(self, level):
        "Set the active quality's effect strength; remembered per quality."
        if self._resize_quality == "normal":
            return
        self._resize_strength[self._resize_quality] = level
        self._refresh_resize_strength()

    def _refresh_resize_strength(self):
        "Show the strength block for soft/sharp (hidden for normal) + light its chip."
        if self._resize_quality == "normal":
            self._resize_str_block.pack_forget()
            return
        self._resize_str_block.pack(fill="x", padx=EDIT_PAD,
                                    before=self._resize_q_hint)
        active = self._resize_strength[self._resize_quality]
        for k, chip in self._resize_str_chips.items():
            set_chip_active(chip, k == active, CHIP_BG)

    def _reset_resize_input(self):
        "Seed the value: the current long side (px mode) or 100 (percent mode)."
        if self.current_pil is None:
            self._resize_var.set("")
            return
        iw, ih = self.current_pil.size
        self._resize_var.set("100" if self._resize_mode == "pct"
                             else str(max(iw, ih)))

    # --- Computation + display ----------------------------------------------

    def _resize_value(self):
        "The entered number (>0) as a float, or None if blank / invalid."
        try:
            val = float(self._resize_var.get().strip().replace(",", "."))
        except (ValueError, AttributeError):
            return None
        return val if val > 0 else None

    def _resize_target_for(self, iw, ih):
        "(new_w, new_h) for an iw×ih image from the value + mode; None if invalid."
        val = self._resize_value()
        if val is None:
            return None
        scale = (val / 100.0) if self._resize_mode == "pct" else (val / max(iw, ih))
        return (max(1, round(iw * scale)), max(1, round(ih * scale)))

    def _resize_target_size(self):
        "(new_w, new_h) for the open photo, keeping aspect; None if invalid."
        if self.current_pil is None:
            return None
        return self._resize_target_for(*self.current_pil.size)

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
        "Open the resize tool: refresh the panel from the current photo, plain view."
        self.preview.configure(cursor="")
        if hasattr(self, "_resize_mode_chips"):
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

    def _resize_folder(self):
        "Resize every photo in the open folder by the current rule, saving copies."
        if not self.files or not self.folder:
            self.toast(t("Open a folder first"))
            return
        if self._resize_value() is None:
            self.toast(t("Enter a valid size"))
            return
        cfg = self._ask_batch_config(
            len(self.files), title=t("Resize whole folder"),
            intro=t("Resize all {n} photos in the folder and save the copies.").format(
                n=len(self.files)),
            default_dir=os.path.join(self.folder, "_resized"))
        if cfg is None:
            return
        try:
            os.makedirs(cfg["dir"], exist_ok=True)
        except OSError:
            self.toast(t("Could not create the output folder"))
            return
        from ..storage import unique_path
        ext = self.FMT_EXT[cfg["fmt"]]
        total, ok, fail = len(self.files), 0, 0
        for i, fname in enumerate(self.files):
            self.toast(t("Resizing folder… {i}/{n}").format(i=i + 1, n=total))
            self.root.update()                        # show progress, stay responsive
            try:
                with Image.open(os.path.join(self.folder, fname)) as im:
                    im.load()
                    target = self._resize_target_for(*im.size)
                    if target is None:                # value went blank mid-run
                        fail += 1
                        continue
                    out = self._resize_pixels(im, target)
                    extra = self._batch_export_meta(im)
                # Don't let two sources (a.jpg + a.png) or a re-run overwrite each
                # other — number a clashing name instead.
                dest = unique_path(os.path.join(cfg["dir"],
                                                os.path.splitext(fname)[0] + ext))
                if cfg["fmt"] == "PNG":
                    out.save(dest, "PNG", **extra)
                else:
                    out.convert("RGB").save(dest, cfg["fmt"],
                                            quality=int(cfg["quality"]), **extra)
                ok += 1
            except Exception:
                fail += 1
        self.toast(t("Done — {ok} resized, {fail} failed  ·  {dir}").format(
            ok=ok, fail=fail, dir=os.path.basename(cfg["dir"]) or cfg["dir"]))
