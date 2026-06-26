# 01 — Overview

## What Manoni (the tool) is
A **fast, lightweight, dark-themed photo browser + culler** with simple editing,
for Lasha's online store workflow. Not a pro RAW tool — simple and quick.

The core loop Lasha wants:
1. Open a folder of photos.
2. **See them as a library** (thumbnail panel) and flip through quickly.
3. **Cull**: delete the bad ones, **keep the good ones into folders**.
4. **Quick edits**: resize, brightness/lighting, and apply a filter.
5. Nothing more. Speed and simplicity over features.

## Hard constraints (these shaped every decision)
- **Weak laptop** — must be light and fast. No heavy frameworks, no GPU needs.
- **Real interface** — buttons, panels, a toolbar. Not keyboard-only.
- **Commercial-OK license** — it's for a *store* (commercial use). So MIT/BSD/GPL
  open source is fine; "free for personal use only" tools (XnView, FastStone,
  IrfanView) are **not** cleanly free for him.
- **Co-developable** — Lasha + the agent improve it together over time, so the
  code must be easy to read and change quickly (no long compile cycles).

## Why we built our own instead of using an existing app
No single existing app satisfied all four constraints at once (see
`04-decisions-and-research.md` for the full evaluation). The lightest stack that
is commercial-OK *and* instantly co-developable is **Python + Tkinter + Pillow**.
We modeled the interface on **ImageGlass** (Lasha picked that layout) and went
**dark theme** (the Lucide icons are white, and it suits the look).

## About Lasha (how to work with him)
- Communicate in **Georgian**. Short, concrete, no filler, no emoji.
- He has **ADHD**: one step at a time; suggest, never command; give a clear
  recommendation instead of a menu; acknowledge progress.
- He runs an online jewelry store (Sallora / By Kandelucky). This photo tool is to
  speed up preparing product photos.
- He is capable and has built several apps before — but building from zero drains
  him. Always build on something that already runs.
