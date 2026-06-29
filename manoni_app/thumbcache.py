"""Persistent thumbnail cache for Manoni — decode each image once, reuse forever.

Why this exists: opening a folder used to re-decode every full-resolution photo
into a thumbnail on every load, resize, cull *or* relaunch (see
``browser._build_thumbs`` / ``gridview._build_grid_thumbs``). On a weak laptop a
folder of hundreds of JPEG/RAW files took many seconds, and every small change —
a different thumbnail size, a moved file, reopening the app — paid the full cost
again. This stores each decoded thumbnail (as WebP bytes) in a single SQLite file
under the user's app-data cache dir, keyed by the file path + thumbnail size and
validated against the source's mtime + byte size. A second open is a cheap blob
read, not a decode.

It follows the freedesktop Thumbnail Managing Standard where it matters:

  * Validation is EXACT equality on mtime *and* size — never ``file.mtime >
    cached.mtime``. A file restored from a backup has an OLDER mtime, so a ``>``
    check would keep serving a stale thumbnail. See
    https://specifications.freedesktop.org/thumbnail/latest-single/ .
  * A failed decode is itself cached (``failed=1``) so a corrupt / unreadable
    file is not re-attempted on every folder open (the spec's ``fail/`` dir).
  * Writes are atomic at the SQLite level (one committed transaction).

Beyond the spec we add an LRU byte cap: deleted or renamed photos leave orphan
rows that mtime/size validation can never reach, so when the cache outgrows
``max_bytes`` the least-recently-used rows are evicted oldest-first.

The cache is BEST-EFFORT: any SQLite error degrades silently to a direct decode,
so a locked / full / read-only cache can never break thumbnail loading.
"""

import hashlib
import io
import os
import sqlite3
import sys
import threading
import time
from collections import OrderedDict

from PIL import Image

# Sentinel: a cache lookup that is neither a hit nor a cached failure — the
# caller must decode. (None already means "a cached failure: don't decode".)
_MISS = object()

# How many puts between LRU sweeps, and how stale last_used may get before a hit
# bothers to rewrite it (avoids a DB write on every single cache hit).
_PRUNE_EVERY = 256
_TOUCH_AFTER = 86400  # seconds


def decode_thumb(path, tsize):
    "Open + downscale one image to a <=tsize RGB thumbnail (no Tk, no cache). Runs"
    " in a worker thread; returns a PIL image, or None if the file can't be read."
    try:
        with Image.open(path) as im:
            # draft() lets the JPEG decoder load at a reduced scale (no-op for
            # other formats) — far faster, especially feeding the parallel decode.
            im.draft("RGB", (tsize, tsize))
            im.thumbnail((tsize, tsize))
            return im.convert("RGB")
    except Exception:
        return None


def _default_db_path():
    "Per-OS app-data cache location for the thumbnail database (regenerable data)."
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "Manoni", "Cache")
    elif sys.platform == "darwin":
        d = os.path.join(os.path.expanduser("~/Library/Caches"), "Manoni")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        d = os.path.join(base, "manoni")
    return os.path.join(d, "thumbnails.db")


def _key(path, px):
    "Cache key: sha1 of the case-normalised absolute path + thumbnail size."
    # normcase lowercases + unifies slashes on Windows (so C:\\Foo and c:/foo
    # share one entry); it is a no-op on POSIX. px in the key keeps each
    # thumbnail size a separate entry, matching the spec's size directories.
    norm = os.path.normcase(os.path.abspath(path))
    return hashlib.sha1(f"{norm}|{px}".encode("utf-8")).hexdigest()


# Fixed thumbnail size buckets (px). Every requested display size is rounded UP to
# one of these, so a photo is decoded at most len(_BUCKETS) times EVER — zooming
# the tiles or nudging a size re-derives from a bucket master instead of decoding
# the whole folder again. Tuned to cover the sidebar strip (72–240) and the
# culling grid (110–360 logical, ×DPI) without an oversized top tier. (This mirrors
# the freedesktop spec's discrete normal/large/x-large/xx-large sizes.)
_BUCKETS = (128, 256, 448, 640)


def _bucket_for(px):
    "The smallest bucket >= px (or the largest bucket when px exceeds them all)."
    for b in _BUCKETS:
        if b >= px:
            return b
    return _BUCKETS[-1]


def _pil_to_blob(pil):
    "Encode a thumbnail to compact bytes (WebP, PNG fallback); None on failure."
    for fmt, kw in (("WEBP", {"quality": 80, "method": 2}), ("PNG", {})):
        try:
            buf = io.BytesIO()
            pil.save(buf, format=fmt, **kw)
            return buf.getvalue()
        except Exception:
            continue
    return None


