# -*- mode: python ; coding: utf-8 -*-
# Build with:  pyinstaller --noconfirm HullVanguard.spec
#
# Produces dist/HullVanguard/ containing:
#   HullVanguard.exe           windowed release (no console)
#   HullVanguard-Debug.exe     console build for diagnosing crashes
#   _internal/                 PyInstaller deps (Python, torch, ultralytics, ...)

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# Heavy deps with non-trivial data files / DLLs / dynamic imports.
for pkg in ("ultralytics", "torch", "torchvision", "pygame", "PIL", "serial"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[spec] collect_all({pkg}) failed: {e}")

# Ultralytics pulls these dynamically; pin them so PyInstaller sees them.
hiddenimports += [
    "ultralytics.utils",
    "ultralytics.engine",
    "ultralytics.nn",
    "ultralytics.models",
    "ultralytics.data",
]

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter.test",
        "test",
        # NOTE: do NOT exclude "unittest" — Ultralytics / PyTorch lazily import
        # unittest.mock when loading YOLO models, and dropping it breaks AI mode
        # with "No module named 'unittest'".
        "pydoc",
        "pdb",
        "matplotlib.tests",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Windowed release exe — what users double-click.
exe_release = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HullVanguard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",
    version="version_info.txt",
)

# Console exe — same code, console window visible so stdout/stderr show.
exe_debug = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HullVanguard-Debug",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",
    version="version_info.txt",
)

coll = COLLECT(
    exe_release,
    exe_debug,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HullVanguard",
)
