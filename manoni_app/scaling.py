"""Windows DPI awareness + Tk scaling for Manoni (raw Tkinter).

The problem
-----------
Tkinter never declares the process DPI-aware on its own. So on a display
scaled above 100 % (e.g. 150 %) Windows treats the window as a legacy
96-DPI surface and **bitmap-stretches** it by the scaling factor. Crisp
96-DPI pixels blown up 1.5x read as blurry text and soft icons.

The fix mirrors what CustomTkinter does internally (CTk's `ScalingTracker`
+ its `SetProcessDpiAwareness` call): declare the process DPI-aware BEFORE
the first window exists — so Windows stops stretching and lets us draw at
the monitor's true pixels — then tell Tk the real DPI so point-sized fonts
render at their intended physical size, crisp.

Usage
-----
1. ``set_dpi_awareness()`` — call ONCE, before ``tk.Tk()``.
2. ``apply_tk_scaling(root)`` — call right after creating the root; returns
   the DPI factor so callers can scale pixel-sized assets (icons) to match.

``get_dpi_factor()`` exposes the OS multiplier (1.0 / 1.25 / 1.5 / …).
Everything is a no-op returning 1.0 off Windows — only Windows
bitmap-stretches Tk windows; macOS/Linux Tk is already crisp.
"""
from __future__ import annotations

import sys

_dpi_factor: float | None = None


def set_dpi_awareness() -> None:
    """Declare the process DPI-aware so Windows stops bitmap-stretching the
    window. Tries Per-Monitor-v2 first (rescales correctly when the window
    is dragged between monitors of different scaling), then falls back to
    System-DPI for older Windows. Must run before ``tk.Tk()``. No-op off
    Windows. Safe if called more than once (the redundant call is ignored).
    """
    if sys.platform != "win32":
        return
    import ctypes
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2 (shcore.dll, Windows 8.1+).
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()   # System-DPI aware (Vista+)
    except Exception:
        pass


def get_dpi_factor() -> float:
    """OS DPI factor as a multiplier: 96 DPI → 1.0, 125 % → 1.25, 150 % →
    1.5, etc. Cached after the first call. Returns 1.0 on non-Windows.
    """
    global _dpi_factor
    if _dpi_factor is not None:
        return _dpi_factor
    if sys.platform != "win32":
        _dpi_factor = 1.0
        return _dpi_factor
    try:
        import ctypes
        dpi = ctypes.windll.user32.GetDpiForSystem()
        _dpi_factor = max(1.0, dpi / 96.0)
    except Exception:
        _dpi_factor = 1.0
    return _dpi_factor


def apply_tk_scaling(root) -> float:
    """Set Tk's point→pixel scaling to the monitor's true DPI so point-sized
    fonts (Manoni uses positive, i.e. point, font sizes everywhere) render at
    their intended physical size now that Windows no longer stretches them.

    Tk measures fonts in points at 72 points/inch, so the scaling value is
    pixels-per-point = DPI / 72 = factor * 96 / 72. Set as an absolute value,
    so it's correct whether or not Tk pre-detected the DPI itself — no risk
    of double-scaling. Returns the DPI factor for the caller to reuse.
    """
    factor = get_dpi_factor()
    if factor != 1.0:
        root.tk.call("tk", "scaling", factor * 96.0 / 72.0)
    return factor
