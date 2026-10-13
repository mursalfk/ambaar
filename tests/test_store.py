# tests/test_store.py
"""
Regression tests for queue persistence.

The invariant worth guarding is the restore mapping: a job recorded as
Downloading has no worker behind it after a restart, and bringing it back in
that state would show Pause and Cancel buttons for a worker that does not
exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ambaar import engine  # noqa: E402
from ambaar.engine import Job  # noqa: E402
from ambaar.store import QueueStore, discard_incomplete  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = QueueStore(tmp_path / "queue.db")
    assert s.available
    yield s
    s.close()


def _job(**kw) -> Job:
    job = Job(url=kw.pop("url", "https://example.com/v"))
    for k, v in kw.items():
        setattr(job, k, v)
    return job


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #

def test_round_trip_preserves_fields(store):
    job = _job(title="A video", status=engine.READY, kind=engine.KIND_VIDEO,
               duration=3725, uploader="Someone", size="291.5 MB")
    store.save(job, 0)

    back = store.load()[0]
    assert back.job_id == job.job_id
    assert back.title == "A video"
    assert back.kind == engine.KIND_VIDEO
    assert back.duration == 3725
    assert back.uploader == "Someone"


def test_order_is_preserved(store):
    for i in range(5):
        store.save(_job(url=f"https://example.com/{i}", title=f"n{i}",
                        status=engine.READY, kind=engine.KIND_VIDEO), i)
    assert [j.title for j in store.load()] == ["n0", "n1", "n2", "n3", "n4"]


def test_saving_the_same_job_updates_rather_than_duplicates(store):
    job = _job(title="first", status=engine.READY, kind=engine.KIND_VIDEO)
    store.save(job, 0)
    job.title = "second"
    store.save(job, 0)

    rows = store.load()
    assert len(rows) == 1
    assert rows[0].title == "second"


def test_remove_and_clear(store):
    a = _job(url="https://example.com/a", status=engine.READY, kind=engine.KIND_VIDEO)
    b = _job(url="https://example.com/b", status=engine.READY, kind=engine.KIND_VIDEO)
    store.save(a, 0)
    store.save(b, 1)

    store.remove(a.job_id)
    assert [j.job_id for j in store.load()] == [b.job_id]

    store.clear()
    assert store.load() == []


# --------------------------------------------------------------------------- #
# Restore mapping -- the part that actually matters
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("saved,percent,expected", [
    # Mid-flight with bytes on disk: Resume continues from the .part file.
    (engine.DOWNLOADING, 42.0, engine.PAUSED),
    (engine.QUEUED, 42.0, engine.PAUSED),
    (engine.PROCESSING, 99.0, engine.PAUSED),
    # Mid-flight with nothing downloaded: start cleanly.
    (engine.DOWNLOADING, 0.0, engine.READY),
    (engine.QUEUED, 0.0, engine.READY),
    # Settled states survive untouched.
    (engine.READY, 0.0, engine.READY),
    (engine.PAUSED, 50.0, engine.PAUSED),
    (engine.DONE, 100.0, engine.DONE),
    (engine.FAILED, 0.0, engine.FAILED),
])
def test_busy_states_are_rewritten_on_restore(store, saved, percent, expected):
    store.save(_job(title="t", kind=engine.KIND_VIDEO, status=saved,
                    percent=percent), 0)
    assert store.load()[0].status == expected


def test_unclassified_job_goes_back_to_staged(store):
    # Never finished resolving, so it has no kind and no title to show.
    store.save(_job(title="", kind=engine.KIND_UNKNOWN,
                    status=engine.RESOLVING), 0)
    assert store.load()[0].status == engine.STAGED


def test_restore_clears_live_metrics(store):
    # Speed and ETA describe a worker that no longer exists.
    store.save(_job(title="t", kind=engine.KIND_VIDEO, status=engine.DOWNLOADING,
                    percent=10.0, speed="4.2 MB/s", eta="2m"), 0)
    back = store.load()[0]
    assert back.speed == ""
    assert back.eta == ""


def test_no_restored_job_is_ever_busy(store):
    # Nothing may come back in a state whose buttons imply a live worker.
    for status in engine.BUSY:
        store.clear()
        store.save(_job(title="t", kind=engine.KIND_VIDEO, status=status,
                        percent=10.0), 0)
        assert store.load()[0].status not in engine.BUSY, status


# --------------------------------------------------------------------------- #
# Pruning
# --------------------------------------------------------------------------- #

def test_discard_drops_untouched_cancellations():
    kept = _job(status=engine.CANCELLED, percent=30.0)      # partial file exists
    dropped = _job(status=engine.CANCELLED, percent=0.0)    # user said no
    done = _job(status=engine.DONE, percent=100.0)
    out = discard_incomplete([kept, dropped, done])
    assert kept in out and done in out and dropped not in out


# --------------------------------------------------------------------------- #
# Failure modes
# --------------------------------------------------------------------------- #

def test_unwritable_database_degrades_quietly(tmp_path):
    # A directory where the file should be: opening must fail without raising,
    # because losing history should never stop someone downloading.
    blocked = tmp_path / "queue.db"
    blocked.mkdir()
    s = QueueStore(blocked)
    assert not s.available
    s.save(_job(), 0)       # no raise
    assert s.load() == []
    s.close()