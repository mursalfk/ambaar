"""
Engine path bootstrap. This must run before anything imports yt_dlp.

The problem it solves
---------------------
A frozen build has no pip and no writable site-packages, so `pip install -U
yt-dlp` -- the whole basis of the weekly updater -- cannot work once the app is
packaged. Without a fix, every downloaded .exe would be frozen against whatever
yt-dlp existed on build day and would break the first time YouTube changed its
player. That is precisely the failure this project exists to prevent.

The fix
-------
yt-dlp is pure Python, so a newer release does not need installing -- it needs
unpacking somewhere importable. The updater downloads the wheel (a plain zip),
extracts it to <data_dir>/engine/<version>/, and this module puts that directory
at the front of sys.path. The bundled copy stays as the fallback, so a corrupt
or half-written download degrades to "older engine" rather than "app will not
start".

Source checkouts skip all of this and use the virtualenv's yt-dlp via pip, which
is the behaviour a developer expects.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from .paths import engine_dir, is_frozen

__all__ = [
    "active_engine", "set_active_engine", "clear_active_engine",
    "prune_engines", "prepare_engine_path", "engine_source", "bundled_version",
    "engine_dir",
]

MARKER = "active.json"


def active_engine() -> tuple[str, Path] | None:
    """Return (version, path) of the managed engine, or None if unset/unusable."""
    marker = engine_dir() / MARKER
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        version = str(data["version"])
        path = engine_dir() / version
    except (json.JSONDecodeError, KeyError, OSError, TypeError):
        return None
    # Only trust it if the package actually landed.
    if not (path / "yt_dlp" / "__init__.py").is_file():
        return None
    return version, path


def set_active_engine(version: str) -> None:
    (engine_dir() / MARKER).write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )


def clear_active_engine() -> None:
    """Fall back to the bundled engine. Used when a managed one fails verification."""
    marker = engine_dir() / MARKER
    if marker.is_file():
        try:
            marker.unlink()
        except OSError:
            pass


def prune_engines(keep: int = 2) -> None:
    """Delete all but the newest `keep` unpacked engines, plus the active one."""
    current = active_engine()
    keep_names = {current[0]} if current else set()
    versions = sorted(
        (p for p in engine_dir().iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in versions[keep:]:
        if path.name in keep_names:
            continue
        shutil.rmtree(path, ignore_errors=True)


# Set once by prepare_engine_path() at startup and read afterwards. The
# function has to run before yt_dlp is imported, so calling it later just to
# read a status string returns "already imported" no matter what actually
# happened -- which is how the Engine page ended up lying about its own source.
_RESOLUTION = "not yet resolved"


def engine_source() -> str:
    """What prepare_engine_path() decided at startup. Safe to call any time."""
    return _RESOLUTION


def prepare_engine_path() -> str:
    """
    Put the managed engine ahead of the bundled one on sys.path.

    Returns a short description of what was selected, for logging. Safe to call
    more than once. Does nothing outside a frozen build.
    """
    global _RESOLUTION

    if not is_frozen():
        _RESOLUTION = "source checkout: using the environment's yt-dlp"
        return _RESOLUTION

    if "yt_dlp" in sys.modules:
        # Too late to change the import; report honestly rather than pretend.
        _RESOLUTION = "yt_dlp already imported; managed engine not applied"
        return _RESOLUTION

    selected = active_engine()
    if not selected:
        _RESOLUTION = "using the bundled engine"
        return _RESOLUTION

    version, path = selected
    entry = str(path)
    if entry in sys.path:
        sys.path.remove(entry)
    sys.path.insert(0, entry)
    _RESOLUTION = f"using managed engine {version}"
    return _RESOLUTION


def bundled_version() -> str:
    """Version of the engine baked into the bundle, ignoring any managed one."""
    marker = active_engine()
    saved = sys.path[:]
    try:
        if marker and str(marker[1]) in sys.path:
            sys.path.remove(str(marker[1]))
        for mod in [m for m in sys.modules if m.startswith("yt_dlp")]:
            del sys.modules[mod]
        import yt_dlp.version
        return yt_dlp.version.__version__
    except Exception:
        return ""
    finally:
        sys.path[:] = saved
        for mod in [m for m in sys.modules if m.startswith("yt_dlp")]:
            del sys.modules[mod]
