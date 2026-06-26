# START HERE — for the next agent

You are continuing **Manoni**, a photo browser/culler we are building for Lasha.
This folder is self-contained. You do **not** need any external memory — everything
you need is in this `spec/` folder and the code in `../manoni.py`.

## Read these in order
1. `01-overview.md` — what we are building and why, and how to work with Lasha.
2. `02-interface-design.md` — the locked interface design (layout, dark theme, icons).
3. `03-roadmap.md` — what is done and exactly what to build next.
4. `04-decisions-and-research.md` — every tool we evaluated and rejected (so you
   don't repeat the search) + the key technical gotchas.

## Run it first (see it before you touch it)
```
cd C:\Users\likak\Desktop\Manoni
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python manoni.py
```
Then click 📂 (open folder) and pick a photo folder. Or pass a folder as an argument.

## State of the code (one line)
The **interface shell is built and working** (dark, ImageGlass-style: info bar +
toolbar with Lucide icons + thumbnail sidebar + big preview + bottom nav).
Browsing, delete, move-to-folder, open-folder all work. **Editing is stubbed.**

## The single most useful next task
Implement **Brightness** (the ☀ `sun` toolbar button): a slider that adjusts the
current image live (`PIL.ImageEnhance.Brightness`) and saves. It is the easiest,
highest-value win and sets the pattern for Resize and Filter. Details in
`03-roadmap.md`.

## How Lasha works (important)
- Talk to him in **Georgian**, short and concrete. No fluff, no emoji.
- **Suggest, don't command.** Offer one step at a time. Don't dump a big plan.
- He has ADHD — too many options causes paralysis. Give a recommendation, ask one
  question, wait. Acknowledge progress ("what worked out?"), never "what failed?".
- He hates being made to build from zero for weeks. We are building incrementally
  on a working base on purpose.
