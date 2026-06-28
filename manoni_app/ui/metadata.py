"""Photo metadata: read the current photo's embedded ICC profile + EXIF and show
it in a window (the top-bar info button). This module is also the single source
of truth for what counts as "metadata", so the viewer here and the Save dialog's
keep/strip toggle (saving.py) stay in agreement.

Mixin on the Manoni window — every method uses the shared `self`.
"""

import io
import os
import tkinter as tk

from PIL import Image, ExifTags

from ..config import BG, BAR, ACCENT, FG, FG_DIM
from ..i18n import t
from .dialogs import make_dialog_button

_EXIF_IFD = 0x8769     # the Exif sub-IFD (exposure, ISO, lens, …)
_GPS_IFD = 0x8825      # the GPS sub-IFD


def _strip_jpeg_markers(raw):
    """JPEG bytes with the APP1 (Exif/XMP) + APP2 (ICC) segments removed and
    everything else byte-for-byte intact — so the entropy-coded pixels stay
    BIT-identical. None if the stream doesn't parse (caller falls back to PIL)."""
    if raw[:2] != b"\xff\xd8":                 # not SOI → not a JPEG we can trust
        return None
    out = bytearray(raw[:2])
    i, n = 2, len(raw)
    while i < n:
        if raw[i] != 0xFF:                     # not at a marker → bail, don't corrupt
            return None
        marker = raw[i + 1]
        if marker == 0xDA:                     # SOS: copy the scan data verbatim, done
            out += raw[i:]
            break
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            out += raw[i:i + 2]                # standalone marker, no length
            i += 2
            continue
        if i + 4 > n:
            return None
        seg_len = (raw[i + 2] << 8) | raw[i + 3]   # length includes these 2 bytes
        if marker not in (0xE1, 0xE2):         # drop APP1 (Exif/XMP) + APP2 (ICC)
            out += raw[i:i + 2 + seg_len]
        i += 2 + seg_len
    return bytes(out)


# --- value formatting (best-effort; return None to drop the row) ------------

def _rat(v):
    "Float from an EXIF (IFD)Rational / number; None if it can't be read."
    try:
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _fmt_bytes(n):
    if n >= 1024 * 1024:
        return f"{n / 1048576:.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _fmt_shutter(v):
    f = _rat(v)
    if not f or f <= 0:
        return None
    return f"{f:g}s" if f >= 1 else f"1/{round(1 / f)}s"


def _fmt_fnum(v):
    f = _rat(v)
    return f"f/{f:.1f}" if f else None


def _fmt_iso(v):
    if isinstance(v, (tuple, list)):
        v = v[0] if v else None
    try:
        return f"ISO {int(v)}"
    except (TypeError, ValueError):
        return None


def _fmt_focal(v):
    f = _rat(v)
    return f"{f:.0f} mm" if f else None


def _fmt_ev(v):
    f = _rat(v)
    return None if f is None else f"{f:+.1f} EV"


def _fmt_date(v):
    "EXIF 'YYYY:MM:DD HH:MM:SS' → 'YYYY-MM-DD HH:MM' (left as-is if odd)."
    if not v:
        return None
    s = str(v).strip()
    if len(s) >= 16 and s[4] == ":" and s[7] == ":":
        return s[:10].replace(":", "-") + " " + s[11:16]
    return s or None


def _gps_decimal(coord, ref):
    "DMS tri(rationals) + hemisphere ref → signed decimal degrees, or None."
    try:
        d, m, s = _rat(coord[0]), _rat(coord[1]), _rat(coord[2])
    except (TypeError, IndexError, KeyError):
        return None
    if None in (d, m, s):
        return None
    dec = d + m / 60.0 + s / 3600.0
    return -dec if str(ref).upper() in ("S", "W") else dec


def _icc_name(icc):
    "Human name of an ICC profile blob (e.g. 'Display P3'), or None."
    try:
        from PIL import ImageCms
        prof = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        return ImageCms.getProfileDescription(prof).strip() or None
    except Exception:
        return None


def _rows(pairs):
    "Keep only (label, value) pairs that have a non-empty value (as str)."
    out = []
    for k, v in pairs:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out.append((k, s))
    return out


