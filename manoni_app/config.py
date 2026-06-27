"""Static configuration for Manoni: paths, supported formats, theme, sizes.

Pure data — no Tk, no logic. Safe to import from anywhere without side effects.
Paths are anchored to the project root (the folder that contains manoni.py), so
they stay correct even though this module lives one level down in the package.
"""

import os

# Project root = the directory that holds manoni.py (one level above this file).
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(_PKG_DIR)

# Icons live in ./icons at the project root (Lucide, white strokes on transparent).
ICON_DIR = os.path.join(ROOT_DIR, "icons")
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}

# Remembers the last opened folder + image, restored on the next launch.
STATE_FILE = os.path.join(ROOT_DIR, "manoni_state.json")

# User-created filters (saved slider/effect presets). Kept in its own file —
# separate from the session state — so it survives and travels independently.
FILTERS_FILE = os.path.join(ROOT_DIR, "manoni_filters.json")

# Dark theme colors
BG        = "#1b1b1b"   # main background
BAR       = "#262626"   # toolbar / info bar
SIDEBAR   = "#1e1e1e"   # sidebar background
HOVER     = "#3a3a3a"   # button hover
ACCENT    = "#4aa3ff"   # selection / highlight
FG        = "#e6e6e6"   # primary text
FG_DIM    = "#9a9a9a"   # secondary text

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
