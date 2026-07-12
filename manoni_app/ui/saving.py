"""Saving, in three flavours — overwrite the original in place (Ctrl+S), drop a
numbered copy into a subfolder beside the photo (Ctrl+E), or open the full
'Save as...' dialog (Ctrl+Shift+S). Only the first one replaces an existing file.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import io
import os
import tempfile
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

    def _render_for_save(self, keep_meta=True, to_srgb=False):
        """The edited FULL-RES image, plus the metadata kwargs to write beside it.

        The single place that decides what a saved file carries, so EVERY save —
        quick copy, Save as… and overwrite alike — obeys the same two Export
        settings. It is deliberately not inlined into the writers: when each
        writer decided for itself, the overwrite path quietly kept the EXIF (GPS
        included) of a user who had asked in Settings for it to be stripped.

        Returns (img, extra) ready to hand to Image.save(**extra)."""
        extra = self._export_meta() if keep_meta else {}
        img = self._apply_edits(self.current_pil.convert("RGB"))
        # Convert wide-gamut colours into sRGB for the web, if asked. Needs the
        # source profile to convert FROM; an untagged photo is already sRGB.
        if to_srgb:
            icc = (self.current_pil.info or {}).get("icc_profile")
            if icc:
                img, srgb_icc = self._to_srgb(img, icc)
                if keep_meta:
                    extra["icc_profile"] = srgb_icc    # re-tag as sRGB
                # stripped metadata → leave untagged (viewers assume sRGB)
        return img, extra

    def _export_prefs(self):
        "The (keep_meta, to_srgb) the user set in Settings → Export."
        ls = getattr(self, "last_save", None) or {}
        return bool(ls.get("keep_meta", True)), bool(ls.get("to_srgb", False))

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
            img, extra = self._render_for_save(cfg.get("keep_meta", True),
                                               cfg.get("to_srgb", False))
            if fmt == "PNG":
                img.save(out, "PNG", **extra)      # lossless; quality not applicable
            else:
                img.save(out, fmt, quality=int(cfg.get("quality", 95)), **extra)
        except Exception as e:
            self.toast(t("Error: {e}").format(e=e))
            return None
        self._edits_saved = True                   # on disk now → no re-prompt
        self._capture_last_filter()                # remember this look as "Last"
        self._refresh_saved_indicator()            # clear the unsaved ● mark
        return out

    # --- Overwrite: save the edits straight back onto the open file ----------

    _EXT_FMT = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}

    def _overwrite_fmt(self, path):
        "PIL format to write when overwriting `path` in place, or None if we don't"
        " handle that file type (then the user must fall back to Save as…)."
        return self._EXT_FMT.get(os.path.splitext(path)[1].lower())

    def _write_overwrite(self, target):
        """Apply the live edits to the FULL-RES original and write them BACK OVER
        `target` — the open file itself — in its own format. Returns True on success.

        Metadata follows Settings → Export, exactly as the copy saves do: tick
        "strip metadata" and the GPS in the original is gone once this returns.
        (It used to carry EXIF across unconditionally, which silently wrote a
        user's location back into a file they had asked to have it stripped from.)

        This is the one save that DELIBERATELY replaces an existing file, so it
        skips unique_path. It is still crash-safe: the bytes go to a temp file in
        the same folder first and are swapped in with os.replace, so the file on
        disk is always either the whole old photo or the whole new one — never a
        half-written original. There is no backup — the original pixels are gone."""
        fmt = self._overwrite_fmt(target)
        if fmt is None:
            self.toast(t("Can't overwrite this file type — use Save as…"))
            return False
        tmp = None
        try:
            keep_meta, to_srgb = self._export_prefs()
            img, extra = self._render_for_save(keep_meta, to_srgb)
            directory = os.path.dirname(target) or "."
            # Temp file in the SAME folder so os.replace is a true atomic rename.
            fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(target)[1],
                                       dir=directory)
            os.close(fd)
            if fmt == "PNG":
                img.save(tmp, "PNG", **extra)      # lossless; quality n/a
            else:
                quality = int((getattr(self, "last_save", None) or {}).get("quality", 95))
                img.save(tmp, fmt, quality=quality, **extra)
            os.replace(tmp, target)                # atomic swap over the original
            tmp = None
        except Exception as e:
            if tmp is not None:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            self.toast(t("Error: {e}").format(e=e))
            return False
        self._edits_saved = True                   # on disk now → no unsaved ● mark
        self._capture_last_filter()                # remember this look as "Last"
        self._refresh_saved_indicator()
        return True

    def overwrite_save(self):
        """Save the edits straight back onto the open original (Ctrl+S, the panel
        Save button, the top-bar Save). Confirms first — the original has no
        backup — unless the user turned that off. Returns True if written."""
        if not self.files or self.current_pil is None or not self.folder:
            self.toast(t("Open an image first"))
            return False
        if not self._has_any_edits():
            self.toast(t("No edits to save"))
            return False
        fname = self.files[self.index]
        target = os.path.join(self.folder, fname)
        if self._overwrite_fmt(target) is None:
            # No in-place writer for this type (e.g. .tif) → go straight to Save as…
            self.toast(t("Can't overwrite this file type — use Save as…"))
            return self._save_as_dialog()
        if getattr(self, "confirm_overwrite", True):
            # Overwrite / Save a copy / Save as… / Cancel — the other two saves are
            # offered right here, so declining an overwrite still saves the work.
            choice = self._ask_overwrite(fname)
            if choice == "cancel":
                return False
            if choice == "copy":
                return self.quick_copy_save()      # numbered copy beside the photo
            if choice == "saveas":
                return self._save_as_dialog()      # write a copy instead
        if not self._write_overwrite(target):
            return False
        self._update_info(target)                  # refresh size / date, clear ●
        self.toast(t("Saved → {name}").format(name=fname))
        return True

    def _copy_cfg(self, out_dir):
        """Settings for a dialog-less copy into `out_dir`: the last save's format /
        quality / metadata choices, else a format that matches the source file."""
        src_ext = os.path.splitext(self.files[self.index])[1].lower()
        default_fmt = ("PNG" if src_ext == ".png" else
                       "WEBP" if src_ext == ".webp" else "JPEG")
        ls = getattr(self, "last_save", None) or {}
        return {"dir": out_dir,
                "fmt": ls.get("fmt") or default_fmt,
                "quality": int(ls.get("quality", 95)),
                "keep_meta": bool(ls.get("keep_meta", True)),
                "to_srgb": bool(ls.get("to_srgb", False))}

    def _auto_save_copy(self):
        """Silently write an edited COPY using the Export defaults, no dialog — the
        culling auto-save that fires when you arrow off an edited photo with
        'auto-save copies' on, and the 'Save' choice in the leaving prompt.
        Returns True if a file was written."""
        if not self.files or self.current_pil is None or not self.folder:
            return False
        cfg = self._copy_cfg(self._default_export_dir())
        return bool(self._write_save(cfg, self._save_basename()))

    # --- Quick copy: the third save — no overwrite, no dialog ----------------

    def quick_copy_save(self):
        """Ctrl+E / the top-bar copy button: write the edits as a fresh, numbered
        file into a subfolder beside the current photo — the Export output folder
        (<image folder>/_edited by default). No dialog, no picker: the destination
        simply follows the photo, so a copy always lands next to its source.
        Returns True if written.

        This is the overwrite save without the overwrite — same precondition (no
        edits means there is nothing to save, so nothing is written), but the
        original is never touched and neither is any earlier copy: _write_save
        runs the name through unique_path, so a second copy of the same photo
        lands beside the first as "… (1)" rather than replacing it."""
        if not self.files or self.current_pil is None or not self.folder:
            self.toast(t("Open an image first"))
            return False
        if not self._has_any_edits():
            self.toast(t("No edits to save"))
            return False
        out = self._write_save(self._copy_cfg(self._default_export_dir()),
                               self._save_basename())
        if not out:
            return False
        self.toast(t("Copy saved → {name}").format(name=os.path.basename(out)))
        return True

    def _save_as_dialog(self):
        """Full save (Ctrl+Shift+S): pick folder, name, format, quality. Defaults
        come from the last save, else a sensible guess. Returns True if written."""
        if not self.files or self.current_pil is None or not self.folder:
            self.toast(t("Open an image first"))
            return False

        src_ext = os.path.splitext(self.files[self.index])[1].lower()
        default_fmt = ("PNG" if src_ext == ".png" else
                       "WEBP" if src_ext == ".webp" else "JPEG")
        seed = self.last_save or {}
        q_opts = (80, 90, 95, 100)
        # The default folder comes from the Settings → Export → Output config
        # (per-source subfolder or a fixed folder), unless the dialog remembered one.
        st = {"dir": seed.get("dir") or self._default_export_dir(),
              "fmt": seed.get("fmt") or default_fmt,
              "quality": min(q_opts, key=lambda q: abs(q - int(seed.get("quality", 95)))),
              "keep_meta": bool(seed.get("keep_meta", True)),
              "to_srgb": bool(seed.get("to_srgb", False)),
              "name": "", "ok": False}

        dlg = tk.Toplevel(self.root)
        dlg.title(t("Save as"))
        self._tw(dlg, bg="bg")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = self._tw(tk.Frame(dlg, padx=self._edit_dpi_w(22),
                                 pady=self._edit_dpi_w(16)), bg="bg")
        wrap.pack(fill="both", expand=True)

        def heading(text):
            self._tw(tk.Label(wrap, text=text, font=("Segoe UI", 8)),
                     bg="bg", fg="fg_dim").pack(
                         anchor="w", pady=(self._edit_dpi_w(10), self._edit_dpi_w(2)))

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
                           side="right", padx=(self._edit_dpi_w(6), 0))
        dir_field = tintkit.TextField(frow, self.theme, bg="bg")
        dir_field.entry.configure(textvariable=dir_var)
        dir_field.pack(side="left", fill="x", expand=True)

        # --- Name (with a live extension suffix) ---
        heading(t("Name"))
        name_var = tk.StringVar(value=self._save_basename())
        nrow = self._tw(tk.Frame(wrap), bg="bg"); nrow.pack(fill="x")
        ext_lbl = self._tw(tk.Label(nrow, text=self.FMT_EXT[st["fmt"]],
                           font=("Segoe UI", 10)), bg="bg", fg="fg_dim")
        ext_lbl.pack(side="right", padx=(self._edit_dpi_w(6), 0))
        name_field = tintkit.TextField(nrow, self.theme, bg="bg")
        name_field.entry.configure(textvariable=name_var)
        name_field.pack(side="left", fill="x", expand=True)
        ne = name_field.entry                      # for the focus/select-all below

        # --- Quality (lossy only) — built before format so format can show/hide it ---
        qbox = self._tw(tk.Frame(wrap), bg="bg")
        self._tw(tk.Label(qbox, text=t("Quality"), font=("Segoe UI", 8)),
                 bg="bg", fg="fg_dim").pack(
                     anchor="w", pady=(self._edit_dpi_w(10), self._edit_dpi_w(2)))

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

        # Keep camera/colour metadata (ICC + EXIF).
        meta_chk = checkbox(t("Keep metadata (camera info, GPS, colour profile)"),
                            "keep_meta")
        srgb_chk = checkbox(t("Convert colours to sRGB (best for web)"), "to_srgb")

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

        meta_chk.pack(anchor="w", pady=(self._edit_dpi_w(14), 0))   # below format/quality
        srgb_chk.pack(anchor="w", pady=(self._edit_dpi_w(8), 0))
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

        brow = self._tw(tk.Frame(wrap), bg="bg")
        brow.pack(anchor="e", pady=(self._edit_dpi_w(16), 0))
        tintkit.Button(brow, self.theme, t("Cancel"), role="neutral",
                       variant="outline", command=dlg.destroy, bg="bg").pack(
                           side="right", padx=(self._edit_dpi_w(8), 0))
        tintkit.Button(brow, self.theme, t("Save"), role="primary",
                       variant="filled", command=confirm, bg="bg").pack(
                           side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: confirm())
        dlg.update_idletasks()
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        dw = max(dw, self._edit_dpi_w(380))        # a consistent minimum width
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        dlg.geometry(f"{dw}x{dh}+{max(0, rx + (rw - dw) // 2)}+{max(0, ry + (rh - dh) // 2)}")
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
        self._save_state()                         # persist last_save across sessions
        self.toast(t("Saved → {name}").format(name=os.path.basename(out)))
        return True
