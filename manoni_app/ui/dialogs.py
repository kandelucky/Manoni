"""Shared dialog placement: center a Toplevel over the main window.

This module used to also hold `make_dialog_button` (a flat label-as-button copied
across nav / saving / filters / crop / metadata / actions). Every dialog now
builds a themed `tintkit.Button` (via each mixin's `self._dialog_btn`), so only
the centering math remains here.
"""


def center_over(root, dlg):
    "Place a Toplevel centered over the main window (no modal grab)."
    dlg.update_idletasks()
    dw, dh = dlg.winfo_width(), dlg.winfo_height()
    rx, ry = root.winfo_rootx(), root.winfo_rooty()
    rw, rh = root.winfo_width(), root.winfo_height()
    dlg.geometry(f"+{max(0, rx + (rw - dw) // 2)}+{max(0, ry + (rh - dh) // 2)}")
