"""Layer ordering for the text + logo overlays.

Texts and logos compose in ONE z-ordered stack (imaging.overlay_order): each
overlay dict carries a "z" layer number, and the ▲ / ▼ chips drawn beside the
selected element's frame move it up / down through that combined sequence — so
a text can sit above a logo and vice versa. Overlays without "z" (saved before
layers existed) keep the historical order: every text below every logo.

The overlay actions hang off ONE round "…" chip painted above the selected
element's top-right corner — a PIL-rendered disc (4× supersampled + LANCZOS,
because tk.Canvas ovals are aliased and look jagged) with the app's lucide
ellipsis PNG composited dead-centre, blitted as one image. Styled from the live
tintkit theme (surface / ring / fg tokens), so the dark<->light switch and a
custom accent restyle it with the rest of the app. Clicking it opens a small
themed dropdown (reorder ∧ / ∨ when there is a stack + delete) — one tidy
affordance instead of three chips crowding a small text / logo. The chip's hit
box is remembered per draw and consumed by the tools' hit tests (`_text_at` /
`_logo_at` return "menu", which the press handlers route to `_open_layer_menu`).
Mixin on the Manoni window — every method uses the shared `self`.
"""

import os
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk

from ..config import ICON_DIR
from ..i18n import t
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
        # Keep the text panel's list in step when a text is reordered from the
        # on-canvas … chip (the list's own ↑ ↓ already rebuild through here too).
        if kind == "text" and hasattr(self, "_text_list_host"):
            self._rebuild_text_list()

    # --- Canvas chrome ---------------------------------------------------------

    def _layer_chip_image(self, icon, on):
        """One chip disc as a crisp PhotoImage: a solid theme-surface circle with
        a thin ring and a lucide PNG (by icon name — 'chevron-up' / 'chevron-down'
        / 'x') dead-centre, drawn 4× oversize with PIL and LANCZOS-downscaled so
        the edge is smoothly anti-aliased. Cached per icon + size + resolved theme
        colours — both schemes coexist and the cache keeps the Tk image refs alive."""
        t = self.theme
        s = self._edit_dpi_w(self.LAYER_CHIP)
        fill = t["bar"]
        ring = t["ring"] if on else t["border"]
        col = t["fg"] if on else t["fg_dim"]
        key = (icon, s, fill, ring, col)
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
                ICON_DIR, f"{icon}.png")).convert("RGBA")
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

    def _place_layer_chip(self, key, icon, on, bx0, by0, s):
        "Blit one chip disc at (bx0, by0); register its hit box when enabled."
        img = self._layer_chip_image(icon, on)
        self.preview.create_image(round(bx0), round(by0), anchor="nw", image=img)
        if on:
            self._layer_chips[key] = (bx0, by0, bx0 + s, by0 + s)

    def _draw_layer_chips(self, kind, x0, y0, x1, y1):
        """One round "…" chip above the SELECTED overlay's top-right corner. It
        flips to just below the frame when the frame touches the canvas top. Solid,
        theme-styled disc (see _layer_chip_image) — the dark<->light switch restyles
        it with the rest of the app. Clicking it opens the dropdown of overlay
        actions (see _open_layer_menu). Its hit box lands in `self._layer_chips`
        under 'menu'."""
        self._layer_chips = {}
        idx = self.text_sel if kind == "text" else self.logo_sel
        pos, total = self._layer_pos(kind, idx)
        if pos is None:
            return
        s = self._edit_dpi_w(self.LAYER_CHIP)
        gap = self._edit_dpi_w(self.LAYER_CHIP_GAP)
        cy0 = y0 - gap - s
        if cy0 < 0:                        # frame at the canvas top → flip inside
            cy0 = y0 + gap
        self._place_layer_chip("menu", "ellipsis", True, max(0, x1 - s), cy0, s)

    def _layer_chip_at(self, x, y):
        "'menu' when (x, y) sits on the … chip; None otherwise."
        for key, (bx0, by0, bx1, by1) in getattr(self, "_layer_chips", {}).items():
            if bx0 <= x <= bx1 and by0 <= y <= by1:
                return key
        return None

    # --- The … dropdown --------------------------------------------------------

    def _open_layer_menu(self, kind):
        """Dropdown off the … chip: reorder up / down (only with a stack to move
        through, each dimmed when it's already at that end) and delete. Same
        borderless dark popup the filter … menus use, positioned under the chip."""
        self._close_layer_menu()
        box = getattr(self, "_layer_chips", {}).get("menu")
        if box is None:
            return
        idx = self.text_sel if kind == "text" else self.logo_sel
        pos, total = self._layer_pos(kind, idx)
        if pos is None:
            return
        th = self.theme
        bar, border, fg = th["bar"], th["border"], th["fg"]
        fg_dim, hover = th["fg_dim"], th["hover"]
        pop = tk.Toplevel(self.root)
        pop.overrideredirect(True)
        pop.configure(bg=border)              # 1px hairline border via the inset
        self._layer_popup = pop
        inner = tk.Frame(pop, bg=bar)
        inner.pack(padx=1, pady=1)

        def add_row(icon_name, label, command, enabled=True):
            col = fg if enabled else fg_dim
            r = tk.Frame(inner, bg=bar, cursor="hand2" if enabled else "arrow")
            r.pack(fill="x")
            cells = [r]
            img = self.icon(icon_name, size=14, color=col)
            if img is not None:
                ic = tk.Label(r, image=img, bg=bar)
                ic.pack(side="left", padx=(10, 8), pady=6)
                cells.append(ic)
            lab = tk.Label(r, text=label, bg=bar, fg=col, anchor="w",
                           font=("Segoe UI", 9))
            lab.pack(side="left", padx=(0 if img else 12, 18), pady=6)
            cells.append(lab)
            if enabled:
                for w in cells:
                    w.bind("<Enter>",
                           lambda e: [c.configure(bg=hover) for c in cells])
                    w.bind("<Leave>",
                           lambda e: [c.configure(bg=bar) for c in cells])
                    w.bind("<Button-1>",
                           lambda e, c=command: (self._close_layer_menu(), c()))

        if total >= 2:
            add_row("chevron-up", t("Move up"),
                    lambda: self._layer_move(kind, 1), pos < total - 1)
            add_row("chevron-down", t("Move down"),
                    lambda: self._layer_move(kind, -1), pos > 0)
            tk.Frame(inner, bg=border, height=1).pack(fill="x")
        delete = self._delete_text if kind == "text" else self._delete_logo
        add_row("trash-2", t("Delete"), delete)

        pop.update_idletasks()
        bx0, by0, bx1, by1 = box
        rx, ry = self.preview.winfo_rootx(), self.preview.winfo_rooty()
        x = rx + bx1 - pop.winfo_width()      # right-align the popup under the chip
        y = ry + by1 + 2
        pop.geometry(f"+{max(0, int(x))}+{int(y)}")
        pop.bind("<Escape>", lambda e: self._close_layer_menu())
        pop.bind("<FocusOut>", lambda e: self._close_layer_menu())
        pop.focus_force()                     # so clicking elsewhere closes it

    def _close_layer_menu(self):
        "Tear down the open … dropdown, if any."
        pop = getattr(self, "_layer_popup", None)
        if pop is not None:
            self._layer_popup = None
            try:
                pop.destroy()
            except tk.TclError:
                pass
