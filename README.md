<div align="center">

<img src="manoni-icon.png" width="96" alt="Manoni">

# Manoni

**A fast, simple, dark photo browser, culler & editor — built for a weak laptop.**

Browse a folder → keep the good ones → cull the rest → quick edits → export.

<img src="assets/readme/folder-open.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/folder-check.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/sliders-horizontal.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/palette.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/crop.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/wand-sparkles.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/upload.png" width="22" alt="">

Pure **Python + Tkinter + Pillow**. Tiny, MIT-friendly, fully ours to extend.

<br>

<img src="assets/screenshot.jpg" width="900" alt="The Manoni window: folder tree and thumbnails on the left, the photo in the centre, the edit-tool rail on the right, and the filter preview strip along the bottom.">

</div>

---

## Run

```bash
# one-time setup
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# run (optionally pass a folder)
.venv\Scripts\python manoni.py
.venv\Scripts\python manoni.py "C:\path\to\photos"
```

- Python 3.14 is installed on this machine and works.
- The only dependency is **Pillow**. `tkinter` ships with Python.
- If you capture console output and paths contain Georgian/Unicode, set
  `PYTHONUTF8=1` (the Windows console is cp1252 and cannot *print* Georgian —
  the app itself handles Georgian paths fine via Pillow).

---

## The top bar

<table>
<tr>
<td align="center"><img src="assets/readme/folder-open.png" width="22" alt=""></td><td>Open a folder</td>
<td align="center"><img src="assets/readme/save.png" width="22" alt=""></td><td>Save as…</td>
<td align="center"><img src="assets/readme/undo.png" width="22" alt=""></td><td>Undo</td>
<td align="center"><img src="assets/readme/redo.png" width="22" alt=""></td><td>Redo</td>
</tr>
<tr>
<td align="center"><img src="assets/readme/hand.png" width="22" alt=""></td><td>Pan the photo</td>
<td align="center"><img src="assets/readme/square-split-horizontal.png" width="22" alt=""></td><td>Before / after</td>
<td align="center"><img src="assets/readme/settings.png" width="22" alt=""></td><td>Settings</td>
<td align="center"><img src="assets/readme/circle-help.png" width="22" alt=""></td><td>Help</td>
</tr>
</table>

---

## Browse & cull

<img src="assets/readme/folder-check.png" width="18" alt=""> A virtualized thumbnail
strip (handles thousands of files) beside a nested folder-tree sidebar. Click or
press <kbd>←</kbd> / <kbd>→</kbd> to browse, <kbd>↑</kbd> / <kbd>↓</kbd> to cull
each photo into configurable **keep** / **reject** folders. Info bar (name, size,
date), before/after compare, and your session is restored on the next launch.
Nothing is deleted — culling only *moves* files, and <kbd>Ctrl</kbd>+<kbd>Z</kbd>
undoes any move.

---

## The editor

An Adobe-Camera-Raw-style rail on the right — click a tool to open its panel.

| | Tool | What it does |
|:--:|---|---|
| <img src="assets/readme/sliders-horizontal.png" width="22" alt=""> | **Basic** | White balance · tone (highlights / shadows / whites / blacks) · detail (clarity / texture / denoise / dehaze / sharpen) · colour (vibrance / saturation) |
| <img src="assets/readme/palette.png" width="22" alt=""> | **Color mixer** | Per-hue HSL bands, plus dedicated gold & skin mini-HSLs |
| <img src="assets/readme/wand-sparkles.png" width="22" alt=""> | **Effects** | Vignette · grain · split-tone |
| <img src="assets/readme/crop.png" width="22" alt=""> | **Crop** | Trim & straighten, with ratio / social presets |
| <img src="assets/readme/scaling.png" width="22" alt=""> | **Resize** | Change the pixel dimensions |
| <img src="assets/readme/frame.png" width="22" alt=""> | **Perspective** | Fix keystoning, straighten converging lines |
| <img src="assets/readme/bandage.png" width="22" alt=""> | **Heal & Clone** | Remove blemishes (auto, or <kbd>Alt</kbd>+click a clone source) |
| <img src="assets/readme/circle-dot.png" width="22" alt=""> | **Focus blur** | Blur the surroundings, keep the subject sharp |
| <img src="assets/readme/type.png" width="22" alt=""> | **Text & Watermark** | Live text overlays — many per photo, snap to a corner |
| <img src="assets/readme/blend.png" width="22" alt=""> | **Filters** | Saved slider presets with a clickable preview strip |
| <img src="assets/readme/circle-play.png" width="22" alt=""> | **Actions** | Record a macro and replay it on one photo or a whole folder |

Undo / redo · a live histogram · dark / light theme with an accent colour · a
Georgian / English UI.

---

## Filters & the "Last" slot

<img src="assets/readme/blend.png" width="18" alt=""> A **filter** is a saved
slider preset — one click applies the whole look. The strip under the photo
previews every filter *on the current photo*.

<img src="assets/readme/refresh-cw.png" width="18" alt=""> The moment you save a
photo, its edit is pinned as a **"Last"** slot in the strip and the filter list —
click it to apply the same look to the next photo, no saving needed. "Last" is
session-only; its `…` menu can promote it into a permanent named filter.

---

## Export

<img src="assets/readme/upload.png" width="18" alt=""> **Save as…** writes a
full-resolution copy as JPEG / PNG / WEBP — to an `_edited/` subfolder or one
fixed folder. Metadata (camera info, date, GPS, colour profile) is kept or
stripped per your choice, and the original is **never touched**.

---

## Keyboard

| Keys | Action |
|---|---|
| <kbd>←</kbd> / <kbd>→</kbd> | Previous / next photo *(edit panel closed)* |
| <kbd>↑</kbd> / <kbd>↓</kbd> | Keep / reject the current photo |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> | Undo |
| <kbd>Ctrl</kbd>+<kbd>Y</kbd> | Redo *(or <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd>)* |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> | Show / hide the pixel rulers |
| <kbd>[</kbd> / <kbd>]</kbd> | Shrink / grow the heal brush |

The <img src="assets/readme/circle-help.png" width="16" alt=""> **Help** button in
the top bar opens a tabbed guide covering all of the above.

---

## Not done yet

Grid view (2×2 library) · RAW support — both deferred, see `spec/03-roadmap.md`.

## Where to start

Read **`spec/00-START-HERE.md`** first. The whole plan lives in `spec/`.
