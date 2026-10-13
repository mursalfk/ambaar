# ambaar/space.py
"""
Disk-space estimates and checks.

A 4K download that dies at 93% because the drive filled is the worst kind of
failure: it costs an hour and leaves a large .part file behind. Everything here
exists to say so before starting rather than after.

Estimates are deliberately honest about being estimates. yt-dlp reports exact
sizes for some formats, approximate for others, and none for streaming ones, so
the answer is "about N", and the caller treats a shortfall as a question to the
user rather than a refusal.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

MIN_FREE = 300 * 1024 * 1024       # below this, warn even with no estimate
HEADROOM = 1.10                    # post-processing needs room beside the download

# Typical bitrates in megabits per second, used only when yt-dlp reports no
# sizes (playlists, whose entries are listed rather than resolved).
_MBPS = {2160: 16.0, 1440: 9.0, 1080: 5.0, 720: 2.5, 480: 1.2, 360: 0.7}
_BEST_MBPS = 8.0
_AUDIO_BYTES_PER_SEC = 24_000      # ~192 kbps


def _fmt_size(fmt: dict, duration: float) -> int:
    """Best available size for one format: exact, approximate, or from bitrate."""
    for key in ("filesize", "filesize_approx"):
        n = fmt.get(key)
        if isinstance(n, (int, float)) and n > 0:
            return int(n)
    tbr = fmt.get("tbr")
    if isinstance(tbr, (int, float)) and tbr > 0 and duration > 0:
        return int(tbr * 1000 / 8 * duration)
    return 0


def pack_sizes(info: dict) -> str:
    """
    Compact JSON of a video's format sizes: {"v": [[height, bytes, has_audio]],
    "a": best audio bytes}. Empty string when nothing useful was reported.
    """
    duration = float(info.get("duration") or 0)
    video: dict[tuple[int, bool], int] = {}
    audio = 0
    heights: set[int] = set()
    codecs: set[str] = set()
    for f in info.get("formats") or []:
        has_v = f.get("vcodec") not in (None, "none")
        has_a = f.get("acodec") not in (None, "none")
        # Availability is recorded even for formats with no known size, so the
        # format picker can offer qualities the size estimate cannot price.
        if has_v:
            h = int(f.get("height") or 0)
            if h > 0:
                heights.add(h)
            family = _codec_family(str(f.get("vcodec") or ""))
            if family:
                codecs.add(family)
        size = _fmt_size(f, duration)
        if size <= 0:
            continue
        if has_v:
            h = int(f.get("height") or 0)
            if h > 0:
                key = (h, has_a)
                video[key] = max(video.get(key, 0), size)
        elif has_a:
            audio = max(audio, size)
    if not video and not audio and not heights:
        return ""
    rows = [[h, n, int(a)] for (h, a), n in sorted(video.items())]
    return json.dumps({"v": rows, "a": audio, "h": sorted(heights),
                       "c": sorted(codecs)}, separators=(",", ":"))


def _codec_family(vcodec: str) -> str:
    low = vcodec.lower()
    if low.startswith(("avc1", "h264")):
        return "h264"
    if low.startswith(("vp9", "vp09")):
        return "vp9"
    if low.startswith("av01"):
        return "av1"
    return ""


def available_formats(sizes: str) -> tuple[list[int], list[str]]:
    """(heights highest first, codec families) a video offers; empty if unknown."""
    data = _unpack(sizes)
    heights = [h for h in data.get("h", []) if isinstance(h, int)]
    codecs = [c for c in data.get("c", []) if c in ("h264", "vp9", "av1")]
    return sorted(heights, reverse=True), codecs


def _unpack(text: str) -> dict:
    try:
        data = json.loads(text or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def estimate_video(sizes: str, height_cap: int | None) -> int:
    """
    Bytes for the best video at or under `height_cap` (None means no cap), plus
    separate audio when the chosen stream carries none. 0 when unknown.
    """
    data = _unpack(sizes)
    rows = [r for r in data.get("v", []) if isinstance(r, list) and len(r) == 3]
    if not rows:
        return 0
    allowed = [r for r in rows if height_cap is None or r[0] <= height_cap]
    # Everything is taller than the cap: yt-dlp falls back to the smallest.
    pool = allowed or [min(rows, key=lambda r: r[0])]
    top = max(pool, key=lambda r: (r[0], r[2]))
    total = int(top[1])
    if not top[2]:
        total += int(data.get("a") or 0)
    return total


def estimate_audio(sizes: str) -> int:
    return int(_unpack(sizes).get("a") or 0)


def rough_estimate(seconds: int, height_cap: int | None, audio: bool) -> int:
    """Duration-based guess for when no sizes are known."""
    if seconds <= 0:
        return 0
    if audio:
        return seconds * _AUDIO_BYTES_PER_SEC
    mbps = _BEST_MBPS if height_cap is None else _MBPS.get(height_cap, _BEST_MBPS)
    return int(seconds * mbps * 125_000)


def free_bytes(path: str | Path) -> int | None:
    """Free space where `path` will be written, even if it does not exist yet."""
    p = Path(path).expanduser()
    for candidate in (p, *p.parents):
        if candidate.exists():
            try:
                return shutil.disk_usage(candidate).free
            except OSError:
                return None
    return None


def shortfall(needed: int, free: int | None) -> int:
    """
    Bytes missing, or 0 when there is enough (or when it cannot be known).

    With no estimate the only claim worth making is "the drive is nearly full".
    """
    if free is None:
        return 0
    if needed <= 0:
        return max(0, MIN_FREE - free)
    return max(0, int(needed * HEADROOM) - free)
