"""Tiny disk-safety helpers for Manoni — save files without losing data.

Two ways a naive save destroys data, both fixed here:

* ``save_json`` — ``open(path, "w"); json.dump(...)`` truncates the target the
  instant it opens it, so a crash / full disk / error mid-write leaves a
  half-written file and the user's data is gone. We write a temp file in the SAME
  directory first, then atomically rename it over the target (``os.replace``): the
  real file is always either the old good copy or the new good copy, never a
  truncated one. Returns True/False so callers can warn on a failed save.

* ``unique_path`` — saving to a name that already exists silently overwrites
  whatever was there (e.g. a folder batch where ``a.jpg`` and ``a.png`` both map
  to ``a.jpg``, or a typed save-as name that clashes with another file). We append
  ``" (1)"``, ``" (2)"`` … before the extension until the name is free, so a save
  never clobbers an existing file.
"""

import json
import os
import tempfile


def unique_path(path):
    """Return ``path`` if nothing is there, else the same name with ``" (1)"``,
    ``" (2)"`` … inserted before the extension until it doesn't collide. A save
    therefore never silently overwrites an existing file."""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 1
    while True:
        candidate = f"{root} ({n}){ext}"
        if not os.path.exists(candidate):
            return candidate
        n += 1


def save_json(path, data):
    """Atomically write ``data`` as pretty UTF-8 JSON to ``path``.

    Returns True on success, False on any failure. On failure the existing file
    (if any) is left untouched and the temp file is cleaned up.
    """
    directory = os.path.dirname(path) or "."
    tmp = None
    try:
        # Temp file in the same directory so os.replace is a true atomic rename
        # (a cross-filesystem move would not be atomic).
        fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False
