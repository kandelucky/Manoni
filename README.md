<div align="center">

<img src="manoni-icon.png" width="96" alt="Manoni">

# Manoni

**A fast, simple photo browser, culler & editor — built for a weak laptop.**

Browse a folder → keep the good ones → cull the rest → quick edits → export.

<img src="assets/readme/folder-open.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/folder-check.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/sliders-horizontal.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/palette.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/crop.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/wand-sparkles.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/image.png" width="22" alt="">&nbsp;&nbsp;
<img src="assets/readme/save-all.png" width="22" alt="">

Pure **Python + Tkinter + Pillow**. Tiny, open source, fully ours to extend.

**[Website](https://kandelucky.github.io/Manoni)** · **[Download](https://github.com/kandelucky/Manoni/releases/latest)** · **[Community & sharing](https://github.com/kandelucky/Manoni/discussions)**

<br>

<img src="assets/screenshot.jpg" width="900" alt="The Manoni window: folder tree and thumbnails on the left, the photo in the centre, the edit-tool rail on the right, and the filter preview strip along the bottom.">

</div>

---

## Who it's for

For photographers who shoot a lot and work on a modest machine. Manoni is built
to **cull a big batch fast, make quick but real edits, and hand back clean
copies** — light enough to stay smooth on a weak laptop, simple enough to stay
out of your way.

You'll feel at home if you:

- shoot in **volume** and need to sort keepers from rejects quickly;
- want **real edits** — tone, colour, crop, heal, filters — without a heavy install;
- work on a **weak or old laptop** and want it to stay fast;
- care that your **originals stay untouched** — edits go to exported copies, and the
  three ways to change an original (Overwrite, wiping its metadata, and the delete in
  the thumbnail menu) each ask you first.

---

## Run

**Most people — install it.** Download the **Windows installer**
(`Manoni-<version>-Setup.exe`) from the
[Releases page](https://github.com/kandelucky/Manoni/releases/latest), run it,
and launch Manoni from the Start menu. No Python needed. It installs into Program
Files, so Windows asks for administrator rights. Manoni is not code-signed yet, so
SmartScreen will warn you first — [here's why, and what you can check instead](https://kandelucky.github.io/Manoni#smartscreen).

The installer registers `.mnf` / `.mnl` files so a double-click opens them in Manoni,
and adds Manoni to the **Open with** menu for photos — without taking the association,
so whatever opens your `.jpg` today still opens it tomorrow.

Manoni never phones home on its own. **Settings → About → Check for updates** asks
GitHub for the latest release only when you click it.

**Run from source** (for development):

```bash
# one-time setup
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# run (optionally pass a folder)
.venv\Scripts\python manoni.py
.venv\Scripts\python manoni.py "C:\path\to\photos"
```

- Developed on Python 3.14. There is no version gate in the code, but older versions
  are untested.
- Three dependencies, all in `requirements.txt`: **Pillow** (imaging), **tintkit** (the
  widget kit), and **tkinterdnd2** (drag & drop — the only one that is optional; without
  it Manoni starts fine and simply won't accept dropped files). `tkinter` ships with
  Python.

---

## Browse & cull

<img src="assets/readme/folder-check.png" width="18" alt=""> A virtualized thumbnail
strip (handles thousands of files) beside a nested folder-tree sidebar. Click a
thumbnail, or walk the strip with the **arrow keys** — <kbd>←</kbd> / <kbd>↑</kbd>
back, <kbd>→</kbd> / <kbd>↓</kbd> forward. <kbd>Enter</kbd> keeps the photo and
<kbd>Backspace</kbd> rejects it, each into a configurable **keep** / **reject**
folder. Info bar (name, size, date), before/after compare, and your session is
restored on the next launch. Culling never deletes — it only *moves* files, and
<kbd>Ctrl</kbd>+<kbd>Z</kbd> undoes any move. (A thumbnail's right-click menu does
offer a permanent delete, behind a confirm. It is the one thing in Manoni you cannot
undo, and it is the only way a photo leaves your disk.)

---

## The editor

A tool rail on the right — click a tool to open its panel.

| | Tool | What it does |
|:--:|---|---|
| <img src="assets/readme/sliders-horizontal.png" width="22" alt=""> | **Basic** | White balance · tone (highlights / shadows / whites / blacks) · detail (clarity / texture / denoise / dehaze / sharpen) · colour (vibrance / saturation) |
| <img src="assets/readme/palette.png" width="22" alt=""> | **Color mixer** | Eight per-hue saturation bands, plus dedicated gold & skin mini-HSLs (hue, saturation and lightness) |
| <img src="assets/readme/wand-sparkles.png" width="22" alt=""> | **Effects** | Vignette · grain · split-tone |
| <img src="assets/readme/crop.png" width="22" alt=""> | **Crop** | Trim, straighten a tilted horizon (±45°), rotate 90°, flip H / V — with ratio and social presets |
| <img src="assets/readme/scaling.png" width="22" alt=""> | **Resize** | Resize one photo, or every photo in a folder and its subfolders in one batch |
| <img src="assets/readme/frame.png" width="22" alt=""> | **Perspective** | Fix keystoning, straighten converging lines |
| <img src="assets/readme/bandage.png" width="22" alt=""> | **Heal & Clone** | Remove blemishes (auto, or <kbd>Alt</kbd>+click a clone source) |
| <img src="assets/readme/circle-dot.png" width="22" alt=""> | **Focus blur** | Blur the surroundings, keep the subject sharp |
| <img src="assets/readme/type.png" width="22" alt=""> | **Text & Watermark** | Live text overlays — many per photo, with fonts, bold / italic, colour, shadow and corner-snap |
| <img src="assets/readme/image.png" width="22" alt=""> | **Logo** | Drop a transparent PNG onto the photo — many per photo, with size / opacity / tint / flip and corner-snap |
| <img src="assets/readme/blend.png" width="22" alt=""> | **Filters** | Saved slider presets with a clickable preview strip |
| <img src="assets/readme/circle-play.png" width="22" alt=""> | **Actions** | Record a macro and replay it on one photo or a whole folder |

Text and logo overlays share **one layer stack** — a text can sit above a logo or
below it. The `…` chip beside the selected overlay moves it up or down through the
others, or deletes it.

Undo / redo · a live histogram · before / after compare (a split line, or a
press-and-hold peek) · dark / light theme with an accent colour · an English &
Polish UI, with Georgian one download away.

---

## Filters & the "Last" slot

<img src="assets/readme/blend.png" width="18" alt=""> A **filter** is a saved
slider preset — one click applies the whole look. The strip under the photo
previews every filter *on the current photo*.

<img src="assets/readme/refresh-cw.png" width="18" alt=""> The moment you save a
photo, its edit is pinned as a **"Last"** slot in the strip and the filter list —
click it to apply the same look to the next photo, no saving needed. "Last" is
session-only; its `…` menu can promote it into a permanent named filter.

<img src="assets/readme/share-2.png" width="18" alt=""> **Share filters.** A
filter group's `…` menu exports the whole group to a small `.mnf` file — send it
to a friend, and they load it from the **Import** button pinned atop the Filters
panel (or just double-click the file). Swap looks with other people on the
[Community board](https://github.com/kandelucky/Manoni/discussions/categories/filters).

---

## Save & export

Three ways to save, at full resolution. **Only the first one replaces a file.**

<img src="assets/readme/save.png" width="18" alt=""> **Save**
(<kbd>Ctrl</kbd>+<kbd>S</kbd>) writes your edits straight **back over the open
file**. There is no backup, so it asks you to confirm — the one save that alters
an original.

<img src="assets/readme/copy-plus.png" width="18" alt=""> **Save a copy**
(<kbd>Ctrl</kbd>+<kbd>E</kbd>) drops the same edits into a **subfolder beside the
photo** (`_edited/` by default) as a new, numbered file — no dialog, no folder to
pick. Neither the original nor an earlier copy is replaced; a second copy of the
same photo lands beside the first. Set the subfolder in **Settings → Export** — or
point that setting at one fixed folder, and every copy lands there instead.

<img src="assets/readme/save-all.png" width="18" alt=""> **Save as…**
(<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd>) opens a dialog — pick the format
(JPEG / PNG / WEBP), quality and folder, either an `_edited/` subfolder or one
fixed folder. The original is left untouched.

For every save — Overwrite included — metadata (camera info, date, GPS, colour
profile) is kept or stripped per your choice in **Settings → Export**, and colours
can be **converted to sRGB** so a wide-gamut photo still looks right on the web.

<img src="assets/readme/circle-help.png" width="18" alt=""> An **info** button in
the top bar shows a photo's full metadata — camera, capture, colour profile and
location — and can **wipe GPS & EXIF** from a file before you share it.

---

## Keyboard

| Keys | Action |
|---|---|
| <kbd>←</kbd> / <kbd>↑</kbd> | Previous photo |
| <kbd>→</kbd> / <kbd>↓</kbd> | Next photo |
| <kbd>Enter</kbd> | Keep the current photo |
| <kbd>Backspace</kbd> | Reject the current photo |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> | Open a folder of photos |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | Save — **overwrite** the open file |
| <kbd>Ctrl</kbd>+<kbd>E</kbd> | Save a copy — a numbered file in a subfolder beside the photo |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>S</kbd> | Save as… — pick format, quality and folder |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> | Undo |
| <kbd>Ctrl</kbd>+<kbd>Y</kbd> | Redo *(or <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd>)* |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> | Show / hide the pixel rulers |
| <kbd>[</kbd> / <kbd>]</kbd> | Shrink / grow the heal brush |
| <kbd>R</kbd> | Start / stop recording an action |
| <kbd>Esc</kbd> | Cancel recording |
| <kbd>P</kbd> | Replay the highlighted action on the current photo |
| <kbd>Shift</kbd>+<kbd>P</kbd> | Replay it over the whole folder |

The <img src="assets/readme/circle-help.png" width="16" alt=""> **Help** button in
the top bar opens a tabbed guide covering all of the above.

---

## Any language

The interface ships in **English and Polish**. Every other language is a small
`.mnl` pack you download and double-click — **Georgian** is the first one, up on
the [Community board](https://github.com/kandelucky/Manoni/discussions/categories/language-packs).

Building your own is easy — no code, no rebuild. **Settings → General → Add your
language** generates a template listing every phrase in the app; translate the
ones you want, then import it back. Anything you leave untranslated simply stays
English, so even a half-finished pack works the moment you load it. Share your
pack — or grab someone else's — on the same board.

---

## TODO

- [x] **`.mnf` / `.mnl` file types** — filters export as `.mnf`, languages as
  `.mnl`; opening or dropping one on the window imports it.
- [x] **Register the file types with Windows** — double-click a `.mnf` / `.mnl`
  opens Manoni, with their own file icons *(in the installer)*.
- [x] **Windows installer** — single-instance, drag & drop, a PyInstaller build and
  an Inno Setup installer *(ships as Setup.exe)*.
- [x] **"Open with Manoni"** — the installer adds Manoni to the Open-with menu for
  the photo formats it can open, without taking the association from whatever you
  use today.
- [x] **Community sharing** — a
  [Discussions board](https://github.com/kandelucky/Manoni/discussions) for
  swapping language packs and filter groups, with a how-to in each category.
- [ ] **In-app sharing** — share / receive buttons inside Manoni, so you can
  publish or grab a pack without leaving the app.
- [ ] **RAW support** — an optional add-on (installer tick-box or on-demand
  download) so the base app stays light; export as JPEG or 16-bit TIFF.

## License

Manoni is free software, released under the
[GNU General Public License v3.0](LICENSE). You can use, study, share and
modify it; anything built on it must stay under the same license.
