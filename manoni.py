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
import threading
import tkinter as tk

import tintkit  # DPI + theme; declares DPI awareness at import, before tk.Tk()

from manoni_app.config import (BG, ACCENT, THUMB_W, STATE_FILE, ROOT_DIR,
                               ICON_DIR, THEME_DARK)
from manoni_app import i18n
from manoni_app import translations  # noqa: F401 — registers language packs on import
from manoni_app.ui.chrome import ChromeMixin
from manoni_app.ui.editpanel import EditPanelMixin
from manoni_app.ui.saving import SaveMixin
from manoni_app.ui.browser import BrowserMixin
from manoni_app.ui.viewer import ViewerMixin
from manoni_app.ui.nav import NavMixin
from manoni_app.ui.crop import CropMixin
from manoni_app.ui.resize import ResizeMixin
from manoni_app.ui.perspective import PerspectiveMixin
from manoni_app.ui.heal import HealMixin
from manoni_app.ui.focus import FocusMixin
from manoni_app.ui.text import TextMixin
from manoni_app.ui.filters import FiltersMixin
from manoni_app.ui.actions import ActionsMixin
from manoni_app.ui.about import AboutMixin
from manoni_app.ui.metadata import MetadataMixin
from manoni_app.ui.settings import SettingsMixin


