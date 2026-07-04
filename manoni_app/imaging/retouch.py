"""Destructive in-memory bakes: spot healing / clone stamp, and perspective.

Unlike the slider pipeline (global, non-destructive), these rewrite pixels in
place when the user commits a retouch stroke or a keystone correction. Pure
Pillow — no OpenCV/inpainting — so they stay tiny on a weak laptop.
"""

import math

from PIL import Image, ImageDraw, ImageFilter, ImageStat


# --- Spot healing ------------------------------------------------------------

# A "spot heal" is a LOCAL pixel edit, unlike the global slider filters. It
# clones the smoothest nearby same-size region over the blemish, colour-matched
# to the clean ring around it and feathered so the seam disappears. The target
# box is padded a little beyond the brush so there is a clean border to (a)
# sample the colour from and (b) feather into.

HEAL_FEATHER = 0.5   # mask-edge blur as a fraction of the brush radius
HEAL_DIRS    = 8     # nearby source candidates probed around the spot


def _shift_channels(img, deltas):
    "Add a per-channel constant (signed), clamped to 0..255 — a cheap colour match."
    bands = []
    for band, d in zip(img.split(), deltas):
        di = int(round(d))
        if di == 0:
            bands.append(band)
        else:
            bands.append(band.point(lambda x, di=di: max(0, min(255, x + di))))
    return Image.merge("RGB", bands)


def heal_region(img, cx, cy, radius, feather=HEAL_FEATHER, opacity=1.0,
                src=None, flip=False):
    """Spot-heal a round blemish centred at (cx, cy) in full-res pixels.

    `opacity` (0..1) is the blend strength: 1.0 fully replaces the spot with the
    clean clone, lower values keep some of the original showing through — a soft,
    partial heal (e.g. fading a wrinkle rather than erasing it).

    `src`, an explicit (src_cx, src_cy) the user picked (Alt+click), clones from
    there instead of auto-searching the smoothest neighbour — same idea as
    clone_region, but still colour-matched and feathered like a heal rather than
    an exact copy. `flip` mirrors that source left-right about its own point,
    same as clone's Mirror option. Ignored when `src` is None (auto search).

    Returns (patched_region, box): the caller pastes `patched_region` at `box`
    into the working image, so only the touched area is rewritten — cheap on a
    big photo and trivial to snapshot for undo. Returns (None, None) when the
    brush is too small, off the image, or (with `src`) the source disc falls
    outside it.
    """
    img = img.convert("RGB")
    iw, ih = img.size
    r = int(round(radius))
    if r < 1:
        return None, None
    # Pad the box beyond the brush: that margin is the clean border we colour-
    # match to and feather into. The disc itself stays radius `r`.
    margin = max(4, int(round(r * 0.6)))
    half = r + margin
    cxi, cyi = int(round(cx)), int(round(cy))
    x0 = max(0, cxi - half); y0 = max(0, cyi - half)
    x1 = min(iw, cxi + half); y1 = min(ih, cyi + half)
    bw, bh = x1 - x0, y1 - y0
    if bw < 3 or bh < 3:
        return None, None
    box = (x0, y0, x1, y1)
    target = img.crop(box)
    # Disc centre in the box's own coordinates (the spot is off-centre near edges).
    lx, ly = cx - x0, cy - y0

    # Hard disc (for stats) + a feathered copy (for the actual blend).
    hard = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(hard).ellipse([lx - r, ly - r, lx + r, ly + r], fill=255)
    mask = hard.filter(ImageFilter.GaussianBlur(max(0.5, feather * r)))
    if opacity < 1.0:
        a = max(0.0, min(1.0, opacity))         # scale the alpha → partial heal
        mask = mask.point(lambda v: int(round(v * a)))
    ring = hard.point(lambda x: 255 - x)        # the clean border outside the disc

    if src is not None:
        # User-picked source (like clone_region's dst/src pair): the source crop
        # lines the source point up with the dest disc centre (lx, ly). For flip,
        # take the window whose centre column maps onto lx after a left-right
        # flip, so the source point stays put and only the texture mirrors.
        scx, scy = src
        sx0 = (int(round(scx - (bw - 1 - lx))) if flip
               else int(round(scx - lx)))
        sy0 = int(round(scy - ly))
        if sx0 < 0 or sy0 < 0 or sx0 + bw > iw or sy0 + bh > ih:
            return None, None
        clone = img.crop((sx0, sy0, sx0 + bw, sy0 + bh))
        if flip:
            clone = clone.transpose(Image.FLIP_LEFT_RIGHT)
    else:
        # No source picked: auto-search a same-size region offset around the
        # spot, kept only if it fits fully inside the image; among those, the
        # smoothest (lowest stddev) one, so we clone flat skin/sky/wall rather
        # than dragging an edge over the spot.
        d = max(bw, bh)
        best = None
        for k in range(HEAL_DIRS):
            ang = 2.0 * math.pi * k / HEAL_DIRS
            ox = int(round(cx + d * math.cos(ang) - lx))
            oy = int(round(cy + d * math.sin(ang) - ly))
            if ox < 0 or oy < 0 or ox + bw > iw or oy + bh > ih:
                continue
            cand = img.crop((ox, oy, ox + bw, oy + bh))
            score = sum(ImageStat.Stat(cand).stddev)
            if best is None or score < best[0]:
                best = (score, cand)
        if best is None:
            # Spot in a corner with a big brush: no neighbour fits. Blur the spot
            # itself — still hides a small blemish, just without borrowed texture.
            clone = target.filter(ImageFilter.GaussianBlur(r))
        else:
            clone = best[1]

    # Colour-match: shift the source so its mean under the disc equals the clean
    # ring's mean — the cloned centre then blends into the surrounding tone.
    tref = ImageStat.Stat(target, ring).mean
    sref = ImageStat.Stat(clone, hard).mean
    clone = _shift_channels(clone, [t - s for t, s in zip(tref, sref)])

    return Image.composite(clone, target, mask), box


