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

from ..config import BG, BAR, FG, FG_DIM
from ..i18n import t
from .dialogs import make_dialog_button, center_over


class NavMixin:
    # --- Navigation ---------------------------------------------------------

    def go_to(self, index):
        if not (0 <= index < len(self.files)) or index == self.index:
            return
        if not self._maybe_prompt_save():
            return                       # user chose to stay on the edited photo
        self.index = index
        self.show_current()

    # --- Unsaved-edit guard (offer to save a copy before leaving a photo) ----

    def _has_unsaved_edits(self):
        "True if the current photo has edits (sliders or rotation) not yet saved to a copy."
        if self.current_pil is None or self._edits_saved:
            return False
        return (self._rotated or self._cropped or self._resized or self._healed
                or any(v != self._slider_neutral(k)
                       for k, v in self._edit_state().items()))

    def _maybe_prompt_save(self):
        "Before leaving an edited photo, offer to save a copy. Returns False to stay."
        if not self._has_unsaved_edits():
            return True
        choice = self._ask_save_copy()
        if choice == "cancel":
            return False
        if choice == "save":
            return self.quick_save()     # quick-save logic (opens dialog if unarmed)
        return True                      # 'discard' → leave; live edits are dropped

    def _ask_save_copy(self):
        """Modal dark dialog shown when leaving a photo that has unsaved edits.

        Offers to save an edited copy (into _edited), discard the edits, or stay
        on the photo. Returns 'save', 'discard', or 'cancel'.
        """
        result = {"choice": "cancel"}
        dlg = tk.Toplevel(self.root)
        dlg.title(t("Save?"))
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        def choose(c):
            result["choice"] = c
            dlg.destroy()

        wrap = tk.Frame(dlg, bg=BG, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=t("The image has changed"), bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        fname = self.files[self.index] if self.files else ""
        tk.Label(wrap, text=t("{fname} — save a copy to _edited?").format(fname=fname), bg=BG,
                 fg=FG_DIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 16))

        row = tk.Frame(wrap, bg=BG)
        row.pack(anchor="e")
        make_dialog_button(row, t("Cancel"), lambda: choose("cancel")).pack(
            side="right", padx=(8, 0))
        make_dialog_button(row, t("Don't save"), lambda: choose("discard")).pack(
            side="right", padx=(8, 0))
        make_dialog_button(row, t("Save"), lambda: choose("save"),
                           primary=True).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))
        dlg.bind("<Escape>", lambda e: choose("cancel"))
        dlg.bind("<Return>", lambda e: choose("save"))

        # Center the dialog over the main window.
        dlg.update_idletasks()
        w, h = dlg.winfo_width(), dlg.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        dlg.geometry(f"+{max(0, rx + (rw - w) // 2)}+{max(0, ry + (rh - h) // 2)}")

        dlg.grab_set()
        dlg.focus_set()
        self.root.wait_window(dlg)
        return result["choice"]

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
        """True when the arrow shortcuts may act: a photo is shown, the edit
        panel is closed, and no text field is focused. (Modal dialogs grab the
        keyboard, so an open dialog never reaches these handlers anyway.)"""
        if self.panel_open or not self.files:
            return False
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text)):
            return False
        return True

    def _arrow_prev(self):
        "← previous photo; at the first one, report the folder edge."
        if not self._browse_keys_active():
            return
        if self.index > 0:
            self.go_to(self.index - 1)
        else:
            self._folder_edge(-1)

    def _arrow_next(self):
        "→ next photo; at the last one, report the folder edge."
        if not self._browse_keys_active():
            return
        if self.index < len(self.files) - 1:
            self.go_to(self.index + 1)
        else:
            self._folder_edge(1)

    def _folder_edge(self, direction):
        """Reached the first (-1) / last (+1) photo of the folder.

        TODO (planned, see Settings): when a "continue into the adjacent folder"
        option is enabled, load the previous/next sibling folder and select its
        last/first photo instead of toasting. Until that option exists we only
        report the edge.
        """
        self.toast(t("End of the folder") if direction > 0
                   else t("Start of the folder"))

    def _arrow_keep(self):
        "↑ sort the current photo into the keep (good) folder."
        if self._browse_keys_active():
            self.move_to_folder()

    def _arrow_reject(self):
        "↓ sort the current photo into the reject (bad) folder."
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
        os.makedirs(self.cull_keep, exist_ok=True)
        if self._move_current_to(self.cull_keep):
            self.toast(t("Kept → {name}  ·  Ctrl+Z").format(
                name=os.path.basename(self.cull_keep)))

    def delete(self):
        "Reject: move the current photo into the configured ✗ reject folder."
        if not self._require_cull():
            return
        os.makedirs(self.cull_reject, exist_ok=True)
        if self._move_current_to(self.cull_reject):
            self.toast(t("Rejected → {name}  ·  Ctrl+Z").format(
                name=os.path.basename(self.cull_reject)))

    # --- Cull configuration + help dialogs ----------------------------------

    def _center_dialog(self, dlg):
        "Place a Toplevel centered over the main window."
        center_over(self.root, dlg)

    def _cull_options_dialog(self):
        "Configure the two sort folders (keep + reject) used by the cull buttons."
        st = {"keep": self.cull_keep or "", "reject": self.cull_reject or "",
              "ok": False}

        dlg = tk.Toplevel(self.root)
        dlg.title(t("Sorting folders"))
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = tk.Frame(dlg, bg=BG, padx=22, pady=18)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text=t("Sorting folders"), bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(wrap, text=t("Set where kept and rejected photos go. Until both are set, the buttons don't work."),
                 bg=BG, fg=FG_DIM, font=("Segoe UI", 9), justify="left",
                 wraplength=380).pack(anchor="w", pady=(4, 4))

        keep_var = tk.StringVar(value=st["keep"])
        reject_var = tk.StringVar(value=st["reject"])

        def folder_row(label, var):
            tk.Label(wrap, text=label, bg=BG, fg=FG_DIM,
                     font=("Segoe UI", 8)).pack(anchor="w", pady=(12, 2))
            row = tk.Frame(wrap, bg=BG)
            row.pack(fill="x")

            def pick():
                dlg.grab_release()                 # let the native picker take over
                d = tkfd.askdirectory(
                    parent=dlg, title=label,
                    initialdir=var.get() or self.folder or os.path.expanduser("~"))
                dlg.grab_set()
                if d:
                    var.set(d)
            make_dialog_button(row, t("Select"), pick).pack(side="right",
                                                            padx=(6, 0))
            tk.Entry(row, textvariable=var, bg=BAR, fg=FG, insertbackground=FG,
                     relief="flat", font=("Segoe UI", 9), width=34).pack(
                         side="left", fill="x", expand=True, ipady=5)

        folder_row(t("✓ Keep (keeper) — photos you keep"), keep_var)
        folder_row(t("✗ Reject — photos you discard"), reject_var)

        def confirm():
            st["keep"] = keep_var.get().strip()
            st["reject"] = reject_var.get().strip()
            st["ok"] = True
            dlg.destroy()

        brow = tk.Frame(wrap, bg=BG)
        brow.pack(anchor="e", pady=(18, 0))
        make_dialog_button(brow, t("Cancel"), dlg.destroy).pack(
            side="right", padx=(8, 0))
        make_dialog_button(brow, t("Save"), confirm, primary=True).pack(
            side="right")

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

    def _cull_help_dialog(self):
        "Explain the cull workflow: what keep / reject / options do."
        dlg = tk.Toplevel(self.root)
        dlg.title(t("Culling — Help"))
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = tk.Frame(dlg, bg=BG, padx=24, pady=20)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text=t("Culling photos"), bg=BG, fg=FG,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(wrap, text=t("You browse the photos and sort each into two folders — keep and discard."), bg=BG, fg=FG_DIM,
                 font=("Segoe UI", 9), justify="left",
                 wraplength=360).pack(anchor="w", pady=(0, 12))

        rows = [
            ("folder-check", "Keep (keeper)",
             "Moves the current photo to the keep folder."),
            ("folder-x",     "Reject",
             "Moves the current photo to the discard folder."),
            ("settings",     "Settings",
             "Set these two folders — until you do, the buttons don't work."),
        ]
        for icon_name, title, desc in rows:
            r = tk.Frame(wrap, bg=BG)
            r.pack(fill="x", pady=6)
            img = self.icon(icon_name)
            if img is not None:
                tk.Label(r, image=img, bg=BG).pack(side="left", padx=(0, 10))
            col = tk.Frame(r, bg=BG)
            col.pack(side="left", fill="x", expand=True)
            tk.Label(col, text=t(title), bg=BG, fg=FG, anchor="w",
                     font=("Segoe UI", 10, "bold")).pack(anchor="w")
            tk.Label(col, text=t(desc), bg=BG, fg=FG_DIM, anchor="w",
                     font=("Segoe UI", 9), justify="left",
                     wraplength=300).pack(anchor="w")

        tk.Label(wrap, text=t("Ctrl+Z undoes any move."), bg=BG,
                 fg=FG_DIM, font=("Segoe UI", 9)).pack(anchor="w", pady=(12, 0))

        brow = tk.Frame(wrap, bg=BG)
        brow.pack(anchor="e", pady=(16, 0))
        make_dialog_button(brow, t("Got it"), dlg.destroy,
                           primary=True).pack(side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: dlg.destroy())
        self._center_dialog(dlg)
        dlg.grab_set()
        dlg.focus_set()
        self.root.wait_window(dlg)

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
        self._recompute_auto()
        self._refresh_auto_buttons()
        self._render_preview()
        self._repaint_filter_strip()          # the active filter cell may have changed
        return True
