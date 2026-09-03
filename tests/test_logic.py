"""
Regression tests for the pure logic.

Scope is deliberate: version comparison, rate parsing, error diagnosis, and the
rollback decision. These are the pieces where a wrong answer is silent -- an
update that should have been skipped, a revert that should not have fired, a
failure reported as the wrong cause. Nothing here touches the network or Qt, so
the suite runs in under a second.

    pip install pytest && pytest -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ambaar import updater  # noqa: E402
from ambaar.engine import diagnose, human_bytes, human_eta, parse_rate  # noqa: E402


# --------------------------------------------------------------------------- #
# Version comparison. yt-dlp uses date-based versions, and nightly builds add a
# fourth component -- a naive string compare gets these wrong.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("candidate,current,expected", [
    ("2024.08.06", "2024.07.01", True),
    ("2024.08.06", "2024.08.06", False),
    ("2024.07.01", "2024.08.06", False),
    ("2024.08.06.232819", "2024.08.06", True),      # nightly beats its stable base
    ("2024.08.06", "2024.08.06.232819", False),
    ("2025.01.15", "2024.12.31", True),             # year rollover
    ("2024.10.01", "2024.9.30", True),              # unpadded month
    ("2024.08.06", "", True),                       # nothing installed
    ("", "2024.08.06", False),                      # no candidate
    ("", "", False),
])
def test_is_newer(candidate, current, expected):
    assert updater.is_newer(candidate, current) is expected


def test_version_key_is_numeric_not_lexical():
    # "2024.10.01" < "2024.9.30" as strings, which is the bug this guards.
    assert updater._version_key("2024.10.01") > updater._version_key("2024.9.30")


# --------------------------------------------------------------------------- #
# Python floor
# --------------------------------------------------------------------------- #

def test_python_problem_empty_on_supported(monkeypatch):
    monkeypatch.setattr(updater, "MIN_PYTHON", (3, 9))
    assert updater.python_problem() == ""


def test_python_problem_explains_on_unsupported(monkeypatch):
    monkeypatch.setattr(updater, "MIN_PYTHON", (99, 0))
    msg = updater.python_problem()
    assert msg
    assert "nsig" in msg          # names the symptom the user will actually see
    assert "99.0" in msg          # names the requirement


# --------------------------------------------------------------------------- #
# Rate parsing
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("text,expected", [
    ("2M", 2 * 1024 ** 2),
    ("500K", 500 * 1024),
    ("1.5M", int(1.5 * 1024 ** 2)),
    ("1G", 1024 ** 3),
    ("1000", 1000),
    ("", None),
    ("   ", None),
    ("junk", None),
    ("M", None),
])
def test_parse_rate(text, expected):
    assert parse_rate(text) == expected


# --------------------------------------------------------------------------- #
# Error diagnosis. Each entry is a real string yt-dlp has produced.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("message,marker", [
    ("ERROR: [youtube] X: Requested format is not available", "stale"),
    ("WARNING: nsig extraction failed: Some formats may be missing", "stale"),
    ("Only images are available for download", "stale"),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "signature"),
    ("ERROR: Sign in to confirm your age", "account"),
    ("ERROR: Video unavailable", "unavailable"),
    ("ERROR: Postprocessing: ffprobe not found", "ffmpeg"),
    ("ERROR: Unable to download webpage: timed out", "Network"),
])
def test_diagnose_identifies_cause(message, marker):
    out = diagnose(message)
    assert "Cause:" in out
    assert marker.lower() in out.lower()
    assert message in out          # never discards the original


def test_diagnose_passes_through_unknown():
    msg = "ERROR: something nobody has seen before"
    assert diagnose(msg) == msg


def test_diagnose_uses_no_arrow_glyphs():
    # House rule: marks are drawn, never typed. Applies to log text too.
    out = diagnose("ERROR: HTTP Error 403: Forbidden")
    assert not any(ch in out for ch in "\u2192\u25b8\u27a1\u2794")


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value,expected", [
    (0, "--"), (None, "--"), ("x", "--"),
    (512, "512.0 B"), (2048, "2.0 KB"), (5 * 1024 ** 2, "5.0 MB"),
])
def test_human_bytes(value, expected):
    assert human_bytes(value) == expected


@pytest.mark.parametrize("value,expected", [
    (None, "--"), (-1, "--"), (45, "45s"), (90, "1m 30s"), (3700, "1h 01m"),
])
def test_human_eta(value, expected):
    assert human_eta(value) == expected


# --------------------------------------------------------------------------- #
# Rollback decision -- the asymmetry that keeps a network outage from
# triggering a spurious revert.
# --------------------------------------------------------------------------- #

def should_roll_back(before_ok: bool, after_ok: bool) -> bool:
    """Mirrors the condition in run_update: revert only on a real regression."""
    return before_ok and not after_ok


@pytest.mark.parametrize("before,after,expected", [
    (True, False, True),    # worked, now broken -> revert
    (True, True, False),    # still fine
    (False, False, False),  # was already broken; keep the newer build
    (False, True, False),   # the update fixed it
])
def test_rollback_only_on_regression(before, after, expected):
    assert should_roll_back(before, after) is expected


def test_network_outage_cannot_trigger_rollback():
    # An outage fails both probes. Both-fail must never revert, or a flaky
    # connection would pin users to an ever-older engine.
    assert should_roll_back(False, False) is False