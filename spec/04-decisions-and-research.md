# 04 — Decisions & research (so you don't repeat it)

We searched extensively. **Do not redo this search.** Summary of what was
evaluated and why we landed on building our own with Python+Tkinter+Pillow.

## The deciding requirement set
Light (weak laptop) · real interface · browse→cull→keep-to-folders→quick edit ·
**commercial-OK license (it's for a store)** · easy to co-develop (fast iteration).

## Tools evaluated and rejected
| Tool | License | Why not |
|---|---|---|
| Jimp, Pillow, GraphicsMagick | MIT-ish | Libraries, **no UI**. (We do use Pillow as our engine.) |
| **Blurry** (genotrance) | MIT, Python/Tkinter | Closest in stack, but **keyboard-only, no real UI**; its "delete" only removes from the *view*, not disk; built around similarity-grouping, not a simple folder browser. We reused the **idea + stack**, not the code. |
| Oculante | MIT, Rust | Great + light, but **Rust recompile is heavy on a weak laptop**; minimal keyboard-ish UI. Bad for fast co-dev. |
| PhotoDemon | BSD, VB6 | Rich UI, very light, portable — but **VB6 = we can't co-develop**, Windows-only. |
| Pinta | MIT, C#/.NET | Clean editor, but **no gallery/cull** (single-image editor). |
| nomacs | GPL, C++ | Viewer + thumbnails + light edit, light — but **C++ build heavy** for co-dev. |
| darktable | GPL, C | Best library+edit interface (free Lightroom) but **heavy (8GB RAM + GPU recommended)**, pro RAW, complex. Too much for a weak laptop and "simple/fast". |
| Isolate (seenaburns) | BSD, TS/React/Electron | On-target culling (grid + move-to-folder) and co-dev-friendly language, but **unmaintained since 2018** and **Electron = heavy** on a weak laptop. |
| Caesium | GPL **not MIT** | Compressor only. |
| XnView MP / FastStone / IrfanView | freeware | The best fast cullers, **but free only for personal use → not free for a store (commercial)**. |

## Final decision
Build **our own** ("Manoni") on **Python + Tkinter + Pillow**:
- Lightest realistic stack, runs on a weak laptop.
- Commercial-OK (all MIT/PSF/BSD-style; no license fee for the store).
- **Instantly co-developable** — edit a `.py` file and re-run, no compile.
- Interface modeled on **ImageGlass** (Lasha's pick), **dark theme**, Lucide icons.

## Key technical gotchas (learned the hard way)
1. **OpenCV `cv2.imread` returns `None` for non-ASCII (Georgian) paths on Windows.**
   Proven. Workaround if cv2 is ever needed: `cv2.imdecode(np.fromfile(path, np.uint8), ...)`.
   **Manoni avoids this entirely by using Pillow** (`Image.open`), which handles
   Georgian paths fine. Do not introduce cv2 for image loading.
2. **Windows console is cp1252** and cannot *print* Georgian (crashes with
   `UnicodeEncodeError`). When you capture stdout, set `PYTHONUTF8=1`. This is only
   a *printing* issue; file/path handling is fine.
3. **Python 3.14** is installed and works (Pillow has wheels for it).
4. Tkinter `tk.PhotoImage`/`ImageTk.PhotoImage` objects must be **kept referenced**
   or they get garbage-collected and disappear. Manoni keeps them in lists
   (`thumb_images`) and on the widget (`preview.image`).

## Environment notes
- Machine: Windows 11, Python 3.14 at
  `C:\Users\likak\AppData\Local\Python\pythoncore-3.14-64`.
- Lucide icon source set (full, 1943 icons):
  `C:\Users\likak\Desktop\lucide-icons\png-icons` — we copied ~54 into `../icons/`.
- An earlier prototype/clone of Blurry may still exist under the session scratchpad;
  it is **not** part of this project. This project is self-contained.
