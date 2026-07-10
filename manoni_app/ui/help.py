"""Help: a tabbed help window (the "?" button in the top bar).

The same shell as Settings — a header bar, a `tintkit.SettingsWindow` (the kit's
left tab rail + scrollable pane), then a small footer (Done) — but its pages are
short, illustrated explanations instead of controls. One tab per part of the
app: Getting started · Culling · Keyboard · Editing · Filters · Actions ·
Save & Export.

Each page is built from two helpers that read the live theme, so the whole
window switches dark<->light like the rest of the UI:
  * ``_help_row``     — a tinted tool icon + bold title + one dim sentence.
  * ``_help_key_row`` — a key-cap chip + one dim sentence (the shortcut lists).

The tool icons deliberately match the edit rail's glyphs (basic =
sliders-horizontal, crop = crop, …) so the help points at the same pictures the
user clicks. Mixin on the Manoni window — every method uses the shared `self`,
like the other ui mixins.
"""

import tkinter as tk

import tintkit

from ..i18n import t


# --- tab spec: (key, label-source, rail-icon, builder-method-name) -----------
# Labels are translated where the tabs are built (so a language switch retexts).
# Rail icons come from Manoni's own icon set (handed to the kit as icon_loader).
_HELP_TABS = [
    ("start",   "Getting started", "image",             "_help_tab_start"),
    ("cull",    "Culling",         "folder-check",      "_help_tab_cull"),
    ("keys",    "Keyboard",        "arrow-left-right",  "_help_tab_keys"),
    ("edit",    "Editing",         "sliders-horizontal", "_help_tab_edit"),
    ("filters", "Filters",         "blend",             "_help_tab_filters"),
    ("actions", "Actions",         "circle-play",       "_help_tab_actions"),
    ("export",  "Save & Export",   "upload",            "_help_tab_export"),
]


