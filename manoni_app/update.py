"""Manual update check: ask GitHub for the latest release and compare versions.

There is NO background / automatic checking anywhere — the network is only ever
touched when the user clicks "Check for updates" in Settings → About. That keeps
the app fully offline until the user asks, so there is nothing to explain about
why it connects and no timer / thread running on launch.

Uses only the standard library (urllib), so it adds no dependency. The one call
here is blocking; the UI runs it on a short-lived daemon thread and marshals the
result back with root.after (see settings._set_tab_about).
"""

import json
import urllib.request

# The public releases feed. `/releases/latest` is the newest NON-prerelease tag.
REPO = "kandelucky/Manoni"
LATEST_API = "https://api.github.com/repos/{}/releases/latest".format(REPO)
RELEASES_PAGE = "https://github.com/{}/releases/latest".format(REPO)

_TIMEOUT = 8  # seconds — a click that hangs on a bad connection should give up


def _parse(ver):
    "Turn '1.10.2' (or 'v1.10.2') into a comparable (1, 10, 2) tuple."
    ver = (ver or "").strip().lstrip("vV")
    out = []
    for part in ver.split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(latest, current):
    "True if release string `latest` is a newer version than `current`."
    return _parse(latest) > _parse(current)


def fetch_latest_version():
    """Return the latest release's version string (no leading 'v'), e.g. '1.2.0'.

    Raises on any network / parse error — the caller turns that into a friendly
    'couldn't check' message. GitHub wants a User-Agent on API requests.
    """
    req = urllib.request.Request(
        LATEST_API,
        headers={"User-Agent": "Manoni", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = (data.get("tag_name") or data.get("name") or "").strip()
    if not tag:
        raise ValueError("no tag_name in release")
    return tag.lstrip("vV")
