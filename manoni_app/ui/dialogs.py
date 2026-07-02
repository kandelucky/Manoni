"""Shared dialog building blocks: the flat dialog button and the
center-over-the-main-window placement.

These used to be copy-pasted across nav / saving / filters / crop / metadata /
actions (several verbatim copies of the same button, plus the same centering
math). They live here once so a tweak to the look or placement lands everywhere.
"""

from ..config import BAR, HOVER, ACCENT, FG, ON_ACCENT, ACCENT_HOVER

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
