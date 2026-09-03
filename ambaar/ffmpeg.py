"""
ffmpeg discovery and on-demand install.

Someone who downloads a packaged build will not have ffmpeg on PATH, and without
it every download above 360p silently degrades to a low-quality single stream.
That failure is invisible -- the download "succeeds" -- so it has to be solved
before first use, not explained in a README nobody reads.

Search order: bundled copy, then our managed tools directory, then PATH. If none
hit, `fetch()` pulls an official static build for the platform.
"""

from __future__ import annotations

import platform
import shutil
import stat
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .paths import bundle_dir, tools_dir

# Official static builds. These are the same sources yt-dlp's own docs point at.
SOURCES = {
    "win32": (
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
        "ffmpeg-master-latest-win64-gpl.zip",
        "zip",
    ),
    "linux": (
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
        "ffmpeg-master-latest-linux64-gpl.tar.xz",
        "tar",
    ),
}

BINARIES = ("ffmpeg", "ffprobe")


def _exe(name: str) -> str:
    import sys
    return f"{name}.exe" if sys.platform == "win32" else name


def find() -> tuple[Path | None, Path | None]:
    """Return (ffmpeg, ffprobe) paths, either may be None."""
    found: list[Path | None] = []
    for name in BINARIES:
        exe = _exe(name)
        candidates = [bundle_dir() / "bin" / exe, tools_dir() / exe]
        hit = next((c for c in candidates if c.is_file()), None)
        if hit is None:
            which = shutil.which(name)
            hit = Path(which) if which else None
        found.append(hit)
    return found[0], found[1]


def available() -> bool:
    ffmpeg, ffprobe = find()
    return ffmpeg is not None and ffprobe is not None


def location_hint() -> str:
    ffmpeg, _ = find()
    return str(ffmpeg.parent) if ffmpeg else ""


def install_instructions() -> str:
    import sys
    if sys.platform == "darwin":
        return "brew install ffmpeg"
    if sys.platform == "win32":
        return "winget install Gyan.FFmpeg"
    return "sudo apt install ffmpeg    (or your distribution's equivalent)"


def can_fetch() -> bool:
    """macOS has no single reliable static archive, so we send users to brew."""
    import sys
    key = "win32" if sys.platform == "win32" else "linux" if sys.platform.startswith("linux") else ""
    return bool(key) and platform.machine().lower() in {"x86_64", "amd64"}


def fetch(on_progress: Callable[[str, float], None] | None = None) -> tuple[bool, str]:
    """
    Download a static ffmpeg build into the managed tools directory.

    Returns (ok, message). Never raises -- the caller is a GUI.
    """
    import sys

    key = "win32" if sys.platform == "win32" else "linux"
    if not can_fetch():
        return False, (
            "No automatic download for this platform or architecture. "
            f"Install it with:  {install_instructions()}"
        )

    url, kind = SOURCES[key]

    def report(msg: str, pct: float) -> None:
        if on_progress:
            on_progress(msg, pct)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / ("ffmpeg.zip" if kind == "zip" else "ffmpeg.tar.xz")
            report("Contacting the download server", 0.0)

            req = urllib.request.Request(url, headers={"User-Agent": "ambaar"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(archive, "wb") as fh:
                total = int(resp.headers.get("Content-Length") or 0)
                read = 0
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    fh.write(chunk)
                    read += len(chunk)
                    if total:
                        report(f"Downloading ffmpeg ({read // 1048576} of "
                               f"{total // 1048576} MB)", read / total * 90)

            report("Extracting", 92.0)
            extract_to = Path(tmp) / "x"
            extract_to.mkdir()
            if kind == "zip":
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(extract_to)
            else:
                with tarfile.open(archive) as tf:
                    tf.extractall(extract_to)

            report("Installing", 96.0)
            installed = 0
            wanted = {_exe(n) for n in BINARIES}
            for path in extract_to.rglob("*"):
                if path.is_file() and path.name in wanted:
                    target = tools_dir() / path.name
                    shutil.copy2(path, target)
                    target.chmod(target.stat().st_mode | stat.S_IXUSR |
                                 stat.S_IXGRP | stat.S_IXOTH)
                    installed += 1

            if installed < len(BINARIES):
                return False, (
                    f"Archive downloaded but only {installed} of {len(BINARIES)} "
                    f"binaries were found inside it. Install manually: "
                    f"{install_instructions()}"
                )

        report("Done", 100.0)
        return True, f"ffmpeg installed to {tools_dir()}"

    except urllib.error.URLError as e:
        return False, f"Download failed: {e}. Install manually: {install_instructions()}"
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as e:
        return False, f"Could not unpack the archive: {e}"
