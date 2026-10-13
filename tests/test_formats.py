# tests/test_formats.py
"""
Per-item format override: parsing, application, build_opts, persistence.

The parser's job is to be forgiving. A malformed or stale value must mean
"follow the settings", never an exception inside a download worker.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ambaar import engine  # noqa: E402
from ambaar.engine import Job, Settings  # noqa: E402
from ambaar.store import QueueStore  # noqa: E402


def _hooks():
    return {"progress": lambda d: None, "postprocessor": lambda d: None,
            "logger": object()}


def _settings(tmp_path, **kw):
    return Settings(output_dir=str(tmp_path), **kw)


def test_roundtrip_video():
    c = engine.encode_format(False, "1080p", "mkv")
    assert c == "video|1080p|mkv"
    assert engine.decode_format(c) == {"audio": False, "quality": "1080p",
                                       "container": "mkv", "codec": "any"}


def test_roundtrip_audio():
    c = engine.encode_format(True, audio_format="flac")
    assert c == "audio|flac"
    assert engine.decode_format(c) == {"audio": True, "audio_format": "flac"}


@pytest.mark.parametrize("bad", ["", "video", "video|9999p|mp4", "audio|ogg",
                                 "video|1080p|avi", "x|y|z", "audio|mp3|extra"])
def test_malformed_means_defaults(bad):
    assert engine.decode_format(bad) == {}
    s = Settings()
    assert engine.apply_format(s, bad) is s
    assert engine.describe_format(bad) == ""


def test_encode_rejects_unknown_values():
    assert engine.encode_format(False, "bogus", "mp4") == ""
    assert engine.encode_format(True, audio_format="ogg") == ""


def test_apply_video_overrides_audio_default():
    base = Settings(audio_only=True, quality="Best available", container="mp4")
    out = engine.apply_format(base, "video|720p|webm")
    assert (out.audio_only, out.quality, out.container) == (False, "720p", "webm")
    assert base.audio_only is True          # original untouched


def test_apply_audio_overrides_video_default():
    out = engine.apply_format(Settings(audio_only=False), "audio|opus")
    assert out.audio_only and out.audio_format == "opus"


def test_describe():
    assert engine.describe_format("audio|mp3") == "MP3 audio"
    assert engine.describe_format("video|2160p (4K)|mp4") == "2160p MP4"


def test_build_opts_uses_overridden_format(tmp_path):
    s = engine.apply_format(_settings(tmp_path), "video|480p|mkv")
    o = engine.build_opts(s, _hooks())
    assert "height<=480" in o["format"] and o["merge_output_format"] == "mkv"
    a = engine.build_opts(engine.apply_format(_settings(tmp_path), "audio|m4a"),
                          _hooks())
    assert a["format"] == "bestaudio/best"
    assert a["postprocessors"][0]["preferredcodec"] == "m4a"


def test_playlist_flag_overrides_setting(tmp_path):
    # A playlist added while the global playlist setting is off still gets its
    # own folder and is not truncated to one video.
    o = engine.build_opts(_settings(tmp_path, playlist=False), _hooks(), playlist=True)
    assert o["noplaylist"] is False and "playlist_title" in o["outtmpl"]
    # And a single video is never treated as a playlist because the setting is on.
    v = engine.build_opts(_settings(tmp_path, playlist=True), _hooks(), playlist=False)
    assert v["noplaylist"] is True and "playlist_title" not in v["outtmpl"]
    # None keeps the old behaviour.
    n = engine.build_opts(_settings(tmp_path, playlist=True), _hooks())
    assert n["noplaylist"] is False


def test_fmt_persists(tmp_path):
    st = QueueStore(tmp_path / "q.db")
    j = Job(url="https://x/y", title="t", status=engine.READY,
            kind=engine.KIND_VIDEO, fmt="audio|mp3")
    st.save(j, 0)
    st.close()
    st = QueueStore(tmp_path / "q.db")
    assert st.load()[0].fmt == "audio|mp3"
    st.close()


def test_migrates_database_without_fmt_column(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE jobs (job_id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT,
            status TEXT, kind TEXT, item_count INTEGER, duration INTEGER,
            uploader TEXT, percent REAL, size TEXT, filepath TEXT, folder TEXT,
            error TEXT, thumb TEXT, position INTEGER, added_at REAL);
        INSERT INTO jobs (job_id, url, title, status, kind, position)
            VALUES ('a', 'https://x', 'old row', 'Ready', 'video', 0);
    """)
    db.commit()
    db.close()
    st = QueueStore(path)
    assert st.available
    rows = st.load()
    assert rows[0].title == "old row" and rows[0].fmt == ""
    st.save(rows[0], 0)         # writing the new column must work too
    st.close()
