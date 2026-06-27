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

Browse thumbnails (left panel) · click to open · ◀ ▶ first/last navigation ·
🗑 delete (moves file to a `_deleted` subfolder — safe, reversible) ·
📁 move-to-folder (keep good ones) · 📂 open folder · info bar (name, size, date).

**Photo editor** (right-side panel, Adobe-Camera-Raw style): live sliders for
**brightness · contrast · saturation · temperature · blur↔sharpen**, "reset", and
**save** — the edited full-res copy goes to an `_edited/` subfolder, the original is
never touched.

## Not done yet

Tint · Vignette · Shadows/Highlights · custom filter presets · Resize · Grid view · Menu.
The toolbar's ☀/🎨 buttons are still stubs (editing lives in the right panel).
See `spec/03-roadmap.md`.

## Where to start

Read **`spec/00-START-HERE.md`** first. The whole plan is in `spec/`.
