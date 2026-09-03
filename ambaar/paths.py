"""
Single source of truth for where the app keeps its state.

A frozen build cannot write next to its own executable (Program Files and
/Applications are read-only for normal users), so everything mutable lives in
the per-user data directory. Source checkouts use the same location, which
means a developer and a packaged user hit identical paths and bugs reproduce.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_dir() -> Path:
    """Directory holding bundled read-only resources."""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Per-user writable directory for settings, logs, and the managed engine."""
    override = os.environ.get("AMBAAR_HOME")
    if override:
        p = Path(override).expanduser()
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        p = Path(base) / "ambaar"
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "ambaar"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        p = Path(base) / "ambaar"
    p.mkdir(parents=True, exist_ok=True)
    return p


def engine_dir() -> Path:
    """Where the updater unpacks newer yt-dlp releases in frozen builds."""
    p = data_dir() / "engine"
    p.mkdir(parents=True, exist_ok=True)
    return p


def tools_dir() -> Path:
    """Where a downloaded ffmpeg lands."""
    p = data_dir() / "tools"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_download_dir() -> Path:
    for name in ("Downloads", "Download"):
        candidate = Path.home() / name
        if candidate.is_dir():
            return candidate
    return Path.home()
