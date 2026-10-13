# tests/test_links.py
"""
Link keys, duplicate detection and clipboard filtering.

Duplicate detection is only useful if different spellings of one link collapse
to one key, and only safe if different media never do.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ambaar import links  # noqa: E402
from ambaar.engine import Job  # noqa: E402


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=abc123",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "https://music.youtube.com/watch?v=dQw4w9WgXcQ&si=x",
    "  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ",
])
def test_same_video_same_key(url):
    assert links.normalize_url(url) == "yt:dQw4w9WgXcQ"


def test_different_videos_differ():
    a = links.normalize_url("https://www.youtube.com/watch?v=AAAAAAAAAAA")
    b = links.normalize_url("https://www.youtube.com/watch?v=BBBBBBBBBBB")
    assert a != b


def test_playlist_key():
    assert links.normalize_url("https://www.youtube.com/playlist?list=PL123") == "ytlist:PL123"


def test_other_sites_drop_tracking_and_fragment():
    a = links.normalize_url("https://vimeo.com/12345?utm_source=x#t=10")
    b = links.normalize_url("https://www.vimeo.com/12345/")
    assert a == b == "vimeo.com/12345"


def test_meaningful_query_is_kept():
    assert links.normalize_url("https://site.example/v?id=1") != \
        links.normalize_url("https://site.example/v?id=2")


@pytest.mark.parametrize("junk", ["", "not a url", "http://", "ftp://x/y", None])
def test_normalize_never_raises(junk):
    assert isinstance(links.normalize_url(junk), str)


def test_find_duplicate():
    jobs = [Job(url="https://youtu.be/AAAAAAAAAAA"), Job(url="https://vimeo.com/9")]
    assert links.find_duplicate("https://www.youtube.com/watch?v=AAAAAAAAAAA", jobs) is jobs[0]
    assert links.find_duplicate("https://www.youtube.com/watch?v=ZZZZZZZZZZZ", jobs) is None
    assert links.find_duplicate("https://x", []) is None


@pytest.mark.parametrize("text,ok", [
    ("https://www.youtube.com/watch?v=abc", True),
    ("https://youtu.be/abc", True),
    ("https://vimeo.com/123", True),
    ("https://www.example.com/page", False),
    ("two https://youtu.be/a https://youtu.be/b", False),
    ("https://youtu.be/a\nhttps://youtu.be/b", False),
    ("youtube.com/watch?v=abc", False),
    ("", False),
    ("x" * 1000, False),
    ("https://notyoutube.com/watch", False),
    ("https://evil.com/youtube.com", False),
])
def test_clipboard_candidate(text, ok):
    assert links.is_clipboard_candidate(text) is ok


def test_archive_lookup(tmp_path):
    f = tmp_path / "archive.txt"
    f.write_text("youtube AAAAAAAAAAA\nyoutube BBBBBBBBBBB\n", encoding="utf-8")
    assert links.archive_has("https://youtu.be/AAAAAAAAAAA", f)
    assert not links.archive_has("https://youtu.be/CCCCCCCCCCC", f)
    assert not links.archive_has("https://vimeo.com/1", f)         # not matchable
    assert not links.archive_has("https://youtu.be/AAAAAAAAAAA", tmp_path / "missing.txt")
