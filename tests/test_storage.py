"""Data-safety tests for manoni_app.storage — the disk helpers that must never
lose the user's data (save_json atomic write, unique_path no-clobber).

All writes go to a throwaway temp directory; the real state / filter / action
files are never touched. Run:

    python tests/test_storage.py
"""

import os
import sys
import json
import glob
import shutil
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from manoni_app.storage import save_json, unique_path    # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def save_json_writes_and_roundtrips():
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "state.json")
        assert save_json(p, {"a": 1, "unicode": "日本語 café"}) is True, "save returned False"
        with open(p, encoding="utf-8") as f:
            assert json.load(f) == {"a": 1, "unicode": "日本語 café"}, "content did not round-trip"
    finally:
        shutil.rmtree(d, ignore_errors=True)


@check
def save_json_overwrites_on_success():
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "state.json")
        save_json(p, {"v": 1})
        save_json(p, {"v": 2})
        with open(p, encoding="utf-8") as f:
            assert json.load(f)["v"] == 2, "second save did not replace the first"
    finally:
        shutil.rmtree(d, ignore_errors=True)


@check
def save_json_failure_keeps_old_file_and_no_temp():
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "state.json")
        save_json(p, {"good": True})                    # a valid existing file
        # object() is not JSON-serializable -> json.dump raises mid-write.
        ok = save_json(p, {"bad": object()})
        assert ok is False, "a failed save must report False"
        with open(p, encoding="utf-8") as f:
            assert json.load(f) == {"good": True}, "failed save corrupted the old file"
        assert not glob.glob(os.path.join(d, "*.tmp")), "a temp file was left behind"
    finally:
        shutil.rmtree(d, ignore_errors=True)


@check
def unique_path_never_clobbers():
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "photo.jpg")
        assert unique_path(p) == p, "a free name should be returned unchanged"
        open(p, "w").close()                            # now it exists
        p1 = unique_path(p)
        assert p1 == os.path.join(d, "photo (1).jpg"), f"first clash wrong: {p1}"
        open(p1, "w").close()
        p2 = unique_path(p)
        assert p2 == os.path.join(d, "photo (2).jpg"), f"second clash wrong: {p2}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    passed = failed = 0
    for fn in CHECKS:
        try:
            fn()
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
            if "-v" in sys.argv:
                traceback.print_exc()
        else:
            passed += 1
            print(f"pass  {fn.__name__}")
    print(f"\n{passed} passed, {failed} failed, of {len(CHECKS)} checks.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
