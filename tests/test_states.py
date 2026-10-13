# tests/test_states.py
"""
Regression tests for the job state machine and the row's button table.

These guard the invariants that are easy to break while editing the UI: that
the button a row offers always matches the job's state, that the geometry the
painter uses is the geometry the click test uses, and that pause and cancel
stay distinguishable.

    pytest -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ambaar import engine  # noqa: E402
from ambaar.engine import Cancelled, Job, Paused, Settings, human_duration  # noqa: E402

# --------------------------------------------------------------------------- #
# State sets
# --------------------------------------------------------------------------- #


def test_new_job_starts_staged():
    assert Job(url="x").status == engine.STAGED


def test_state_sets_do_not_overlap():
    # A state cannot be both busy and finished; the UI branches on exactly this.
    assert not (engine.BUSY & engine.TERMINAL)


def test_startable_excludes_busy():
    # Offering Download on a job that is already running would double-submit it.
    assert not (engine.STARTABLE & engine.BUSY)


def test_terminal_states_are_startable_except_done():
    assert engine.FAILED in engine.STARTABLE
    assert engine.CANCELLED in engine.STARTABLE
    assert engine.DONE not in engine.STARTABLE


# --------------------------------------------------------------------------- #
# Interrupts
# --------------------------------------------------------------------------- #


def _worker() -> engine.DownloadWorker:
    return engine.DownloadWorker(Job(url="x"), Settings(output_dir="/tmp/ambaar-test"))


def test_idle_worker_does_not_interrupt():
    assert _worker()._interrupt() is None


def test_pause_raises_paused():
    w = _worker()
    w.pause()
    assert isinstance(w._interrupt(), Paused)


def test_cancel_beats_pause():
    # A user who pauses then cancels means cancel. The reverse would leave the
    # job sitting in Paused with no worker behind it.
    w = _worker()
    w.pause()
    w.cancel()
    assert isinstance(w._interrupt(), Cancelled)


def test_paused_and_cancelled_are_distinct_types():
    assert not issubclass(Paused, Cancelled)
    assert not issubclass(Cancelled, Paused)


def test_logger_raises_what_the_interrupt_returns():
    raised = []
    lg = engine._QuietLogger(lambda m: None, lambda: Paused())
    for name in ("debug", "info", "warning"):
        with pytest.raises(Paused):
            getattr(lg, name)("working")
        raised.append(name)
    assert raised == ["debug", "info", "warning"]


def test_logger_error_never_raises():
    # yt-dlp calls error() while unwinding its own failure; raising there would
    # replace the real cause with ours.
    engine._QuietLogger(lambda m: None, lambda: Cancelled()).error("real cause")


# --------------------------------------------------------------------------- #
# Duration
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, ""),
        (None, ""),
        (-5, ""),
        ("x", ""),
        (45, "0:45"),
        (95, "1:35"),
        (3600, "1:00:00"),
        (3725, "1:02:05"),
    ],
)
def test_human_duration(seconds, expected):
    assert human_duration(seconds) == expected


# --------------------------------------------------------------------------- #
# Row buttons -- imported lazily so the suite runs without a display
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session", autouse=True)
def _qt_app():
    """
    One offscreen QApplication for the whole session.

    QFontMetrics -- which the button geometry needs -- aborts the interpreter if
    no QApplication exists, so this cannot be left to chance. Offscreen means no
    display is required, which is what lets the suite run in CI.
    """
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ambaar import theme

    app = QApplication.instance() or QApplication([])
    theme.load_fonts()
    yield app


def _delegate():
    pytest.importorskip("PySide6")
    from ambaar.widgets import JobDelegate

    return JobDelegate


@pytest.mark.parametrize(
    "status,expected",
    [
        (engine.STAGED, []),
        (engine.RESOLVING, ["cancel"]),
        (engine.READY, ["download", "format", "remove"]),
        (engine.QUEUED, ["cancel"]),
        (engine.DOWNLOADING, ["pause", "cancel"]),
        (engine.PAUSED, ["resume", "cancel"]),
        (engine.DONE, ["folder", "remove"]),
        (engine.FAILED, ["retry", "remove"]),
        (engine.CANCELLED, ["retry", "remove"]),
    ],
)
def test_buttons_per_state(status, expected):
    assert [a for a, _, _ in _delegate().buttons_for(status)] == expected


def test_processing_offers_cancel_but_never_pause():
    # ffmpeg cannot resume a half-written merge, so a pause here would silently
    # mean redoing the work.
    actions = [a for a, _, _ in _delegate().buttons_for("Processing (Merger)")]
    assert actions == ["cancel"]


def test_running_states_never_offer_remove():
    # Remove on a running job would orphan its worker.
    for status in (engine.DOWNLOADING, engine.QUEUED, engine.RESOLVING):
        actions = [a for a, _, _ in _delegate().buttons_for(status)]
        assert "remove" not in actions


def test_button_geometry_fits_and_does_not_overlap():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QRect

    JobDelegate = _delegate()
    rect = QRect(0, 0, 900, 84)
    for status in (engine.READY, engine.DOWNLOADING, engine.DONE, engine.PAUSED):
        rects = [r for *_, r in JobDelegate.button_rects(rect, status)]
        assert all(rect.contains(r) for r in rects), status
        for a, b in zip(rects, rects[1:]):
            assert a.right() <= b.left(), status


def test_text_stops_before_the_buttons():
    # The painter elides title and metrics to this edge; if it drifted past the
    # first button the text would be drawn underneath it.
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QRect

    JobDelegate = _delegate()
    rect = QRect(0, 0, 900, 84)
    for status in (engine.READY, engine.DOWNLOADING, engine.DONE):
        rects = JobDelegate.button_rects(rect, status)
        assert JobDelegate.buttons_left_edge(rect, status) == rects[0][3].left()


def test_no_buttons_means_text_runs_to_the_padding():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QRect
    from ambaar.widgets import ROW_PAD_X

    JobDelegate = _delegate()
    rect = QRect(0, 0, 900, 84)
    # QRect.right() is left + width - 1, not left + width. Using the width here
    # would be off by one, which is exactly the kind of drift this test exists
    # to catch in the painter.
    assert (
        JobDelegate.buttons_left_edge(rect, engine.STAGED) == rect.right() - ROW_PAD_X
    )
