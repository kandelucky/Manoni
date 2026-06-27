"""Tiny i18n for Manoni — translate UI strings at runtime.

The source strings written in the code are GEORGIAN (the app's original
language). That Georgian text is the lookup key (the "msgid"). A language pack
maps each Georgian key to its translation in another language.

The default language ("ka") needs no pack: t() returns the key unchanged. A
missing key also falls back to the key, so the UI never goes blank — at worst a
not-yet-translated string simply stays Georgian.

How to add a language: drop a {georgian_source: translation} dict into
translations.py and register it. Nothing else changes.

Why translate at runtime (not at import): so the same code can run in any
language, and so labels stored in class-level tables (e.g. VIEW_MENU) are
translated where they are *shown*, not frozen when the module is imported.
Changing the language persists the choice and relaunches the app — far simpler
and less bug-prone than re-texting every live widget. See manoni.py.
"""

# The original language the source strings are written in. Needs no pack.
DEFAULT_LANG = "ka"

# Languages offered in the menu, each shown in its OWN script (so a speaker can
# always recognise their language regardless of the current UI language). A code
# only appears in the menu once it has a registered pack (or it is the default).
LANGUAGES = [
    ("ka", "ქართული"),
    ("en", "English"),
]

_lang = DEFAULT_LANG
_catalogs = {}          # lang code -> {georgian_source: translation}


def register(lang, catalog):
    "Add (or replace) a language pack: a {georgian_source: translation} dict."
    _catalogs[lang] = dict(catalog)


def available():
    "(code, native_name) for every language that can be selected right now."
    return [(code, name) for code, name in LANGUAGES
            if code == DEFAULT_LANG or code in _catalogs]


def set_language(lang):
    "Switch the active language (ignored if there is no pack for it)."
    global _lang
    _lang = lang if (lang == DEFAULT_LANG or lang in _catalogs) else DEFAULT_LANG
    return _lang


def get_language():
    "The active language code."
    return _lang


def t(msgid):
    "Translate a Georgian source string to the active language (fallback: source)."
    if _lang == DEFAULT_LANG:
        return msgid
    return _catalogs.get(_lang, {}).get(msgid, msgid)
