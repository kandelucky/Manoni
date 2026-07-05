"""Language loading for Manoni.

The strings written in the code are ENGLISH (the app's original language); English
is the default and needs no pack. Every other language is a pack mapping each
English source string to its translation.

Georgian — the language bundled with the app — lives as DATA in langs/ka.json (the
same {code, name, strings} shape as a user-imported pack), so its wording can be
edited without touching code. Importing this module loads and registers the bundled
pack, then any user packs found in config.LANG_DIR (added via the "Add your
language" studio — see chrome.py).

A pack key must match the source string t() is called with character-for-character;
a mismatch just falls back to English. A key may carry a context prefix
("<ctx>\\u0004<source>") to give one English word two translations by place — see
i18n.t's ctx argument.

To ship another built-in language, drop its {code, name, strings} .json into langs/,
load it below, and add its (code, native_name) to i18n.LANGUAGES. (Packaged builds
must bundle the langs/ directory — it is data, not code.)
"""

import json
import os

from . import i18n
from .config import LANG_DIR

_LANGS_DIR = os.path.join(os.path.dirname(__file__), "langs")


def _load_bundled(code):
    "Load and register a language pack shipped inside the package (langs/<code>.json)."
    with open(os.path.join(_LANGS_DIR, code + ".json"), encoding="utf-8") as f:
        i18n.load_pack(json.load(f))


# Bundled Georgian first, then any user-imported packs on disk (so a language added
# via the studio survives the relaunch a language switch triggers). English is the
# default and needs no pack.
_load_bundled("ka")
_load_bundled("pl")
i18n.load_user_packs(LANG_DIR)
