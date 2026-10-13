# tests/test_space.py
"""
Disk-space estimates and the shortfall rule.

The rule that matters: an unknown size must never block a download. With no
estimate the only warning is a nearly full drive; with one, the warning appears
only when the estimate plus headroom exceeds free space.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ambaar import engine, space  # noqa: E402
from ambaar.engine import Job, Settings  # noqa: E402

MB = 1024 * 1024
GB = 1024 * MB

INFO = {
    "duration": 600,
    "formats": [
        {"vcodec": "avc1", "acodec": "none", "height": 1080, "filesize": 800 * MB},
        {"vcodec": "avc1", "acodec": "none", "height": 720, "filesize": 400 * MB},
        {"vcodec": "avc1", "acodec": "none", "height": 360, "filesize_approx": 90 * MB},
        {"vcodec": "none", "acodec": "opus", "filesize": 10 * MB},
        {"vcodec": "none", "acodec": "mp4a", "filesize": 8 * MB},
        {"vcodec": "avc1", "acodec": "mp4a", "height": 360, "filesize": 100 * MB},
        {"vcodec": "avc1", "acodec": "none", "height": 2160},        # no size known
    ],
}


def _video(sizes=None, **kw):
    return Job(url="u", kind=engine.KIND_VIDEO, sizes=sizes if sizes is not None
               else space.pack_sizes(INFO), **kw)


def test_pack_ignores_formats_without_a_size():
    heights = [r[0] for r in __import__("json").loads(space.pack_sizes(INFO))["v"]]
    assert 2160 not in heights


def test_pack_empty_when_nothing_reported():
    assert space.pack_sizes({}) == ""
    # Availability alone is still worth recording for the format picker.
    only_avail = space.pack_sizes({"formats": [{"vcodec": "avc1", "height": 720}]})
    assert space.estimate_video(only_avail, None) == 0
    assert space.available_formats(only_avail) == ([720], ["h264"])


def test_pack_uses_bitrate_when_no_size():
    info = {"duration": 100, "formats": [
        {"vcodec": "avc1", "acodec": "none", "height": 720, "tbr": 800}]}
    assert space.estimate_video(space.pack_sizes(info), None) == 800 * 1000 // 8 * 100


def test_video_estimate_adds_audio_to_video_only_stream():
    assert space.estimate_video(space.pack_sizes(INFO), 1080) == 800 * MB + 10 * MB


def test_height_cap_picks_best_allowed():
    assert space.estimate_video(space.pack_sizes(INFO), 720) == 400 * MB + 10 * MB


def test_combined_stream_needs_no_extra_audio():
    only = {"duration": 60, "formats": [
        {"vcodec": "avc1", "acodec": "mp4a", "height": 360, "filesize": 50 * MB},
        {"vcodec": "none", "acodec": "opus", "filesize": 5 * MB}]}
    assert space.estimate_video(space.pack_sizes(only), None) == 50 * MB


def test_cap_below_everything_falls_back_to_smallest():
    assert space.estimate_video(space.pack_sizes(INFO), 144) > 0


def test_unknown_sizes_estimate_zero():
    assert space.estimate_video("", 1080) == 0
    assert space.estimate_video("garbage", None) == 0
    assert space.estimate_audio(None) == 0


def test_audio_estimate():
    assert space.estimate_audio(space.pack_sizes(INFO)) == 10 * MB


def test_rough_estimate_scales_with_duration_and_quality():
    assert space.rough_estimate(0, 720, False) == 0
    assert space.rough_estimate(3600, 2160, False) > space.rough_estimate(3600, 720, False)
    assert space.rough_estimate(3600, 720, True) < space.rough_estimate(3600, 720, False)


def test_job_estimate_follows_quality_and_override(tmp_path):
    s = Settings(output_dir=str(tmp_path), quality="720p")
    assert engine.estimate_job_bytes(_video(), s) == 410 * MB
    j = _video(fmt="video|1080p|mp4")
    assert engine.estimate_job_bytes(j, s) == 810 * MB
    a = _video(fmt="audio|mp3")
    assert engine.estimate_job_bytes(a, s) == 10 * MB


def test_job_estimate_subtracts_progress():
    s = Settings(quality="720p")
    j = _video(percent=50.0)
    assert engine.estimate_job_bytes(j, s) == 205 * MB


def test_playlist_estimate_uses_selected_duration():
    raw = [{"title": f"t{i}", "duration": 600} for i in range(1, 11)]
    pl = Job(url="u", kind=engine.KIND_PLAYLIST, item_count=10, duration=6000,
             entries=engine.pack_entries(raw), items="1-2")
    full = Job(url="u", kind=engine.KIND_PLAYLIST, item_count=10, duration=6000,
               entries=engine.pack_entries(raw))
    s = Settings(quality="720p")
    assert 0 < engine.estimate_job_bytes(pl, s) < engine.estimate_job_bytes(full, s)


def test_unknown_video_estimates_zero():
    assert engine.estimate_job_bytes(Job(url="u", kind=engine.KIND_VIDEO), Settings()) == 0


@pytest.mark.parametrize("needed,free,missing", [
    (1 * GB, 10 * GB, 0),                     # plenty
    (1 * GB, int(1.05 * GB), int(1.1 * GB) - int(1.05 * GB)),   # fits raw, not with headroom
    (10 * GB, 1 * GB, int(11 * GB) - 1 * GB),
    (0, 10 * GB, 0),                          # unknown size, roomy drive
    (0, 100 * MB, 300 * MB - 100 * MB),       # unknown size, nearly full drive
    (5 * GB, None, 0),                        # free space unknowable: never block
])
def test_shortfall(needed, free, missing):
    assert abs(space.shortfall(needed, free) - missing) <= 1


def test_free_bytes_walks_up_to_existing_parent(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    assert space.free_bytes(deep) == space.free_bytes(tmp_path)
    assert space.free_bytes(deep) > 0


def test_disk_full_is_diagnosed():
    out = engine.diagnose("OSError: [Errno 28] No space left on device")
    assert "drive is full" in out
