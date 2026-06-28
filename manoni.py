"""Manoni — a fast, simple dark photo browser + culler.

Runs on a weak laptop. Pure Python + Tkinter + Pillow (MIT-friendly stack).

This file is the entry point and the application *shell*: it builds the window,
holds the shared state, and wires things together. All the behaviour lives in
the manoni_app package, split by topic into mixins that Manoni composes (see
spec/05-architecture.md). A new feature goes into the matching module there —
never back into one giant file.

Run:  python manoni.py [optional_folder]
See:  spec/00-START-HERE.md
"""

import os
import sys
import json
import tkinter as tk

from manoni_app.config import BG, THUMB_W, STATE_FILE, ROOT_DIR
from manoni_app import i18n
from manoni_app import translations  # noqa: F401 — registers language packs on import
from manoni_app.scaling import set_dpi_awareness, apply_tk_scaling
from manoni_app.ui.chrome import ChromeMixin
from manoni_app.ui.editpanel import EditPanelMixin
from manoni_app.ui.saving import SaveMixin
from manoni_app.ui.browser import BrowserMixin
from manoni_app.ui.viewer import ViewerMixin
from manoni_app.ui.nav import NavMixin
from manoni_app.ui.crop import CropMixin
from manoni_app.ui.resize import ResizeMixin
from manoni_app.ui.heal import HealMixin
from manoni_app.ui.focus import FocusMixin
from manoni_app.ui.filters import FiltersMixin
from manoni_app.ui.actions import ActionsMixin
from manoni_app.ui.about import AboutMixin
from manoni_app.ui.metadata import MetadataMixin


