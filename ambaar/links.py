# ambaar/links.py
"""
Link handling: canonical keys, duplicate detection, clipboard filtering.

Two URLs that name the same video rarely look alike -- youtu.be/ID, watch?v=ID
with a tracking suffix, a shorts link. Comparing raw strings would miss every
one of those, so each link is reduced to a key first and keys are compared.

Pure functions only; nothing here touches Qt or the network.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

_YT_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com",
             "youtube-nocookie.com", "youtu.be"}
_YT_PATH_ID = ("shorts", "embed", "live", "v")

# Query parameters that never change which media a link points at.
_NOISE = {"si", "feature", "fbclid", "gclid", "pp", "t", "start", "ab_channel",
          "igshid", "ref", "ref_src"}

# Hosts worth offering from the clipboard. yt-dlp supports far more sites, and
# those can still be pasted by hand; the watcher is conservative because a
# prompt for every copied link would be worse than none.
CLIPBOARD_HOSTS = (
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "twitch.tv",
    "tiktok.com", "instagram.com", "facebook.com", "fb.watch", "twitter.com",
    "x.com", "reddit.com", "soundcloud.com", "bilibili.com", "bandcamp.com",
    "streamable.com", "rumble.com",
)


def _host(netloc: str) -> str:
    host = netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def normalize_url(url: str) -> str:
    """
    Canonical key for a link. Stable across forms of the same media; never raises.

    YouTube becomes "yt:<video id>" or "ytlist:<playlist id>". Anything else
    keeps host and path and loses tracking parameters and the fragment.
    """
    text = (url or "").strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        return text.lower()
    if not parts.netloc:
        return text.lower()

    host = _host(parts.netloc)
    query = parse_qs(parts.query)
    path = parts.path.rstrip("/")

    if host in _YT_HOSTS or host == "youtube.com":
        if host == "youtu.be":
            vid = path.lstrip("/").split("/")[0]
            if vid:
                return f"yt:{vid}"
        if path == "/watch" and query.get("v"):
            return f"yt:{query['v'][0]}"
        segs = [s for s in path.split("/") if s]
        if len(segs) >= 2 and segs[0] in _YT_PATH_ID:
            return f"yt:{segs[1]}"
        if path == "/playlist" and query.get("list"):
            return f"ytlist:{query['list'][0]}"

    kept = sorted((k, v[0]) for k, v in query.items()
                  if k.lower() not in _NOISE and not k.lower().startswith("utm_"))
    suffix = "?" + "&".join(f"{k}={v}" for k, v in kept) if kept else ""
    return f"{host}{path}{suffix}"


def is_clipboard_candidate(text: str) -> bool:
    """One http(s) link on a host we recognise, and nothing else in the text."""
    text = (text or "").strip()
    if not text or len(text) > 600 or any(c.isspace() for c in text):
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    host = _host(parts.netloc)
    return any(host == h or host.endswith("." + h) for h in CLIPBOARD_HOSTS)


def find_duplicate(url: str, jobs) -> object | None:
    """The first job in `jobs` that points at the same media as `url`, if any."""
    key = normalize_url(url)
    for job in jobs:
        if normalize_url(job.url) == key:
            return job
    return None


def archive_has(url: str, archive_file: Path) -> bool:
    """
    True when yt-dlp's download archive already lists this video.

    The archive stores "<extractor> <id>" per line. Only YouTube keys can be
    matched without asking yt-dlp, which is the common case; other sites
    simply report False and fall through to the history check.
    """
    key = normalize_url(url)
    if not key.startswith("yt:"):
        return False
    wanted = f"youtube {key[3:]}"
    try:
        with open(archive_file, encoding="utf-8", errors="replace") as f:
            return any(line.strip() == wanted for line in f)
    except OSError:
        return False
