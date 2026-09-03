"""
Application identity: the window icon and, on Windows, the taskbar identity.

Why this file exists
--------------------
Setting a window icon is the obvious half. The non-obvious half is that on
Windows it is not enough, and the symptom is the one everyone hits: you set a
beautiful icon, the title bar shows it, and the taskbar still shows the Python
logo.

That happens because Windows groups taskbar buttons by *AppUserModelID*, not by
window icon. A script launched through `python.exe` inherits Python's AUMID, so
the shell decides the running program is Python and draws Python's icon. Calling
SetCurrentProcessExplicitAppUserModelID before any window is created gives the
process its own identity, and only then does the taskbar use our icon.

It has to happen before the first window exists. After that, Windows has already
assigned the grouping and the call is ignored.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

from .paths import bundle_dir

APP_ID = "dev.mursalfk.ambaar"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def set_windows_app_id(app_id: str = APP_ID) -> bool:
    """
    Give this process its own taskbar identity on Windows.

    Must run before the first window is created. Returns True if applied.
    No-op everywhere else.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        return True
    except (AttributeError, OSError):
        # Older Windows or a locked-down shell. The app still runs; the taskbar
        # just falls back to the interpreter's icon.
        return False


def icon_dir() -> Path:
    return bundle_dir() / "assets" / "icons" / "generated"


def app_icon() -> QIcon:
    """
    Build a multi-resolution QIcon.

    Every size is added explicitly rather than letting Qt scale one bitmap. The
    16px taskbar and 256px alt-tab renders come from art drawn at those sizes,
    so the mark stays crisp instead of turning to mush at small sizes.
    """
    icon = QIcon()
    folder = icon_dir()
    added = 0
    for size in ICON_SIZES:
        path = folder / f"icon_{size}.png"
        if path.is_file():
            icon.addPixmap(QPixmap(str(path)))
            added += 1

    if added == 0:
        # Fall back to the brand mark, then to nothing. A missing icon is a
        # cosmetic problem and must never stop the app from starting.
        fallback = bundle_dir() / "assets" / "brand" / "mark-512.png"
        if fallback.is_file():
            icon.addPixmap(QPixmap(str(fallback)))
    return icon


def apply(app) -> None:
    """Attach the icon to the QApplication. Call after QApplication exists."""
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