class HelpMixin:
    # --- window -------------------------------------------------------------

    def _help_dialog(self):
        "Open the tabbed Help window (or re-focus it if already open)."
        win = getattr(self, "_help_win", None)
        if win is not None:
            try:
                win.deiconify()
                win.lift()
                win.focus_force()
                return
            except tk.TclError:
                self._help_win = None

        dlg = self._tw(tk.Toplevel(self.root), bg="bg")
        dlg.title(t("Help"))
        dlg.transient(self.root)
        self._help_win = dlg

        dlg.rowconfigure(1, weight=1)
        dlg.columnconfigure(0, weight=1)

        self._help_build_header(dlg)
        self._help_build_body(dlg)
        self._help_build_footer(dlg)

        def close():
            self._help_win = None
            try:
                dlg.destroy()
            except tk.TclError:
                pass
        dlg.protocol("WM_DELETE_WINDOW", close)
        dlg.bind("<Escape>", lambda e: close())
        # Wheel anywhere in the window scrolls the pane (the body owns the canvas).
        dlg.bind("<MouseWheel>", lambda e: self._help_body.canvas.yview_scroll(
            int(-e.delta / 120), "units"))

        w, h = self._edit_dpi_w(680), self._edit_dpi_w(560)
        dlg.minsize(self._edit_dpi_w(580), self._edit_dpi_w(440))
        dlg.geometry(f"{w}x{h}")
        self._center_dialog(dlg)
        dlg.focus_force()

    def _help_build_header(self, dlg):
        bar = self._tw(tk.Frame(dlg, height=self._edit_dpi_w(52)), bg="bar")
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        if self.icon("circle-help", size=20) is not None:
            self._icon_label(bar, "circle-help", size=20, token="fg",
                             bg="bar").pack(side="left", padx=(16, 10))
        self._tw(tk.Label(bar, text=t("Help"), font=("Segoe UI", 13, "bold")),
                 bg="bar", fg="fg").pack(side="left")
        self._tw(tk.Frame(dlg, height=1), bg="border").grid(
            row=0, column=0, sticky="sew")

    def _help_build_body(self, dlg):
        "The kit's tab rail + scrollable pane; each tab's content is a builder."
        self._help_body = tintkit.SettingsWindow(
            dlg, self.theme,
            tabs=[(key, t(label), icon, getattr(self, method))
                  for key, label, icon, method in _HELP_TABS],
            header=None, rail_w=180, icon_loader=self.icon)
        self._help_body.root.grid(row=1, column=0, sticky="nsew")

    def _help_build_footer(self, dlg):
        self._tw(tk.Frame(dlg, height=1), bg="border").grid(
            row=2, column=0, sticky="new")
        foot = self._tw(tk.Frame(dlg, height=self._edit_dpi_w(58)), bg="bar")
        foot.grid(row=2, column=0, sticky="ew")
        foot.grid_propagate(False)
        inner = self._tw(tk.Frame(foot), bg="bar")
        inner.pack(fill="x", padx=16, pady=11)

        def close():
            self._help_win = None
            try:
                dlg.destroy()
            except tk.TclError:
                pass
        tintkit.Button(inner, self.theme, t("Done"), role="primary",
                       variant="filled", bg="bar", command=close).pack(
            side="right")

    # --- page helpers -------------------------------------------------------

    def _help_icon(self, parent, name, tint=None):
        "Icon label for a help row: theme-fg by default, or a live keep/reject"
        " tint. Re-tints on every dark<->light switch (the window is non-modal)."
        if tint is None:
            return self._icon_label(parent, name, token="fg", bg="bg")
        lbl = tk.Label(parent, bg=self.theme["bg"])

        def restyle():
            try:
                im = self.icon(name, color=self._cull_tint(tint))
                if im is not None:
                    lbl.configure(image=im)
                    lbl._icon_ref = im            # keep a hard ref alive
                lbl.configure(bg=self.theme["bg"])
            except tk.TclError:                   # widget destroyed
                self.theme.unsubscribe(restyle)

        self.theme.subscribe(restyle)
        lbl.bind("<Destroy>",
                 lambda e: e.widget is lbl and self.theme.unsubscribe(restyle),
                 add="+")
        restyle()
        return lbl

    def _help_row(self, win, icon, title, desc, tint=None):
        "One explanation line: a tool icon, a bold title, one dim sentence."
        p = win.body.widget
        r = self._tw(tk.Frame(p), bg="bg")
        r.pack(fill="x", pady=self._edit_dpi_w(7))
        if icon:
            self._help_icon(r, icon, tint).pack(
                side="left", padx=(0, self._edit_dpi_w(12)), anchor="n")
        col = self._tw(tk.Frame(r), bg="bg")
        col.pack(side="left", fill="x", expand=True)
        self._tw(tk.Label(col, text=t(title), anchor="w",
                 font=("Segoe UI", 10, "bold")), bg="bg", fg="fg").pack(anchor="w")
        self._tw(tk.Label(col, text=t(desc), anchor="w", justify="left",
                 font=("Segoe UI", 9), wraplength=self._edit_dpi_w(380)),
                 bg="bg", fg="fg_dim").pack(anchor="w")

    def _help_key_row(self, win, keys, desc):
        "A shortcut line: a key-cap chip (`keys`, verbatim) + one dim sentence."
        p = win.body.widget
        r = self._tw(tk.Frame(p), bg="bg")
        r.pack(fill="x", pady=self._edit_dpi_w(5))
        chip = self._tw(tk.Label(r, text=keys, font=("Segoe UI", 9, "bold"),
                        padx=self._edit_dpi_w(10), pady=self._edit_dpi_w(3)),
                        bg="chip", fg="fg")
        chip.pack(side="left")
        self._tw(tk.Label(r, text=t(desc), anchor="w", justify="left",
                 font=("Segoe UI", 9), wraplength=self._edit_dpi_w(300)),
                 bg="bg", fg="fg_dim").pack(
            side="left", padx=(self._edit_dpi_w(12), 0))

    # --- Getting started tab ------------------------------------------------

    def _help_tab_start(self, win):
        win.note(t("Manoni is a fast photo browser, culler and editor. "
                   "The whole workflow, in five steps:"))
        self._help_row(win, "folder-open", "1 · Open a folder",
                       "Pick a folder of photos — thumbnails fill the sidebar.")
        self._help_row(win, "arrow-left-right", "2 · Browse",
                       "The arrow keys step through the photos; click a "
                       "thumbnail to jump.")
        self._help_row(win, "folder-check", "3 · Cull",
                       "Enter keeps and Backspace rejects — each photo moves to "
                       "its folder.")
        self._help_row(win, "sliders-horizontal", "4 · Edit",
                       "Open the edit panel to adjust light, colour, crop and more.")
        self._help_row(win, "upload", "5 · Save",
                       "Export the result as JPEG, PNG or WEBP.")
        win.note(t("Each tab on the left explains one part in more detail."))

        win.group(t("Your language"))
        self._help_row(win, "settings", "Add your language",
                       "The app comes in English and Polish. Every other language "
                       "is a pack: download one from the Discussions board and "
                       "double-click it, or build your own — Settings → General "
                       "→ Add your language writes a template you translate and "
                       "import. No code needed, and anything left untranslated "
                       "simply stays English.")

    # --- Culling tab --------------------------------------------------------

    def _help_tab_cull(self, win):
        win.group(t("Sort into two folders"))
        win.note(t("You browse the photos and sort each into a keep folder "
                   "and a discard folder — nothing is deleted, only moved."))
        self._help_row(win, "folder-check", "Keep",
                       "Moves the current photo to the keep folder.", tint="keep")
        self._help_row(win, "folder-x", "Reject",
                       "Moves the current photo to the discard folder.",
                       tint="reject")
        self._help_row(win, "settings", "Set the folders",
                       "Choose the keep and reject folders in Settings first — "
                       "until then these buttons do nothing.")

        win.group(t("Faster with keys"))
        self._help_key_row(win, "Enter", "Keep the current photo.")
        self._help_key_row(win, "Backspace", "Reject the current photo.")
        self._help_key_row(win, "Ctrl + Z", "Undo the last move.")
        win.note(t("At the end of a folder Manoni can loop back to the first "
                   "photo or open the next folder — set this in "
                   "Settings → Culling."), kind="info")

    # --- Keyboard tab -------------------------------------------------------

    def _help_tab_keys(self, win):
        win.group(t("Browsing"))
        self._help_key_row(win, "←  /  ↑", "Previous photo.")
        self._help_key_row(win, "→  /  ↓", "Next photo.")
        self._help_key_row(win, "Enter", "Keep the current photo.")
        self._help_key_row(win, "Backspace", "Reject the current photo.")
        win.note(t("These work whether the edit panel is open or closed; if the "
                   "photo has unsaved edits, Manoni saves a copy or asks first "
                   "(Settings → Culling → Auto-save)."))

        win.group(t("Anytime"))
        self._help_key_row(win, "Ctrl + O", "Open a folder of photos.")
        self._help_key_row(win, "Ctrl + S", "Save — overwrite the open file.")
        self._help_key_row(win, "Ctrl + E",
                           "Save a copy — a numbered file in the quick-copy folder.")
        self._help_key_row(win, "Ctrl + Shift + S", "Save as… — write a new copy.")
        self._help_key_row(win, "Ctrl + Z", "Undo.")
        self._help_key_row(win, "Ctrl + Y", "Redo  (or Ctrl + Shift + Z).")
        self._help_key_row(win, "Ctrl + R", "Show / hide the pixel rulers.")

        win.group(t("Heal & Clone"))
        self._help_key_row(win, "[   ]", "Shrink / grow the brush.")

        win.group(t("Actions"))
        self._help_key_row(win, "R", "Start / stop recording an action.")
        self._help_key_row(win, "Esc", "Cancel recording (throw the steps away).")
        self._help_key_row(win, "P", "Replay the highlighted action on the "
                                     "open photo.")
        self._help_key_row(win, "Shift + P", "Replay it over the whole folder.")

        win.group(t("On the photo  (mouse)"))
        self._help_row(win, "hand", "Hand / pan",
                       "Toggle the hand in the top bar, then drag to move the photo.")
        self._help_row(win, "square-split-horizontal", "Before / after",
                       "Drag the split line, or hold it to peek at the original.")

    # --- Editing tab --------------------------------------------------------

    def _help_tab_edit(self, win):
        win.note(t("The chevron on the icon rail (right of the photo) opens and "
                   "closes the edit panel. The tools:"))
        self._help_row(win, "sliders-horizontal", "Basic Edits",
                       "Exposure, contrast, white balance, highlights and shadows.")
        self._help_row(win, "palette", "Color mixer",
                       "Per-hue saturation, plus dedicated gold and skin tuning.")
        self._help_row(win, "wand-sparkles", "Effects",
                       "Clarity, sharpen, denoise, dehaze, grain and vignette.")
        self._help_row(win, "crop", "Crop",
                       "Trim, straighten a tilted horizon (±45°), rotate 90° and "
                       "flip horizontally or vertically; ratio, social and your "
                       "own saved presets.")
        self._help_row(win, "scaling", "Resize",
                       "Change the pixel dimensions — one photo, or a whole "
                       "folder (optionally its subfolders), with a progress bar "
                       "you can cancel.")
        self._help_row(win, "frame", "Perspective",
                       "Correct keystoning and straighten converging lines.")
        self._help_row(win, "bandage", "Heal & Clone",
                       "Paint over blemishes; Alt+click sets a clone source.")
        self._help_row(win, "circle-dot", "Focus blur",
                       "Blur the surroundings and keep the subject sharp.")
        self._help_row(win, "type", "Text & Watermark",
                       "Add live text overlays — many per photo, snap to a corner.")
        win.note(t("Ctrl+Z steps back through your edits; the before/after "
                   "button compares the result with the original."), kind="tip")

    # --- Filters tab --------------------------------------------------------

    def _help_tab_filters(self, win):
        win.group(t("One-click looks"))
        self._help_row(win, "blend", "Filters",
                       "A filter is a saved slider preset — click it to apply "
                       "the whole look at once.")
        win.note(t("The strip of previews under the photo shows each filter on "
                   "the current photo; click one to apply it."))

        win.group(t("Reuse the last look"))
        self._help_row(win, "refresh-cw", "Last",
                       "The moment you save a photo, its edit is pinned as a "
                       "“Last” slot in the strip and the filter list — click it "
                       "to apply the same look to the next photo, no saving "
                       "needed.")
        win.note(t("“Last” lasts only for this session; its … menu can promote "
                   "it into a permanent named filter, or clear it."), kind="warn")

        win.group(t("Make your own"))
        self._help_row(win, "star", "Save a filter",
                       "Dial in an edit you like, then save it as a filter to "
                       "reuse on any photo.")
        win.note(t("Rename, reorder or delete your filters from the Filters "
                   "panel."))

        win.group(t("Share with others"))
        self._help_row(win, "share-2", "Export & import a group",
                       "A filter group's … menu exports the whole group to a "
                       "small .mnf file — send it to a friend, and they load it "
                       "from the Import button pinned atop the Filters panel.")
        win.note(t("Sharing works per group, not per single filter: export a "
                   "group, import the file someone sends you."), kind="info")

    # --- Actions tab --------------------------------------------------------

    def _help_tab_actions(self, win):
        win.note(t("An action is a recorded macro of edits you can replay on "
                   "other photos."))
        self._help_row(win, "clapperboard", "Record",
                       "Arm the recorder, make your edits, then stop — the steps "
                       "are saved as an action.")
        self._help_row(win, "circle-play", "Replay",
                       "Play an action on the open photo, or batch it over a "
                       "whole folder.")
        win.note(t("Heal strokes are not recorded; everything else — light, "
                   "colour, crop, text, filters — is."), kind="warn")

        win.group(t("Keyboard"))
        self._help_key_row(win, "R", "Start / stop recording an action.")
        self._help_key_row(win, "Esc", "Cancel recording (throw the steps away).")
        self._help_key_row(win, "P", "Replay the highlighted action on the "
                                     "open photo.")
        self._help_key_row(win, "Shift + P", "Replay it over the whole folder.")
        win.note(t("P uses the last action you recorded or played — shown in "
                   "the panel in the accent colour. These keys pause while you "
                   "type a name."))

    # --- Save & Export tab --------------------------------------------------

    def _help_tab_export(self, win):
        win.group(t("Three ways to save"))
        self._help_row(win, "save", "Save — overwrite",
                       "Ctrl+S (or the Save button under the edit panel, and the "
                       "Save button in the top bar) writes your edits straight "
                       "back onto the open file, replacing it. There is no "
                       "backup, so the first time it asks you to confirm.")
        self._help_row(win, "folder-output", "Save a copy — no overwrite",
                       "Ctrl+E (or the copy button in the top bar) saves the same "
                       "edits as a NEW, numbered file in your quick-copy folder — "
                       "no dialog, and neither the original nor an earlier copy is "
                       "replaced. Pick the folder in Settings → Export.")
        self._help_row(win, "upload", "Save as… — a copy",
                       "Ctrl+Shift+S (or Save as… in the top bar) opens a dialog "
                       "to write a NEW file — pick the format (JPEG / PNG / WEBP), "
                       "quality and folder. The original is left untouched.")
        self._help_row(win, "folder-check", "Auto-copy while culling",
                       "Turn on Settings → Culling → Auto-save, and each time you "
                       "step away from or cull an edited photo Manoni silently "
                       "drops a copy in the export folder — no clicks. With it off, it "
                       "asks (Save a copy / Discard) before you leave.")

        win.group(t("Saved, or not?"))
        self._help_row(win, "circle-dot", "The ● dot",
                       "A ● in front of the file name — in the bottom bar and the "
                       "window title — means the photo has edits not yet saved "
                       "anywhere. It disappears the moment you save.")

        win.group(t("Where copies land"))
        self._help_row(win, "folder-output", "Output folder",
                       "Save as… and the culling copy default to a subfolder next "
                       "to each photo, or to one fixed folder — set it in "
                       "Settings → Export.")

        win.group(t("Metadata"))
        self._help_row(win, "info", "View or delete",
                       "The info button on the bottom bar — the strip showing "
                       "which file you're editing right now — opens the photo's "
                       "metadata, and its red Delete metadata button wipes the "
                       "colour profile and all EXIF (including GPS) from the "
                       "file, keeping the pixels exactly.")
        self._help_row(win, "upload", "Keep or strip on export",
                       "The same camera info, date, GPS and colour profile can "
                       "also be kept or removed when you save a copy.")
        win.note(t("The overwrite confirmation and every export default live in "
                   "Settings → Export."), kind="info")
