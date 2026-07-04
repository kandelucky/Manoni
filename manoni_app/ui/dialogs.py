"""Shared dialog placement: center a Toplevel over the main window.

This module used to also hold `make_dialog_button` (a flat label-as-button copied
across nav / saving / filters / crop / metadata / actions). Every dialog now
builds a themed `tintkit.Button` (via each mixin's `self._dialog_btn`), so only
the centering math remains here.

Centring is also where keyboard navigation is switched on: every modal dialog
routes through `center_over`, so wiring the arrow-key / Enter button traversal
here gives it to all of them for free.
"""

from ..widgets import enable_dialog_button_nav


def center_over(root, dlg):
    "Place a Toplevel centered over the main window (no modal grab)."
    dlg.update_idletasks()
    dw, dh = dlg.winfo_width(), dlg.winfo_height()
    rx, ry = root.winfo_rootx(), root.winfo_rooty()
    rw, rh = root.winfo_width(), root.winfo_height()
    dlg.geometry(f"+{max(0, rx + (rw - dw) // 2)}+{max(0, ry + (rh - dh) // 2)}")
    enable_dialog_button_nav(dlg)               # ←/→/↑/↓ move focus, Enter fires
