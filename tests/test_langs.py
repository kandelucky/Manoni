"""Translation tests — a release must never ship a string nobody translated.

Manoni's UI strings are English source text used as pack keys (manoni_app/i18n.py).
Nothing at runtime notices when a new string is added and no pack follows: t()
quietly returns the English, and a Georgian user reads an English button. That is
how a whole Help window once stayed untranslated in both languages for months.

These checks close that hole. They read the code with the AST — see
tools/check_langs.py — and never import the app, so no state file is touched.

    python tests/test_langs.py
"""

import os
import sys
import json
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import check_langs                                       # noqa: E402

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def _packs():
    paths = check_langs.pack_paths()
    assert paths, "no language packs found at all"
    return paths


@check
def every_visible_string_is_translated():
    keys, _ = check_langs.translatable_strings()
    literals = check_langs.literal_strings()
    for path in _packs():
        r = check_langs.audit_pack(path, keys, literals)
        name = os.path.basename(path)
        assert not r["missing"], (
            f"{name} is missing {len(r['missing'])} strings, "
            f"first: {r['missing'][0]!r}")


@check
def no_pack_carries_a_dead_string():
    keys, _ = check_langs.translatable_strings()
    literals = check_langs.literal_strings()
    for path in _packs():
        r = check_langs.audit_pack(path, keys, literals)
        name = os.path.basename(path)
        assert not r["dead"], (
            f"{name} translates {len(r['dead'])} strings the code no longer has, "
            f"first: {r['dead'][0]!r}")


@check
def placeholders_and_newlines_survive_translation():
    # A translation that drops {name} from a format string raises at runtime;
    # one that loses a \n silently reflows a dialog.
    keys, _ = check_langs.translatable_strings()
    literals = check_langs.literal_strings()
    for path in _packs():
        r = check_langs.audit_pack(path, keys, literals)
        name = os.path.basename(path)
        assert not r["broken"], f"{name}: {r['broken'][0]}"


@check
def packs_agree_on_their_keys():
    # Every pack translates the same set, so a language is never a subset of
    # another by accident.
    sets = {}
    for path in _packs():
        with open(path, encoding="utf-8") as f:
            sets[os.path.basename(path)] = set(json.load(f)["strings"])
    first, keys = next(iter(sets.items()))
    for name, other in sets.items():
        assert other == keys, (
            f"{name} and {first} disagree on "
            f"{len(other ^ keys)} keys")


@check
def source_list_is_current():
    assert check_langs.source_is_current(), (
        "manoni_app/langs/_source.json no longer matches the code — "
        "run: python tools/check_langs.py --write-source")


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
