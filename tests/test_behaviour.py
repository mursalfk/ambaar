# tests/test_behaviour.py
"""
Retry policy, codec selection, per-item log, output folder override, history.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ambaar import engine, space  # noqa: E402
from ambaar.engine import Job, Settings  # noqa: E402
from ambaar.store import QueueStore  # noqa: E402


# -- retry -------------------------------------------------------------------- #

@pytest.mark.parametrize("err,transient", [
    ("ERROR: Unable to download webpage: timed out", True),
    ("HTTP Error 503: Service Unavailable", True),
    ("HTTP Error 429: Too Many Requests", True),
    ("Connection reset by peer", True),
    ("HTTP Error 403: Forbidden", False),
    ("Sign in to confirm you're not a bot", False),
    ("Video unavailable", False),
    ("No space left on device", False),
    ("Requested format is not available", False),
    ("", False),
])
def test_is_transient(err, transient):
    assert engine.is_transient(err) is transient


def test_delays_grow_then_plateau():
    assert [engine.retry_delay(n) for n in (1, 2, 3, 4, 9)] == [15, 60, 300, 300, 300]
    assert engine.retry_delay(0) == 15


def test_should_retry_respects_limit_and_off_switch():
    err = "timed out"
    assert engine.should_retry(err, 0, 3)
    assert engine.should_retry(err, 2, 3)
    assert not engine.should_retry(err, 3, 3)
    assert not engine.should_retry(err, 0, 0)
    assert not engine.should_retry("Video unavailable", 0, 3)


# -- codec -------------------------------------------------------------------- #

def test_codec_roundtrip_and_label():
    c = engine.encode_format(False, "1080p", "mp4", codec="av1")
    assert c == "video|1080p|mp4|av1"
    assert engine.decode_format(c)["codec"] == "av1"
    assert engine.describe_format(c) == "1080p MP4 AV1"
    assert engine.describe_format("video|1080p|mp4") == "1080p MP4"


def test_unknown_codec_means_defaults():
    assert engine.decode_format("video|1080p|mp4|divx") == {}
    # an unknown codec on encode is dropped, not stored
    assert engine.encode_format(False, "1080p", "mp4", codec="divx") == "video|1080p|mp4"


def test_video_format_falls_back_to_plain_quality():
    f = engine.video_format("1080p", "h264")
    assert "avc1" in f and "height<=1080" in f
    assert f.endswith("/" + engine.QUALITY_MAP["1080p"])      # fallback present
    assert engine.video_format("1080p", "any") == engine.QUALITY_MAP["1080p"]
    assert "height" not in engine.video_format("Best available", "vp9").split("/")[0]


def test_h264_never_muxed_into_webm(tmp_path):
    s = Settings(output_dir=str(tmp_path), codec="h264", container="webm")
    o = engine.build_opts(s, {"progress": print, "postprocessor": print, "logger": object()})
    assert o["merge_output_format"] == "mkv"


def test_apply_format_carries_codec():
    out = engine.apply_format(Settings(), "video|720p|mkv|vp9")
    assert out.codec == "vp9"


# -- availability ------------------------------------------------------------- #

def test_available_formats_from_info():
    info = {"duration": 10, "formats": [
        {"vcodec": "avc1.64", "acodec": "none", "height": 1080, "filesize": 5},
        {"vcodec": "vp09.00", "acodec": "none", "height": 2160},
        {"vcodec": "av01.0", "acodec": "none", "height": 720, "filesize": 3},
        {"vcodec": "none", "acodec": "opus", "filesize": 1},
    ]}
    heights, codecs = space.available_formats(space.pack_sizes(info))
    assert heights == [2160, 1080, 720]
    assert codecs == ["av1", "h264", "vp9"]
    assert space.available_formats("") == ([], [])
    assert space.available_formats("garbage") == ([], [])


# -- log ---------------------------------------------------------------------- #

def test_log_is_capped_and_skips_blank_lines():
    j = Job(url="u")
    engine.append_log(j, "one\n\n  \ntwo")
    assert j.log == ["one", "two"]
    for i in range(engine.MAX_LOG_LINES + 50):
        engine.append_log(j, f"line {i}")
    assert len(j.log) == engine.MAX_LOG_LINES
    assert j.log[-1] == f"line {engine.MAX_LOG_LINES + 49}"


def test_logs_are_per_job():
    a, b = Job(url="a"), Job(url="b")
    engine.append_log(a, "only a")
    assert b.log == []


# -- output folder ------------------------------------------------------------ #

def test_output_dir_override():
    s = Settings(output_dir="/default")
    assert engine.output_dir_for(Job(url="u"), s) == "/default"
    assert engine.output_dir_for(Job(url="u", dest="/mine"), s) == "/mine"


def test_dest_persists_and_session_state_does_not(tmp_path):
    st = QueueStore(tmp_path / "q.db")
    j = Job(url="u", title="t", status=engine.READY, kind=engine.KIND_VIDEO,
            dest="/somewhere", redo=True, attempts=2)
    j.log.append("x")
    st.save(j, 0)
    st.close()
    st = QueueStore(tmp_path / "q.db")
    back = st.load()[0]
    assert back.dest == "/somewhere"
    assert back.redo is False and back.attempts == 0 and back.log == []
    st.close()


# -- history ------------------------------------------------------------------ #

def _done(url, title="T", path="/a/b.mp4"):
    return Job(url=url, title=title, status=engine.DONE, kind=engine.KIND_VIDEO,
               filepath=path, folder="/a", size="10 MB")


def test_history_records_and_searches(tmp_path):
    st = QueueStore(tmp_path / "q.db")
    st.add_history(_done("https://youtu.be/AAAAAAAAAAA", "Gearbox rebuild"))
    st.add_history(_done("https://youtu.be/BBBBBBBBBBB", "Cooking pasta"))
    assert len(st.history()) == 2
    assert [h["title"] for h in st.history("gear")] == ["Gearbox rebuild"]
    assert st.history("zzz") == []
    st.close()


def test_history_one_entry_per_media(tmp_path):
    st = QueueStore(tmp_path / "q.db")
    st.add_history(_done("https://youtu.be/AAAAAAAAAAA", "first"))
    st.add_history(_done("https://www.youtube.com/watch?v=AAAAAAAAAAA", "second"))
    rows = st.history()
    assert len(rows) == 1 and rows[0]["title"] == "second"
    st.close()


def test_history_find_matches_other_spellings(tmp_path):
    st = QueueStore(tmp_path / "q.db")
    st.add_history(_done("https://youtu.be/AAAAAAAAAAA", "Known"))
    assert st.history_find("https://www.youtube.com/watch?v=AAAAAAAAAAA&t=5")["title"] == "Known"
    assert st.history_find("https://youtu.be/ZZZZZZZZZZZ") is None
    st.close()


def test_history_remove_and_clear(tmp_path):
    st = QueueStore(tmp_path / "q.db")
    st.add_history(_done("https://youtu.be/AAAAAAAAAAA"))
    st.add_history(_done("https://youtu.be/BBBBBBBBBBB"))
    st.history_remove(st.history()[0]["id"])
    assert len(st.history()) == 1
    st.history_clear()
    assert st.history() == []
    st.close()


def test_history_survives_queue_clear(tmp_path):
    st = QueueStore(tmp_path / "q.db")
    st.add_history(_done("https://youtu.be/AAAAAAAAAAA"))
    st.clear()
    assert len(st.history()) == 1
    st.close()


@pytest.mark.parametrize("quality,codec,expected", [
    ("1080p", "h264", ["v1", "a1"]),
    ("1080p", "vp9", ["v2", "a1"]),       # "vp09.*" must match the vp9 choice
    ("1080p", "av1", ["v1", "a1"]),       # no AV1 stream: falls back to best
    ("720p", "vp9", ["v3", "a1"]),        # nothing vp9 under 720p: falls back
    ("Best available", "vp9", ["v2", "a1"]),
    ("1080p", "any", ["v1", "a1"]),
])
def test_selector_against_real_ytdlp(quality, codec, expected):
    yt_dlp = pytest.importorskip("yt_dlp")
    ydl = yt_dlp.YoutubeDL({"quiet": True})
    base = {"protocol": "https", "url": "u", "ext": "mp4"}
    # yt-dlp hands selectors formats ordered worst to best.
    fmts = [
        {**base, "format_id": "a1", "vcodec": "none", "acodec": "mp4a", "tbr": 128},
        {**base, "format_id": "v3", "vcodec": "avc1.64", "acodec": "none", "height": 480, "tbr": 300},
        {**base, "format_id": "v2", "vcodec": "vp09.00.40.08", "acodec": "none", "height": 1080, "tbr": 900},
        {**base, "format_id": "v1", "vcodec": "avc1.64", "acodec": "none", "height": 1080, "tbr": 1000},
    ]
    sel = ydl.build_format_selector(engine.video_format(quality, codec))
    out = list(sel({"formats": fmts, "incomplete_formats": False}))
    picked = [f["format_id"] for f in (out[0].get("requested_formats") or [out[0]])]
    assert picked == expected


# -- queue priority ------------------------------------------------------------ #

def _run_order(prios_and_reorder):
    """
    Hold a one-slot pool busy, queue three runnables, reorder, release, and
    return the order they actually ran in.
    """
    import threading
    from PySide6.QtCore import QCoreApplication, QRunnable

    QCoreApplication.instance() or QCoreApplication([])
    gate = threading.Event()
    ran: list[str] = []

    class Block(QRunnable):
        def run(self): gate.wait(5)

    class Rec(QRunnable):
        def __init__(self, name): super().__init__(); self.name = name
        def run(self): ran.append(self.name)

    mgr = engine.DownloadManager(Settings(max_parallel_jobs=1))
    mgr.pool.start(Block())
    for pos, name in enumerate("abc"):
        mgr._enqueue(name, Rec(name), pos)
    moved = prios_and_reorder(mgr)
    gate.set()
    mgr.pool.waitForDone(5000)
    return ran, moved


def test_waiting_downloads_run_in_list_order():
    ran, moved = _run_order(lambda m: 0)
    assert ran == ["a", "b", "c"]


def test_reorder_changes_what_runs_next():
    ran, moved = _run_order(lambda m: m.apply_order(["c", "a", "b"]))
    assert ran == ["c", "a", "b"] and moved == 3


def test_reorder_never_disturbs_a_running_download():
    import threading
    from PySide6.QtCore import QCoreApplication, QRunnable
    QCoreApplication.instance() or QCoreApplication([])
    started, gate = threading.Event(), threading.Event()

    class Running(QRunnable):
        def run(self): started.set(); gate.wait(5)

    mgr = engine.DownloadManager(Settings(max_parallel_jobs=1))
    r = Running()
    mgr._enqueue("x", r, 0)
    assert started.wait(5)
    assert mgr.apply_order(["x"]) == 0          # already running: left alone
    gate.set()
    mgr.pool.waitForDone(5000)


def test_apply_order_ignores_unknown_jobs():
    mgr = engine.DownloadManager(Settings())
    assert mgr.apply_order(["nope", "also-nope"]) == 0
