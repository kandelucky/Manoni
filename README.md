# Manoni

A fast, simple, **dark** photo browser + culler for a weak laptop.
Browse a folder → keep the good ones → cull the rest → quick edits.

Pure **Python + Tkinter + Pillow**. Tiny, MIT-friendly, fully ours to extend.

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
- Only dependency is **Pillow**. `tkinter` ships with Python.
- If you capture console output and paths contain Georgian/Unicode, set
  `PYTHONUTF8=1` (Windows console is cp1252 and cannot *print* Georgian —
  the app itself handles Georgian paths fine via Pillow).

## What works now

**Browse & cull** — virtualized thumbnail strip (handles thousands of files) ·
nested folder tree sidebar · click or ←/→ to browse · ↑/↓ to cull into
configurable keep/reject folders · sort · info bar (name, size, date) ·
before/after compare · session restored on the next launch.

**Photo editor** (right-side rail, Adobe-Camera-Raw style), each a tool section:
- **Basic** — white balance, tone (highlights/shadows/whites/blacks), detail
  (clarity/texture/denoise/dehaze/sharpen) and colour (vibrance/saturation).
- **Colour mixer** — per-hue HSL bands plus gold/skin mini-HSLs.
- **Crop · Resize · Perspective · Straighten**, with ratio/social presets.
- **Heal & Clone** (auto or Alt+click source), **Focus blur** (DoF),
  **Text/Watermark**, **Effects** (vignette · grain · split-tone).
- **Filters** — saved slider presets with a clickable preview strip.
- **Actions** — record a macro and replay it on one photo or a whole folder.

Undo/redo · live histogram · dark/light theme + accent colour · Georgian/English
UI · settings window · metadata keep-or-strip on export. **Save** writes an
sRGB full-res copy to an `_edited/` subfolder; the original is never touched.

## Not done yet

Grid view (2×2 library) · RAW support (both deferred — see `spec/03-roadmap.md`).

## Where to start

Read **`spec/00-START-HERE.md`** first. The whole plan is in `spec/`.
