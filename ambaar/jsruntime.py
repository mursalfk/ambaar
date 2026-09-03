"""
JavaScript runtime detection.

yt-dlp solves YouTube's `nsig` challenge by executing obfuscated JavaScript. It
needs a JS engine to do that, and when none is present it falls back to weaker
extraction and warns:

    No supported JavaScript runtime could be found... some formats may be
    missing.

That warning is easy to ignore because downloads still succeed -- they just
quietly return fewer, lower-quality formats than the video actually offers.
Same failure shape as missing ffmpeg: nothing errors, the result is just worse.

Deno is the runtime yt-dlp enables by default, so that is what we look for and
what we offer to install.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .paths import tools_dir

# Official Deno release assets, by platform and architecture.
TARGETS = {
    ("win32", "amd64"): "x86_64-pc-windows-msvc",
    ("win32", "x86_64"): "x86_64-pc-windows-msvc",
    ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("darwin", "x86_64"): "x86_64-apple-darwin",
    ("darwin", "arm64"): "aarch64-apple-darwin",
}


def _exe() -> str:
    return "deno.exe" if sys.platform == "win32" else "deno"


def find() -> Path | None:
    """Managed copy first, then PATH."""
    managed = tools_dir() / _exe()
    if managed.is_file():
        return managed
    found = shutil.which("deno")
    return Path(found) if found else None


def available() -> bool:
    return find() is not None


def version() -> str:
    path = find()
    if not path:
        return ""
    try:
        out = subprocess.run([str(path), "--version"], capture_output=True,
                             text=True, timeout=15)
        return out.stdout.splitlines()[0].strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def _target() -> str:
    import platform
    machine = platform.machine().lower()
    plat = "win32" if sys.platform == "win32" else \
           "darwin" if sys.platform == "darwin" else "linux"
    return TARGETS.get((plat, machine), "")


def can_fetch() -> bool:
    return bool(_target())


def install_instructions() -> str:
    if sys.platform == "win32":
        return "winget install DenoLand.Deno"
    if sys.platform == "darwin":
        return "brew install deno"
    return "curl -fsSL https://deno.land/install.sh | sh"


def fetch(on_progress: Callable[[str, float], None] | None = None) -> tuple[bool, str]:
    """Download Deno into the managed tools directory. Never raises."""
    target = _target()
    if not target:
        return False, ("No automatic download for this platform. Install with: "
                       f"{install_instructions()}")

    url = f"https://github.com/denoland/deno/releases/latest/download/deno-{target}.zip"

    def report(msg: str, pct: float) -> None:
        if on_progress:
            on_progress(msg, pct)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "deno.zip"
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
                        report(f"Downloading Deno ({read // 1048576} of "
                               f"{total // 1048576} MB)", read / total * 90)

            report("Extracting", 93.0)
            staging = Path(tmp) / "x"
            staging.mkdir()
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(staging)

            src = next((p for p in staging.rglob(_exe()) if p.is_file()), None)
            if src is None:
                return False, "Archive did not contain a deno binary"

            dst = tools_dir() / _exe()
            shutil.copy2(src, dst)
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        report("Done", 100.0)
        return True, f"Deno installed to {tools_dir()}"

    except urllib.error.URLError as e:
        return False, f"Download failed: {e}. Install manually: {install_instructions()}"
    except (OSError, zipfile.BadZipFile) as e:
        return False, f"Could not unpack the archive: {e}"
