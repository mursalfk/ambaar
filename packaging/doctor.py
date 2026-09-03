#!/usr/bin/env python3
"""
Environment doctor.

Run this when the app will not start, before rebuilding anything:

    python packaging/doctor.py

It checks the things that actually break Ambaar in the field, in the order they
are worth checking. Most useful for Qt DLL failures, where the error message
names QtCore but the real damage is usually elsewhere.
"""

from __future__ import annotations

import importlib.metadata as md
import os
import platform
import shutil
import sys
from pathlib import Path

OK, WARN, BAD = "ok  ", "warn", "FAIL"


def line(state: str, label: str, detail: str = "") -> None:
    print(f"  [{state}] {label}" + (f" -- {detail}" if detail else ""))


def check_python() -> bool:
    v = sys.version_info
    good = v[:2] >= (3, 9)
    line(OK if good else BAD, f"Python {v.major}.{v.minor}.{v.micro}",
         "" if good else "yt-dlp needs 3.9+; pip installs an obsolete build below that")
    in_venv = sys.prefix != sys.base_prefix
    line(OK if in_venv else WARN, "virtualenv active" if in_venv else "not in a virtualenv",
         "" if in_venv else "system-wide installs mix Qt versions more easily")
    return good


def check_qt_versions() -> bool:
    """The single most common cause of 'procedure could not be found'."""
    names = ["PySide6", "PySide6-Essentials", "PySide6-Addons", "shiboken6"]
    found = {}
    for n in names:
        try:
            found[n] = md.version(n)
        except md.PackageNotFoundError:
            pass

    if not found:
        line(BAD, "PySide6 not installed", "pip install -r requirements.txt")
        return False

    versions = set(found.values())
    matched = len(versions) == 1
    for n, v in found.items():
        line(OK if matched else BAD, f"{n} {v}")
    if not matched:
        line(BAD, "Qt package versions disagree",
             "reinstall together: pip uninstall -y " + " ".join(found) +
             " && pip install PySide6==6.8.1")
        return False

    # A second Qt binding in the same environment is a reliable way to load the
    # wrong Qt6Core.dll at import time.
    rivals = [n for n in ("PyQt5", "PyQt6", "PySide2") if _installed(n)]
    if rivals:
        line(BAD, f"conflicting Qt bindings: {', '.join(rivals)}",
             f"pip uninstall -y {' '.join(rivals)}")
        return False
    line(OK, "no conflicting Qt bindings")
    return True


def _installed(name: str) -> bool:
    try:
        md.version(name)
        return True
    except md.PackageNotFoundError:
        return False


def check_qt_import() -> bool:
    try:
        from PySide6 import QtCore
        line(OK, f"QtCore imports, Qt {QtCore.qVersion()}")
    except Exception as e:
        line(BAD, "QtCore import failed", str(e))
        if "procedure could not be found" in str(e).lower():
            line(BAD, "diagnosis",
                 "a Qt DLL of the wrong version is being loaded; check PATH below")
        elif "module could not be found" in str(e).lower():
            line(BAD, "diagnosis",
                 "a Qt DLL is missing; install the VC++ 2015-2022 redistributable")
        return False

    for mod in ("QtWidgets", "QtGui", "QtSvg"):
        try:
            __import__(f"PySide6.{mod}")
            line(OK, f"{mod} imports")
        except Exception as e:
            line(BAD, f"{mod} import failed", str(e))
            return False
    return True


def check_path_contamination() -> None:
    """Foreign Qt DLLs on PATH outclass the bundled ones during DLL resolution."""
    if sys.platform != "win32":
        line(OK, "PATH scan skipped (not Windows)")
        return
    hits = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            p = Path(entry)
            if p.is_dir() and any(p.glob("Qt6Core.dll")):
                hits.append(str(p))
        except OSError:
            continue
    safe = [h for h in hits if ".venv" in h or "dist" in h]
    foreign = [h for h in hits if h not in safe]
    if foreign:
        line(BAD, "foreign Qt on PATH", "; ".join(foreign[:3]))
        line(BAD, "diagnosis", "remove these from PATH, or build in a clean shell")
    else:
        line(OK, "no foreign Qt6Core.dll on PATH")


def check_engine() -> None:
    try:
        import yt_dlp.version
        line(OK, f"yt-dlp {yt_dlp.version.__version__}")
    except ImportError:
        line(BAD, "yt-dlp not installed", "pip install -r requirements.txt")
    try:
        import yt_dlp.extractor  # noqa: F401
        line(OK, "extractors importable")
    except ImportError as e:
        line(BAD, "extractors missing", str(e))


def check_ffmpeg() -> None:
    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ff and fp:
        line(OK, "ffmpeg on PATH", str(Path(ff).parent))
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from ambaar import ffmpeg as tool
        if tool.available():
            line(OK, "ffmpeg in managed tools", tool.location_hint())
            return
    except Exception:
        pass
    line(WARN, "ffmpeg not found",
         "the app offers a one-click install on first run")


def main() -> int:
    print(f"\nAmbaar doctor  --  {platform.system()} {platform.release()}\n")

    print("Interpreter")
    py_ok = check_python()

    print("\nQt packages")
    qt_ok = check_qt_versions()

    print("\nQt import")
    import_ok = check_qt_import() if qt_ok else False

    print("\nPATH")
    check_path_contamination()

    print("\nEngine")
    check_engine()

    print("\nffmpeg")
    check_ffmpeg()

    print()
    if py_ok and qt_ok and import_ok:
        print("  Environment looks healthy. If the packaged build still fails,")
        print("  rebuild clean:  pyinstaller packaging/ambaar.spec --noconfirm --clean\n")
        return 0
    print("  Fix the FAIL lines above, then rerun this script.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
