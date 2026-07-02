"""Saving: quick non-destructive save and the full 'Save as...' dialog.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import io
import os
import tkinter as tk
import tkinter.filedialog as tkfd

from ..i18n import t
import tintkit


class SaveMixin:
    # --- Save: quick save + full "Save as…" dialog --------------------------

    FMT_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}  # format → extension

    def _save_basename(self):
        "Default output name for the current photo: its real name + _edited."
        return os.path.splitext(self.files[self.index])[0] + "_edited"

    def _default_export_dir(self):
        """The folder the Save dialog opens at, per Settings → Export → Output.

        "subfolder" → a folder (export_subfolder, e.g. _edited) beside each photo;
        "fixed" → one configured folder for every export. Falls back to a
        <folder>/_edited subfolder if the fixed folder is unset.
        """
        if getattr(self, "export_dir_mode", "subfolder") == "fixed" \
                and self.export_fixed_dir:
            return self.export_fixed_dir
        name = (self.export_subfolder or "_edited").strip() or "_edited"
        return os.path.join(self.folder, name) if self.folder else name

    def _export_meta(self):
        """Metadata to carry from the source into the saved file, as save() kwargs.

        ICC: keep the source colour profile (e.g. Display P3) so colours look
        identical — edits stay in that space, so it's still valid after them.

        EXIF: keep camera / date / exposure / GPS, but force Orientation = 1.
        The viewer shows raw pixels and never auto-rotates, so the saved pixels
        already match what was on screen; any stored orientation would make other
        viewers double-rotate. (tobytes() also drops the stale embedded thumbnail.)"""
        if self.current_pil is None:
            return {}
        info = self.current_pil.info
        extra = {}
        icc = info.get("icc_profile")
        if icc:
            extra["icc_profile"] = icc
        exif = self.current_pil.getexif()
        if exif:
            exif[0x0112] = 1                       # Orientation → normal
            extra["exif"] = exif.tobytes()
        return extra

    def _to_srgb(self, img, icc):
        """Convert `img` (RGB pixels in the source ICC space) to sRGB.

        The save normally only CARRIES the source profile across; a wide-gamut
        photo (Adobe RGB / ProPhoto / Display P3) then looks wrong on the web,
        where browsers, Facebook and Instagram often ignore the embedded profile.
        This re-maps the pixels into sRGB so they look right untagged.

        Returns (converted_img, srgb_icc_bytes). If the source is already sRGB —
        or colour management fails for any reason — returns (img, icc) unchanged:
        a save must never break over colour conversion."""
        try:
            from PIL import ImageCms
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            if "srgb" in (ImageCms.getProfileDescription(src) or "").lower():
                return img, icc                    # already sRGB → nothing to do
            srgb = ImageCms.createProfile("sRGB")
            out = ImageCms.profileToProfile(img, src, srgb, outputMode="RGB")
            if out is None:
                return img, icc
            return out, ImageCms.ImageCmsProfile(srgb).tobytes()
        except Exception:
            return img, icc

    def _write_save(self, cfg, base):
        """Apply the live edits to the FULL-RES original and write ONE file using
        cfg = {dir, fmt, quality}, named `base` + the format's extension. The
        original is never touched. Returns the output path on success, else None."""
        from ..storage import unique_path
        fmt = cfg["fmt"]
        try:
            os.makedirs(cfg["dir"], exist_ok=True)
            # Never silently overwrite an existing file (a clashing name, or a
            # second save of the same photo) — number it instead.
            out = unique_path(os.path.join(cfg["dir"], base + self.FMT_EXT[fmt]))
            # Carry ICC profile + EXIF across, unless this save strips metadata.
            extra = self._export_meta() if cfg.get("keep_meta", True) else {}
            img = self._apply_edits(self.current_pil.convert("RGB"))
            # Convert wide-gamut colours into sRGB for the web, if asked. Needs the
            # source profile to convert FROM; an untagged photo is already sRGB.
            if cfg.get("to_srgb"):
                icc = (self.current_pil.info or {}).get("icc_profile")
                if icc:
                    img, srgb_icc = self._to_srgb(img, icc)
                    if cfg.get("keep_meta", True):
                        extra["icc_profile"] = srgb_icc   # re-tag as sRGB
                    # stripped metadata → leave untagged (viewers assume sRGB)
            if fmt == "PNG":
                img.save(out, "PNG", **extra)      # lossless; quality not applicable
            else:
                img.save(out, fmt, quality=int(cfg.get("quality", 95)), **extra)
        except Exception as e:
            self.toast(t("Error: {e}").format(e=e))
            return None
        self._edits_saved = True                   # on disk now → no re-prompt
        return out

    def quick_save(self):
        """Rail button + 'save on leaving an edited photo'. Writes silently with the
        session's quick-save config. If that isn't armed yet THIS session, open the
        full Save-as dialog instead (which can arm it). Returns True if saved."""
        if not self.files or self.current_pil is None or not self.folder:
            return False
        if self.quick_save_cfg is None:
            return self._save_as_dialog()          # configure + save in one go
        out = self._write_save(self.quick_save_cfg, self._save_basename())
        if out:
            self.toast(t("Saved → {name}").format(name=os.path.basename(out)))
            return True
        return False

    def _save_as_dialog(self):
        """Full save: pick folder, name, format, quality; optionally arm quick save.
        Defaults come from this session's quick cfg → the last saved → a sensible
        guess. Returns True if a file was written."""
        if not self.files or self.current_pil is None or not self.folder:
            self.toast(t("Open an image first"))
            return False

        src_ext = os.path.splitext(self.files[self.index])[1].lower()
        default_fmt = ("PNG" if src_ext == ".png" else
                       "WEBP" if src_ext == ".webp" else "JPEG")
        seed = self.quick_save_cfg or self.last_save or {}
        q_opts = (80, 90, 95, 100)
        # The default folder comes from the Settings → Export → Output config
        # (per-source subfolder or a fixed folder); a session quick-save dir wins.
        st = {"dir": (self.quick_save_cfg or {}).get("dir") or self._default_export_dir(),
              "fmt": seed.get("fmt") or default_fmt,
              "quality": min(q_opts, key=lambda q: abs(q - int(seed.get("quality", 95)))),
              "keep_meta": bool(seed.get("keep_meta", True)),
              "to_srgb": bool(seed.get("to_srgb", False)),
              "name": "", "quick": False, "ok": False}

        dlg = tk.Toplevel(self.root)
        dlg.title(t("Save as"))
        self._tw(dlg, bg="bg")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = self._tw(tk.Frame(dlg, padx=22, pady=16), bg="bg")
        wrap.pack(fill="both", expand=True)

        def heading(text):
            self._tw(tk.Label(wrap, text=text, font=("Segoe UI", 8)),
                     bg="bg", fg="fg_dim").pack(anchor="w", pady=(10, 2))

        # --- Folder (with a browse button) ---
        heading(t("Folder"))
        dir_var = tk.StringVar(value=st["dir"])

        def pick_dir():
            dlg.grab_release()                     # let the native picker take over
            d = tkfd.askdirectory(parent=dlg, title=t("Choose a folder"),
                                  initialdir=dir_var.get() or self.folder)
            dlg.grab_set()
            if d:
                dir_var.set(d)

        frow = self._tw(tk.Frame(wrap), bg="bg"); frow.pack(fill="x")
        tintkit.Button(frow, self.theme, t("Select"), role="neutral",
                       variant="outline", command=pick_dir, bg="bg").pack(
                           side="right", padx=(6, 0))
        dir_field = tintkit.TextField(frow, self.theme, bg="bg")
        dir_field.entry.configure(textvariable=dir_var)
        dir_field.pack(side="left", fill="x", expand=True)

        # --- Name (with a live extension suffix) ---
        heading(t("Name"))
        name_var = tk.StringVar(value=self._save_basename())
        nrow = self._tw(tk.Frame(wrap), bg="bg"); nrow.pack(fill="x")
        ext_lbl = self._tw(tk.Label(nrow, text=self.FMT_EXT[st["fmt"]],
                           font=("Segoe UI", 10)), bg="bg", fg="fg_dim")
        ext_lbl.pack(side="right", padx=(6, 0))
        name_field = tintkit.TextField(nrow, self.theme, bg="bg")
        name_field.entry.configure(textvariable=name_var)
        name_field.pack(side="left", fill="x", expand=True)
        ne = name_field.entry                      # for the focus/select-all below

        # --- Quality (lossy only) — built before format so format can show/hide it ---
        qbox = self._tw(tk.Frame(wrap), bg="bg")
        self._tw(tk.Label(qbox, text=t("Quality"), font=("Segoe UI", 8)),
                 bg="bg", fg="fg_dim").pack(anchor="w", pady=(10, 2))

        def pick_q(i, _label):
            st["quality"] = q_opts[i]
        tintkit.SegmentedTabs(qbox, self.theme, [str(q) for q in q_opts],
                              selected=q_opts.index(st["quality"]),
                              command=pick_q, bg="bg").pack(anchor="w")

        # --- Checkboxes (built before format; format packs qbox above them) ---
        def checkbox(label, key):
            "A tintkit checkbox bound to st[key] (on/off ← its bool)."
            def toggled(state):
                st[key] = (state == "on")
            return tintkit.Checkbox(wrap, self.theme, label,
                                    state="on" if st[key] else "off",
                                    command=toggled, bg="bg")

        # Keep camera/colour metadata (ICC + EXIF). Quick save arms this config.
        meta_chk = checkbox(t("Keep metadata (camera info, GPS, colour profile)"),
                            "keep_meta")
        srgb_chk = checkbox(t("Convert colours to sRGB (best for web)"), "to_srgb")
        chk = checkbox(t("Use this config for quick save"), "quick")

        # --- Format (drives the extension label + quality visibility) ---
        heading(t("Format"))
        fmt_row = self._tw(tk.Frame(wrap), bg="bg"); fmt_row.pack(anchor="w")
        fmt_opts = ("JPEG", "PNG", "WEBP")

        def apply_fmt(f):
            st["fmt"] = f
            ext_lbl.configure(text=self.FMT_EXT[f])
            if f == "PNG":
                qbox.pack_forget()                 # PNG is lossless — no quality
            else:
                qbox.pack(fill="x", anchor="w", before=meta_chk.canvas)
        tintkit.SegmentedTabs(fmt_row, self.theme, list(fmt_opts),
                              selected=fmt_opts.index(st["fmt"]),
                              command=lambda i, label: apply_fmt(label),
                              bg="bg").pack(anchor="w")

        meta_chk.pack(anchor="w", pady=(14, 0))    # below format/quality
        srgb_chk.pack(anchor="w", pady=(8, 0))
        chk.pack(anchor="w", pady=(8, 0))
        apply_fmt(st["fmt"])                        # initial styling + quality visibility

        # --- Confirm / cancel ---
        def confirm():
            name = name_var.get().strip()
            stem, e = os.path.splitext(name)
            if e.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                name = stem                        # strip a typed extension
            st["name"] = name or self._save_basename()
            st["dir"] = dir_var.get().strip() or self._default_export_dir()
            st["ok"] = True
            dlg.destroy()

        brow = self._tw(tk.Frame(wrap), bg="bg"); brow.pack(anchor="e", pady=(16, 0))
        tintkit.Button(brow, self.theme, t("Cancel"), role="neutral",
                       variant="outline", command=dlg.destroy, bg="bg").pack(
                           side="right", padx=(8, 0))
        tintkit.Button(brow, self.theme, t("Save"), role="primary",
                       variant="filled", command=confirm, bg="bg").pack(
                           side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: confirm())
        dlg.update_idletasks()
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        dlg.geometry(f"+{max(0, rx + (rw - dw) // 2)}+{max(0, ry + (rh - dh) // 2)}")
        dlg.grab_set()
        ne.focus_set(); ne.select_range(0, "end")
        self.root.wait_window(dlg)

        if not st["ok"]:
            return False
        cfg = {"dir": st["dir"], "fmt": st["fmt"], "quality": st["quality"],
               "keep_meta": st["keep_meta"], "to_srgb": st["to_srgb"]}
        out = self._write_save(cfg, st["name"])
        if not out:
            return False
        self.last_save = dict(cfg)                 # remember as the dialog's defaults
        if st["quick"]:
            self.quick_save_cfg = dict(cfg)        # arm quick save for this session
        self._save_state()                         # persist last_save across sessions
        self.toast(t("Saved → {name}").format(name=os.path.basename(out)))
        return True
