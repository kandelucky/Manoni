"""Windows-only fix for non-Latin (Georgian, etc.) keyboard typing in Tk.

Root cause, found 2026-07-04 debugging Georgian filter names showing as "?":
Tcl's own "encoding system utf-8" fix (see manoni.py) makes *programmatic*
text (widget.insert()/.get(), file I/O) round-trip Georgian correctly, but a
*typed* keystroke for a character outside the Windows system ANSI code page
(here cp1250, which has no Georgian) still arrives at Tk's Entry/Text widgets
as a literal "?" — proven by comparing a directly-posted Unicode WM_CHAR
(round-trips perfectly) against real typing (doesn't). The loss happens
somewhere between the physical keydown and Tk's own character synthesis, a
path Tcl's "encoding system" setting doesn't reach. A per-machine Windows
setting (System locale → "Beta: UTF-8 worldwide language support") is the
usual fix for this class of bug, but that only helps the one machine it's
set on — this app should work for every user out of the box instead.

Fix: a thread-local WH_KEYBOARD hook intercepts each keydown BEFORE Tk/Windows
synthesize their own (lossy) character, re-translates it ourselves with the
real Unicode API (ToUnicodeEx — verified correct for every loaded layout,
Georgian included), and inserts the correct character straight into whichever
Entry/Text currently holds Tk's input focus, swallowing the original keydown
so Tk never sees the mangled version. It only steps in when our own
translation yields a non-ASCII character — plain English/number typing, and
every keyboard shortcut, is untouched.

2026-07-04 crash fix: the first cut left every user32/kernel32 call without
explicit argtypes/restype. ctypes then guesses a plain 32-bit c_int for
handle-sized (HKL/HHOOK, pointer-width on 64-bit Windows) values — right for
some numeric HKLs, silent stack corruption for others, which is exactly why
one keyboard layout worked and a second one crashed the app. Every call below
now has an explicit, correctly-sized signature, and the hook callback itself
never lets a Python exception cross back into the native caller.
"""

import os
import sys
import ctypes
from ctypes import wintypes
import tkinter as tk

_WH_KEYBOARD = 2
_HC_ACTION = 0

_installed = False   # install() is a no-op after the first call (one hook/app)
_LRESULT = ctypes.c_ssize_t   # pointer-width on both 32- and 64-bit Windows


def _bind_signatures(user32, kernel32):
    "Explicit argtypes/restype for every foreign call — see the 2026-07-04 note."
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.CallNextHookEx.argtypes = [
        wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = _LRESULT
    user32.GetKeyboardState.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
    user32.GetKeyboardState.restype = wintypes.BOOL
    user32.ToUnicodeEx.argtypes = [
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ubyte),
        wintypes.LPWSTR, ctypes.c_int, wintypes.UINT, wintypes.HKL]
    user32.ToUnicodeEx.restype = ctypes.c_int
    user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
    user32.GetKeyboardLayout.restype = wintypes.HKL
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def _to_unicode(vk, scancode, hkl, user32):
    "The character this key actually produces, via the real Unicode API —"
    " unaffected by the legacy ANSI code page that mangles live typing."
    state = (ctypes.c_ubyte * 256)()
    if not user32.GetKeyboardState(state):
        return None
    buf = ctypes.create_unicode_buffer(8)
    n = user32.ToUnicodeEx(vk, scancode, state, buf, 8, 0, hkl)
    if n <= 0 or n > 1:      # skip dead keys (n<0) / multi-char results
        return None
    return buf.value


def _insert_into_focused(root, text):
    "Insert text at the caret of whichever Entry/Text currently has Tk focus."
    w = root.focus_get()
    if isinstance(w, tk.Entry):
        if w.selection_present():
            w.delete("sel.first", "sel.last")
        w.insert("insert", text)
    elif isinstance(w, tk.Text):
        try:
            if w.tag_ranges("sel"):
                w.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        w.insert("insert", text)


def install(root):
    "Install the fix for this Tk root's thread. Safe to call once at startup;"
    " a no-op on non-Windows or if already installed."
    global _installed
    if _installed or os.name != "nt":
        return
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        _bind_signatures(user32, kernel32)

        HOOKPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM)
        state = {"hook": None}

        def proc(nCode, wParam, lParam):
            try:
                if nCode == _HC_ACTION and (lParam >> 31) & 1 == 0:  # key DOWN
                    vk, scancode = wParam, (lParam >> 16) & 0xFF
                    hkl = user32.GetKeyboardLayout(kernel32.GetCurrentThreadId())
                    fixed = _to_unicode(vk, scancode, hkl, user32)
                    if fixed and ord(fixed) > 0x7F:
                        root.after_idle(_insert_into_focused, root, fixed)
                        return 1   # swallow — Tk never sees the mangled version
            except Exception:
                pass   # never let a Python error cross back into native code
            return user32.CallNextHookEx(state["hook"], nCode, wParam, lParam)

        callback = HOOKPROC(proc)
        thread_id = kernel32.GetCurrentThreadId()
        hook = user32.SetWindowsHookExW(_WH_KEYBOARD, callback, None, thread_id)
        if not hook:
            return
        state["hook"] = hook
        # Keep the hook handle + native callback trampoline alive for the
        # app's life (tied to root so it isn't GC'd out from under Windows).
        root._win_unicode_keys_hook = (hook, callback)
        _installed = True
    except Exception:
        print("win_unicode_keys: install failed, Georgian typing may still "
              "show '?' — continuing without the fix", file=sys.stderr)