def clone_region(img, dst_cx, dst_cy, src_cx, src_cy, radius,
                 feather=HEAL_FEATHER, opacity=1.0, flip=False):
    """Clone-stamp: copy a feathered disc from (src_cx, src_cy) straight onto
    (dst_cx, dst_cy) in full-res pixels.

    Unlike heal_region this is an EXACT copy — no smoothest-neighbour search and
    no colour match — exactly Photoshop's Clone Stamp: the user picks the source,
    so the tool just duplicates it. `feather` / `opacity` behave as in heal. With
    `flip` the source texture is mirrored left↔right about the source point (handy
    for symmetric retouching), while the source point itself stays anchored.

    Returns (patched_region, box) for the destination, or (None, None) if the
    brush is too small, off the image, or the source disc falls outside it.
    """
    img = img.convert("RGB")
    iw, ih = img.size
    r = int(round(radius))
    if r < 1:
        return None, None
    margin = max(4, int(round(r * 0.6)))
    half = r + margin
    dxi, dyi = int(round(dst_cx)), int(round(dst_cy))
    x0 = max(0, dxi - half); y0 = max(0, dyi - half)
    x1 = min(iw, dxi + half); y1 = min(ih, dyi + half)
    bw, bh = x1 - x0, y1 - y0
    if bw < 3 or bh < 3:
        return None, None
    box = (x0, y0, x1, y1)
    target = img.crop(box)
    lx, ly = dst_cx - x0, dst_cy - y0
    # The source crop lines the source point up with the dest disc centre (lx, ly).
    # For flip, take the window whose centre column maps onto lx after a left↔right
    # flip, so the source point stays put and only the texture mirrors — no wrap.
    sy0 = y0 + int(round(src_cy - dst_cy))
    if flip:
        sx0 = int(round(src_cx - (bw - 1 - lx)))
    else:
        sx0 = x0 + int(round(src_cx - dst_cx))
    if sx0 < 0 or sy0 < 0 or sx0 + bw > iw or sy0 + bh > ih:
        return None, None
    src = img.crop((sx0, sy0, sx0 + bw, sy0 + bh))
    if flip:
        src = src.transpose(Image.FLIP_LEFT_RIGHT)

    hard = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(hard).ellipse([lx - r, ly - r, lx + r, ly + r], fill=255)
    mask = hard.filter(ImageFilter.GaussianBlur(max(0.5, feather * r)))
    if opacity < 1.0:
        a = max(0.0, min(1.0, opacity))
        mask = mask.point(lambda v: int(round(v * a)))
    return Image.composite(src, target, mask), box


