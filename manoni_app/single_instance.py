"""Single-instance guard: a second launch hands its file to the first window.

Manoni should feel like one app. When you "Open with Manoni" a photo while a
Manoni window is already open, we don't want a second window — we want that
photo to open in the window you already have. This module does that with a tiny
loopback socket: the first instance BINDS a fixed local port (127.0.0.1 only,
never the network — so no firewall prompt); every later launch finds the port
taken, connects, forwards its file path, and exits without building a window.

Threading note: the listener runs on a daemon thread and NEVER touches Tk. It
drops received paths onto a Queue that the UI drains from the Tk thread via
root.after — the same worker -> queue -> after pattern viewer.py's render worker
uses, because Tcl/Tk is not thread-safe and a stray socket event must not touch
it directly.
"""

import socket
import threading
import queue

HOST = "127.0.0.1"
# Fixed port that means "Manoni is running". Kept BELOW 49152 on purpose: the
# 49152-65535 range is Windows' ephemeral pool, which the OS hands out to any
# app's outbound sockets — a fixed port up there would intermittently be stolen
# and our bind would flakily fail. 47923 is in the quiet registered range.
PORT = 47923
_MAGIC = "MANONI-OPEN"   # handshake's first line; guards against a foreign
                         # process that happens to hold the same port
_POLL_MS = 200           # how often the UI thread drains forwarded paths


def try_become_primary():
    "Claim the port. Returns a listening socket, or None if another Manoni holds it."
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # No SO_REUSEADDR on purpose: we WANT bind to fail when another instance
    # already holds the port — that failure is exactly how we detect it.
    try:
        s.bind((HOST, PORT))
        s.listen(8)
        return s
    except OSError:
        s.close()
        return None


def forward(path):
    "Hand `path` (may be None) to the running instance. Returns True if it acknowledged."
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0) as c:
            c.settimeout(1.0)
            c.sendall((_MAGIC + "\n" + (path or "") + "\n").encode("utf-8"))
            return c.recv(16).startswith(b"OK")
    except OSError:
        return False


def start_listener(server):
    """Start accepting + ACKing forwarded paths RIGHT AWAY, before the window is
    built. Returns a queue the received paths land on.

    This runs the instant we claim the port — not after Manoni finishes building
    — so a second launch that races the first one's startup still gets its OK and
    its path queued (the window drains it once it exists). Needs no Tk.
    """
    q = queue.Queue()

    def handle(conn):
        # One short-lived thread per connection, so a client that connects but
        # never sends can't stall the next launch's handshake.
        try:
            conn.settimeout(2.0)
            buf = b""
            while buf.count(b"\n") < 2 and len(buf) < 8192:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
            lines = buf.decode("utf-8", "replace").split("\n")
            if lines and lines[0] == _MAGIC:
                conn.sendall(b"OK\n")
                q.put(lines[1] if len(lines) > 1 else "")
        except OSError:
            pass                             # a malformed / dropped connection is ignored
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def accept_loop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return                       # server closed → app is shutting down
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=accept_loop, name="manoni-single-instance",
                     daemon=True).start()
    return q


def deliver(q, root, on_open):
    """Drain received paths into `on_open`, always called on the Tk thread.

    Call once the window exists; it flushes anything queued during startup and
    keeps polling. `on_open(path)` runs on the UI thread (path is "" for a bare
    relaunch that carried no file).
    """
    def drain():
        try:
            while True:
                on_open(q.get_nowait())
        except queue.Empty:
            pass
        root.after(_POLL_MS, drain)

    root.after(_POLL_MS, drain)
