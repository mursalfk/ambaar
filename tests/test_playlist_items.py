# tests/test_playlist_items.py
"""
Playlist selection: position specs, resolve-time listing, persistence.

The easy bug here is an off-by-one between our positions and yt-dlp's. Entries
that are unavailable still occupy a playlist slot, so positions must be taken
from the raw listing before empty entries are dropped.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ambaar import engine  # noqa: E402
from ambaar.engine import Job  # noqa: E402
from ambaar.store import QueueStore  # noqa: E402


@pytest.mark.parametrize(
    "positions,spec",
    [
        ([], ""),
        ([1], "1"),
        ([1, 2, 3], "1-3"),
        ([1, 2, 3, 7], "1-3,7"),
        ([5, 3, 4, 9, 10], "3-5,9-10"),
        ([2, 2, 2], "2"),
    ],
)
def test_compress(positions, spec):
    assert engine.compress_items(positions) == spec


@pytest.mark.parametrize("spec", ["1", "1-3,7", "3-5,9-10", ""])
def test_roundtrip(spec):
    assert engine.compress_items(engine.expand_items(spec)) == spec


@pytest.mark.parametrize("bad", ["x", "1-", "-3", "a-b", ",,", "0", "-1"])
def test_expand_ignores_garbage(bad):
    assert engine.expand_items(bad) == set()


def test_pack_keeps_original_positions_when_entries_missing():
    raw = [{"title": "one", "duration": 60}, None, {"title": "three", "duration": 30}]
    packed = engine.unpack_entries(engine.pack_entries(raw))
    assert [e["i"] for e in packed] == [1, 3]


def test_unpack_survives_garbage():
    assert engine.unpack_entries("not json") == []
    assert engine.unpack_entries('{"a": 1}') == []
    assert engine.unpack_entries(None) == []


def _playlist(spec="", n=5):
    raw = [{"title": f"t{i}", "duration": 100} for i in range(1, n + 1)]
    return Job(
        url="u",
        kind=engine.KIND_PLAYLIST,
        item_count=n,
        duration=100 * n,
        entries=engine.pack_entries(raw),
        items=spec,
    )


def test_selection_defaults_to_all():
    assert engine.selected_positions(_playlist()) == {1, 2, 3, 4, 5}
    assert engine.selection_summary(_playlist()) == (5, 5, 500)


def test_selection_summary_for_subset():
    assert engine.selection_summary(_playlist("2-3")) == (2, 5, 200)


def test_stale_positions_are_ignored():
    assert engine.selected_positions(_playlist("4-9")) == {4, 5}


def test_summary_without_entries_falls_back():
    j = Job(url="u", kind=engine.KIND_PLAYLIST, item_count=7, duration=70)
    assert engine.selection_summary(j) == (7, 7, 70)


def test_selection_persists(tmp_path):
    st = QueueStore(tmp_path / "q.db")
    j = _playlist("1,3")
    j.status = engine.READY
    j.title = "pl"
    st.save(j, 0)
    st.close()
    st = QueueStore(tmp_path / "q.db")
    back = st.load()[0]
    assert back.items == "1,3"
    assert engine.selection_summary(back) == (2, 5, 200)
    st.close()


def test_items_button_only_for_ready_playlists():
    from ambaar.widgets import JobDelegate

    ready = [
        a for a, _, _ in JobDelegate.buttons_for(engine.READY, engine.KIND_PLAYLIST)
    ]
    assert ready == ["download", "items", "format", "remove"]
    video = [a for a, _, _ in JobDelegate.buttons_for(engine.READY, engine.KIND_VIDEO)]
    assert "items" not in video
    other = [
        a for a, _, _ in JobDelegate.buttons_for(engine.DONE, engine.KIND_PLAYLIST)
    ]
    assert "items" not in other
