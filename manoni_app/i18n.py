"""Tiny i18n for Manoni — translate UI strings at runtime.

The source strings written in the code are ENGLISH (the app's original
language). That English text is the lookup key (the "msgid"). A language pack
maps each English key to its translation in another language.

The default language ("en") needs no pack: t() returns the key unchanged. A
missing key also falls back to the key, so the UI never goes blank — at worst a
not-yet-translated string simply stays English.

How to add a language: drop an {english_source: translation} dict into
translations.py and register it — or, at runtime, import a JSON pack from the
☰ → Language → "Add your language" studio (see chrome.py). User packs live in
config.LANG_DIR and are re-registered on every launch by translations.py.

Why translate at runtime (not at import): so the same code can run in any
language, and so labels stored in class-level tables (e.g. VIEW_MENU) are
translated where they are *shown*, not frozen when the module is imported.
Changing the language persists the choice and relaunches the app — far simpler
and less bug-prone than re-texting every live widget. See manoni.py.
"""

# The original language the source strings are written in. Needs no pack.
DEFAULT_LANG = "en"

# Built-in languages, each shown in its OWN script (so a speaker can always
# recognise their language regardless of the current UI language), in menu order.
# A code only appears in the menu once it has a registered pack (or is default).
# User-imported packs are added on top of these at runtime (see load_user_packs).
LANGUAGES = [
    ("en", "English"),
    ("pl", "Polski"),
]

_lang = DEFAULT_LANG
_catalogs = {}          # lang code -> {english_source: translation}
_names = dict(LANGUAGES)  # lang code -> native name (built-ins + user packs)


def register(lang, catalog, name=None):
    "Add (or replace) a language pack: an {english_source: translation} dict."
    _catalogs[lang] = dict(catalog)
    if name:
        _names[lang] = name


def available():
    "(code, native_name) for every selectable language — built-ins first, then"
    " any imported packs sorted by name."
    out, seen = [], set()
    for code, name in LANGUAGES:
        if code == DEFAULT_LANG or code in _catalogs:
            out.append((code, name))
            seen.add(code)
    extra = [(c, _names.get(c, c)) for c in _catalogs if c not in seen]
    out.extend(sorted(extra, key=lambda cn: cn[1].lower()))
    return out


def native_name(code):
    "The language's own-script name (falls back to the code itself)."
    return _names.get(code, code)


def catalog(lang):
    "A copy of a language's {source: translation} pack (empty for default/unknown)."
    return dict(_catalogs.get(lang, {}))


def source_strings():
    "Every English source string known to any pack — the master translatable set."
    keys = set()
    for cat in _catalogs.values():
        keys.update(cat.keys())
    return sorted(keys)


def load_pack(data):
    "Validate a {code, name, strings} pack dict and register it. Returns (code,"
    " name). Raises ValueError if the shape is wrong."
    if not isinstance(data, dict):
        raise ValueError("not a language pack")
    code = str(data.get("code") or "").strip()
    name = str(data.get("name") or "").strip()
    strings = data.get("strings")
    if not code or not isinstance(strings, dict):
        raise ValueError("a pack needs a non-empty 'code' and a 'strings' object")
    clean = {str(k): str(v) for k, v in strings.items() if isinstance(v, str)}
    register(code, clean, name or code)
    return code, _names.get(code, code)


def load_user_packs(directory):
    "Register every {code,name,strings} JSON pack found in a directory (best"
    " effort — a malformed file is skipped, never fatal)."
    import json
    import os
    import glob
    if not directory or not os.path.isdir(directory):
        return
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                load_pack(json.load(f))
        except Exception:
            pass


def set_language(lang):
    "Switch the active language (ignored if there is no pack for it)."
    global _lang
    _lang = lang if (lang == DEFAULT_LANG or lang in _catalogs) else DEFAULT_LANG
    return _lang


def get_language():
    "The active language code."
    return _lang


CTX_SEP = "\x04"  # separates an optional context from the source (gettext msgctxt style)


def t(msgid, ctx=None):
    """Translate an English source string to the active language (fallback: source).

    Pass ctx to disambiguate one English word that needs different translations in
    different places — e.g. t("Light", "font") vs t("Light", "sharpen"). English is
    unaffected (both still show "Light"); only a pack keys on the context. Lookup
    order: context-qualified key, then the plain key, then the source string.
    """
    if _lang == DEFAULT_LANG:
        return msgid
    cat = _catalogs.get(_lang, {})
    if ctx is not None:
        hit = cat.get(ctx + CTX_SEP + msgid)
        if hit is not None:
            return hit
    return cat.get(msgid, msgid)
