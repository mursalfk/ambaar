# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec.

Build with:
    pyinstaller packaging/ambaar.spec --noconfirm

Two things here are not boilerplate and are worth understanding before editing.

1. yt-dlp's extractors are imported lazily by name, so PyInstaller's static
   analysis cannot see them. `collect_submodules("yt_dlp")` pulls the whole tree
   in. Drop it and the app builds fine, then fails at runtime on the first URL
   with "no suitable extractor" -- a bug that only shows up in the packaged
   artifact, never in development.

2. Qt is trimmed hard. PySide6 ships WebEngine, 3D, Charts, Multimedia and more;
   none are used here and together they roughly triple the download. The
   excludes below are what keeps the build in sensible territory.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
ICONS = ROOT / "assets" / "icons" / "generated"

icon = None
if sys.platform == "win32" and (ICONS / "icon.ico").is_file():
    icon = str(ICONS / "icon.ico")
elif sys.platform == "darwin" and (ICONS / "icon.icns").is_file():
    icon = str(ICONS / "icon.icns")

datas = []
fonts = ROOT / "assets" / "fonts"
if fonts.is_dir() and any(p.suffix.lower() in {".ttf", ".otf"} for p in fonts.iterdir()):
    datas.append((str(fonts), "assets/fonts"))

# branding.app_icon() reads these at runtime, so they have to be inside the
# bundle. Without them the window falls back to the generic Qt icon.
for folder in ("assets/icons/generated", "assets/brand"):
    src = ROOT / folder
    if src.is_dir():
        datas.append((str(src), folder))

hidden = collect_submodules("yt_dlp")

# ---------------------------------------------------------------------------
# Excludes
#
# Qt is shipped whole by default. Trimming it is opt-in via AMBAAR_LEAN=1,
# because the excludes below have already caused a build that packaged cleanly
# and then failed to start.
# ---------------------------------------------------------------------------

# Default is OFF. Trimming Qt broke real builds with "DLL load failed while
# importing QtCore" on PySide6 6.11 + Windows: the app compiled, packaged, and
# then would not start. Correctness beats roughly 60 MB.
#
# Set AMBAAR_LEAN=1 to trim, and actually launch the result before shipping it.
# The failure does not appear at build time.
LEAN = os.environ.get("AMBAAR_LEAN", "0") == "1"

# Never Qt. Safe in every configuration.
BASE_EXCLUDES = [
    "tkinter", "matplotlib", "numpy", "scipy", "pandas", "IPython", "pytest",
]

# Whole Qt subsystems with their own DLL trees. Nothing in the app imports these.
QT_EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSerialPort",
    "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtDesigner",
]

# Deliberately NOT excluded, whatever the size cost: QtOpenGL,
# QtOpenGLWidgets, QtNetwork, QtSvg, QtDBus, QtQml, QtPrintSupport.
# Qt6Gui and Qt6Widgets link against several of these, and dropping one gives
# you a build that fails pointing at QtCore while the real damage is elsewhere.

EXCLUDES = BASE_EXCLUDES + (QT_EXCLUDES if LEAN else [])

# onefile produces a single .exe instead of a folder. Convenient to hand out,
# but it unpacks to a temp directory on every launch, so startup is noticeably
# slower and antivirus heuristics flag it far more often. onedir is the default
# for good reason.
ONEFILE = os.environ.get("AMBAAR_ONEFILE", "0") == "1"

print(f"[ambaar.spec] {'LEAN' if LEAN else 'full'} Qt, "
      f"{'onefile' if ONEFILE else 'onedir'}, {len(EXCLUDES)} excludes")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

_common = dict(
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=sys.platform == "darwin",
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

if ONEFILE and sys.platform != "darwin":
    # Everything folded into one executable. No COLLECT step.
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="ambaar",
        runtime_tmpdir=None,
        **_common,
    )
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ambaar", **_common)
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False, upx=False, upx_exclude=[], name="ambaar",
    )

    if sys.platform == "darwin":
        app = BUNDLE(
            coll,
            name="Ambaar.app",
            icon=icon,
            bundle_identifier="dev.mursalfk.ambaar",
            info_plist={
                "CFBundleName": "Ambaar",
                "CFBundleDisplayName": "Ambaar",
                "CFBundleShortVersionString": "1.1.0",
                "CFBundleVersion": "1.1.0",
                "NSHighResolutionCapable": True,
                "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
                "LSMinimumSystemVersion": "11.0",
            },
        )