class MetadataMixin:
    # --- gather -------------------------------------------------------------

    def _gather_metadata(self):
        """Read the current photo from disk → (sections, has_embedded).

        sections = [(title, [(label, value), …]), …]; the File section is always
        present, while Colour profile / Camera / Capture / Location appear only
        when the file actually carries them. has_embedded is True when any ICC or
        EXIF metadata was found (drives the 'no metadata' note)."""
        if not self.files or not self.folder:
            return [], False
        path = os.path.join(self.folder, self.files[self.index])
        try:
            im = Image.open(path)
        except Exception:
            return [], False
        # Read everything we need, then ALWAYS close the file handle. The info
        # window can be opened repeatedly; a leaked handle per open adds up.
        try:
            return self._read_metadata(im, path)
        finally:
            im.close()

    def _read_metadata(self, im, path):
        "Build (sections, has_embedded) from an open PIL image (caller closes it)."
        sections = []
        has_embedded = False

        # File facts — always available, no embedded metadata needed.
        w, h = im.size
        try:
            size_b = os.path.getsize(path)
        except OSError:
            size_b = 0
        sections.append((t("File"), _rows([
            (t("Name"), self.files[self.index]),
            (t("Format"), im.format),
            (t("Dimensions"), f"{w} × {h}"),
            (t("Megapixels"), f"{w * h / 1_000_000:.1f} MP"),
            (t("Colour mode"), im.mode),
            (t("File size"), _fmt_bytes(size_b)),
        ])))

        # Colour profile (ICC) — what the keep/strip toggle preserves.
        icc = im.info.get("icc_profile")
        if icc:
            has_embedded = True
            sections.append((t("Colour profile"), _rows([
                (t("Profile"), _icc_name(icc) or t("embedded")),
                (t("Size"), _fmt_bytes(len(icc))),
            ])))

        # EXIF — camera / capture / GPS.
        try:
            exif = im.getexif()
        except Exception:
            exif = None
        if exif and len(exif):
            has_embedded = True
            TAGS = ExifTags.TAGS
            base = {TAGS.get(k, k): v for k, v in exif.items()}
            try:
                sub = {TAGS.get(k, k): v for k, v in exif.get_ifd(_EXIF_IFD).items()}
            except Exception:
                sub = {}

            cam = _rows([
                (t("Make"), base.get("Make")),
                (t("Model"), base.get("Model")),
                (t("Lens"), sub.get("LensModel")),
                (t("Software"), base.get("Software")),
            ])
            if cam:
                sections.append((t("Camera"), cam))

            cap = _rows([
                (t("Date taken"), _fmt_date(sub.get("DateTimeOriginal")
                                            or base.get("DateTime"))),
                (t("Shutter"), _fmt_shutter(sub.get("ExposureTime"))),
                (t("Aperture"), _fmt_fnum(sub.get("FNumber"))),
                (t("ISO"), _fmt_iso(sub.get("ISOSpeedRatings"))),
                (t("Focal length"), _fmt_focal(sub.get("FocalLength"))),
                (t("Exposure bias"), _fmt_ev(sub.get("ExposureBiasValue"))),
            ])
            if cap:
                sections.append((t("Capture"), cap))

            try:
                gps = exif.get_ifd(_GPS_IFD)
            except Exception:
                gps = {}
            if gps:
                loc = []
                lat = _gps_decimal(gps.get(2), gps.get(1))
                lon = _gps_decimal(gps.get(4), gps.get(3))
                if lat is not None and lon is not None:
                    loc.append((t("Coordinates"), f"{lat:.6f}, {lon:.6f}"))
                alt = _rat(gps.get(6))
                if alt is not None:
                    loc.append((t("Altitude"), f"{alt:.0f} m"))
                if loc:
                    sections.append((t("Location"), loc))

        return sections, has_embedded

    # --- window -------------------------------------------------------------

    def _metadata_dialog(self):
        "Top-bar info button → a scrollable window of the photo's metadata."
        if not self.files or self.current_pil is None or not self.folder:
            self.toast(t("Open an image first"))
            return
        sections, has_embedded = self._gather_metadata()
        if not sections:
            self.toast(t("Open an image first"))
            return

        dlg = tk.Toplevel(self.root)
        dlg.title(t("Photo info"))
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        wrap = tk.Frame(dlg, bg=BG, padx=16, pady=14)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text=t("Photo info"), bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 10))

        # Scrollable body (same idiom as _filter_dialog, but with our own button
        # row below so the red action stays pinned, never scrolling away).
        area = tk.Frame(wrap, bg=BG)
        area.pack(fill="both", expand=True)
        canvas = tk.Canvas(area, bg=BAR, highlightthickness=0,
                           width=self._edit_dpi_w(300),
                           height=self._edit_dpi_w(250))
        sb = self._make_scrollbar(area, canvas)
        body = tk.Frame(canvas, bg=BAR)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y", padx=(4, 0))

        def on_body(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win, width=canvas.winfo_width())
        body.bind("<Configure>", on_body)
        canvas.bind("<Configure>", on_body)

        self._fill_metadata_body(body, sections, has_embedded)

        # Buttons: a red "Delete metadata" on the left (only when there IS any to
        # delete), Close on the right.
        brow = tk.Frame(wrap, bg=BG)
        brow.pack(fill="x", pady=(12, 0))
        self._dialog_btn(brow, t("Close"), dlg.destroy).pack(side="right")
        if has_embedded:
            self._danger_btn(brow, t("Delete metadata"),
                             lambda: self._strip_metadata(dlg)).pack(side="left")

        # Wheel-scroll the list; bind on the Toplevel so child labels bubble up.
        dlg.bind("<MouseWheel>",
                 lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        self._place_filter_dialog(dlg)

    def _fill_metadata_body(self, body, sections, has_embedded):
        "Lay the (title, rows) sections into the scrollable body as a 2-col grid."
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        r = 0
        for i, (title, rows) in enumerate(sections):
            tk.Label(body, text=title, bg=BAR, fg=ACCENT,
                     font=("Segoe UI", 9, "bold"), anchor="w").grid(
                row=r, column=0, columnspan=2, sticky="w",
                padx=10, pady=(12 if i else 8, 4))
            r += 1
            for key, val in rows:
                tk.Label(body, text=key, bg=BAR, fg=FG_DIM, font=("Segoe UI", 9),
                         anchor="nw").grid(row=r, column=0, sticky="nw",
                                           padx=(18, 10), pady=2)
                tk.Label(body, text=val, bg=BAR, fg=FG, font=("Segoe UI", 9),
                         anchor="nw", justify="left",
                         wraplength=self._edit_dpi_w(190)).grid(
                    row=r, column=1, sticky="nw", padx=(0, 10), pady=2)
                r += 1

        if not has_embedded:
            tk.Label(body, text=t("This photo has no embedded metadata "
                                  "(no colour profile or EXIF)."),
                     bg=BAR, fg=FG_DIM, font=("Segoe UI", 9), anchor="w",
                     justify="left", wraplength=self._edit_dpi_w(280)).grid(
                row=r, column=0, columnspan=2, sticky="w", padx=10, pady=(12, 6))

    def _danger_btn(self, parent, text, command):
        "A red (destructive-action) dialog button (see ui/dialogs.py)."
        return make_dialog_button(parent, text, command, danger=True)

    # --- strip (the red button) --------------------------------------------

    def _strip_metadata(self, dlg):
        "Red button: permanently wipe ICC + EXIF from the current photo's file."
        if not self.files or not self.folder:
            return
        name = self.files[self.index]
        if not self._confirm(
                t("Permanently remove the colour profile and all EXIF "
                  "(including GPS location) from “{name}”?\n\nThe pixels are "
                  "kept exactly; this can't be undone.").format(name=name),
                ok_label=t("Delete metadata")):
            return
        if not self._strip_file_metadata(os.path.join(self.folder, name)):
            return
        # Keep the in-memory copy in sync so a later Save can't re-embed it.
        if self.current_pil is not None:
            for k in ("icc_profile", "exif"):
                self.current_pil.info.pop(k, None)
        self.toast(t("Metadata removed → {name}").format(name=name))
        try:
            dlg.destroy()
        except tk.TclError:
            pass

    def _strip_file_metadata(self, path):
        """Remove ICC + EXIF from `path` in place, keeping the pixels.

        JPEG: drop the APP1/APP2 marker segments → pixels stay BIT-identical.
        PNG / others: re-save without the metadata (PNG is lossless). Reading the
        bytes first means we never hold a handle on `path` while overwriting it
        (Windows lock-safe). Returns True on success."""
        try:
            with open(path, "rb") as f:
                raw = f.read()
            if raw[:2] == b"\xff\xd8":             # JPEG → lossless marker surgery
                out = _strip_jpeg_markers(raw)
                if out is not None:
                    with open(path, "wb") as f:
                        f.write(out)
                    return True
            im = Image.open(io.BytesIO(raw))        # other formats → PIL re-save
            im.load()
            # PIL re-embeds icc_profile/exif from .info on save, so clear them or
            # the strip is a no-op (PNG silently keeps its ICC otherwise).
            im.info.pop("icc_profile", None)
            im.info.pop("exif", None)
            fmt = (im.format or "").upper()
            kw = {}
            if fmt in ("JPEG", "JPG", "MPO"):       # unparseable JPEG fallback
                fmt, kw = "JPEG", {"quality": "keep", "subsampling": "keep"}
            elif fmt == "WEBP":
                kw = {"quality": 100}
            im.save(path, fmt, **kw)
            return True
        except Exception as e:
            self.toast(t("Error: {e}").format(e=e))
            return False
