"""Saving: quick non-destructive save and the full 'Save as...' dialog.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import tkinter as tk
import tkinter.filedialog as tkfd

from ..config import BG, BAR, HOVER, ACCENT, FG, FG_DIM
from ..i18n import t


class SaveMixin:
    # --- Save: quick save + full "Save as…" dialog --------------------------

    FMT_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}  # format → extension

    def _save_basename(self):
        "Default output name for the current photo: its real name + _edited."
        return os.path.splitext(self.files[self.index])[0] + "_edited"

    def _write_save(self, cfg, base):
        """Apply the live edits to the FULL-RES original and write ONE file using
        cfg = {dir, fmt, quality}, named `base` + the format's extension. The
        original is never touched. Returns the output path on success, else None."""
        fmt = cfg["fmt"]
        out = os.path.join(cfg["dir"], base + self.FMT_EXT[fmt])
        try:
            os.makedirs(cfg["dir"], exist_ok=True)
            img = self._apply_edits(self.current_pil.convert("RGB"))
            if fmt == "PNG":
                img.save(out, "PNG")               # lossless; quality not applicable
            else:
                img.save(out, fmt, quality=int(cfg.get("quality", 95)))
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
        st = {"dir": seed.get("dir") or os.path.join(self.folder, "_edited"),
              "fmt": seed.get("fmt") or default_fmt,
              "quality": min(q_opts, key=lambda q: abs(q - int(seed.get("quality", 95)))),
              "name": "", "quick": False, "ok": False}

        dlg = tk.Toplevel(self.root)
        dlg.title(t("Save as"))
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = tk.Frame(dlg, bg=BG, padx=22, pady=16)
        wrap.pack(fill="both", expand=True)

        def heading(text):
            tk.Label(wrap, text=text, bg=BG, fg=FG_DIM,
                     font=("Segoe UI", 8)).pack(anchor="w", pady=(10, 2))

        def mkbtn(parent, text, command, primary=False):
            bg = ACCENT if primary else BAR
            hov = "#5ab0ff" if primary else HOVER
            b = tk.Label(parent, text=text, bg=bg, fg="#0b0b0b" if primary else FG,
                         cursor="hand2", padx=14, pady=7,
                         font=("Segoe UI", 9, "bold" if primary else "normal"))
            b.bind("<Enter>", lambda e: b.configure(bg=hov))
            b.bind("<Leave>", lambda e: b.configure(bg=bg))
            b.bind("<Button-1>", lambda e: command())
            return b

        def style_chip(w, active):
            w.configure(bg=ACCENT if active else BAR,
                        fg="#0b0b0b" if active else FG)

        def mkchip(parent, text, command):
            c = tk.Label(parent, text=text, bg=BAR, fg=FG, cursor="hand2",
                         padx=13, pady=6, font=("Segoe UI", 9))
            c.bind("<Button-1>", lambda e: command())
            c.pack(side="left", padx=(0, 6))
            return c

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

        frow = tk.Frame(wrap, bg=BG); frow.pack(fill="x")
        mkbtn(frow, t("Select"), pick_dir).pack(side="right", padx=(6, 0))
        tk.Entry(frow, textvariable=dir_var, bg=BAR, fg=FG, insertbackground=FG,
                 relief="flat", font=("Segoe UI", 9)).pack(
                     side="left", fill="x", expand=True, ipady=5)

        # --- Name (with a live extension suffix) ---
        heading(t("Name"))
        name_var = tk.StringVar(value=self._save_basename())
        nrow = tk.Frame(wrap, bg=BG); nrow.pack(fill="x")
        ext_lbl = tk.Label(nrow, text=self.FMT_EXT[st["fmt"]], bg=BG, fg=FG_DIM,
                           font=("Segoe UI", 10))
        ext_lbl.pack(side="right", padx=(6, 0))
        ne = tk.Entry(nrow, textvariable=name_var, bg=BAR, fg=FG, insertbackground=FG,
                      relief="flat", font=("Segoe UI", 10))
        ne.pack(side="left", fill="x", expand=True, ipady=5)

        # --- Quality (lossy only) — built before format so format can show/hide it ---
        qbox = tk.Frame(wrap, bg=BG)
        tk.Label(qbox, text=t("Quality"), bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(10, 2))
        qrow = tk.Frame(qbox, bg=BG); qrow.pack(anchor="w")
        q_chips = {}

        def pick_q(q):
            st["quality"] = q
            for k, w in q_chips.items():
                style_chip(w, k == q)
        for q in q_opts:
            q_chips[q] = mkchip(qrow, str(q), lambda q=q: pick_q(q))

        # --- Checkbox: arm quick save (built before format; format packs qbox here) ---
        chk = tk.Frame(wrap, bg=BG)
        box = tk.Label(chk, text="☐", bg=BG, fg=FG, font=("Segoe UI", 13),
                       cursor="hand2")
        box.pack(side="left")
        ctxt = tk.Label(chk, text=t("Use this config for quick save"),
                        bg=BG, fg=FG, font=("Segoe UI", 9), cursor="hand2")
        ctxt.pack(side="left", padx=(6, 0))

        def toggle_quick(_e=None):
            st["quick"] = not st["quick"]
            box.configure(text="☑" if st["quick"] else "☐",
                          fg=ACCENT if st["quick"] else FG)
        for w in (box, ctxt):
            w.bind("<Button-1>", toggle_quick)

        # --- Format chips (drive the extension label + quality visibility) ---
        heading(t("Format"))
        fmt_row = tk.Frame(wrap, bg=BG); fmt_row.pack(anchor="w")
        fmt_chips = {}

        def pick_fmt(f):
            st["fmt"] = f
            for k, w in fmt_chips.items():
                style_chip(w, k == f)
            ext_lbl.configure(text=self.FMT_EXT[f])
            if f == "PNG":
                qbox.pack_forget()                 # PNG is lossless — no quality
            else:
                qbox.pack(fill="x", anchor="w", before=chk)
        for f in ("JPEG", "PNG", "WEBP"):
            fmt_chips[f] = mkchip(fmt_row, f, lambda f=f: pick_fmt(f))

        chk.pack(anchor="w", pady=(14, 0))         # below format/quality
        pick_fmt(st["fmt"])                        # initial styling + quality visibility
        for k, w in q_chips.items():
            style_chip(w, k == st["quality"])

        # --- Confirm / cancel ---
        def confirm():
            name = name_var.get().strip()
            stem, e = os.path.splitext(name)
            if e.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                name = stem                        # strip a typed extension
            st["name"] = name or self._save_basename()
            st["dir"] = dir_var.get().strip() or os.path.join(self.folder, "_edited")
            st["ok"] = True
            dlg.destroy()

        brow = tk.Frame(wrap, bg=BG); brow.pack(anchor="e", pady=(16, 0))
        mkbtn(brow, t("Cancel"), dlg.destroy).pack(side="right", padx=(8, 0))
        mkbtn(brow, t("Save"), confirm, primary=True).pack(side="right")

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
        cfg = {"dir": st["dir"], "fmt": st["fmt"], "quality": st["quality"]}
        out = self._write_save(cfg, st["name"])
        if not out:
            return False
        self.last_save = dict(cfg)                 # remember as the dialog's defaults
        if st["quick"]:
            self.quick_save_cfg = dict(cfg)        # arm quick save for this session
        self._save_state()                         # persist last_save across sessions
        self.toast(t("Saved → {name}").format(name=os.path.basename(out)))
        return True