# --- Perspective / keystone correction ---------------------------------------
# Fix converging verticals (a building shot from below) or horizontals. The
# corrected image is a PROJECTIVE warp: the output rectangle samples a trapezoid
# of the source. Because that trapezoid stays INSIDE the source, the output is
# always fully filled — no empty corners to crop or fill. KEYSTONE_MAX caps how
# far an edge is pinched (a fraction of that dimension) at a full ±slider. The
# warp is defined in image-fraction terms, so it is scale-free: applying it to
# the small fitted preview and to the full-res photo gives the identical result.

KEYSTONE_MAX = 0.30   # max edge inset as a fraction of W/H, at a full ±1 slider


def _solve_linear(A, b):
    "Solve the n×n system A·x = b by Gauss-Jordan with partial pivoting (no numpy)."
    n = len(A)
    m = [list(row) + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None                       # singular (degenerate quad)
        m[col], m[piv] = m[piv], m[col]
        pv = m[col][col]
        for c in range(col, n + 1):
            m[col][c] /= pv
        for r in range(n):
            if r != col and m[r][col] != 0.0:
                f = m[r][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] for i in range(n)]


def perspective_coeffs(out_pts, in_pts):
    """The 8 PERSPECTIVE coefficients for Image.transform: for each OUTPUT corner
    in `out_pts` give the INPUT point in `in_pts` it should sample from. Returns
    (a,b,c,d,e,f,g,h) such that output (X,Y) maps to input
    ((aX+bY+c)/(gX+hY+1), (dX+eY+f)/(gX+hY+1)); None if the quad is degenerate."""
    A, bvec = [], []
    for (X, Y), (x, y) in zip(out_pts, in_pts):
        A.append([X, Y, 1, 0, 0, 0, -x * X, -x * Y]); bvec.append(x)
        A.append([0, 0, 0, X, Y, 1, -y * X, -y * Y]); bvec.append(y)
    return _solve_linear(A, bvec)


def apply_perspective(img, v, h):
    """Keystone-correct `img`: `v` vertical, `h` horizontal, each signed -1..+1.
    v>0 widens the top (fixes verticals that converge upward), v<0 widens the
    bottom; h>0 widens the left, h<0 the right. The output is the same size and
    fully filled (the sampled trapezoid lies inside the source). Scale-free, so
    the fitted-preview warp matches the full-res commit. Pure Pillow."""
    if v == 0.0 and h == 0.0:
        return img
    if img.mode in ("P", "1"):
        img = img.convert("RGB")
    w, hh = img.size
    kx = KEYSTONE_MAX * w
    ky = KEYSTONE_MAX * hh
    vt = kx * v if v > 0 else 0.0     # inset each TOP corner in x (v>0)
    vb = -kx * v if v < 0 else 0.0    # inset each BOTTOM corner in x (v<0)
    hl = ky * h if h > 0 else 0.0     # inset each LEFT corner in y (h>0)
    hr = -ky * h if h < 0 else 0.0    # inset each RIGHT corner in y (h<0)
    # Input trapezoid (TL, TR, BR, BL) sampled across the full output rectangle.
    in_pts = [(vt, hl), (w - vt, hr), (w - vb, hh - hr), (vb, hh - hl)]
    out_pts = [(0, 0), (w, 0), (w, hh), (0, hh)]
    coeffs = perspective_coeffs(out_pts, in_pts)
    if coeffs is None:
        return img
    return img.transform((w, hh), Image.PERSPECTIVE, coeffs,
                         resample=Image.BICUBIC)
