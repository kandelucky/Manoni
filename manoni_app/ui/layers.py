"""Layer ordering for the text + logo overlays.

Texts and logos compose in ONE z-ordered stack (imaging.overlay_order): each
overlay dict carries a "z" layer number, and the ▲ / ▼ chips drawn beside the
selected element's frame move it up / down through that combined sequence — so
a text can sit above a logo and vice versa. Overlays without "z" (saved before
layers existed) keep the historical order: every text below every logo.

The chips are canvas chrome — two round buttons painted by the text / logo
overlay painters right above the selection frame. Each is a PIL-rendered disc
(4× supersampled + LANCZOS, because tk.Canvas ovals are aliased and look
jagged) with the app's lucide chevron PNG composited dead-centre, blitted as
one image. Styled from the live tintkit theme (surface / ring / fg tokens), so
the dark<->light switch and a custom accent restyle them with the rest of the
app. Hit boxes are remembered per draw and consumed by the tools' hit tests
(`_text_at` / `_logo_at` return "layer_up" / "layer_down", which the press
handlers route here). Mixin on the Manoni window — every method uses the
shared `self`.
"""

import os

from PIL import Image, ImageDraw, ImageTk

from ..config import ICON_DIR
from .. import imaging


class LayersMixin:
    LAYER_CHIP     = 18   # chip disc diameter, logical px (DPI-scaled when drawn)
    LAYER_CHIP_GAP = 6    # gap between the chips / off the frame, logical px

    # --- Order bookkeeping ----------------------------------------------------

    def _layer_seq(self):
        "Bottom→top order of every overlay on the photo, as (kind, index) pairs."
        return imaging.overlay_order(self.texts, self.logos)

    def _layer_next_z(self):
        "A z above every existing overlay — a new element lands on top of all."
        zs = [ov.get("z", 0) for ov in list(self.texts) + list(self.logos)]
        return (max(zs) + 1) if zs else 0

    def _layer_pos(self, kind, idx):
        "The element's position in the combined stack: (position, total)."
        seq = self._layer_seq()
        try:
            return seq.index((kind, idx)), len(seq)
        except ValueError:
            return None, len(seq)

    def _layer_move(self, kind, delta):
        "Move the selected text / logo one layer up (+1) or down (-1), undoably."
        " Renumbers EVERY overlay's z to its stack position first, so pre-layer"
        " overlays (which all read as z 0) get distinct slots before the swap."
        idx = self.text_sel if kind == "text" else self.logo_sel
        lst = self.texts if kind == "text" else self.logos
        if idx is None or not (0 <= idx < len(lst)):
            return
        seq = self._layer_seq()
        pos = seq.index((kind, idx))
        tgt = pos + delta
        if not (0 <= tgt < len(seq)):
            return                       # already at the top / bottom
        before = self._edit_state()
        seq[pos], seq[tgt] = seq[tgt], seq[pos]
        texts = [dict(ov) for ov in self.texts]   # rebind copies — undo snapshots
        logos = [dict(ov) for ov in self.logos]   # must never be aliased
        for z, (k, i) in enumerate(seq):
            (texts if k == "text" else logos)[i]["z"] = z
        self.texts, self.logos = texts, logos
        self._edits_saved = False
        self._render_preview()
        self._record_edit(before)

    # --- Canvas chrome ---------------------------------------------------------

    def _layer_chip_image(self, direction, on):
        """One chip disc as a crisp PhotoImage: a solid theme-surface circle with
        a thin ring and the lucide chevron PNG dead-centre, drawn 4× oversize
        with PIL and LANCZOS-downscaled so the edge is smoothly anti-aliased.
        Cached per size + resolved theme colours — both schemes coexist and the
        cache keeps the Tk image references alive."""
        t = self.theme
        s = self._edit_dpi_w(self.LAYER_CHIP)
        fill = t["bar"]
        ring = t["ring"] if on else t["border"]
        col = t["fg"] if on else t["fg_dim"]
        key = (direction, s, fill, ring, col)
        cache = getattr(self, "_layer_chip_cache", None)
        if cache is None:
            cache = self._layer_chip_cache = {}
        photo = cache.get(key)
        if photo is not None:
            return photo

        def rgb(h):
            return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

        d = s * 4                                   # 4× supersample
        ow = max(1, self._edit_dpi_w(1.2)) * 4      # ring stroke, same scale
        im = Image.new("RGBA", (d, d), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        dr.ellipse((ow // 2, ow // 2, d - 1 - ow // 2, d - 1 - ow // 2),
                   fill=rgb(fill) + (255,), outline=rgb(ring) + (255,), width=ow)
        try:
            ic = Image.open(os.path.join(
                ICON_DIR, f"chevron-{direction}.png")).convert("RGBA")
            ipx = round(d * 0.62)                   # icon box ≈ the mock's 14/24
            ic = ic.resize((ipx, ipx), Image.LANCZOS)
            tint = Image.new("RGBA", ic.size, rgb(col) + (0,))
            tint.putalpha(ic.split()[3])            # recolour, keep soft edges
            im.alpha_composite(tint, ((d - ipx) // 2, (d - ipx) // 2))
        except Exception:
            pass                                    # missing PNG → a plain disc
        photo = ImageTk.PhotoImage(im.resize((s, s), Image.LANCZOS))
        cache[key] = photo
        return photo

    def _draw_layer_chips(self, kind, x0, y0, x1, y1):
        """Two round ∧ / ∨ buttons above the selection frame's top-right corner
        (flipped to just below it when the frame touches the canvas top). Solid,
        theme-styled discs (see _layer_chip_image) — the dark<->light switch
        restyles them with the rest of the app. Hit boxes land in
        `self._layer_chips`; a direction that can't move draws dimmed and takes
        no clicks. Nothing shows while the photo holds fewer than two overlays —
        there is no stack to move through."""
        self._layer_chips = {}
        idx = self.text_sel if kind == "text" else self.logo_sel
        pos, total = self._layer_pos(kind, idx)
        if pos is None or total < 2:
            return
        c = self.preview
        s = self._edit_dpi_w(self.LAYER_CHIP)
        gap = self._edit_dpi_w(self.LAYER_CHIP_GAP)
        cy0 = y0 - gap - s
        if cy0 < 0:                        # frame at the canvas top → flip inside
            cy0 = y0 + gap
        cx1 = max(x1, x0 + 2 * s + gap)    # a tiny frame still fits both chips
        boxes = {"layer_up":   (cx1 - 2 * s - gap, cy0, cx1 - s - gap, cy0 + s),
                 "layer_down": (cx1 - s, cy0, cx1, cy0 + s)}
        can = {"layer_up": pos < total - 1, "layer_down": pos > 0}
        for key, (bx0, by0, bx1, by1) in boxes.items():
            on = can[key]
            img = self._layer_chip_image(key.split("_")[1], on)
            c.create_image(round(bx0), round(by0), anchor="nw", image=img)
            if on:
                self._layer_chips[key] = (bx0, by0, bx1, by1)

    def _layer_chip_at(self, x, y):
        "'layer_up' / 'layer_down' when (x, y) sits on an enabled chip, else None."
        for key, (bx0, by0, bx1, by1) in getattr(self, "_layer_chips", {}).items():
            if bx0 <= x <= bx1 and by0 <= y <= by1:
                return key
        return None