class Manoni(ChromeMixin, EditPanelMixin, SaveMixin, BrowserMixin,
             ViewerMixin, NavMixin, CropMixin, ResizeMixin, PerspectiveMixin,
             HealMixin, FocusMixin, TextMixin, FiltersMixin, ActionsMixin,
             AboutMixin, MetadataMixin, SettingsMixin):
    "Main application window"

    # Zoom is an ABSOLUTE scale: display-pixels per source-pixel.
    # 1.0 = 100% (true pixels); "Fit" is a separate mode that tracks the window.
    MIN_SCALE = 0.05    # 5% — most zoomed out
    MAX_SCALE = 16.0    # 1600% — most zoomed in
    ZOOM_STEP = 1.25    # multiply/divide per wheel notch or −/+ click
    ZOOM_PRESETS = [("Fit", None), ("50%", 0.5), ("100%", 1.0), ("200%", 2.0)]

    # Every thumbnail zoom — the sidebar strip, the culling grid, their −/+ buttons,
    # Ctrl+wheel — snaps to one of these four sizes. They are exactly the sizes the
    # thumbnail cache decodes at (thumbcache._BUCKETS), so a zoom shows each thumb at
    # its native decoded resolution: instant and crisp, never an in-between downscale.
    THUMB_LEVELS = (128, 256, 448, 640)

    # Sidebar thumbnail grid (file-manager style: drag-resizable + zoomable).
    THUMB_MIN   = THUMB_LEVELS[0]   # smallest thumbnail (px)
    THUMB_MAX   = THUMB_LEVELS[-1]  # largest thumbnail (px)
    THUMB_PAD   = 16    # a grid cell's width beyond the image (padding + border)
    THUMB_NAME_H = 20   # px reserved under a grid thumbnail for its (one-line) name
    THUMB_CELL_V = 12   # a grid cell's height beyond the image + name (border + gaps)
    LIST_ROW_H  = 44    # fixed height of one list-view row (px)
    SIDEBAR_MIN = 110   # narrowest the sidebar can be dragged
    SIDEBAR_MAX = 720   # widest the sidebar can be dragged

    # Sidebar view modes (the footer dropdown). Grid modes set the icon size to one
    # of THUMB_LEVELS; "list" switches to compact rows. (key, label, px | None.)
    VIEW_MENU = [
        ("xlarge", "Extra large icons", THUMB_LEVELS[3]),
        ("large",  "Large icons",       THUMB_LEVELS[2]),
        ("medium", "Medium icons",      THUMB_LEVELS[1]),
        ("small",  "Small icons",       THUMB_LEVELS[0]),
        ("list",   "List",              None),
    ]
    LIST_THUMB = 36     # tiny preview beside the filename in list view
    LIST_NAME_PAD = 30  # px reserved beside a list name (thumb gaps + border + scrollbar)
    LIST_COL_MIN = 190  # min px per list column → list reflows to 2/3/4… cols when wide

    # Loading/rebuilding a strip with this many photos (or more) puts up a dark,
    # input-blocking "please wait" screen until the *visible* thumbnails finish, so
    # a slider or key press mid-load can't act on a half-painted strip. See browser.py.
    LOADING_OVERLAY_MIN = 40
    # Thumbnail virtualization: only the cells inside the viewport (plus this many
    # rows of buffer above and below) are ever realized + decoded, so cost is bound
    # to the screen, not the folder size. See browser._render_window.
    THUMB_BUFFER_ROWS = 3
    # Rows to move per mouse-wheel notch in the strip. Scrolling is row-based (not
    # raw pixels) so the strip's own Tk canvas never has to represent an absolute
    # position that could exceed Tk's ~32,767 px canvas coordinate ceiling — see
    # browser._render_window.
    THUMB_WHEEL_ROWS = 3

    # The top sub-folder list never grows past min(FOLDER_LIST_MAX, a fraction of
    # the sidebar height) — so on a short laptop screen it can't crowd the photo
    # list below it down to a single row; the overflow scrolls (with a scrollbar).
    FOLDER_LIST_MAX = 170  # absolute ceiling for the folder list's AUTO height (px)
    FOLDER_LIST_MIN = 56   # but always tall enough for ~2 folder rows (px)
    FOLDER_CAP_FRACTION = 0.34  # auto height: at most this share of the sidebar height
    FOLDER_DRAG_MAX_FRACTION = 0.7  # but a manual drag may claim up to this share
    # The top panel is now a real, nested folder TREE (tintkit.FolderTree) rooted
    # at self.tree_root; rows lazily list expanded folders only. A non-empty filter
    # scans the subtree for matches, bounded so a huge tree can't freeze the UI.
    FOLDER_FILTER_BUDGET = 4000   # max directories a live folder-filter scan visits

    # A photo counts as edited when ANY live factor leaves its neutral, or it
    # has been rotated/cropped — see _has_unsaved_edits, which drives the
    # "save a copy?" prompt on navigation. (Comparing every factor to its neutral
    # instead of a fixed dict means new sliders are covered automatically.)
    # Most factors rest at 1.0; creative effects rest at 0.0 (off → full). List
    # the 0-neutral ones here so reset / "is edited" use the right rest point.
    # auto_mode is not a slider; its rest is None (no auto correction active).
    SLIDER_NEUTRAL = {"bw": 0.0, "sepia": 0.0, "grain": 0.0, "denoise": 0.0,
                      "focus": None, "auto_mode": None, "texts": []}

    def __init__(self, folder=None):
        # DPI awareness is declared the moment tintkit is imported (its
        # enable_dpi_awareness runs at import, before this first window exists),
        # so Windows draws the UI at the monitor's true pixels instead of
        # bitmap-stretching it — the blur otherwise seen at 150 % scaling.

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
        # Make Tcl/Tk talk Unicode. Tk 8.6 defaults its string bridge to the
        # Windows ANSI code page ("language for non-Unicode programs") — e.g.
        # cp1250 here — which has no Georgian, so a Georgian keystroke arrives
        # in the text box as "?" and typed captions are lost. Forcing UTF-8
        # fixes input AND display for every script (Tk 9 already defaults to it).
        try:
            self.root.tk.call("encoding", "system", "utf-8")
        except tk.TclError:
            pass
        # DISABLED 2026-07-04: win_unicode_keys.py (a WH_KEYBOARD hook meant to
        # fix typed, not just programmatic, Georgian text) crashed live typing
        # twice despite a first fix — pulled out until it can be debugged
        # against real hardware input, since a crash is worse than the "?" it
        # was trying to fix. See win_unicode_keys.py's docstring for the story.
        # from manoni_app import win_unicode_keys
        # win_unicode_keys.install(self.root)
        # Give TintKit Manoni's own palette + icon set BEFORE the Theme is built,
        # so any panel migrated onto TintKit widgets matches the rest of the app
        # exactly (same colours) and finds the same Lucide icons.
        tintkit.theme.SCHEMES["dark"].update(THEME_DARK)
        tintkit.set_icon_dir(ICON_DIR)
        # One DPI path (tintkit): scale Tk fonts + the kit's canvas geometry to
        # the monitor, resolve the OS-native UI font, and return the factor so
        # icons load at a matching pixel size. Replaces Manoni's apply_tk_scaling.
        self.dpi = tintkit.setup_dpi(self.root)
        # One live Theme for the whole app (dark, Manoni's accent). Wired now;
        # each panel starts reading from it as it migrates onto TintKit.
        self.theme = tintkit.Theme(scheme="dark", accent=ACCENT)
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
        self._tw(self.root, bg="bg")   # outermost surface follows dark<->light too
        self._center_window(1280, 800)

        self.folder = None
        self.files = []          # image filenames in the folder
        # Sidebar folder TREE (tintkit.FolderTree): a fixed root, a set of expanded
        # folders (lazy — only expanded folders are listed), the current folder
        # highlighted, and a live name filter. See ui/browser.py.
        self.tree_root = None       # fixed root of the folder tree (re-roots on leaving it)
        self.folder_expanded = set()  # absolute paths currently expanded in the tree
        self.folder_filter = ""     # live folder-name filter ("" = show the tree)
        self._subdir_cache = {}     # path -> [(name, full)] sub-dirs, rebuilt each navigation
        self.folder_tree = None     # the tintkit.FolderTree widget (built on first use)
        self.index = 0           # current image index
        self.current_pil = None  # PIL image currently shown (full res)
        self.brightness = 1.0    # live edit factors (1.0 = unchanged)
        self.exposure_g = 1.0    # TEST: gamma-based exposure, alongside the linear one
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
        self.dehaze = 1.0        # >1.0 clears haze, <1.0 adds it (1.0 = unchanged)
        self.sharpen = 1.0       # >1.0 sharpen, <1.0 blur (1.0 = unchanged)
        self.denoise = 0.0       # noise reduction: 0 = off, up to 1 = full strength
        # Effects (creative looks) rest at 0.0 = off, up to 1.0 = full strength.
        self.bw = 0.0            # black-and-white: blend toward grayscale (0 = colour)
        self.sepia = 0.0         # sepia: blend toward a warm-toned monochrome (0 = colour)
        self.vignette = 1.0      # vignette: <1 lightens corners, >1 darkens; 1 = off
        self.grain = 0.0         # film grain: 0 = off, up to 1 = full strength
        # Split-tone (colour grading): warm↔cool tint for highlights / shadows.
        # 1.0 = neutral (>1 warm, <1 cool); bidirectional like temperature/tint.
        self.split_hi = 1.0
        self.split_sh = 1.0
        self._vig_cache = {}     # geometry key -> mask; reused across slider drags
        # Selective focus blur (Fotor-style depth of field): a draggable shape
        # kept sharp while the rest blurs. None = off, else a dict with shape
        # "circle" {cx, cy, r} or "line" {cx, cy, angle, width} (all source px),
        # plus blur + feather. A LIVE non-destructive effect like the vignette.
        self.focus = None
        self._focus_cache = {}   # geometry key -> mask; reused across blur drags
        self._focus_drag = None  # in-progress circle drag state, or None
        # Text / watermark overlays: LIVE non-destructive effects like the focus
        # blur. `texts` is a LIST of dicts {text, cx, cy, size (all source px),
        # color, opacity, font, align, shadow}; `text_sel` is the index of the
        # selected element (or None). The `text_overlay` PROPERTY (see TextMixin)
        # exposes the selected element so the per-control edit code stays simple.
        # Added only via the "Add text" button — never auto-inserted.
        self.texts = []
        self.text_sel = None
        self._text_drag = None   # in-progress move/resize drag state, or None
        # Auto tone (Photoshop "Auto Levels" / "Auto Contrast"). One mode at a
        # time: "levels" stretches each RGB channel (fixes a colour cast),
        # "contrast" stretches luminance only (keeps colour balance). The per-band
        # LUTs are computed once from the full base image and cached, so the
        # preview viewport and the saved full-res file get the same mapping.
        self.auto_mode = None
        self._auto_luts = None
        self._rotated = False    # has the current photo been rotated since loaded?
        self._mirrored = False   # has the current photo been mirrored since loaded?
        self._cropped = False    # has the current photo been cropped since loaded?
        self._resized = False    # has the current photo been resized since loaded?
        self._perspd = False     # has the current photo been keystone-corrected?
        # Perspective / keystone correction (pending, like straighten): −100..100
        # vertical / horizontal, 0 = none. A destructive in-memory bake on commit.
        self.persp_v = 0.0
        self.persp_h = 0.0
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
        # What ←/→ do at the folder edge (last photo + → , or first photo + ←):
        # None = ask each time (a small dialog with the two choices), "wrap" =
        # jump to the first/last photo of the same folder, "sibling" = continue
        # into the next/previous sibling folder. Persisted across sessions.
        self.edge_action = None
        # Simple on/off preferences (Settings → General). All persisted.
        self.restore_session = True   # reopen the last folder on launch
        self.restore_photo = True     # …and land on the last photo (else the first)
        self.confirm_reject = False   # ask before the reject (✗) move
        self.warn_unsaved = True      # offer to save when leaving an edited photo
        # Where the Save dialog defaults to (Settings → Export → Output):
        #   "subfolder" → a folder named export_subfolder beside each photo,
        #   "fixed"     → one fixed export_fixed_dir for every export.
        self.export_dir_mode = "subfolder"
        self.export_subfolder = "_edited"   # subfolder name (mode "subfolder")
        self.export_fixed_dir = ""          # absolute folder (mode "fixed")
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
        # Incremental edit cache: (base_key, stages) for the live viewport render,
        # so a slider only recomputes the pipeline stages downstream of what
        # changed (see imaging.apply_edits_cached). `_view_epoch` is its validity
        # token: it bumps whenever _view_base's pixels change (rebuilt on zoom/pan,
        # or patched in place by a heal dab), which retires the cached stages.
        self._edit_cache = {}
        self._view_epoch = 0
        # Async render (see viewer): the heavy edit pass runs on a worker thread so
        # a costly effect can't freeze the window; the finished frame is drawn back
        # on the UI thread. `_render_gen` tags each request so a stale result is
        # dropped once a newer one supersedes it. `_cache_lock` guards `_edit_cache`
        # (worker-owned in async mode; the lock only matters across a toggle flip).
        self._render_gen = 0
        self._cache_lock = threading.Lock()
        self._interacting = False    # a slider drag is live → draft render, no histogram
        self._preview_scheduled = False  # a coalesced render is queued for the next idle
        self._checker_img = None    # cached transparency checkerboard (grows with view)
        self._checker_size = (0, 0)
        self.show_rulers = True  # top + left pixel rulers (Ctrl+R); persisted
        self.show_filter_strip = True  # the filter-preview filmstrip; persisted
        self.show_histogram = True  # the edit panel's live histogram; persisted
        self.basic_full = False  # Basic Edits: show all sliders vs the simple 7; persisted
        self.fast_preview = True  # drop heavy filters during a slider drag; persisted
        self.async_render = True  # render off the UI thread so a heavy edit can't
                                  # freeze the window; persisted (Settings → General)
        self._message = None     # placeholder text shown when no photo is loaded
        self.icons = {}          # name -> PhotoImage (kept alive)
        # Virtualized thumbnail strip: only the cells in (or near) the viewport are
        # ever realized, so a 50- or 5000-file folder opens equally fast. See
        # ui/browser.py — _render_window builds/destroys cells as you scroll.
        self._cells = {}                # file index -> realized cell Frame (visible window)
        self._cell_imgs = {}            # file index -> PhotoImage for a realized cell
        self._cell_failed = set()       # file indices whose thumbnail couldn't be decoded
        self._poll_job = None           # after-job draining finished decodes into cells
        self._overlay_active = False    # is the "please wait" screen up for this build?
        self._loading_overlay = None    # the "please wait" screen while a folder loads
        self._decode_pool = None        # worker pool decoding thumbnails in parallel
        self._decode_futures = {}       # file index -> pending decode Future
        self._decode_tsize = self.THUMB_LEVELS[0]  # px the workers decode at (view-dependent)
        self.thumb_size = self.THUMB_LEVELS[0]  # current thumbnail size (px), zoomable
        self.view_mode = "grid"         # sidebar layout: "grid" icons | "list" rows
        self.sidebar_width = THUMB_W + 30  # current sidebar width (px), drag-resizable
        self.folder_list_height = None  # user-dragged sub-folder list height (px); None = auto
        self._thumb_cols = 1            # columns in the thumbnail grid (recomputed)
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
        self._filter_anchor = None  # edit state from before the current run of
                                     # filter-trying started (see "Remove filter")

        self._init_scrollbar_style()
        # The ttk scrollbar style is global (not per-widget), so re-run it on a
        # dark<->light switch to recolour the sidebar / folder / section scrollbars.
        self.theme.subscribe(self._init_scrollbar_style)
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
                 "show_filter_strip": self.show_filter_strip,
                 "show_histogram": self.show_histogram,
                 "basic_full": self.basic_full,
                 "fast_preview": self.fast_preview,
                 "async_render": self.async_render,
                 "restore_session": self.restore_session,
                 "restore_photo": self.restore_photo,
                 "confirm_reject": self.confirm_reject,
                 "warn_unsaved": self.warn_unsaved,
                 "scheme": self.theme.scheme,   # dark / light interface theme
                 "accent": self.theme.accent,   # highlight colour (accent picker)
                 "language": i18n.get_language()}
        if self.folder_list_height is not None:
            state["folder_list_height"] = self.folder_list_height
        if self.last_save:
            state["last_save"] = self.last_save   # remembered Save-as defaults
        if self.cull_keep:
            state["cull_keep"] = self.cull_keep   # ✓ keeper destination
        if self.cull_reject:
            state["cull_reject"] = self.cull_reject  # ✗ reject destination
        if self.edge_action:
            state["edge_action"] = self.edge_action  # folder-edge behaviour
        state["export_dir_mode"] = self.export_dir_mode
        state["export_subfolder"] = self.export_subfolder
        if self.export_fixed_dir:
            state["export_fixed_dir"] = self.export_fixed_dir
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

    def _snap_thumb_level(self, size, direction=0):
        "Snap a thumbnail size onto THUMB_LEVELS. direction 0 → the nearest level;"
        " +1 → the next larger level; −1 → the next smaller (clamped at the ends)."
        levels = self.THUMB_LEVELS
        if direction > 0:
            return next((s for s in levels if s > size), levels[-1])
        if direction < 0:
            return next((s for s in reversed(levels) if s < size), levels[0])
        return min(levels, key=lambda s: abs(s - size))

    def _load_prefs(self):
        "Read sidebar width + thumbnail size from the state file (before the UI builds)."
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            return
        ts = state.get("thumb_size")
        if isinstance(ts, int):
            self.thumb_size = self._snap_thumb_level(ts)   # old sizes snap to a level
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
        # Interface theme (dark / light). Applied to the live Theme BEFORE the UI
        # builds (this runs at line ~383, the chrome builds at ~405), so the whole
        # window comes up in the saved scheme with no dark→light flash.
        scheme = state.get("scheme")
        if scheme in ("dark", "light") and scheme != self.theme.scheme:
            self.theme.set(scheme=scheme)
        # Accent colour (the app highlight). Any well-formed #rrggbb is honoured,
        # so a hand-edited state can't crash the Theme.
        accent = state.get("accent")
        if isinstance(accent, str) and len(accent) == 7 and accent[0] == "#" \
                and all(c in "0123456789abcdefABCDEF" for c in accent[1:]):
            self.theme.set(accent=accent)
        # Simple General toggles (each defaults as set in __init__ if absent).
        for key in ("restore_session", "restore_photo", "confirm_reject",
                    "warn_unsaved", "show_filter_strip", "show_histogram",
                    "basic_full", "fast_preview", "async_render"):
            val = state.get(key)
            if isinstance(val, bool):
                setattr(self, key, val)
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
                              "keep_meta": bool(ls.get("keep_meta", True)),
                              "to_srgb": bool(ls.get("to_srgb", False))}
        # Cull destinations (keep + reject). Restored even if the folder no
        # longer exists — the cull action re-creates it (makedirs) on use.
        ck = state.get("cull_keep")
        if isinstance(ck, str) and ck:
            self.cull_keep = ck
        cr = state.get("cull_reject")
        if isinstance(cr, str) and cr:
            self.cull_reject = cr
        # Folder-edge behaviour (None = ask). Only the two real actions persist.
        ea = state.get("edge_action")
        if ea in ("wrap", "sibling"):
            self.edge_action = ea
        # Export output location (mode + subfolder name + fixed folder).
        edm = state.get("export_dir_mode")
        if edm in ("subfolder", "fixed"):
            self.export_dir_mode = edm
        esf = state.get("export_subfolder")
        if isinstance(esf, str) and esf.strip():
            self.export_subfolder = esf.strip()
        efd = state.get("export_fixed_dir")
        if isinstance(efd, str):
            self.export_fixed_dir = efd
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
        if not self.restore_session:
            return                       # the user opted out of reopening the folder
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            return
        folder = state.get("folder")
        if folder and os.path.isdir(folder):
            # Land on the last photo only if that's wanted; else open at the first.
            select = state.get("file") if self.restore_photo else None
            self.load_folder(folder, select=select)

    def _on_close(self):
        if not self._maybe_prompt_save():
            return                       # unsaved edits + 'cancel' → keep window open
        self._shutdown_decode_pool()     # stop any in-flight thumbnail decoding
        self._save_state()
        self.root.destroy()

    # --- Misc ---------------------------------------------------------------

    def toast(self, message):
        "Show a short status message in the bottom info bar."
        self.lbl_info.configure(text=message)

    def run(self):
        self.root.mainloop()


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else None
    app = Manoni(folder)
    app.run()


if __name__ == "__main__":
    main()
