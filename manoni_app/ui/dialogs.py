"""Shared dialog / chip building blocks: the flat dialog button, the
center-over-the-main-window placement, and the two chip families.

These used to be copy-pasted across nav / saving / filters / crop / metadata /
actions / focus / heal (several verbatim copies of the same button and chips,
plus the same centering math). They live here once so a tweak to the look or
placement lands everywhere.
"""

from ..config import BAR, HOVER, ACCENT, FG, ON_ACCENT, ACCENT_HOVER, CHIP_BG

import tkinter as tk

DANGER = "#a83232"        # destructive-action button (e.g. "Delete metadata")
DANGER_HOVER = "#c43d3d"


def make_dialog_button(parent, text, command, primary=False, danger=False):
    """A flat label-as-button for dialogs.

    primary -> accent fill + bold; danger -> red fill + white + bold;
    otherwise the neutral BAR fill. Click fires `command`.
    """
    if danger:
        bg, hov, fg, bold = DANGER, DANGER_HOVER, "#ffffff", True
    else:
        bg = ACCENT if primary else BAR
        hov = ACCENT_HOVER if primary else HOVER
        fg = ON_ACCENT if primary else FG
        bold = primary
    b = tk.Label(parent, text=text, bg=bg, fg=fg, cursor="hand2",
                 padx=14, pady=7,
                 font=("Segoe UI", 9, "bold" if bold else "normal"))
    b.bind("<Enter>", lambda e: b.configure(bg=hov))
    b.bind("<Leave>", lambda e: b.configure(bg=bg))
    b.bind("<Button-1>", lambda e: command())
    return b


def center_over(root, dlg):
    "Place a Toplevel centered over the main window (no modal grab)."
    dlg.update_idletasks()
    dw, dh = dlg.winfo_width(), dlg.winfo_height()
    rx, ry = root.winfo_rootx(), root.winfo_rooty()
    rw, rh = root.winfo_width(), root.winfo_height()
    dlg.geometry(f"+{max(0, rx + (rw - dw) // 2)}+{max(0, ry + (rh - dh) // 2)}")


# --- Chips -----------------------------------------------------------------
# Two visually distinct families share one active-state toggle:
#   * dialog chips  — neutral BAR fill, normal weight, packed left (Save-as,
#     batch-action dialogs: format / quality pickers).
#   * panel chips   — CHIP_BG fill, bold, gridded two-up (focus shape, heal
#     mode, clone toggles in the edit panel).

def set_chip_active(w, active, base=BAR):
    "Repaint a chip as selected (accent) or idle (its `base` fill)."
    w.configure(bg=ACCENT if active else base, fg=ON_ACCENT if active else FG)


def make_chip(parent, text, command):
    "A neutral dialog chip, packed left; click fires `command`. Idle fill = BAR."
    c = tk.Label(parent, text=text, bg=BAR, fg=FG, cursor="hand2",
                 padx=13, pady=6, font=("Segoe UI", 9))
    c.bind("<Button-1>", lambda e: command())
    c.pack(side="left", padx=(0, 6))
    return c


def make_panel_chip(parent, text, command, col, gap):
    "A bold edit-panel chip gridded at `col` (0/1) with `gap` px between the two."
    chip = tk.Label(parent, text=text, bg=CHIP_BG, fg=FG, cursor="hand2",
                    font=("Segoe UI", 8, "bold"), padx=4, pady=6)
    chip.bind("<Button-1>", lambda e: command())
    pad = (0, gap // 2) if col == 0 else (gap // 2, 0)
    chip.grid(row=0, column=col, sticky="ew", padx=pad)
    return chip
