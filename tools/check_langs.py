"""Audit Manoni's language packs against the strings the code actually uses.

The source strings written in the code are ENGLISH and double as the lookup keys
of every pack (see manoni_app/i18n.py). This tool answers three questions a pack
cannot answer about itself:

  * which keys are MISSING — a string the UI shows that no pack translates, so a
    Georgian or Polish user reads it in English;
  * which keys are DEAD — a translation left behind by a string the code deleted
    or reworded, so the pack carries weight it never uses;
  * whether the {placeholders} and newlines survived translation — a pack that
    drops "{name}" from a format string makes the app raise at runtime.

Strings are collected with the AST, not by grepping. A grep misses the implicit
concatenation Python folds at parse time —

    "The app comes in English "
    "and Polish."

— which is exactly how the long help texts are written, and exactly how a whole
untranslated Help window once hid from a text search.

Two kinds of call site are collected:

  * ``t("...")`` directly, context argument included (``t("Light", "font")`` keys
    as ``font\\x04Light``, matching i18n.CTX_SEP);
  * literal arguments to any function that passes its own parameter to ``t()`` —
    ``_help_row(win, icon, title, desc)`` translates title and desc, so both are
    translatable strings even though ``t`` appears nowhere at the call site.
    These wrappers are DISCOVERED, not hard-coded: write a new one and this tool
    picks it up.

What it cannot see: ``t(variable)``, where the string arrives at runtime out of a
table (``_HELP_TABS``, ``SECTION_TITLES``, the crop tool row…). Those call sites
are listed by ``-v`` so a human can eye them. Two consequences shape this tool:

  * MISSING is judged against the strings it CAN see. A key it cannot see is
    never reported missing — better a quiet gap than a wall of false alarms.
  * DEAD is judged against every string literal in the source, table strings
    included. A translation is only dropped once its English text is gone from
    the code entirely.

So the master list in ``langs/_source.json`` is the strings the tool can see,
plus the table strings the packs already carry and the code still contains. A
brand-new table string reaches the list once any pack translates it — while the
strings ``t()`` names directly are guaranteed the moment they are written.

Usage:

    python tools/check_langs.py                  # audit every pack, exit 1 if bad
    python tools/check_langs.py -v               # …and list the dynamic call sites
    python tools/check_langs.py --write-source   # regenerate langs/_source.json
"""

import ast
import glob
import json
import os
import re
import sys

CTX_SEP = "\x04"                       # keep in step with i18n.CTX_SEP
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_FILE = os.path.join(ROOT, "manoni_app", "langs", "_source.json")
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _source_files():
    "Every .py file that can hold a UI string, in a stable order."
    out = [os.path.join(ROOT, "manoni.py")]
    for base, dirs, files in os.walk(os.path.join(ROOT, "manoni_app")):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        out += [os.path.join(base, f) for f in sorted(files) if f.endswith(".py")]
    return [p for p in out if os.path.isfile(p)]


def _find_wrappers(trees):
    "Functions that translate one of their own parameters -> {name: [param, ...]}."
    wrappers = {}
    for tree in trees.values():
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            params = [a.arg for a in fn.args.args]
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "id", None) == "t" and node.args
                        and isinstance(node.args[0], ast.Name)
                        and node.args[0].id in params):
                    wrappers.setdefault(fn.name, set()).add(node.args[0].id)
    return {n: sorted(p) for n, p in wrappers.items()}


def _param_index(trees, fname, param):
    "Position of a parameter in the first function of that name (None if absent)."
    for tree in trees.values():
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            if fn.name == fname:
                names = [a.arg for a in fn.args.args]
                return names.index(param) if param in names else None
    return None


def _const(node):
    "The string a node holds, or None. AST folds implicit concatenation for us."
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def translatable_strings(root=ROOT):
    "Every translatable key in the source -> (keys, dynamic_call_sites)."
    trees = {}
    for path in _source_files():
        with open(path, encoding="utf-8") as f:
            trees[path] = ast.parse(f.read(), filename=path)

    wrappers = _find_wrappers(trees)
    slots = {}                                  # wrapper name -> [param positions]
    for name, params in wrappers.items():
        idx = [_param_index(trees, name, p) for p in params]
        slots[name] = ([i for i in idx if i is not None], params)

    keys, dynamic = set(), []
    for path, tree in trees.items():
        rel = os.path.relpath(path, root)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else "")
            if name == "t" and node.args:
                src = _const(node.args[0])
                if src is None:
                    dynamic.append((rel, node.lineno))
                    continue
                ctx = None
                if len(node.args) > 1:
                    ctx = _const(node.args[1])
                for kw in node.keywords:
                    if kw.arg == "ctx":
                        ctx = _const(kw.value)
                keys.add(ctx + CTX_SEP + src if ctx else src)
            elif name in slots:
                positions, params = slots[name]
                # A method call omits self, so its arguments sit one slot to the left.
                args = ([None] + list(node.args) if isinstance(func, ast.Attribute)
                        else list(node.args))
                for i in positions:
                    if i < len(args) and args[i] is not None:
                        val = _const(args[i])
                        if val:
                            keys.add(val)
                for kw in node.keywords:
                    if kw.arg in params and _const(kw.value):
                        keys.add(_const(kw.value))
    return keys, dynamic


