# 02 — Interface design (LOCKED with Lasha)

Modeled on **ImageGlass** (Lasha showed a screenshot and approved this layout).
**Dark theme.** Icons are **Lucide** (white strokes, 24×24 PNG) from `../icons/`.

## Layout (4 zones)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  foto_07.jpg   │  11/27   │  49%  │  3871×2579  │  1.78 MB  │  2026/06/26  │  ← info bar
├──────────────────────────────────────────────────────────────────────────┤
│  ◀  ▶  │  ⤢ fit   ▦ grid │  ✂ resize   ☀ bright   🎨 filter │ 📁 keep  🗑 del │ 📂 ☰ │  ← toolbar
├───────────────┬────────────────────────────────────────────────────────────┤
│ ┌──┐┌──┐┌──┐  │                                                            │
│ thumbnails of │                BIG PREVIEW of the                          │
│ the open      │                selected image                              │
│ folder (left, │                                                            │
│ scrollable,   │                                                            │
│ current one   │                                                            │
│ highlighted)  │                                                            │
├───────────────┴────────────────────────────────────────────────────────────┤
│                       1/27   │◀  ◀   ▶  ▶│                                  │  ← bottom nav
└──────────────────────────────────────────────────────────────────────────┘
```

1. **Info bar** (top): filename · index/total · zoom · dimensions · size · date.
2. **Toolbar**: nav · fit/grid · **resize / brightness / filter** · keep-to-folder /
   delete · open-folder / menu.
3. **Sidebar** (left): thumbnails of every image in the open folder, scrollable,
   current image highlighted (accent border), click to open.
4. **Preview** (right) + **bottom nav** (position + first/prev/next/last).

## Dark theme colors (in `manoni.py`)
| token | hex | use |
|---|---|---|
| BG | `#1b1b1b` | main background / preview |
| BAR | `#262626` | toolbar + info bar + bottom bar |
| SIDEBAR | `#1e1e1e` | thumbnail panel |
| HOVER | `#3a3a3a` | button hover |
| ACCENT | `#4aa3ff` | selected thumbnail border |
| FG | `#e6e6e6` | primary text |
| FG_DIM | `#9a9a9a` | secondary text |

## Toolbar button → Lucide icon (verified, files in ../icons/)
| button | icon file | status |
|---|---|---|
| ◀ previous | `chevron-left` | works |
| ▶ next | `chevron-right` | works |
| ⤢ fit | `maximize` | works (re-fits preview) |
| ▦ grid view | `grid-2x2` | **stub** |
| ✂ resize | `scaling` | **stub** |
| ☀ brightness | `sun` | **stub** |
| 🎨 filter | `palette` | **stub** |
| 📁 keep-to-folder | `folder-check` | works (moves file) |
| 🗑 delete | `trash-2` | works (→ `_deleted`) |
| 📂 open folder | `folder-open` | works |
| ☰ menu | `menu` | **stub** |
| ⟪ first / ⟫ last (bottom) | `chevrons-left` / `chevrons-right` | works |

Icons are white → only visible on the dark bars. To recolor (e.g. for a future
light theme) tint them at load time in `Manoni.icon()`.
`../icons/` already contains ~54 curated Lucide icons for current + upcoming buttons.
