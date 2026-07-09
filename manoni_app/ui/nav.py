"""Moving between photos and changing the set: prev/next, the unsaved-edit
guard, cull (keep / reject into two configured folders, with options + help
dialogs), file-move primitives, and undo / redo.

Mixin on the Manoni window — every method uses the shared `self`, so the
behaviour is identical to when it lived directly on the class.
"""

import os
import shutil
import tkinter as tk
import tkinter.filedialog as tkfd

import tintkit

# nav's dialogs are transient modals — they read live theme colours at build time
# (they can't outlive a dark<->light switch). Only the scheme-independent cull
# icon tints + SUPPORTED stay as config constants.
from ..config import SUPPORTED, CULL_KEEP_TINT, CULL_REJECT_TINT
from ..i18n import t
from .dialogs import center_over


class NavMixin:
    # --- Navigation ---------------------------------------------------------

    def go_to(self, index):
        if not (0 <= index < len(self.files)) or index == self.index:
            return
        if not self._maybe_prompt_save():
            return                       # user chose to stay on the edited photo
        self.index = index
        self.show_current()

    # --- Bottom info bar: what each arrow does / just did --------------------
    #
    # No new widget — this reuses the info bar at the very bottom of the window
    # (the one that normally shows the current photo's size / date / folder).
    # Hovering a nav button replaces that line with a description of the button;
    # moving off restores the photo info. Outcomes ("Wrapped to the first
    # photo", "Kept → …") arrive through toast(), which writes the same line.

    def _nav_hint(self, text, sub="", color=None):
        "Pointer is over a nav button → describe it in the bottom info bar. `sub`"
        " is an optional trailing note (keep / reject use it for their folder);"
        " `color` tints the whole line (keep / reject use their button tint)."
        lbl = getattr(self, "lbl_info", None)
        if lbl is None:
            return
        if sub:
            text = f"{text}      ·      {sub}"
        # brighten (or tint) while hinting — theme fg so it reads in light mode too
        lbl.configure(text=text, fg=color or self.theme["fg"])

    def _nav_hint_clear(self):
        "Pointer left a nav button → restore the current photo's info line."
        lbl = getattr(self, "lbl_info", None)
        if lbl is not None:
            lbl.configure(text=getattr(self, "_info_text", ""),
                          fg=self.theme["fg_dim"])

    # --- Arrow-action pop: a brief, self-fading label over the preview ------
    #
    # A small pill flashes what an arrow key just did ("Next photo", "Kept →
    # …") then fades out on its own. Unlike the bottom info line (easy to miss)
    # it floats over the photo. It's a borderless, alpha-blended Toplevel so it
    # can fade smoothly and sit above any image; one window is reused, and a
    # fresh flash cancels the previous one's fade so rapid keypresses stay snappy.

    _FLASH_COLORS = {          # text tint per outcome — all light so they read
        "nav":    "#ececec",   # on the always-dark letterbox and over any photo
        "keep":   CULL_KEEP_TINT,
        "reject": CULL_REJECT_TINT,
    }

    def flash(self, message, kind="nav"):
        "Pop `message` over the preview for a moment, then fade it out. `kind` is"
        " 'nav' (neutral), 'keep' (green) or 'reject' (red)."
        win = getattr(self, "_flash_win", None)
        if win is None or not win.winfo_exists():
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)          # borderless, no title bar
            win.withdraw()                       # hidden until placed (no corner flash)
            try:
                win.attributes("-topmost", True)
            except tk.TclError:
                pass
            lbl = tk.Label(win, font=("Segoe UI", 13), bg="#141414",
                           padx=18, pady=9)
            lbl.pack()
            self._flash_win, self._flash_lbl = win, lbl
        win, lbl = self._flash_win, self._flash_lbl

        for aid in getattr(self, "_flash_after", ()):   # drop a previous fade
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        self._flash_after = []

        lbl.configure(text=message, fg=self._FLASH_COLORS.get(kind, "#ececec"))
        try:
            win.attributes("-alpha", 0.96)
        except tk.TclError:
            pass
        win.update_idletasks()
        cv = self.preview                        # centre over the preview canvas
        cx = cv.winfo_rootx() + cv.winfo_width() // 2
        cy = cv.winfo_rooty() + max(24, cv.winfo_height() // 12)
        win.geometry(f"+{cx - win.winfo_width() // 2}+{cy}")
        win.deiconify()

        def fade(step):
            a = 0.96 - step * 0.16
            if a <= 0.02:
                win.withdraw()
                return
            try:
                win.attributes("-alpha", a)
            except tk.TclError:
                return
            self._flash_after.append(self.root.after(45, fade, step + 1))

        self._flash_after.append(self.root.after(650, fade, 1))

    def _cull_hint_line(self, folder):
        "Trailing note for a cull button: where it saves, or that it's unset."
        if folder:
            return t("saving to  {path}").format(path=folder)
        return t("no folder set yet — choose it in  ⚙ Settings")

    # --- Nav-arrow buttons: act, then report the special cases --------------
    #
    # A plain step needs no message — the info bar already flips to the new
    # photo. Only the surprising outcomes are called out (already at an edge, or
    # a wrap-around), via toast() so they land on the same info line.

    def _nav_click_first(self):
        self._nav_move(self.first, "first")

    def _nav_click_last(self):
        self._nav_move(self.last, "last")

    def _nav_click_prev(self):
        self._nav_move(self.prev, "prev")

    def _nav_click_next(self):
        self._nav_move(self.next, "next")

    def _nav_move(self, action, kind):
        "Run one arrow action, then toast only the outcomes that aren't obvious."
        if not self.files:
            return
        before = self.index
        action()                              # may pop the unsaved-edit dialog
        if not self.files or self.index == before:
            if self.files and (kind == "first" or (kind == "prev"
                                                    and len(self.files) == 1)):
                self.toast(t("Already on the first photo"))
            elif self.files and (kind == "last" or (kind == "next"
                                                    and len(self.files) == 1)):
                self.toast(t("Already on the last photo"))
            return                            # cancelled save → the dialog said it
        # Moved. The prev / next buttons wrap around at the folder edges.
        if kind == "prev" and before == 0:
            self.toast(t("Wrapped around to the last photo"))
        elif kind == "next" and before == len(self.files) - 1:
            self.toast(t("Wrapped around to the first photo"))

    # --- Unsaved-edit guard (offer to save a copy before leaving a photo) ----

    def _has_unsaved_edits(self):
        "True if the current photo has edits (sliders or rotation) not yet saved to a copy."
        if self._edits_saved:
            return False
        return self._has_any_edits()

    def _has_any_edits(self):
        "True if the current photo carries any edit — whether or not it was saved."
        if self.current_pil is None:
            return False
        return (self._rotated or self._mirrored or self._cropped or self._resized
                or self._perspd or self._healed
                or any(v != self._slider_neutral(k)
                       for k, v in self._edit_state().items()))

    # --- Restore original (discard every edit, reload the file) --------------

    def restore_original(self):
        "Discard every edit on the current photo and reload the original from disk."
        if not self._has_any_edits():
            self.toast(t("Nothing to restore — no edits yet"))
            return
        if not self._ask_restore_original():
            return
        self.show_current()   # re-reads the file → original pixels, all edits reset
        self.toast(t("The original is back — every edit was cleared"))

    def _confirm_dialog(self, title, message, buttons, checkbox=None, width=360):
        """The shared kit-standard confirm modal behind the save / restore prompts:
        a self._tw-threaded Toplevel (follows dark<->light), DPI-scaled padding,
        centered with keyboard nav.

        `buttons` is a list of (key, label, role) in VISUAL left-to-right order,
        the primary first; they pack right-to-left so the primary sits leftmost and
        Cancel rightmost (the house order), and Enter fires the primary. `checkbox`
        is an optional (label, key) tick. Returns (choice_key, checkbox_on);
        closing / Escape gives ("cancel", False), so pass a "cancel" button."""
        state = {"choice": "cancel", "chk": False}
        dlg = self._tw(tk.Toplevel(self.root), bg="bg")
        dlg.title(title)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        def choose(k):
            state["choice"] = k
            dlg.destroy()

        wrap = self._tw(tk.Frame(dlg, padx=self._edit_dpi_w(22),
                                 pady=self._edit_dpi_w(18)), bg="bg")
        wrap.pack(fill="both", expand=True)
        self._tw(tk.Label(wrap, text=title, font=("Segoe UI", 11, "bold")),
                 bg="bg", fg="fg").pack(anchor="w")
        self._tw(tk.Label(wrap, text=message, font=("Segoe UI", 9), justify="left",
                 wraplength=self._edit_dpi_w(width)), bg="bg", fg="fg_dim").pack(
            anchor="w", pady=(self._edit_dpi_w(4), self._edit_dpi_w(15)))

        if checkbox:
            def toggled(s):
                state["chk"] = (s == "on")
            tintkit.Checkbox(wrap, self.theme, checkbox[0], state="off",
                             command=toggled, bg="bg").pack(
                anchor="w", pady=(0, self._edit_dpi_w(2)))

        row = self._tw(tk.Frame(wrap), bg="bg")
        row.pack(anchor="e", pady=(self._edit_dpi_w(16), 0))
        for key, label, role in reversed(buttons):     # cancel packs first → rightmost
            tintkit.Button(row, self.theme, label, role=role,
                           variant="filled" if role == "primary" else "outline",
                           command=lambda k=key: choose(k), bg="bg").pack(
                side="right", padx=(self._edit_dpi_w(8), 0))

        dlg.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))
        dlg.bind("<Escape>", lambda e: choose("cancel"))
        dlg.bind("<Return>", lambda e: choose(buttons[0][0]))   # Enter = primary
        center_over(self.root, dlg)
        dlg.grab_set()
        dlg.focus_set()
        self.root.wait_window(dlg)
        return state["choice"], state["chk"]

    def _ask_restore_original(self):
        "Confirm before wiping the live edits (not undoable). Returns True to proceed."
        fname = self.files[self.index] if self.files else ""
        choice, _ = self._confirm_dialog(
            t("Restore the original?"),
            t("Discard every edit on {fname} and reload the original from disk?")
            .format(fname=fname),
            [("restore", t("Restore"), "primary"),
             ("cancel", t("Cancel"), "neutral")])
        return choice == "restore"

    def _maybe_prompt_save(self):
        """Before leaving an edited photo (arrow step, Enter/Backspace cull,
        folder switch, close): auto-save a copy, ask, or just go. Returns False
        only to STAY put.

        With 'auto-save copies while culling' on, an edited photo silently drops a
        copy into the export folder and we move on — the fast many-photos flow.
        Otherwise the unsaved-edit prompt offers Save-a-copy / Discard / Cancel
        (unless that warning is switched off, in which case edits are dropped).
        This runs for BOTH the arrow step and the Enter/Backspace cull, so a keep
        / reject that would move the original off-screen also saves the edit first."""
        if not self._has_unsaved_edits():
            return True
        if getattr(self, "autosave_copy", False):
            self._auto_save_copy()       # silent copy → _edited, then move on
            return True
        if not getattr(self, "warn_unsaved", True):
            return True                  # warning off → leave; live edits are dropped
        choice = self._ask_save_copy()
        if choice == "cancel":
            return False
        if choice == "save":
            return bool(self._auto_save_copy())
        return True                      # 'discard' → leave; live edits are dropped

    def _ask_save_copy(self):
        """Prompt shown when leaving a photo with unsaved edits: save an edited
        copy (into _edited), discard the edits, or stay. Returns 'save',
        'discard' or 'cancel'."""
        fname = self.files[self.index] if self.files else ""
        choice, _ = self._confirm_dialog(
            t("The image has changed"),
            t("{fname} — save a copy to _edited?").format(fname=fname),
            [("save", t("Save"), "primary"),
             ("discard", t("Don't save"), "neutral"),
             ("cancel", t("Cancel"), "neutral")])
        return choice

    def _ask_overwrite(self, fname):
        """Ask what Ctrl+S should do: overwrite the original in place, save a copy
        instead (Save as…), or cancel. Returns 'overwrite', 'saveas' or 'cancel'.
        A 'Don't ask again' tick — only meaningful for Overwrite — turns the
        confirmation off for good (persisted)."""
        choice, dont = self._confirm_dialog(
            t("Overwrite the original?"),
            t("Write your edits straight onto {fname}, replacing it — no backup, "
              "can't be undone. Or save a copy instead.").format(fname=fname),
            [("overwrite", t("Overwrite"), "primary"),
             ("saveas", t("Save as…"), "neutral"),
             ("cancel", t("Cancel"), "neutral")],
            checkbox=(t("Don't ask again"), "dont"), width=380)
        if choice == "overwrite" and dont:
            self.confirm_overwrite = False       # honoured next time; persist it now
            self._save_state()
        return choice

    def prev(self):
        if self.files:
            self.go_to((self.index - 1) % len(self.files))

    def next(self):
        if self.files:
            self.go_to((self.index + 1) % len(self.files))

    def first(self):
        self.go_to(0)

    def last(self):
        self.go_to(len(self.files) - 1)

    # --- Arrow-key browse shortcuts (only while the edit panel is closed) ----

    def _browse_keys_active(self):
        """True when the arrow shortcuts may act: a photo is shown and no text
        field is focused. Works whether or not the edit panel is open — leaving
        an edited photo (an arrow step or an Enter/Backspace cull alike) is
        guarded by the unsaved-edit prompt. (Modal dialogs grab the keyboard, so
        an open dialog never reaches these handlers anyway.)"""
        if not self.files:
            return False
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text)):
            return False
        return True

    def _arrow_prev(self):
        "← / ↑ previous photo; at the first one, report the folder edge."
        if not self._browse_keys_active():
            return
        if self.index > 0:
            before = self.index
            self.go_to(self.index - 1)
            if self.index != before:             # actually moved (not save-cancelled)
                self.flash(t("Previous photo"), "nav")
        else:
            self._folder_edge(-1)

    def _arrow_next(self):
        "→ / ↓ next photo; at the last one, report the folder edge."
        if not self._browse_keys_active():
            return
        if self.index < len(self.files) - 1:
            before = self.index
            self.go_to(self.index + 1)
            if self.index != before:             # actually moved (not save-cancelled)
                self.flash(t("Next photo"), "nav")
        else:
            self._folder_edge(1)

    def _folder_edge(self, direction):
        """Reached the first (-1) / last (+1) photo of the folder.

        What happens next is `self.edge_action`: "wrap" loops to the first/last
        photo of THIS folder, "sibling" continues into the next/previous folder,
        and None (unset) pops a small dialog that lets the user choose this time
        (and optionally remember it). Either way a clear toast reports the result.
        """
        action = self.edge_action
        if action is None:
            action, remember = self._ask_edge_action(direction)
            if action is None:
                return                       # cancelled → stay on this photo
            if remember:
                self.edge_action = action    # "mark" it so it stops asking
                self._save_state()
        if action == "wrap":
            self._edge_wrap(direction)
        else:
            self._edge_sibling(direction)

    def _edge_wrap(self, direction):
        "Loop to the first (after the last) / last (before the first) photo here."
        if not self.files:
            return
        target = 0 if direction > 0 else len(self.files) - 1
        before = self.index
        self.go_to(target)
        if self.index == target and target != before:   # actually moved (not cancelled)
            self.toast(t("Back to the first photo") if direction > 0
                       else t("Jumped to the last photo"))

    def _edge_sibling(self, direction):
        "Continue into the next (+1) / previous (-1) sibling folder that has photos."
        dest = self._sibling_folder(direction)
        if dest is None:
            self.toast(t("No more folders this way"))
            return
        if not self._maybe_prompt_save():    # leaving the folder: honour unsaved edits
            return
        self.load_folder(dest)               # selects the first photo by default
        if direction < 0 and self.files:     # entered from the end → land on the last
            self.index = len(self.files) - 1
            self.show_current()
        self.toast(t("Folder: {name}").format(
            name=os.path.basename(dest.rstrip("\\/"))))

    def _sibling_folder(self, direction):
        "The next (+1) / previous (-1) sibling folder holding photos, or None."
        if not self.folder:
            return None
        parent = os.path.dirname(os.path.normpath(self.folder))
        if not parent or not os.path.isdir(parent):
            return None
        try:
            names = sorted(
                (n for n in os.listdir(parent)
                 if not n.startswith(".")
                 and os.path.isdir(os.path.join(parent, n))),
                key=str.lower)
        except OSError:
            return None
        cur = os.path.basename(os.path.normpath(self.folder))
        try:
            i = next(k for k, n in enumerate(names) if n.lower() == cur.lower())
        except StopIteration:
            return None
        j = i + direction
        while 0 <= j < len(names):           # skip siblings with no photos
            cand = os.path.join(parent, names[j])
            if self._folder_has_photos(cand):
                return cand
            j += direction
        return None

    @staticmethod
    def _folder_has_photos(path):
        "True if `path` holds at least one supported image (best effort)."
        try:
            for f in os.listdir(path):
                if os.path.splitext(f)[1].lower() in SUPPORTED \
                        and os.path.isfile(os.path.join(path, f)):
                    return True
        except OSError:
            pass
        return False

    def _ask_edge_action(self, direction):
        """At the folder edge with no saved choice: ask what to do.

        A small modal dialog with two radio choices (neither pre-selected) — wrap
        to the first/last photo here, or continue into the next/previous folder —
        plus a 'remember this' toggle. Returns (action, remember): action is
        "wrap" / "sibling", or None if the user cancels.
        """
        st = {"action": None, "remember": False, "ok": False}
        bg, fg, fg_dim = self.theme["bg"], self.theme["fg"], self.theme["fg_dim"]
        dlg = tk.Toplevel(self.root)
        dlg.title(t("End of the folder") if direction > 0
                  else t("Start of the folder"))
        dlg.configure(bg=bg)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = tk.Frame(dlg, bg=bg, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text=(t("You're on the last photo") if direction > 0
                             else t("You're on the first photo")),
                 bg=bg, fg=fg, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(wrap, text=t("Where should the arrow keys go next?"),
                 bg=bg, fg=fg_dim, font=("Segoe UI", 9)).pack(anchor="w",
                                                              pady=(4, 14))

        radios = []

        def pick(val):
            st["action"] = val
            for v, dot in radios:
                dot.configure(text="◉" if v == val else "○",
                              fg=self.theme["accent"] if v == val else fg)

        def radio(val, label):
            row = tk.Frame(wrap, bg=bg, cursor="hand2")
            row.pack(anchor="w", pady=3)
            dot = tk.Label(row, text="○", bg=bg, fg=fg, font=("Segoe UI", 13),
                           cursor="hand2")
            dot.pack(side="left")
            lb = tk.Label(row, text=label, bg=bg, fg=fg, font=("Segoe UI", 10),
                          cursor="hand2")
            lb.pack(side="left", padx=(8, 0))
            radios.append((val, dot))
            for w in (row, dot, lb):
                w.bind("<Button-1>", lambda e, v=val: pick(v))

        radio("wrap", t("Go to the first photo") if direction > 0
              else t("Go to the last photo"))
        radio("sibling", t("Go to the next folder") if direction > 0
              else t("Go to the previous folder"))

        # Remember-this-choice toggle (so the dialog stops popping up).
        rem = tk.Frame(wrap, bg=bg, cursor="hand2")
        rem.pack(anchor="w", pady=(14, 0))
        bx = tk.Label(rem, text="☐", bg=bg, fg=fg, font=("Segoe UI", 13),
                      cursor="hand2")
        bx.pack(side="left")
        rl = tk.Label(rem, text=t("Remember my choice"), bg=bg, fg=fg,
                      font=("Segoe UI", 9), cursor="hand2")
        rl.pack(side="left", padx=(8, 0))

        def toggle_rem(_e=None):
            st["remember"] = not st["remember"]
            bx.configure(text="☑" if st["remember"] else "☐",
                         fg=self.theme["accent"] if st["remember"] else fg)
        for w in (rem, bx, rl):
            w.bind("<Button-1>", toggle_rem)

        def confirm():
            if st["action"] is None:         # nothing chosen yet → ignore OK
                return
            st["ok"] = True
            dlg.destroy()

        brow = tk.Frame(wrap, bg=bg)
        brow.pack(anchor="e", pady=(18, 0))
        tintkit.Button(brow, self.theme, t("Cancel"), role="neutral",
                       variant="outline", command=dlg.destroy).pack(
            side="right", padx=(8, 0))
        tintkit.Button(brow, self.theme, t("OK"), role="primary",
                       command=confirm).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: confirm())
        self._center_dialog(dlg)
        dlg.grab_set()
        dlg.focus_set()
        self.root.wait_window(dlg)
        if not st["ok"]:
            return None, False
        return st["action"], st["remember"]

    def _key_keep(self):
        "Enter sorts the current photo into the keep (good) folder."
        if self._browse_keys_active():
            self.move_to_folder()

    def _key_reject(self):
        "Backspace sorts the current photo into the reject (bad) folder."
        if self._browse_keys_active():
            self.delete()

    # --- Cull: keep / reject (sort into two configured folders) -------------

    def _cull_ready(self):
        "True once BOTH sort folders (keep + reject) are configured."
        return bool(self.cull_keep and self.cull_reject)

    def _require_cull(self):
        "Guard for the cull buttons: until both folders are set, toast + open"
        " the options dialog and refuse the action. Returns True when ready."
        if not self.files:
            return False
        if not self._cull_ready():
            self.toast(t("Set the sorting folders first  ·  ⚙ Settings"))
            self._cull_options_dialog()
            return False
        return True

    def move_to_folder(self):
        "Keep: move the current photo into the configured ✓ keeper folder."
        if not self._require_cull():
            return
        if not self._maybe_prompt_save():    # moving the original: honour unsaved edits
            return
        os.makedirs(self.cull_keep, exist_ok=True)
        if self._move_current_to(self.cull_keep):
            msg = t("Kept → {name}  ·  Ctrl+Z").format(
                name=os.path.basename(self.cull_keep))
            self.toast(msg)
            self.flash(msg, "keep")

    def delete(self):
        "Reject: move the current photo into the configured ✗ reject folder."
        if not self._require_cull():
            return
        if self.confirm_reject and not self._confirm(
                t("Move this photo to the Reject folder?"), ok_label=t("Reject")):
            return                       # asked to confirm and the user backed out
        if not self._maybe_prompt_save():    # moving the original: honour unsaved edits
            return
        os.makedirs(self.cull_reject, exist_ok=True)
        if self._move_current_to(self.cull_reject):
            msg = t("Rejected → {name}  ·  Ctrl+Z").format(
                name=os.path.basename(self.cull_reject))
            self.toast(msg)
            self.flash(msg, "reject")

    # --- Cull configuration + help dialogs ----------------------------------

    def _center_dialog(self, dlg):
        "Place a Toplevel centered over the main window."
        center_over(self.root, dlg)

    def _cull_options_dialog(self):
        "Configure the two sort folders (keep + reject) used by the cull buttons."
        st = {"keep": self.cull_keep or "", "reject": self.cull_reject or "",
              "ok": False}
        bg, fg, fg_dim = self.theme["bg"], self.theme["fg"], self.theme["fg_dim"]
        bar = self.theme["bar"]

        dlg = tk.Toplevel(self.root)
        dlg.title(t("Sorting folders"))
        dlg.configure(bg=bg)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = tk.Frame(dlg, bg=bg, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text=t("Sorting folders"), bg=bg, fg=fg,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(wrap, text=t("Set where kept and rejected photos go. Until both are set, the buttons don't work."),
                 bg=bg, fg=fg_dim, font=("Segoe UI", 9), justify="left",
                 wraplength=380).pack(anchor="w", pady=(4, 4))

        keep_var = tk.StringVar(value=st["keep"])
        reject_var = tk.StringVar(value=st["reject"])

        def folder_row(label, var):
            tk.Label(wrap, text=label, bg=bg, fg=fg_dim,
                     font=("Segoe UI", 8)).pack(anchor="w", pady=(12, 2))
            row = tk.Frame(wrap, bg=bg)
            row.pack(fill="x")

            def pick():
                dlg.grab_release()                 # let the native picker take over
                d = tkfd.askdirectory(
                    parent=dlg, title=label,
                    initialdir=var.get() or self.folder or os.path.expanduser("~"))
                dlg.grab_set()
                if d:
                    var.set(d)
            tintkit.Button(row, self.theme, t("Select"), role="neutral",
                           variant="outline", command=pick).pack(
                side="right", padx=(6, 0))
            tk.Entry(row, textvariable=var, bg=bar, fg=fg, insertbackground=fg,
                     relief="flat", font=("Segoe UI", 9), width=34).pack(
                         side="left", fill="x", expand=True, ipady=5)

        folder_row(t("✓ Keep (keeper) — photos you keep"), keep_var)
        folder_row(t("✗ Reject — photos you discard"), reject_var)

        def confirm():
            st["keep"] = keep_var.get().strip()
            st["reject"] = reject_var.get().strip()
            st["ok"] = True
            dlg.destroy()

        brow = tk.Frame(wrap, bg=bg)
        brow.pack(anchor="e", pady=(18, 0))
        tintkit.Button(brow, self.theme, t("Cancel"), role="neutral",
                       variant="outline", command=dlg.destroy).pack(
            side="right", padx=(8, 0))
        tintkit.Button(brow, self.theme, t("Save"), role="primary",
                       command=confirm).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: confirm())
        self._center_dialog(dlg)
        dlg.grab_set()
        dlg.focus_set()
        self.root.wait_window(dlg)

        if not st["ok"]:
            return
        self.cull_keep = st["keep"] or None
        self.cull_reject = st["reject"] or None
        self._save_state()
        if self._cull_ready():
            self.toast(t("Sorting folders saved"))
        else:
            self.toast(t("Folders incomplete — culling doesn't work yet"))

    def _move_current_to(self, dest):
        "Move the current file to `dest`, push an undo entry. Returns True on success."
        file = self.files[self.index]
        src = self.folder
        if not self._fs_move(file, src, dest):
            return False
        self._drop_from_list(file)
        self._push_undo({"kind": "move", "file": file, "src": src, "dest": dest})
        return True

    # --- File move primitives (shared by actions and undo/redo) -------------

    def _fs_move(self, file, src, dest):
        "Physically move one file from src folder to dest folder. Toasts on error."
        try:
            shutil.move(os.path.join(src, file), os.path.join(dest, file))
            return True
        except Exception as e:
            self.toast(t("Error: {e}").format(e=e))
            return False

    def _drop_from_list(self, file):
        "Remove `file` from the loaded list (if present) and refresh the view."
        if not self.folder or file not in self.files:
            return
        i = self.files.index(file)
        del self.files[i]
        if self.index >= len(self.files):
            self.index = max(0, len(self.files) - 1)
        self._build_thumbs()
        if self.files:
            self.show_current()
        else:
            self.load_folder(self.folder)

    def _add_to_list(self, file):
        "Insert `file` back into the loaded list (kept sorted) and select it."
        if not self.folder or file in self.files:
            return
        if not os.path.isfile(os.path.join(self.folder, file)):
            return
        self.files.append(file)
        self.files.sort()
        self.index = self.files.index(file)
        self._build_thumbs()
        self.show_current()

    # --- Undo / redo --------------------------------------------------------

    def _push_undo(self, cmd):
        "Record a new action; any pending redo history is discarded."
        self._undo_stack.append(cmd)
        self._redo_stack.clear()
        self._record_capture(cmd)   # feed the macro recorder if it is armed

    def undo(self):
        if not self._undo_stack:
            self.toast(t("Nothing to undo"))
            return
        cmd = self._undo_stack.pop()
        if self._revert(cmd):
            self._redo_stack.append(cmd)
        else:
            self._undo_stack.append(cmd)   # failed → leave history intact

    def redo(self):
        if not self._redo_stack:
            self.toast(t("Nothing to redo"))
            return
        cmd = self._redo_stack.pop()
        if self._reapply(cmd):
            self._undo_stack.append(cmd)
        else:
            self._redo_stack.append(cmd)

    def _revert(self, cmd):
        "Reverse one command. Returns True if it was applied."
        if cmd["kind"] == "move":
            if not self._fs_move(cmd["file"], cmd["dest"], cmd["src"]):
                return False
            if self.folder == cmd["src"]:
                self._add_to_list(cmd["file"])
            self.toast(t("Restored: {name}").format(name=cmd['file']))
            return True
        if cmd["kind"] == "edit":
            return self._apply_edit_state(cmd, cmd["before"])
        if cmd["kind"] == "heal":
            return self._apply_heal_patch(cmd, cmd["before"])
        if cmd["kind"] == "geometry":
            return self._apply_geometry_state(cmd, cmd["before"])
        return False

    def _reapply(self, cmd):
        "Re-do one previously undone command. Returns True if it was applied."
        if cmd["kind"] == "move":
            if self.folder == cmd["src"] and cmd["file"] in self.files:
                self.index = self.files.index(cmd["file"])
            if not self._fs_move(cmd["file"], cmd["src"], cmd["dest"]):
                return False
            if self.folder == cmd["src"]:
                self._drop_from_list(cmd["file"])
            self.toast(t("Moved: {name}").format(name=cmd['file']))
            return True
        if cmd["kind"] == "edit":
            return self._apply_edit_state(cmd, cmd["after"])
        if cmd["kind"] == "heal":
            return self._apply_heal_patch(cmd, cmd["after"])
        if cmd["kind"] == "geometry":
            return self._apply_geometry_state(cmd, cmd["after"])
        return False

    def _apply_edit_state(self, cmd, state):
        "Restore the four edit factors for the image a command belongs to."
        if cmd["folder"] != self.folder:
            self.toast(t("Can't undo the edit — a different folder is open"))
            return False
        if not self.files or cmd["file"] not in self.files:
            self.toast(t("Can't undo the edit — the file no longer exists"))
            return False
        if self.files[self.index] != cmd["file"]:
            self.index = self.files.index(cmd["file"])
            self.show_current()           # navigate; resets sliders to neutral
        for attr, val in state.items():
            setattr(self, attr, val)
            if attr in self.sliders:          # auto_mode / focus have no factor slider
                self.sliders[attr].set(round(val * 100))
        self._sync_focus_controls()           # focus has its own (non-factor) sliders
        self._sync_text_controls()            # text overlay has its own (non-factor) controls
        self._sync_logo_controls()            # logo overlay has its own (non-factor) controls
        self._recompute_auto()
        self._refresh_auto_buttons()
        self._render_preview()
        self._repaint_filter_strip()          # the active filter cell may have changed
        return True

    # --- Geometry undo (crop / straighten / rotate / mirror / resize /
    #     perspective) --------------------------------------------------------
    # These bake pixels into current_pil, so — unlike an 'edit' (live slider
    # factors) — they can't be reversed by restoring values. We snapshot the
    # whole pixel + overlay state before and after the op and swap it back on
    # undo / redo. Same-image only (like 'heal'): the baked pixels live only in
    # current_pil, which show_current() reloads from disk on navigation, so
    # there is nothing left to restore once a different photo is open.

    _GEOM_FLAGS = ("_rotated", "_mirrored", "_cropped", "_resized",
                   "_perspd", "_healed")

    def _geometry_snapshot(self):
        "Full copy of every field a geometry op mutates (pixels + overlays + flags)."
        return {
            "pil": self.current_pil.copy() if self.current_pil is not None else None,
            "before_pil": (self._before_pil.copy()
                           if self._before_pil is not None else None),
            "focus": dict(self.focus) if self.focus else None,
            "texts": [dict(ov) for ov in self.texts],
            "text_sel": self.text_sel,
            "logos": [dict(ov) for ov in self.logos],
            "logo_sel": self.logo_sel,
            "straighten": getattr(self, "straighten", 0.0),
            "persp_v": getattr(self, "persp_v", 0.0),
            "persp_h": getattr(self, "persp_h", 0.0),
            "flags": {k: getattr(self, k, False) for k in self._GEOM_FLAGS},
        }

    def _record_geometry(self, before):
        "Push one 'geometry' undo entry for a just-applied crop / rotate / resize / warp."
        if not self.files:
            return
        self._push_undo({"kind": "geometry", "folder": self.folder,
                         "file": self.files[self.index],
                         "before": before, "after": self._geometry_snapshot()})

    def _apply_geometry_state(self, cmd, state):
        "Swap the whole pixel + overlay state back in. Same-image only (like heal)."
        if cmd["folder"] != self.folder or not self.files \
                or self.files[self.index] != cmd["file"]:
            self.toast(t("Can't undo — a different image is open"))
            return False
        # Install copies, never the stored snapshot itself: a later in-place heal
        # dab must not mutate the buffer this command still needs for a redo.
        self.current_pil = (state["pil"].copy()
                            if state["pil"] is not None else None)
        self._before_pil = (state["before_pil"].copy()
                            if state["before_pil"] is not None else None)
        self._before_base_key = None
        self.focus = dict(state["focus"]) if state["focus"] else None
        self._focus_auto = False        # a restored focus is committed, not auto
        if hasattr(self, "_focus_cache"):
            self._focus_cache.clear()
        self.texts = [dict(ov) for ov in state["texts"]]
        self.text_sel = state["text_sel"]
        self.logos = [dict(ov) for ov in state.get("logos", [])]
        self.logo_sel = state.get("logo_sel")
        self._logo_drag = None
        self.straighten = state["straighten"]
        self.persp_v = state["persp_v"]
        self.persp_h = state["persp_h"]
        for k, v in state["flags"].items():
            setattr(self, k, v)
        if hasattr(self, "s_straighten"):
            try:
                self.s_straighten.set(round(self.straighten))
            except tk.TclError:
                pass
        for slider, val in (("s_persp_v", self.persp_v), ("s_persp_h", self.persp_h)):
            if hasattr(self, slider):
                try:
                    getattr(self, slider).set(round(val))
                except tk.TclError:
                    pass
        # The pending crop box referenced the old pixels — reset it to the
        # restored full image (or the tilt-fitted box if a straighten survives).
        if self.current_pil is not None:
            nw, nh = self.current_pil.size
            self.crop_rect = [0.0, 0.0, float(nw), float(nh)]
            self.crop_ratio = None
            if self.straighten:
                self._straighten_box()
        else:
            self.crop_ratio = None
        self._crop_btn_active = None
        self.clone_src = self.clone_offset = None
        self.fit_mode = True
        self.pan_x = self.pan_y = 0.0
        self._view_key = None
        self._edits_saved = False
        self._sync_focus_controls()
        self._sync_text_controls()
        self._sync_logo_controls()
        self._restyle_crop_chips()
        self._render_preview()
        self._update_info(os.path.join(self.folder, self.files[self.index]))
        self._refresh_filter_strip()
        return True
