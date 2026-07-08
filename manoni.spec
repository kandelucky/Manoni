# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Manoni (one-folder, windowed).

Build:  .venv\\Scripts\\pyinstaller.exe manoni.spec --noconfirm
Output: dist\\Manoni\\Manoni.exe

CONSOLE toggles a visible console window: keep True while debugging a build (so a
startup traceback is visible), flip to False for the shipping build.
"""

from PyInstaller.utils.hooks import collect_all

CONSOLE = False

# Read-only data shipped with the app (config.py finds these via sys._MEIPASS).
datas = [
    ('icons', 'icons'),
    ('logos', 'logos'),          # Logo tool preset PNGs (config.LOGO_PRESET_DIR)
    ('manoni_app/langs', 'manoni_app/langs'),  # bundled language packs (translations._LANGS_DIR)
    ('Filter_Show.jpg', '.'),
    ('manoni.ico', '.'),
    ('manoni-icon.png', '.'),
]
binaries = []
hiddenimports = []

# tkinterdnd2 ships the native tkdnd binaries as data; tintkit may ship its own
# assets. collect_all pulls each package's modules + data + dylibs.
for _pkg in ('tkinterdnd2', 'tintkit'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h


a = Analysis(
    ['manoni.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Manoni',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,
    disable_windowed_traceback=False,
    icon='manoni.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Manoni',
)