def _blob_to_pil(blob):
    "Decode cached bytes back to an RGB PIL image; None if the blob is bad."
    if not blob:
        return None
    try:
        im = Image.open(io.BytesIO(blob))
        im.load()
        return im.convert("RGB")
    except Exception:
        return None


def _pil_bytes(pil):
    "Rough in-memory footprint of a PIL image, for the LRU byte budget."
    try:
        w, h = pil.size
        return w * h * len(pil.getbands())
    except Exception:
        return 0


def _fit(pil, px):
    "Downscale a bucket master to fit a ``px`` box (never upscales). None passes"
    " through. Copies before shrinking so the shared cached master is never mutated."
    if pil is None:
        return None
    if max(pil.size) <= px:
        return pil
    out = pil.copy()
    out.thumbnail((px, px))
    return out


class ThumbCache:
    "SQLite-backed thumbnail store. Thread-safe; all DB access is best-effort."

    def __init__(self, db_path=None, max_bytes=500 * 1024 * 1024,
                 mem_bytes=192 * 1024 * 1024):
        self.db_path = db_path or _default_db_path()
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._conn = None
        self._puts = 0
        # ONE shared in-memory thumbnail cache for every window (the sidebar strip
        # and the culling grid both reach it through cached_thumb), so a decoded
        # thumbnail is reused instead of re-read from disk on each rebuild. Keyed by
        # (case-normalised path, size); LRU-evicted by a byte budget — an eviction
        # just falls back to the (fast) disk blob, never a full decode. Validated by
        # mtime+size on read, so a changed file is never served stale.
        self._mem = OrderedDict()        # (normcase_path, px) -> (mtime_ns, fsize, PIL)
        self._mem_bytes = 0
        self._mem_max_bytes = mem_bytes
        self._mem_lock = threading.Lock()
        self._open()

    def _open(self):
        "Open (creating if needed) the cache DB. On any error, disable the cache."
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5)
            conn.execute("PRAGMA journal_mode=WAL")      # concurrent reads + a writer
            conn.execute("PRAGMA synchronous=NORMAL")    # fast, still crash-safe with WAL
            conn.execute(
                "CREATE TABLE IF NOT EXISTS thumbs ("
                "  key TEXT PRIMARY KEY,"   # sha1(normcase(abspath) + '|' + px)
                "  uri TEXT,"               # the abspath itself (debug / collision guard)
                "  mtime_ns INTEGER,"       # source st_mtime_ns at decode time
                "  fsize INTEGER,"          # source st_size at decode time
                "  px INTEGER,"             # thumbnail box size
                "  blob BLOB,"              # encoded thumbnail bytes (NULL when failed)
                "  failed INTEGER DEFAULT 0,"  # 1 = source couldn't be decoded
                "  last_used INTEGER)")     # epoch seconds, for LRU eviction
            conn.commit()
            self._conn = conn
        except sqlite3.Error:
            self._conn = None

    # --- public ----------------------------------------------------------------

    def cached_thumb(self, path, px):
        "Return a thumbnail for ``path`` sized to fit a ``px`` box. The image is"
        " decoded ONCE per size bucket (see _BUCKETS) and stored; any requested px is"
        " served by downscaling that bucket master in memory — so changing the"
        " display size re-derives, it never re-decodes. Returns a PIL image, or None"
        " if the file can't be read. Drop-in for the old browser._decode_thumb."
        try:
            st = os.stat(path)
        except OSError:
            return None
        master = self._master(path, st, _bucket_for(px))
        return _fit(master, px)              # None (unreadable / failed) passes through

    def _master(self, path, st, bucket):
        "The decode-once master thumbnail for one size bucket: shared in memory,"
        " backed by disk, decoded only on a cold miss. None = unreadable / failed."
        nkey = (os.path.normcase(os.path.abspath(path)), bucket)
        m = self._mem_get(nkey, st)          # shared in-memory hit (both windows)
        if m is not None:
            return m
        key = _key(path, bucket)
        hit = self._lookup(key, st, bucket)
        if hit is _MISS:                     # cold → decode at the bucket size, store
            m = decode_thumb(path, bucket)   # OUTSIDE the lock: the pool stays parallel
            self._store(key, path, st, bucket, m)
        else:
            m = hit                          # a PIL master, or None for a cached failure
        if m is not None:
            self._mem_put(nkey, st, m)
        return m

    def close(self):
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

    # --- shared in-memory layer ------------------------------------------------

    def _mem_get(self, nkey, st):
        "Return a memory-cached PIL thumb if present AND still valid (mtime+size),"
        " else None. A stale entry is dropped so the caller re-reads disk/decodes."
        with self._mem_lock:
            e = self._mem.get(nkey)
            if e is None:
                return None
            mtime_ns, fsize, pil = e
            if mtime_ns != st.st_mtime_ns or fsize != st.st_size:
                del self._mem[nkey]
                self._mem_bytes -= _pil_bytes(pil)
                return None
            self._mem.move_to_end(nkey)      # mark most-recently-used
            return pil

    def _mem_put(self, nkey, st, pil):
        "Insert/replace a thumbnail in the shared memory cache; evict LRU over cap."
        if self._mem_max_bytes <= 0:
            return
        nbytes = _pil_bytes(pil)
        with self._mem_lock:
            old = self._mem.pop(nkey, None)
            if old is not None:
                self._mem_bytes -= _pil_bytes(old[2])
            self._mem[nkey] = (st.st_mtime_ns, st.st_size, pil)
            self._mem_bytes += nbytes
            while self._mem_bytes > self._mem_max_bytes and len(self._mem) > 1:
                _, ev = self._mem.popitem(last=False)   # drop least-recently-used
                self._mem_bytes -= _pil_bytes(ev[2])

    # --- internals -------------------------------------------------------------

    def _lookup(self, key, st, px):
        "Validated read: a PIL image / None (cached failure) on a fresh hit, else"
        " _MISS (not present, stale, or a corrupt blob) so the caller re-decodes."
        if self._conn is None:
            return _MISS
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT mtime_ns, fsize, px, blob, failed, last_used "
                    "FROM thumbs WHERE key=?", (key,)).fetchone()
            if row is None:
                return _MISS
            mtime_ns, fsize, rpx, blob, failed, last_used = row
            # EXACT equality (not '>'): a backup-restored file with an older mtime
            # must invalidate, never reuse a stale thumbnail.
            if mtime_ns != st.st_mtime_ns or fsize != st.st_size or rpx != px:
                return _MISS
            now = int(time.time())
            if last_used is None or now - last_used > _TOUCH_AFTER:
                self._touch(key, now)        # keep LRU roughly fresh, but rarely write
            if failed:
                return None                  # known-bad source → don't retry the decode
            img = _blob_to_pil(blob)
            return img if img is not None else _MISS  # corrupt blob → re-decode
        except sqlite3.Error:
            return _MISS

    def _touch(self, key, now):
        try:
            with self._lock:
                self._conn.execute(
                    "UPDATE thumbs SET last_used=? WHERE key=?", (now, key))
                self._conn.commit()
        except sqlite3.Error:
            pass

    def _store(self, key, path, st, px, pil):
        "Upsert a decoded thumbnail (or record a failure when pil is None)."
        if self._conn is None:
            return
        if pil is None:
            blob, failed = None, 1
        else:
            blob = _pil_to_blob(pil)
            if blob is None:
                return                       # couldn't encode → just skip caching it
            failed = 0
        now = int(time.time())
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO thumbs "
                    "(key, uri, mtime_ns, fsize, px, blob, failed, last_used) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (key, os.path.normcase(os.path.abspath(path)),
                     st.st_mtime_ns, st.st_size, px, blob, failed, now))
                self._conn.commit()
                self._puts += 1
                due = self._puts >= _PRUNE_EVERY
            if due:
                self.prune()
        except sqlite3.Error:
            pass

    def prune(self):
        "Evict least-recently-used rows until the total blob size is under the cap."
        if self._conn is None:
            return
        try:
            with self._lock:
                self._puts = 0
                total = self._conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(blob)), 0) FROM thumbs").fetchone()[0]
                if total <= self.max_bytes:
                    return
                target = int(self.max_bytes * 0.9)   # drop to 90% so we don't sweep every put
                doomed, freed = [], 0
                for key, n in self._conn.execute(
                        "SELECT key, LENGTH(blob) FROM thumbs ORDER BY last_used ASC"):
                    doomed.append((key,))
                    freed += (n or 0)
                    if total - freed <= target:
                        break
                self._conn.executemany("DELETE FROM thumbs WHERE key=?", doomed)
                self._conn.commit()
        except sqlite3.Error:
            pass


# --- module-level singleton (one cache per process) ----------------------------

_cache = None
_cache_lock = threading.Lock()


def get_cache():
    "The process-wide ThumbCache, created on first use (double-checked locking)."
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = ThumbCache()
    return _cache


def cached_thumb(path, tsize):
    "Cache-or-decode one thumbnail. Drop-in replacement for browser._decode_thumb."
    return get_cache().cached_thumb(path, tsize)
