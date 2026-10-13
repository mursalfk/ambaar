# ambaar/thumbs.py
"""
Thumbnail cache.

A queue of twenty rows reading only as titles is hard to scan; a picture tells
you which one is the lecture and which is the gearbox rebuild without reading
anything. Thumbnails are fetched during resolve, when the metadata request has
already told us the URL, so no extra round trip happens at paint time.

Files are named by a hash of the URL and never expire. A thumbnail is a few
kilobytes and the images do not change, so an eviction policy would cost more
code than the disk it saves.
"""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from pathlib import Path

from .paths import data_dir

CACHE_DIR = data_dir() / "thumbs"
TIMEOUT = 15
MAX_BYTES = 2 * 1024 * 1024    # a thumbnail larger than this is not a thumbnail


def cache_path(url: str) -> Path:
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"{name}.img"


def cached(url: str) -> str:
    """Local path if this URL is already on disk, else an empty string."""
    if not url:
        return ""
    path = cache_path(url)
    return str(path) if path.is_file() else ""


def fetch(url: str) -> str:
    """
    Download one thumbnail. Returns a local path, or "" on any failure.

    Never raises: a missing picture is a cosmetic problem, and a job must not
    fail to resolve because an image host was slow.
    """
    if not url:
        return ""

    existing = cached(url)
    if existing:
        return existing

    path = cache_path(url)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "ambaar"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            return ""
        # Write beside the target then move, so a half-downloaded image is never
        # visible under the final name.
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return str(path)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return ""


def pick(info: dict) -> str:
    """
    Choose a thumbnail URL from yt-dlp's metadata.

    yt-dlp offers several sizes. The widest one under 640px is the sweet spot:
    large enough that the row still looks sharp on a HiDPI screen, small enough
    that fetching it during resolve costs nothing noticeable.
    """
    direct = info.get("thumbnail")
    candidates = info.get("thumbnails") or []
    if not candidates:
        return direct or ""

    usable = [t for t in candidates if t.get("url")]
    if not usable:
        return direct or ""

    sized = [t for t in usable if isinstance(t.get("width"), int)]
    if sized:
        small = [t for t in sized if t["width"] <= 640]
        best = max(small or sized, key=lambda t: t["width"])
        return best.get("url") or direct or ""

    # No width reported: yt-dlp orders thumbnails worst to best.
    return usable[-1].get("url") or direct or ""