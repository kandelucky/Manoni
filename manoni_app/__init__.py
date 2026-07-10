"""Manoni application package.

The app was one 2900-line file (`manoni.py`). To stop it from growing without
bound, the code is being split here by responsibility:

    config.py    static configuration: paths, supported formats, theme, sizes
    widgets.py   small reusable Tk widgets (Slider, Tooltip)
    imaging/     pure image-processing helpers (no Tk, no `self`)
    ui/          the Manoni window, split into mixins by feature area

Rule of thumb: a new feature goes into the module it belongs to. Nothing new
should be added back into a single giant file. See spec/03-architecture.md.
"""
