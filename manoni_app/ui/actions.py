"""Actions (macros): record a sequence of edits once, replay it with one click.

An "action" is a recorded SCRIPT, not just a colour snapshot. While recording is
armed, every edit the user commits is captured as an ordered step:

  • {"op": "edit",  "state": {sliders/effects + auto_mode + relative focus}}
  • {"op": "crop",  "box": [fx0, fy0, fx1, fy1]}   (fractions of the image)

Runs of slider/effect/focus tweaks coalesce into one "edit" step (only the final
values matter for a live, non-destructive pass), while each crop stays its own
ordered step (cropping bakes pixels, so order vs. the live edits matters). The
recorder hooks two commit points: _push_undo (every "edit" command) and
apply_crop. New destructive tools added later just record their own step type.

Everything is stored RESOLUTION-INDEPENDENT — crop boxes and focus geometry are
fractions of the image — so an action recorded on one photo replays correctly on
another of any size. Playback applies to the currently open photo only.

Mixin on the Manoni window — every method uses the shared `self`, so behaviour
is identical to when it lived directly on the class.
"""

import os
import json
import tkinter as tk
import tkinter.filedialog as tkfd

from PIL import Image
import tintkit

from ..config import EDIT_PAD
from .. import imaging
from ..i18n import t


class ActionsMixin:
    # FILTER_KEYS / AUTO_MODES come from FiltersMixin (same class) — an edit step
    # stores exactly those factors plus a relative focus, mirroring _edit_state().

    # --- Store (persisted to ACTIONS_FILE) ----------------------------------

    def _load_actions(self):
        "Read saved actions from ACTIONS_FILE into self.user_actions."
        from ..config import ACTIONS_FILE
        self.user_actions = []
        try:
            with open(ACTIONS_FILE, encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception:
            return
        self.user_actions = self._coerce_action_list(data)

    def _save_actions(self):
        "Write self.user_actions back to ACTIONS_FILE (atomic; warns on failure)."
        from ..config import ACTIONS_FILE
        from ..storage import save_json
        if not save_json(ACTIONS_FILE, {"manoni_actions": 1,
                                        "actions": self.user_actions}):
            self.toast(t("Could not save actions"))

    def _coerce_action_list(self, data):
        "Accept a {actions:[…]} bundle or a bare list → clean [{name, steps}]."
        raw = []
        if isinstance(data, dict) and isinstance(data.get("actions"), list):
            raw = data["actions"]
        elif isinstance(data, list):
            raw = data
        out = []
        for it in raw:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            steps = self._sanitize_steps(it.get("steps"))
            if name and steps:
                out.append({"name": name, "steps": steps})
        return out

    def _sanitize_steps(self, steps):
        "Keep only well-formed crop / edit steps (so a hand-edited file is safe)."
        if not isinstance(steps, list):
            return []
        out = []
        for st in steps:
            if not isinstance(st, dict):
                continue
            if st.get("op") == "crop":
                box = st.get("box")
                if isinstance(box, list) and len(box) == 4:
                    try:
                        out.append({"op": "crop", "box": [float(v) for v in box]})
                    except (TypeError, ValueError):
                        pass
            elif st.get("op") == "edit":
                state = self._sanitize_step_state(st.get("state"))
                if state is not None:
                    out.append({"op": "edit", "state": state})
        return out

    def _sanitize_step_state(self, state):
        "Clean an edit step's state: known factors + a valid auto_mode + rel focus."
        if not isinstance(state, dict):
            return None
        clean = {}
        for k in self.FILTER_KEYS:
            if k in state:
                try:
                    clean[k] = float(state[k])
                except (TypeError, ValueError):
                    pass
        am = state.get("auto_mode")
        clean["auto_mode"] = am if am in self.AUTO_MODES else None
        clean["focus"] = self._sanitize_rel_focus(state.get("focus"))
        return clean

    def _sanitize_rel_focus(self, rel):
        "Validate a relative-focus dict; None if absent / malformed."
        if not isinstance(rel, dict):
            return None
        shape = rel.get("shape")
        if shape not in ("circle", "line"):
            return None
        try:
            out = {"shape": shape,
                   "cx": float(rel["cx"]), "cy": float(rel["cy"]),
                   "blur": float(rel.get("blur", 0.0)),
                   "feather": float(rel.get("feather", 0.4))}
            if shape == "line":
                out["angle"] = float(rel.get("angle", 0.0))
                out["width"] = float(rel.get("width", 0.0))
            else:
                out["r"] = float(rel.get("r", 0.0))
        except (TypeError, ValueError, KeyError):
            return None
        return out

    def _unique_action_name(self, base):
        "A name not already taken: 'Name', then 'Name 2', 'Name 3', …"
        names = {a["name"] for a in self.user_actions}
        if base not in names:
            return base
        i = 2
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    # --- Relative <-> absolute focus ----------------------------------------

    def _focus_to_rel(self, focus):
        "Absolute (source-px) focus → fractions of the current image, or None."
        if not focus or self.current_pil is None:
            return None
        iw, ih = self.current_pil.size
        m = float(min(iw, ih)) or 1.0
        rel = {"shape": focus.get("shape", "circle"),
               "cx": focus["cx"] / iw, "cy": focus["cy"] / ih,
               "blur": focus.get("blur", 0.0),
               "feather": focus.get("feather", 0.4)}
        if rel["shape"] == "line":
            rel["angle"] = focus.get("angle", 0.0)
            rel["width"] = focus.get("width", 0.0) / m
        else:
            rel["r"] = focus.get("r", 0.0) / m
        return rel

    def _focus_from_rel(self, rel):
        "Relative focus → absolute (source-px) for the current image, or None."
        if self.current_pil is None:
            return None
        iw, ih = self.current_pil.size
        return self._focus_from_rel_size(rel, iw, ih)

    def _focus_from_rel_size(self, rel, iw, ih):
        "Relative focus → absolute (source-px) for an iw×ih image, or None."
        if not rel:
            return None
        m = float(min(iw, ih))
        f = {"shape": rel.get("shape", "circle"),
             "cx": rel["cx"] * iw, "cy": rel["cy"] * ih,
             "blur": rel.get("blur", 0.0),
             "feather": rel.get("feather", 0.4)}
        if f["shape"] == "line":
            f["angle"] = rel.get("angle", 0.0)
            f["width"] = rel.get("width", 0.0) * m
        else:
            f["r"] = rel.get("r", 0.0) * m
        return f

    # --- Recording ----------------------------------------------------------

    def _record_capture(self, cmd):
        "Feed one undo command into the recorder if armed (called from _push_undo)."
        if not getattr(self, "_recording", False):
            return
        if cmd.get("kind") == "edit":
            self._record_edit_step(cmd.get("after"))
        # 'heal' is pixel-specific (can't replay on another photo) → not recorded.

    def _record_edit_step(self, state):
        "Append (or coalesce) an 'edit' step from a live-state snapshot."
        if not isinstance(state, dict):
            return
        snap = {k: state[k] for k in self.FILTER_KEYS if k in state}
        snap["auto_mode"] = state.get("auto_mode")
        snap["focus"] = self._focus_to_rel(state.get("focus"))
        if self._record_steps and self._record_steps[-1]["op"] == "edit":
            self._record_steps[-1]["state"] = snap   # only final values matter
        else:
            self._record_steps.append({"op": "edit", "state": snap})
        self._refresh_action_recorder()

    def _record_crop_step(self, box, iw, ih):
        "Append a 'crop' step (absolute box → fractions of the pre-crop image)."
        x0, y0, x1, y1 = box
        self._record_steps.append(
            {"op": "crop", "box": [x0 / iw, y0 / ih, x1 / iw, y1 / ih]})
        self._refresh_action_recorder()

    def _toggle_recording(self):
        "Record/Stop button: arm the recorder, or stop and save what was captured."
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        "Arm the recorder: from now on, committed edits/crops become steps."
        self._recording = True
        self._record_steps = []
        self._refresh_action_recorder()
        self.toast(t("Recording… do your edits, then press Stop"))

    def _stop_recording(self):
        "Stop recording; if anything was captured, name it and save the action."
        self._recording = False
        steps = self._record_steps
        self._record_steps = []
        self._refresh_action_recorder()
        if not steps:
            self.toast(t("Nothing was recorded"))
            return
        default = self._unique_action_name(t("My action"))
        name = self._ask_action_name(t("New action"), default)
        if name is None:
            return
        name = self._unique_action_name(name)
        self.user_actions.append({"name": name, "steps": steps})
        self._save_actions()
        self._refresh_action_list()
        self.toast(t("Action saved: {name}").format(name=name))

    # --- Playback (current photo only) --------------------------------------

    def _play_action(self, action):
        "Replay an action's steps onto the open photo, in recorded order."
        if self.current_pil is None or not self.files:
            self.toast(t("Open an image first"))
            return
        if self._recording:
            self.toast(t("Stop recording first"))
            return
        before = self._edit_state()
        self._playing = True
        try:
            for step in action.get("steps", []):
                if step["op"] == "crop":
                    self._play_crop_step(step["box"])
                elif step["op"] == "edit":
                    self._play_edit_step(step["state"])
        finally:
            self._playing = False
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)   # one undo entry for the live edits
        self.toast(t("Action applied: {name}").format(name=action["name"]))

    def _play_crop_step(self, rel):
        "Apply a relative crop box to the current image (bakes, like the tool)."
        if self.current_pil is None:
            return
        iw, ih = self.current_pil.size
        x0, y0, x1, y1 = rel
        self.crop_rect = [x0 * iw, y0 * ih, x1 * iw, y1 * ih]
        self.crop_ratio = None
        self.apply_crop()   # quiet during playback (see crop._playing guard)

    def _play_edit_step(self, state):
        "Set the live edit factors + focus from a (relative) edit step."
        for k in self.FILTER_KEYS:
            if k in state:
                setattr(self, k, state[k])
                if k in self.sliders:
                    self.sliders[k].set(round(state[k] * 100))
        am = state.get("auto_mode")
        self.auto_mode = am if am in self.AUTO_MODES else None
        self.focus = self._focus_from_rel(state.get("focus"))
        self._sync_focus_controls()
        self._recompute_auto()
        self._refresh_auto_buttons()

    # --- Batch: apply an action to every photo in the folder ----------------

    def _resolve_action(self, action):
        """Flatten an action into (crop boxes in order, final live-edit state).

        Only the LAST edit step's values survive (each edit step overwrites all
        factors), and a crop after that edit clears its focus — exactly how the
        interactive replay composes. Returns (crops, live | None)."""
        crops, live = [], None
        for step in action.get("steps", []):
            if step["op"] == "crop":
                crops.append(step["box"])
                if live is not None and live.get("focus") is not None:
                    live = {**live, "focus": None}   # crop clears focus, like the app
            elif step["op"] == "edit":
                live = dict(step["state"])
        return crops, live

    def _apply_action_to_image(self, img, crops, live):
        "Apply resolved crops + live edits to a PIL image → a new RGB image."
        for rel in crops:
            iw, ih = img.size
            x0, y0 = max(0, round(rel[0] * iw)), max(0, round(rel[1] * ih))
            x1, y1 = min(iw, round(rel[2] * iw)), min(ih, round(rel[3] * ih))
            if x1 - x0 < 2 or y1 - y0 < 2 or (x0, y0, x1, y1) == (0, 0, iw, ih):
                continue                              # degenerate / full-frame → skip
            img = img.crop((x0, y0, x1, y1))
        img = img.convert("RGB")
        if live is not None:
            focus = self._focus_from_rel_size(live.get("focus"), *img.size)
            kw = {k: live[k] for k in self.FILTER_KEYS if k in live}
            e = imaging.Edits(focus=focus, **kw)
            luts = None
            am = live.get("auto_mode")
            if am in ("levels", "contrast"):
                luts = imaging.autocontrast_luts(img, am == "levels")
            img = imaging.apply_edits(img, e, auto_luts=luts)
        return img

    def _play_action_folder(self, action):
        "Apply an action to every photo in the open folder, saving each result."
        if self._recording:
            self.toast(t("Stop recording first"))
            return
        if not self.files or not self.folder:
            self.toast(t("Open a folder first"))
            return
        cfg = self._ask_batch_config(len(self.files))
        if cfg is None:
            return
        try:
            os.makedirs(cfg["dir"], exist_ok=True)
        except OSError:
            self.toast(t("Could not create the output folder"))
            return
        from ..storage import unique_path
        crops, live = self._resolve_action(action)
        ext = self.FMT_EXT[cfg["fmt"]]
        total, ok, fail = len(self.files), 0, 0
        for i, fname in enumerate(self.files):
            self.toast(t("Applying to folder… {i}/{n}").format(i=i + 1, n=total))
            self.root.update()                        # show progress, stay responsive
            try:
                with Image.open(os.path.join(self.folder, fname)) as im:
                    im.load()
                    out = self._apply_action_to_image(im, crops, live)
                # Don't let two sources (e.g. a.jpg + a.png → a.jpg) or a re-run
                # silently overwrite each other — number a clashing name instead.
                dest = unique_path(os.path.join(cfg["dir"],
                                                os.path.splitext(fname)[0] + ext))
                if cfg["fmt"] == "PNG":
                    out.save(dest, "PNG")
                else:
                    out.save(dest, cfg["fmt"], quality=int(cfg["quality"]))
                ok += 1
            except Exception:
                fail += 1
        self.toast(t("Done — {ok} saved, {fail} failed  ·  {dir}").format(
            ok=ok, fail=fail, dir=os.path.basename(cfg["dir"]) or cfg["dir"]))

    def _ask_batch_config(self, n, title=None, intro=None, default_dir=None):
        "Dialog: output folder + format + quality for a folder batch. None = cancel."
        seed = self.quick_save_cfg or self.last_save or {}
        default_dir = default_dir or os.path.join(self.folder, "_actions")
        title = title or t("Apply to whole folder")
        intro = intro or t("Apply this action to all {n} photos and save copies.").format(n=n)
        st = {"dir": default_dir,
              "fmt": seed.get("fmt") or "JPEG",
              "quality": int(seed.get("quality", 95)), "ok": False}

        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        self._tw(dlg, bg="bg")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = self._tw(tk.Frame(dlg, padx=22, pady=16), bg="bg")
        wrap.pack(fill="both", expand=True)

        self._tw(tk.Label(wrap, text=intro,
                 font=("Segoe UI", 10, "bold"),
                 wraplength=320, justify="left"), bg="bg", fg="fg").pack(
                     anchor="w", pady=(0, 10))

        def heading(text):
            self._tw(tk.Label(wrap, text=text, font=("Segoe UI", 8)),
                     bg="bg", fg="fg_dim").pack(anchor="w", pady=(8, 2))

        # Output folder + browse.
        heading(t("Output folder"))
        dir_var = tk.StringVar(value=st["dir"])

        def pick_dir():
            dlg.grab_release()
            d = tkfd.askdirectory(parent=dlg, title=t("Choose a folder"),
                                  initialdir=self.folder)
            dlg.grab_set()
            if d:
                dir_var.set(d)

        frow = self._tw(tk.Frame(wrap), bg="bg")
        frow.pack(fill="x")
        tintkit.Button(frow, self.theme, t("Select"), role="neutral",
                       variant="outline", command=pick_dir, bg="bg").pack(
                           side="right", padx=(6, 0))
        dir_field = tintkit.TextField(frow, self.theme, bg="bg")
        dir_field.entry.configure(textvariable=dir_var)
        dir_field.pack(side="left", fill="x", expand=True)

        # Quality (lossy only) — built before format so format can show/hide it.
        q_opts = (80, 90, 95, 100)
        qbox = self._tw(tk.Frame(wrap), bg="bg")
        self._tw(tk.Label(qbox, text=t("Quality"), font=("Segoe UI", 8)),
                 bg="bg", fg="fg_dim").pack(anchor="w", pady=(8, 2))
        st["quality"] = min(q_opts, key=lambda q: abs(q - st["quality"]))

        def pick_q(i, _label):
            st["quality"] = q_opts[i]
        tintkit.SegmentedTabs(qbox, self.theme, [str(q) for q in q_opts],
                              selected=q_opts.index(st["quality"]),
                              command=pick_q, bg="bg").pack(anchor="w")

        # Format drives the quality visibility.
        heading(t("Format"))
        fmt_row = self._tw(tk.Frame(wrap), bg="bg")
        fmt_row.pack(anchor="w")
        fmt_opts = ("JPEG", "PNG", "WEBP")

        def apply_fmt(f):
            st["fmt"] = f
            if f == "PNG":
                qbox.pack_forget()             # PNG is lossless — no quality
            else:
                qbox.pack(fill="x", anchor="w")
        tintkit.SegmentedTabs(fmt_row, self.theme, list(fmt_opts),
                              selected=fmt_opts.index(st["fmt"]),
                              command=lambda i, label: apply_fmt(label),
                              bg="bg").pack(anchor="w")
        apply_fmt(st["fmt"])                    # initial quality visibility

        def confirm():
            st["dir"] = dir_var.get().strip() or default_dir
            st["ok"] = True
            dlg.destroy()

        brow = self._tw(tk.Frame(wrap), bg="bg")
        brow.pack(anchor="e", pady=(16, 0))
        tintkit.Button(brow, self.theme, t("Cancel"), role="neutral",
                       variant="outline", command=dlg.destroy, bg="bg").pack(
                           side="right", padx=(8, 0))
        tintkit.Button(brow, self.theme, t("Apply"), role="primary",
                       variant="filled", command=confirm, bg="bg").pack(
                           side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: confirm())
        self._place_filter_dialog(dlg)
        if not st["ok"]:
            return None
        return {"dir": st["dir"], "fmt": st["fmt"], "quality": st["quality"]}

    # --- The panel (shown in the edit panel's "actions" section) -------------

    def _build_actions_section(self, parent):
        "Actions panel: a Record/Stop toggle + the list of saved actions to play."
        f = self._tw(tk.Frame(parent), bg="bar")

        self._tw(tk.Label(f, text=t("Record your edits as an action, then play it on any open photo."),
                 anchor="w", justify="left",
                 font=("Segoe UI", 8), wraplength=self._edit_dpi_w(210)),
                 bg="bar", fg="fg_dim").pack(fill="x", padx=EDIT_PAD, pady=(12, 6))

        # Record / Stop toggle: a real Button that flips to danger-red (Stop)
        # while the recorder is armed (see _refresh_action_recorder).
        self._rec_btn = tintkit.Button(
            f, self.theme, t("Record action"), role="neutral", variant="filled",
            icon="circle-dot", stretch=True, bg="bar",
            command=self._toggle_recording)
        self._rec_btn.pack(fill="x", padx=EDIT_PAD, pady=(2, 2))

        self._rec_status = self._tw(tk.Label(f, text="", anchor="w",
                                    font=("Segoe UI", 8)), bg="bar", fg="fg_dim")
        self._rec_status.pack(fill="x", padx=EDIT_PAD, pady=(0, 6))

        self._tw(tk.Frame(f, height=1), bg="divider").pack(
            fill="x", padx=EDIT_PAD, pady=(4, 8))

        self._lbl_action_count = self._tw(tk.Label(f, text="", anchor="w",
                                          font=("Segoe UI", 8, "bold")), bg="bar", fg="fg")
        self._lbl_action_count.pack(fill="x", padx=EDIT_PAD, pady=(0, 4))

        self._actions_list = self._tw(tk.Frame(f), bg="bar")
        self._actions_list.pack(fill="x", padx=EDIT_PAD)

        # Footer: Done just closes the tool. Actions are a manager — nothing to
        # apply or reset at the panel level; saved actions persist on their own.
        done = tintkit.Button(
            f, self.theme, t("Done"), role="primary", variant="filled",
            stretch=True, bg="bar", command=lambda: self.set_section("basic"))
        done.pack(fill="x", padx=EDIT_PAD, pady=(14, 8))

        self._refresh_action_recorder()
        self._refresh_action_list()
        return f

    def _enter_actions(self):
        "Open the actions tool: refresh the button/list, repaint without overlay."
        self._refresh_action_recorder()
        self._refresh_action_list()
        self.preview.configure(cursor="")
        self._render_preview()

    def _refresh_action_recorder(self):
        "Repaint the Record/Stop button + step counter for the current state."
        if not hasattr(self, "_rec_btn"):
            return
        b = self._rec_btn
        if self._recording:
            b.role, b.label, b.icon_name = "danger", t("Stop recording"), "circle-stop"
            self._rec_status.configure(
                text=t("Recording… {n} step(s)").format(n=len(self._record_steps)))
        else:
            b.role, b.label, b.icon_name = "neutral", t("Record action"), "circle-dot"
            self._rec_status.configure(text="")
        b.repaint()

    def _refresh_action_list(self):
        "Rebuild the saved-actions rows from self.user_actions."
        if not hasattr(self, "_actions_list"):
            return
        self._lbl_action_count.configure(
            text=t("Saved actions: {n}").format(n=len(self.user_actions)))
        for w in self._actions_list.winfo_children():
            w.destroy()
        if not self.user_actions:
            self._tw(tk.Label(self._actions_list, text=t("No actions yet"),
                     font=("Segoe UI", 8), anchor="w"), bg="bar", fg="fg_dim") \
                .pack(fill="x", pady=(2, 4))
            return
        for act in list(self.user_actions):
            self._action_row(act)

    def _action_row(self, act):
        "One saved action: a play area (icon + name) + rename / delete icons."
        row = self._tw(tk.Frame(self._actions_list, cursor="hand2"), bg="chip")
        row.pack(fill="x", pady=2)
        pimg = self.icon("circle-play", size=16)
        if pimg is not None:
            pic = self._tw(tk.Label(row, image=pimg), bg="chip")   # bg follows theme
            self._reg_icon(pic, "circle-play", size=16, token="fg")  # image re-tints
        else:
            pic = self._tw(tk.Label(row, text="▶"), bg="chip", fg="accent")
        pic.pack(side="left", padx=(8, 8), pady=7)
        nm = self._tw(tk.Label(row, text=act["name"], anchor="w",
                      font=("Segoe UI", 9)), bg="chip", fg="fg")
        nm.pack(side="left", fill="x", expand=True)
        # batch / rename / delete on the right (own clicks; don't trigger play)
        self._action_icon(row, "trash-2", lambda: self._delete_action(act),
                          t("Delete"))
        self._action_icon(row, "pencil", lambda: self._rename_action(act),
                          t("Rename"))
        self._action_icon(row, "folder-output",
                          lambda: self._play_action_folder(act),
                          t("Apply to the whole folder"))
        play_parts = (row, pic, nm)
        for w in play_parts:
            w.bind("<Button-1>", lambda e, a=act: self._play_action(a))
            w.bind("<Enter>", lambda e: [p.configure(bg=self.theme["hover"]) for p in play_parts])
            w.bind("<Leave>", lambda e: [p.configure(bg=self.theme["chip"]) for p in play_parts])
        pic._tip = tintkit.HoverTip(pic, self.theme, t("Play this action"))

    def _action_icon(self, parent, icon_name, command, tip):
        "A small tintkit icon button on a saved-action row (bg matches the row)."
        b = tintkit.IconButton(parent, self.theme, icon_name, w=26, h=26,
                               icon_px=15, bg="chip", command=command)
        b.pack(side="right", padx=(0, 8))
        b._tip = tintkit.HoverTip(b.canvas, self.theme, tip)
        return b

    def _rename_action(self, act):
        "Prompt for a new name and rename the action in place."
        new = self._ask_action_name(t("Rename"), act["name"])
        if new and new != act["name"]:
            act["name"] = self._unique_action_name(new)
            self._save_actions()
            self._refresh_action_list()

    def _delete_action(self, act):
        "Remove a saved action."
        if act in self.user_actions:
            self.user_actions.remove(act)
            self._save_actions()
            self._refresh_action_list()

    # --- Name prompt (mirrors the filters one, with action wording) ---------

    def _ask_action_name(self, title, default=""):
        "Modal dark prompt for an action name. Returns the trimmed text or None."
        result = {"val": None}
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        self._tw(dlg, bg="bg")
        dlg.transient(self.root)
        dlg.resizable(False, False)

        wrap = self._tw(tk.Frame(dlg, padx=22, pady=18), bg="bg")
        wrap.pack(fill="both", expand=True)
        self._tw(tk.Label(wrap, text=t("Action name"),
                 font=("Segoe UI", 11, "bold")), bg="bg", fg="fg").pack(
                     anchor="w", pady=(0, 8))

        e = self._tw(tk.Entry(wrap, width=24, relief="flat",
                     font=("Segoe UI", 11)), bg="bar", fg="fg", insert="fg")
        e.insert(0, default)
        e.pack(anchor="w", ipady=5, fill="x")

        def confirm():
            txt = e.get().strip()
            if txt:
                result["val"] = txt
            dlg.destroy()

        btnrow = self._tw(tk.Frame(wrap), bg="bg")
        btnrow.pack(anchor="e", pady=(16, 0))
        tintkit.Button(btnrow, self.theme, t("Cancel"), role="neutral",
                       variant="outline", command=dlg.destroy, bg="bg").pack(
                           side="right", padx=(8, 0))
        tintkit.Button(btnrow, self.theme, t("Save"), role="primary",
                       variant="filled", command=confirm, bg="bg").pack(side="right")

        dlg.bind("<Return>", lambda e: confirm())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        e.focus_set()
        e.select_range(0, "end")
        self._place_filter_dialog(dlg)
        return result["val"]