def literal_strings(root=ROOT):
    "Every string literal in the source — the loose net a DEAD key must escape."
    out = set()
    for path in _source_files():
        with open(path, encoding="utf-8") as f:
            for node in ast.walk(ast.parse(f.read(), filename=path)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    out.add(node.value)
    return out


def _bare(key):
    "A key without its optional context prefix — the literal the source holds."
    return key.split(CTX_SEP)[-1]


def master_strings(root=ROOT):
    "Every key a translator should see: the visible ones, plus live table strings"
    " the packs already carry. Ordered by where each appears in the source."
    keys, _ = translatable_strings(root)
    literals = literal_strings(root)
    for path in pack_paths(root):
        with open(path, encoding="utf-8") as f:
            for key in json.load(f)["strings"]:
                if _bare(key) in literals:
                    keys.add(key)

    ordered, seen = [], set()
    for path in _source_files():
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        for node in sorted((n for n in ast.walk(tree) if isinstance(n, ast.Constant)),
                           key=lambda n: (n.lineno, n.col_offset)):
            v = node.value
            if isinstance(v, str) and v in keys and v not in seen:
                seen.add(v)
                ordered.append(v)
    # Context-qualified keys hold no bare literal of their own; append them last.
    ordered += sorted(k for k in keys if k not in seen)
    return ordered


def pack_paths(root=ROOT):
    "Every pack to audit: the bundled ones, plus the downloadable .mnl packs."
    bundled = sorted(glob.glob(os.path.join(root, "manoni_app", "langs", "*.json")))
    bundled = [p for p in bundled if not os.path.basename(p).startswith("_")]
    return bundled + sorted(glob.glob(os.path.join(root, "language-packs", "*.mnl")))


def audit_pack(path, keys, literals):
    "Compare one pack against the source -> a dict of problems (all lists)."
    with open(path, encoding="utf-8") as f:
        strings = json.load(f)["strings"]
    broken = []
    for key, val in strings.items():
        if set(PLACEHOLDER.findall(key)) != set(PLACEHOLDER.findall(val)):
            broken.append((key, "placeholder"))
        elif key.count("\n") != val.count("\n"):
            broken.append((key, "newline"))
    return {
        "path": path,
        "count": len(strings),
        "missing": sorted(keys - set(strings)),
        "dead": sorted(k for k in strings if _bare(k) not in literals),
        "broken": broken,
    }


def _write_source(keys_in_order):
    payload = {"manoni_source": 1, "strings": keys_in_order}
    with open(SOURCE_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(payload, ensure_ascii=False, indent=2))
    return SOURCE_FILE


def source_is_current(root=ROOT):
    "True when langs/_source.json matches the strings in the code right now."
    if not os.path.isfile(SOURCE_FILE):
        return False
    with open(SOURCE_FILE, encoding="utf-8") as f:
        return json.load(f).get("strings") == master_strings(root)


def main(argv):
    keys, dynamic = translatable_strings()
    literals = literal_strings()
    print(f"{len(keys)} translatable strings in the source"
          f"  ({len(dynamic)} dynamic t(var) call sites)")

    if "--write-source" in argv:
        master = master_strings()
        print(f"wrote {os.path.relpath(_write_source(master), ROOT)}"
              f" — {len(master)} strings")
        return 0

    bad = 0
    for path in pack_paths():
        r = audit_pack(path, keys, literals)
        rel = os.path.relpath(path, ROOT)
        flaws = len(r["missing"]) + len(r["dead"]) + len(r["broken"])
        bad += flaws
        print(f"\n{rel} — {r['count']} strings, "
              f"{'clean' if not flaws else str(flaws) + ' problems'}")
        for key in r["missing"]:
            print(f"  MISSING  {key!r}")
        for key in r["dead"]:
            print(f"  DEAD     {key!r}")
        for key, why in r["broken"]:
            print(f"  {why.upper():8} {key!r}")

    if not source_is_current():
        bad += 1
        print("\nlangs/_source.json is stale — run with --write-source")

    if "-v" in argv and dynamic:
        print("\nDynamic t(var) call sites — check these by eye:")
        for rel, line in dynamic:
            print(f"  {rel}:{line}")

    print("\nall packs clean" if not bad else f"\n{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