class Manoni(ChromeMixin, EditPanelMixin, SaveMixin, BrowserMixin,
             ViewerMixin, NavMixin, CropMixin, ResizeMixin, HealMixin,
             FocusMixin, FiltersMixin, ActionsMixin, AboutMixin, MetadataMixin):
    "Main application window"

    # Zoom is an ABSOLUTE scale: display-pixels per source-pixel.
    # 1.0 = 100% (true pixels); "Fit" is a separate mode that tracks the window.
    MIN_SCALE = 0.05    # 5% — most zoomed out
    MAX_SCALE = 16.0    # 1600% — most zoomed in
    ZOOM_STEP = 1.25    # multiply/divide per wheel notch or −/+ click
    ZOOM_PRESETS = [("Fit", None), ("50%", 0.5), ("100%", 1.0), ("200%", 2.0)]

    # Sidebar thumbnail grid (file-manager style: drag-resizable + zoomable).
    THUMB_MIN   = 72    # smallest thumbnail (px)
    THUMB_MAX   = 240   # largest thumbnail (px)
    THUMB_STEP  = 24    # +/- per zoom click
    THUMB_PAD   = 16    # a cell's footprint beyond the image (padding + border)
    SIDEBAR_MIN = 110   # narrowest the sidebar can be dragged
    SIDEBAR_MAX = 720   # widest the sidebar can be dragged

    # Sidebar view modes (the footer dropdown). Grid modes set the icon size;
    # "list" switches to compact rows. (key, label, thumbnail px | None for list.)
    VIEW_MENU = [
        ("large",  "Large icons",    216),
        ("medium", "Medium icons",  144),
        ("small",  "Small icons",   96),
        ("list",   "List",              None),
    ]
    LIST_THUMB = 36     # tiny preview beside the filename in list view
    LIST_NAME_PAD = 30  # px reserved beside a list name (thumb gaps + border + scrollbar)
    LIST_COL_MIN = 190  # min px per list column → list reflows to 2/3/4… cols when wide
    FOLDER_NAME_PAD = 38  # px reserved beside a folder name (glyph + gaps) per column
    MAX_GRID_COLS = 16  # safe upper bound when (re)configuring grid column weights

    # Loading a folder with this many photos (or more) puts up a dark, input-
    # blocking "please wait" screen until the thumbnails finish, so a slider or
    # key press mid-load can't corrupt the half-built grid. See browser.py.
    LOADING_OVERLAY_MIN = 40
    # Thumbnail loading: images are decoded in parallel worker threads and turned
    # into grid cells on the main thread in batches of up to THUMB_BUDGET seconds
    # (so the progress bar still repaints). DECODE_WINDOW caps how many decoded
    # thumbnails are held ahead of the cells being built (bounds memory).
    THUMB_BUDGET = 0.03
    DECODE_WINDOW = 64

    # The top sub-folder list never grows past min(FOLDER_LIST_MAX, a fraction of
    # the sidebar height) — so on a short laptop screen it can't crowd the photo
    # list below it down to a single row; the overflow scrolls (with a scrollbar).
    FOLDER_LIST_MAX = 170  # absolute ceiling for the folder list's AUTO height (px)
    FOLDER_LIST_MIN = 56   # but always tall enough for ~2 folder rows (px)
    FOLDER_CAP_FRACTION = 0.34  # auto height: at most this share of the sidebar height
    FOLDER_DRAG_MAX_FRACTION = 0.7  # but a manual drag may claim up to this share
    FOLDER_COL_MIN = 120   # min px per folder column → 2 columns once the sidebar is wide
    FOLDER_MAX_COLS = 2    # never more than two folder columns (keeps names readable)

    # A photo counts as edited when ANY live factor leaves its neutral, or it
    # has been rotated/cropped — see _has_unsaved_edits, which drives the
    # "save a copy?" prompt on navigation. (Comparing every factor to its neutral
    # instead of a fixed dict means new sliders are covered automatically.)
    # Most factors rest at 1.0; creative effects rest at 0.0 (off → full). List
    # the 0-neutral ones here so reset / "is edited" use the right rest point.
    # auto_mode is not a slider; its rest is None (no auto correction active).
    SLIDER_NEUTRAL = {"bw": 0.0, "sepia": 0.0, "focus": None, "auto_mode": None}

    def __init__(self, folder=None):
        # Declare DPI awareness BEFORE the first window so Windows draws the
        # UI at the monitor's true pixels instead of bitmap-stretching it
        # (the blur seen at 150 % scaling). See manoni_app/scaling.py.
        set_dpi_awareness()

        # Give this process its own Windows taskbar identity. Without it, Tk
        # apps launched via pythonw.exe share a default identity and Windows
        # reuses whatever icon another Tk app (e.g. ctk_maker) registered —
        # so Manoni would borrow that app's icon. Must run before the window.
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "voxe.manoni.photoculler")
            except Exception:
                pass

        self.root = tk.Tk()
        # Tell Tk the real DPI so point-sized fonts render crisp; keep the
        # factor so icons can be loaded at a matching pixel size.
        self.dpi = apply_tk_scaling(self.root)
        self.root.title("Manoni")
        # Manoni's own window/taskbar icon (manoni.ico / -icon.png at the root).
        try:
            ico = os.path.join(ROOT_DIR, "manoni.ico")
            png = os.path.join(ROOT_DIR, "manoni-icon.png")
            if sys.platform == "win32" and os.path.exists(ico):
                self.root.iconbitmap(default=ico)
            elif os.path.exists(png):
                self.root.iconphoto(True, tk.PhotoImage(file=png, master=self.root))
        except Exception:
            pass
        self.root.configure(bg=BG)
        self._center_window(1280, 800)

        self.folder = None
        self.files = []          # image filenames in the folder
        self.subfolders = []     # (name, fullpath) of sub-directories, listed at the sidebar top
        self.index = 0           # current image index
        self.current_pil = None  # PIL image currently shown (full res)
        self.brightness = 1.0    # live edit factors (1.0 = unchanged)
        self.contrast = 1.0
        self.color = 1.0
        self.temperature = 1.0   # >1.0 warmer (more red), <1.0 cooler (more blue)
        self.tint = 1.0          # >1.0 magenta (less green), <1.0 green (more green)
        # HSL colour mixer: per-hue saturation (1.0 = unchanged, 0 = greyed, 2 =
        # doubled) plus a separate "gold shine" that makes golden tones glow.
        self.sat_red = 1.0
        self.sat_orange = 1.0
        self.sat_yellow = 1.0
        self.sat_green = 1.0
        self.sat_aqua = 1.0
        self.sat_blue = 1.0
        self.sat_purple = 1.0
        self.sat_magenta = 1.0
        # Gold and skin each get their own three controls (hue / sat / lightness),
        # hue+saturation gated so they touch only that material.
        self.gold_hue = 1.0
        self.gold_sat = 1.0
        self.gold_light = 1.0
        self.skin_hue = 1.0
        self.skin_sat = 1.0
        self.skin_light = 1.0
        # ACR tone controls (factor 1.0 = neutral; amount = factor - 1.0 in [-1,1])
        self.highlights = 1.0    # + brightens / - recovers the bright tones
        self.shadows = 1.0       # + lifts / - deepens the dark tones
        self.whites = 1.0        # + raises / - pulls back the white point
        self.blacks = 1.0        # + lifts / - crushes the black point
        self.clarity = 1.0       # + midtone local contrast / - soft glow
        self.vibrance = 1.0      # + saturate the muted colours (protects saturated)
        self.texture = 1.0       # + crisper medium detail / - gentle surface smoothing
        self.sharpen = 1.0       # >1.0 sharpen, <1.0 blur (1.0 = unchanged)
        # Effects (creative looks) rest at 0.0 = off, up to 1.0 = full strength.
        self.bw = 0.0            # black-and-white: blend toward grayscale (0 = colour)
        self.sepia = 0.0         # sepia: blend toward a warm-toned monochrome (0 = colour)
        self.vignette = 1.0      # vignette: <1 lightens corners, >1 darkens; 1 = off
        self._vig_cache = {}     # geometry key -> mask; reused across slider drags
        # Selective focus blur (Fotor-style depth of field): a draggable shape
        # kept sharp while the rest blurs. None = off, else a dict with shape
        # "circle" {cx, cy, r} or "line" {cx, cy, angle, width} (all source px),
        # plus blur + feather. A LIVE non-destructive effect like the vignette.
        self.focus = None
        self._focus_cache = {}   # geometry key -> mask; reused across blur drags
        self._focus_drag = None  # in-progress circle drag state, or None
        # Auto tone (Photoshop "Auto Levels" / "Auto Contrast"). One mode at a
        # time: "levels" stretches each RGB channel (fixes a colour cast),
        # "contrast" stretches luminance only (keeps colour balance). The per-band
        # LUTs are computed once from the full base image and cached, so the
        # preview viewport and the saved full-res file get the same mapping.
        self.auto_mode = None
        self._auto_luts = None
        self._rotated = False    # has the current photo been rotated since loaded?
        self._cropped = False    # has the current photo been cropped since loaded?
        self._resized = False    # has the current photo been resized since loaded?
        self._edits_saved = False  # are the current photo's edits already saved to a copy?
        # Save model: "quick save" (rail button + leaving an edited photo) writes
        # silently using quick_save_cfg = {dir, fmt, quality}. It starts UNSET each
        # session on purpose, so the first quick save opens the full Save-as dialog
        # (where it gets armed). last_save = the dialog's remembered defaults
        # (folder/format/quality), persisted across sessions in the state file.
        self.quick_save_cfg = None    # armed only within this session (never loaded)
        self.last_save = None         # {dir, fmt, quality} remembered for the dialog
        # Cull (culling): two destination folders the keep/reject toolbar
        # buttons sort the current photo into. Both must be set (in the ⚙ options
        # dialog) before either button works — see nav._require_cull. Persisted
        # across sessions in the state file.
        self.cull_keep = None         # folder the ✓ keeper button moves photos to
        self.cull_reject = None       # folder the ✗ reject button moves photos to
        self._menu_popup = None       # the ☰ dropdown Toplevel while open, else None
        # Crop tool: a non-destructive selection drawn over the preview, stored in
        # SOURCE-image pixels so it stays anchored through zoom/pan. None = no box.
        self.crop_rect = None         # [x0, y0, x1, y1] in source px, or None
        self.crop_ratio = None        # locked aspect ratio (w/h), or None = free
        self.straighten = 0.0         # horizon-straighten tilt in degrees (0 = level),
                                      # previewed live in the crop tool, baked on Crop
        self._crop_btn_active = None  # the highlighted preset chip (for restyle)
        self._crop_chips = []         # all preset chip widgets (for restyle)
        self._crop_drag = None        # in-progress drag state, or None
        # User-saved custom crop sizes shown in the "My sizes" scroll list,
        # each {"name", "w", "h"}. Persisted across sessions in the state file.
        self.crop_sizes = []
        # Retouch tool: a LOCAL pixel edit baked into current_pil like crop —
        # either auto spot-heal (clone a clean neighbour) or a manual clone stamp.
        # Brush radius is in SOURCE px so it stays constant through zoom. A stroke
        # is one undo step.
        self.heal_radius = 24         # brush radius in source px (slider / wheel / [ ])
        self.heal_opacity = 1.0       # blend strength: 1.0 solid; the Strength slider lowers it
        self.heal_feather = 0.5       # patch-edge softness 0..1 (matches imaging.HEAL_FEATHER)
        self.heal_mode = "auto"       # "auto" = spot heal, "clone" = manual clone stamp
        self.clone_src = None         # clone source anchor (source px), set by Alt+click
        self.clone_offset = None      # locked (dst-src) offset while cloning, or None
        self.clone_aligned = True     # True = offset persists across strokes (Photoshop "aligned")
        self.clone_flip = False       # mirror the cloned source left↔right
        self._healed = False          # has the current photo been retouched (heal/clone)?
        self._heal_cursor = None      # last (screen x, y) for the brush ring, or None
        self._heal_before_img = None  # RGB snapshot taken when a stroke begins
        self._heal_dirty = None       # union box of the stroke's dabs, or None
        self._heal_last = None        # last dabbed source point (for dab spacing)
        self._disp = (1.0, 0.0, 0.0)  # last render transform: (scale, off_x, off_y)
        self.panel_open = False  # is the right-side edit panel (sliders + rail) shown?
        self.active_section = "basic"  # which edit section/tool is open in the panel
        self.fit_mode = True     # True = fit to window; False = use self.user_scale
        self.user_scale = 1.0    # absolute scale when not fitting (1.0 = 100%)
        self.pan_x = 0.0         # viewport pan offset, in screen pixels
        self.pan_y = 0.0
        self._pan_anchor = None  # (mx, my, pan_x, pan_y) captured while panning
        self.hand_tool = False   # hand (pan) tool: while on, left-drag pans the canvas
        # Before/after compare (იყო / არის): split-line view + hold-to-peek.
        self.compare_mode = False  # split-line view on? (drag the line over the photo)
        self.compare_frac = 0.5    # divider position, as a fraction of the canvas width
        self._compare_peek = False  # holding the button → show the full original
        self._compare_span = None   # (left_x, right_x): the photo's on-screen span
        # The "before" image: current_pil's geometry but WITHOUT the destructive
        # heal/clone strokes (and the sliders are skipped at render time). None =
        # no heal yet, so "before" is just current_pil. Crop/rotate transform it
        # in lockstep so it always lines up with the edit. Cached scaled view next.
        self._before_pil = None
        self._before_base = None    # cached cropped+scaled RGB of _before_pil for the view
        self._before_base_key = None
        self._view_base = None   # cached cropped+scaled RGB image for the view
        self._view_key = None    # identity of _view_base (None forces a re-render)
        self._view_alpha = None  # matching alpha mask when the photo is transparent
        self._has_alpha = False  # does the current photo carry transparency?
        self._checker_img = None    # cached transparency checkerboard (grows with view)
        self._checker_size = (0, 0)
        self.show_rulers = True  # top + left pixel rulers (Ctrl+R); persisted
        self._message = None     # placeholder text shown when no photo is loaded
        self.icons = {}          # name -> PhotoImage (kept alive)
        self._folder_imgs = {}   # cached small folder glyph for the list rows (kept alive)
        self.thumb_images = []   # thumbnail PhotoImages (kept alive)
        self.thumb_widgets = []  # cell frame per thumbnail (for highlight); may be None
        self.folder_widgets = []  # sub-folder rows in the top folder list
        self._thumb_job = None
        self._loading_overlay = None    # the "please wait" screen while a folder loads
        self._decode_pool = None        # worker pool decoding thumbnails in parallel
        self._decode_futures = {}       # file index -> pending decode Future
        self.thumb_size = THUMB_W       # current thumbnail size (px), zoomable
        self.view_mode = "grid"         # sidebar layout: "grid" icons | "list" rows
        self.sidebar_width = THUMB_W + 30  # current sidebar width (px), drag-resizable
        self.folder_list_height = None  # user-dragged sub-folder list height (px); None = auto
        self._thumb_cols = 1            # columns in the thumbnail grid (recomputed)
        self._folder_cols = 1          # columns in the top folder list (1 or 2, by width)
        self._thumb_pos = 0            # next free grid slot while loading
        self._load_prefs()             # restore remembered sidebar width + thumb size
        self._load_filters()           # restore the user's saved filters (presets)
        self._load_actions()           # restore the user's saved actions (macros)

        # Action recorder (macros). While armed, committed edits/crops are captured
        # as ordered steps (see manoni_app/ui/actions.py); _playing silences the
        # crop tool's toasts while an action replays its steps.
        self._recording = False        # is the recorder armed?
        self._record_steps = []        # steps captured in the current recording
        self._playing = False          # an action is currently replaying

        # Undo/redo: stacks of command dicts. A command is either
        #   {'kind': 'move', 'file', 'src', 'dest'}            (delete / move-to)
        #   {'kind': 'edit', 'folder', 'file', 'before', 'after'}  (slider edits)
        self._undo_stack = []
        self._redo_stack = []
        self._edit_before = None  # edit-state snapshot taken when a drag begins

        self._init_scrollbar_style()
        self._build_infobar()
        self._build_toolbar()
        self._build_body()
        self._build_bottombar()

        self.root.rowconfigure(2, weight=1)      # body row expands
        self.root.columnconfigure(0, weight=1)

        # Re-fit the preview when the window resizes
        self.preview.bind("<Configure>", lambda e: self._render_preview())

        # Save the session (last folder + image) when the window is closed.
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Keyboard shortcuts dispatch by *physical* key, not by character, so
        # they keep working under a non-Latin layout (e.g. Georgian). With such
        # a layout Tk reports the localized letter as the keysym, so patterns
        # like <Control-z> never match. The handlers below match the keysym OR
        # the Windows virtual-key code (event.keycode), which stays put across
        # layouts. See _on_ctrl_shortcut / _on_plain_key.
        #   Ctrl+Z undo, Ctrl+Y or Ctrl+Shift+Z redo, Ctrl+R toggle rulers.
        self.root.bind("<Control-KeyPress>", self._on_ctrl_shortcut)
        #   [ / ] resize the heal brush (Photoshop-style), only while it is open.
        self.root.bind("<KeyPress>", self._on_plain_key)

        # Browse-mode arrow keys (only while the edit panel is closed — an open
        # panel keeps the arrows for its own controls). ←/→ step between photos
        # (no wrap: they stop at the folder edges); ↑/↓ sort the current photo
        # into the keep / reject folders. See nav.py.
        self.root.bind("<Left>",  lambda e: self._arrow_prev())
        self.root.bind("<Right>", lambda e: self._arrow_next())
        self.root.bind("<Up>",    lambda e: self._arrow_keep())
        self.root.bind("<Down>",  lambda e: self._arrow_reject())

        if folder:
            self.load_folder(folder)
        else:
            self._restore_last_session()

    # --- Keyboard shortcuts (layout-independent) ----------------------------

    # Windows virtual-key codes for the shortcut keys. On Windows Tk puts the
    # VK code in event.keycode and it does NOT change with the keyboard layout,
    # so we use it as a fallback when a non-Latin layout hides the keysym.
    _VK_Z, _VK_Y, _VK_R = 90, 89, 82
    _VK_LBRACKET, _VK_RBRACKET = 219, 221

    def _on_ctrl_shortcut(self, event):
        "Ctrl shortcuts, matched by keysym or physical key (layout-independent)."
        ks = event.keysym.lower()
        kc = event.keycode
        shift = bool(event.state & 0x0001)
        if ks == "z" or kc == self._VK_Z:
            self.redo() if shift else self.undo()   # Ctrl+Shift+Z = redo
            return "break"
        if ks == "y" or kc == self._VK_Y:
            self.redo()
            return "break"
        if ks == "r" or kc == self._VK_R:
            self.toggle_rulers()
            return "break"
        # Leave every other Ctrl combo (copy / paste / select-all, ...) alone.
        return None

    def _on_plain_key(self, event):
        "Unmodified [ / ] resize the heal brush (a no-op while it is closed)."
        if event.state & 0x0004:        # Control held → not ours
            return None
        ks = event.keysym
        kc = event.keycode
        if ks == "bracketleft" or kc == self._VK_LBRACKET:
            self._heal_brush_key(-1)
        elif ks == "bracketright" or kc == self._VK_RBRACKET:
            self._heal_brush_key(1)
        return None

    # --- Session state (last folder + image) --------------------------------

    def _center_window(self, want_w, want_h):
        """Size the window to fit the screen and center it.

        On a small/weak laptop a fixed 1280x800 can spill below the screen edge,
        hiding the bottom of the window under the taskbar. We clamp the size to
        the available screen area (leaving a margin for the title bar + taskbar)
        and place it so the whole window stays visible.
        """
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # Leave room: side margins + title bar (~32px) and taskbar (~56px).
        w = min(want_w, sw - 40)
        h = min(want_h, sh - 88)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - 88 - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _save_state(self):
        "Remember the folder/image plus UI prefs so we can restore them next time."
        state = {"thumb_size": self.thumb_size,
                 "sidebar_width": self.sidebar_width,
                 "view_mode": self.view_mode,
                 "show_rulers": self.show_rulers,
                 "language": i18n.get_language()}
        if self.folder_list_height is not None:
            state["folder_list_height"] = self.folder_list_height
        if self.last_save:
            state["last_save"] = self.last_save   # remembered Save-as defaults
        if self.cull_keep:
            state["cull_keep"] = self.cull_keep   # ✓ keeper destination
        if self.cull_reject:
            state["cull_reject"] = self.cull_reject  # ✗ reject destination
        if self.crop_sizes:
            state["crop_sizes"] = self.crop_sizes    # user's saved crop sizes
        if self.folder:
            state["folder"] = self.folder
            if self.files and 0 <= self.index < len(self.files):
                state["file"] = self.files[self.index]
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except Exception:
            pass

    def _load_prefs(self):
        "Read sidebar width + thumbnail size from the state file (before the UI builds)."
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            return
        ts = state.get("thumb_size")
        if isinstance(ts, int):
            self.thumb_size = max(self.THUMB_MIN, min(self.THUMB_MAX, ts))
        sw = state.get("sidebar_width")
        if isinstance(sw, int):
            self.sidebar_width = max(self.SIDEBAR_MIN, min(self.SIDEBAR_MAX, sw))
        flh = state.get("folder_list_height")
        if isinstance(flh, int):       # clamped to the live sidebar at apply time
            self.folder_list_height = max(self.FOLDER_LIST_MIN, flh)
        vm = state.get("view_mode")
        if vm in ("grid", "list"):
            self.view_mode = vm
        sr = state.get("show_rulers")
        if isinstance(sr, bool):
            self.show_rulers = sr
        # UI language. Falls back to the default (Georgian) if unset/unknown.
        lang = state.get("language")
        if isinstance(lang, str):
            i18n.set_language(lang)
        # Save-as defaults (folder/format/quality). NOT quick_save_cfg — that stays
        # unset each session so the first quick save always opens the dialog.
        ls = state.get("last_save")
        if isinstance(ls, dict) and isinstance(ls.get("dir"), str) \
                and ls.get("fmt") in ("JPEG", "PNG", "WEBP"):
            self.last_save = {"dir": ls["dir"], "fmt": ls["fmt"],
                              "quality": int(ls.get("quality", 95)),
                              "keep_meta": bool(ls.get("keep_meta", True))}
        # Cull destinations (keep + reject). Restored even if the folder no
        # longer exists — the cull action re-creates it (makedirs) on use.
        ck = state.get("cull_keep")
        if isinstance(ck, str) and ck:
            self.cull_keep = ck
        cr = state.get("cull_reject")
        if isinstance(cr, str) and cr:
            self.cull_reject = cr
        # User's saved custom crop sizes. Keep only well-formed {name,w,h} with
        # positive dimensions, so a hand-edited state file can't break the panel.
        cs = state.get("crop_sizes")
        if isinstance(cs, list):
            clean = []
            for it in cs:
                if not isinstance(it, dict):
                    continue
                try:
                    w, h = float(it.get("w")), float(it.get("h"))
                except (TypeError, ValueError):
                    continue
                if w > 0 and h > 0:
                    name = str(it.get("name") or "").strip()
                    clean.append({"name": name, "w": w, "h": h})
            self.crop_sizes = clean

    def _restore_last_session(self):
        "On launch with no folder given, reopen the last session if it still exists."
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            return
        folder = state.get("folder")
        if folder and os.path.isdir(folder):
            self.load_folder(folder, select=state.get("file"))

    def _on_close(self):
        if not self._maybe_prompt_save():
            return                       # unsaved edits + 'cancel' → keep window open
        self._shutdown_decode_pool()     # stop any in-flight thumbnail decoding
        self._save_state()
        self.root.destroy()

    # --- Misc ---------------------------------------------------------------

    def toast(self, message):
        "Show a short status message in the info bar."
        self.lbl_info.configure(text=message)

    def run(self):
        self.root.mainloop()


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    app = Manoni(folder)
    app.run()


if __name__ == "__main__":
    main()
