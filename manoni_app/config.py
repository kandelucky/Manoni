"""Static configuration for Manoni: paths, supported formats, theme, sizes.

Pure data — no Tk, no logic. Safe to import from anywhere without side effects.
Paths are anchored to the project root (the folder that contains manoni.py), so
they stay correct even though this module lives one level down in the package.
"""

import os
import sys

# Two kinds of path, resolved differently so Manoni works both from source and as
# a frozen PyInstaller build:
#   * READ-ONLY data shipped with the app (icons, the showcase image) — inside the
#     bundle when frozen, at the project root when run from source.
#   * WRITABLE user data (session, filters, actions, imported languages) — under
#     %APPDATA%\Manoni when frozen, because a frozen exe may sit in a read-only
#     place (Program Files) where writing beside it fails and data would be lost.
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_SOURCE_ROOT = os.path.dirname(_PKG_DIR)   # the folder that holds manoni.py

if getattr(sys, "frozen", False):
    # PyInstaller sets sys.frozen; _MEIPASS is its bundled-data folder (present in
    # both one-file and one-folder builds), with the exe's dir as a fallback.
    _RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    _DATA_DIR = os.path.join(os.environ.get("APPDATA")
                             or os.path.expanduser("~"), "Manoni")
    os.makedirs(_DATA_DIR, exist_ok=True)   # must exist before the first save
else:
    _RES_DIR = _SOURCE_ROOT
    _DATA_DIR = _SOURCE_ROOT                 # source run: everything at the root

# Kept as ROOT_DIR because the app-icon lookup (manoni.ico) still references it.
ROOT_DIR = _RES_DIR

# Icons live in ./icons (Lucide, white strokes on transparent).
ICON_DIR = os.path.join(_RES_DIR, "icons")

# The fixed showcase image the filter preview strip renders every filter onto
# (a single reference photo instead of a thumbnail of whatever is open), so a
# filter's look reads the same regardless of the current photo.
FILTER_SHOW_IMG = os.path.join(_RES_DIR, "Filter_Show.jpg")

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}

# Remembers the last opened folder + image, restored on the next launch.
STATE_FILE = os.path.join(_DATA_DIR, "manoni_state.json")

# User-created filters (saved slider/effect presets). Kept in its own file —
# separate from the session state — so it survives and travels independently.
FILTERS_FILE = os.path.join(_DATA_DIR, "manoni_filters.json")

# User-recorded actions (macros): an ordered list of edit + crop steps replayed
# onto an open photo. Own file (like filters) so it travels independently.
ACTIONS_FILE = os.path.join(_DATA_DIR, "manoni_actions.json")

# User-imported UI language packs (one {code,name,strings} .json per language).
# Scanned at startup and registered with i18n, so an added language survives the
# relaunch that a language switch triggers. See i18n.load_user_packs.
LANG_DIR = os.path.join(_DATA_DIR, "languages")

# Logo / watermark overlays. Two folders are scanned into the Logo tool's preset
# strip: LOGO_PRESET_DIR ships with the app (read-only, like icons), LOGO_DIR
# holds the PNGs the user imports (writable, so an imported logo is remembered
# and offered again next time). See imaging.logo + ui.logo.
LOGO_PRESET_DIR = os.path.join(_RES_DIR, "logos")
LOGO_DIR = os.path.join(_DATA_DIR, "my_logos")

# Dark theme colors
BG        = "#1b1b1b"   # main background
BAR       = "#262626"   # toolbar / info bar
SIDEBAR   = "#1e1e1e"   # sidebar background
HOVER     = "#3a3a3a"   # button hover
ACCENT    = "#4aa3ff"   # selection / highlight
ACCENT_HOVER = "#5ab0ff"  # brighter accent for a primary button's hover
ON_ACCENT = "#f4f9ff"   # light text / icon on an accent fill — matches TintKit's
                        # derived on-accent, so migrated and not-yet-migrated
                        # accent controls read identically (light, never black)
FG        = "#e6e6e6"   # primary text
FG_DIM    = "#9a9a9a"   # secondary text
CHIP_BG   = "#2f2f2f"   # neutral (inactive) chip / toggle background
BORDER    = "#3a3a3a"   # 1px hairline borders, separators, popup edges
DIVIDER   = "#333333"   # thin divider lines inside panels

# Cull buttons (keep / reject) — near-white with just a hint of colour so they
# read at a glance without shouting: a greenish-white keep (folder-up) and a
# reddish-white reject (folder-down). Those near-white tints only read on the
# DARK chrome; the light scheme uses a saturated green/red so the same icons +
# their info-line text stay legible on a light background (see _cull_tint).
CULL_KEEP_TINT   = "#cfe9cf"   # dark scheme: greenish white — keep / keeper
CULL_REJECT_TINT = "#edcfcf"   # dark scheme: reddish white — reject / discard
CULL_KEEP_TINT_LIGHT   = "#2e7d32"   # light scheme: readable green
CULL_REJECT_TINT_LIGHT = "#c62828"   # light scheme: readable red

# Accent-colour choices for the picker (Settings → General → Interface). The
# active one drives the whole app's highlight (TintKit derives its hover / soft /
# on-accent shades). ACCENT (blue) is the default; each is medium-saturation so
# the derived light on-accent text stays legible on the fill. (name, hex)
ACCENTS = [
    ("Blue",   "#4aa3ff"),
    ("Teal",   "#24b1a6"),
    ("Green",  "#45b36b"),
    ("Purple", "#9b87f5"),
    ("Pink",   "#e0699f"),
    ("Orange", "#ef8a53"),
    ("Red",    "#e5645c"),
    ("Amber",  "#d6a85c"),
]

# TintKit theme tokens = Manoni's dark palette, so a panel migrated onto TintKit
# widgets matches the rest of the app exactly (same bg / bar / fg / border …).
# Applied over TintKit's built-in "dark" scheme once at startup (see manoni.py).
# The accent is passed separately to Theme(); its on-accent / hover shades are
# then derived from it by TintKit.
THEME_DARK = {
    "bg": BG, "panel": BAR, "bar": BAR, "sidebar": SIDEBAR,
    "hover": HOVER, "lift": CHIP_BG, "chip": CHIP_BG,
    "border": BORDER, "divider": DIVIDER,
    "fg": FG, "fg_dim": FG_DIM, "ring": FG_DIM,
    "tooltip": "#0f0f0f",
}

ICON_SIZE = 22
THUMB_W   = 150   # default thumbnail size (px); adjustable at runtime

# Edit panel layout. Every section shares one width and one horizontal inset so
# all panels line up and their controls stretch to the same full width. These
# are LOGICAL px — the build scales them by the screen DPI so the panel fits its
# (DPI-scaled) text the same way at 100% and 150% scaling.
EDIT_PANEL_W = 252   # the section panel's fixed width (col 3)
EDIT_RAIL_W  = 78    # the always-visible icon rail's fixed width (col 4)
EDIT_PAD     = 14    # left/right inset shared by every control in the panel
CHIP_GAP     = 4     # gap between the two columns of a chip / button row
