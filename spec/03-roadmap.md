# 03 — Roadmap

## Done (first increment)
- Dark interface shell: info bar, toolbar (Lucide icons + hover), thumbnail
  sidebar (scrollable, incremental loading), big preview, bottom nav.
- Load a folder; list supported images (jpg/jpeg/png/webp/bmp/gif/tiff).
- Click a thumbnail → open it; current thumbnail highlighted.
- Navigation: prev / next (wrap) / first / last.
- 🗑 **delete** → moves the file to a `_deleted` subfolder (safe, reversible).
- 📁 **keep-to-folder** → moves the file to a folder you pick.
- 📂 **open folder**.
- Info bar updates: name, index/total, dimensions, size, date.
- Handles Georgian/Unicode paths correctly (uses Pillow, not OpenCV).

## Next — in priority order

### 1. Brightness (☀ `sun`) — DO THIS FIRST
- Clicking opens a small panel/slider over or beside the preview.
- Live preview using `PIL.ImageEnhance.Brightness(img).enhance(factor)`
  (factor 1.0 = unchanged; ~0.5–1.5 range).
- A Save action writes the result. **Decide the save model with Lasha** (see below).
- This sets the reusable pattern (panel + live preview + save) for Resize & Filter.

### 2. Resize (✂ `scaling`)
- Dialog: target by max-side pixels or by percent; keep aspect ratio.
- Useful preset for the store: e.g. "max 2000px, web-optimized JPEG".
- `img.resize(...)` / `img.thumbnail(...)` + save.

### 3. Filter (🎨 `palette`)
- A set of one-click looks: B/W, warm, cool, more/less contrast, more saturation.
  Built from `ImageEnhance` (Color/Contrast) + simple curve/tint.
- Lasha specifically wants to **create his own filter** — design it so presets are
  data (e.g. a dict of adjustments) he can define and save to a small json in this
  folder, then apply to one image or to a batch.

### 4. Grid view (▦ `grid-2x2`)
- Toggle the big preview into a multi-image grid for faster culling.

### 5. Menu (☰)
- Settings: thumbnail size, default save behavior, theme, remember last folder.

## Editing save model — decide with Lasha (don't assume)
Options to offer him:
- **Non-destructive (recommended):** never overwrite the original; write edited
  copies to an `_edited/` subfolder (or export on demand). Safest.
- Overwrite in place (simple, risky).
- Undo stack in memory + explicit Save.
Pick one with him before building the save path.

## Backlog (later, only if he asks)
Keyboard shortcuts · zoom / 100% toggle · multi-select + batch apply · EXIF panel ·
remember last folder · RAW support · drag-and-drop · undo/redo.

## Guardrails
- Keep it **light** — no heavy deps. Pillow only unless Lasha agrees otherwise.
- Keep **delete reversible** (`_deleted` folder, never hard-delete silently).
- Keep the code **simple and readable** — this is co-developed.
- Build **one feature at a time**, show it running, then ask what's next.
