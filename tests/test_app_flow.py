# tests/test_app_flow.py
"""
Main-window behaviour with the network and worker threads taken out.

Covers the parts of the UI that are logic rather than painting: duplicate
prompts, the clipboard offer, retry scheduling and cancelling, drag reorder,
history, "download again", and keyboard control.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QModelIndex, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox  # noqa: E402

from ambaar import engine  # noqa: E402
from ambaar import app as appmod  # noqa: E402
from ambaar.engine import Job  # noqa: E402
from ambaar.store import QueueStore  # noqa: E402
from ambaar.widgets import ROW_HEIGHT, key_action  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    # No resolving, no workers: these tests drive state by hand.
    monkeypatch.setattr(appmod.MainWindow, "_resolve", lambda self, job: None)
    monkeypatch.setattr(appmod.MainWindow, "_first_run_checks", lambda self: None)
    w = appmod.MainWindow()
    w.store.close()
    w.store = QueueStore(tmp_path / "q.db")
    w.history_page.store = w.store
    w.settings.archive_enabled = False
    w.manager.release = lambda *_a, **_k: None
    w.manager.submit = lambda job, position=0: _FakeWorker()
    yield w
    _dispose(w, qapp)


def _dispose(w, qapp) -> None:
    """
    Tear a window down deliberately.

    Windows left alive until interpreter shutdown are destroyed in arbitrary
    order against the QApplication, which segfaults at exit on some Qt builds
    even though every test passed. Stopping timers, draining the thread pools
    and deleting the window while the application still exists avoids it.
    """
    for jid in list(w._retry_timers):
        w._stop_retry(jid)
    w.manager.pool.waitForDone(1000)
    w.manager.resolve_pool.waitForDone(1000)
    w.tasks.waitForDone(1000)
    w.store.close()
    w.hide()
    w.setParent(None)
    w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()


class _Sig:
    def connect(self, *_a):
        pass


class _FakeSignals:
    status = progress = finished = failed = cancelled = paused = log = _Sig()


class _FakeWorker:
    signals = _FakeSignals()


def add(w, url="https://youtu.be/AAAAAAAAAAA", status=engine.READY, title="T", **kw):
    job = Job(url=url, title=title, status=status, kind=engine.KIND_VIDEO, **kw)
    w.jobs[job.job_id] = job
    item = QListWidgetItem()
    item.setData(Qt.UserRole, w._job_data(job))
    item.setData(Qt.UserRole + 1, job.job_id)
    from PySide6.QtCore import QSize

    item.setSizeHint(QSize(0, ROW_HEIGHT))
    w.queue.addItem(item)
    w.items[job.job_id] = item
    return job


def answer(monkeypatch, reply):
    calls = []

    def fake(parent, title, text, *a, **k):
        calls.append(text)
        return reply

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(fake))
    return calls


# -- duplicates ---------------------------------------------------------------- #


def test_duplicate_in_queue_asks_and_respects_no(win, monkeypatch):
    add(win, "https://youtu.be/AAAAAAAAAAA", title="First")
    calls = answer(monkeypatch, QMessageBox.No)
    win.url_input.setText("https://www.youtube.com/watch?v=AAAAAAAAAAA&feature=share")
    win.add_from_input()
    assert len(calls) == 1 and "First" in calls[0]
    assert len(win.jobs) == 1


def test_duplicate_yes_adds_it(win, monkeypatch):
    add(win, "https://youtu.be/AAAAAAAAAAA")
    answer(monkeypatch, QMessageBox.Yes)
    win.url_input.setText("https://youtu.be/AAAAAAAAAAA")
    win.add_from_input()
    assert len(win.jobs) == 2


def test_new_link_does_not_ask(win, monkeypatch):
    calls = answer(monkeypatch, QMessageBox.No)
    win.url_input.setText("https://youtu.be/ZZZZZZZZZZZ")
    win.add_from_input()
    assert calls == [] and len(win.jobs) == 1


def test_same_link_twice_in_one_paste_asks_once(win, monkeypatch):
    calls = answer(monkeypatch, QMessageBox.No)
    win.url_input.setText("https://youtu.be/AAAAAAAAAAA https://youtu.be/AAAAAAAAAAA")
    win.add_from_input()
    assert len(calls) == 1 and len(win.jobs) == 1


def test_history_counts_as_duplicate(win, monkeypatch):
    win.store.add_history(
        Job(
            url="https://youtu.be/HHHHHHHHHHH",
            title="Seen",
            status=engine.DONE,
            filepath="/x",
            folder="/",
        )
    )
    calls = answer(monkeypatch, QMessageBox.No)
    win.url_input.setText("https://www.youtube.com/watch?v=HHHHHHHHHHH")
    win.add_from_input()
    assert len(calls) == 1 and "Seen" in calls[0] and not win.jobs


# -- clipboard ----------------------------------------------------------------- #


def test_clipboard_off_by_default(win):
    assert win.settings.watch_clipboard is False
    QGuiApplication.clipboard().setText("https://youtu.be/CCCCCCCCCCC")
    win._on_clipboard()
    assert not win.offer.isVisibleTo(win)


def test_clipboard_offers_once_when_enabled(win):
    win.settings.watch_clipboard = True
    QGuiApplication.clipboard().setText("https://youtu.be/CCCCCCCCCCC")
    win._on_clipboard()
    assert win.offer.isVisibleTo(win)
    win.offer.dismiss()
    win._on_clipboard()  # same text again: no second offer
    assert not win.offer.isVisibleTo(win)


def test_clipboard_ignores_non_media_and_duplicates(win):
    win.settings.watch_clipboard = True
    QGuiApplication.clipboard().setText("just some text I copied")
    win._on_clipboard()
    assert not win.offer.isVisibleTo(win)
    add(win, "https://youtu.be/DDDDDDDDDDD")
    QGuiApplication.clipboard().setText("https://www.youtube.com/watch?v=DDDDDDDDDDD")
    win._on_clipboard()
    assert not win.offer.isVisibleTo(win)


def test_accepting_offer_stages_link(win):
    win.settings.watch_clipboard = True
    QGuiApplication.clipboard().setText("https://youtu.be/EEEEEEEEEEE")
    win._on_clipboard()
    win.offer._accept()
    assert [j.url for j in win.jobs.values()] == ["https://youtu.be/EEEEEEEEEEE"]
    assert not win.offer.isVisibleTo(win)


# -- retry --------------------------------------------------------------------- #


def test_transient_failure_schedules_retry(win):
    job = add(win, status=engine.DOWNLOADING)
    win._on_failed(job.job_id, "ERROR: Unable to download webpage: timed out")
    assert job.status == engine.QUEUED
    assert "Retrying in 15 s (1 of 3)" in job.error
    assert job.job_id in win._retry_timers
    win._stop_retry(job.job_id)


def test_permanent_failure_does_not_retry(win):
    job = add(win, status=engine.DOWNLOADING)
    win._on_failed(job.job_id, "ERROR: Video unavailable")
    assert job.status == engine.FAILED and not win._retry_timers


def test_retry_limit_then_fail(win):
    job = add(win, status=engine.DOWNLOADING)
    win.settings.auto_retry = 2
    for expected in (engine.QUEUED, engine.QUEUED, engine.FAILED):
        job.status = engine.DOWNLOADING
        win._on_failed(job.job_id, "timed out")
        assert job.status == expected
        win._stop_retry(job.job_id)


def test_retry_off(win):
    win.settings.auto_retry = 0
    job = add(win, status=engine.DOWNLOADING)
    win._on_failed(job.job_id, "timed out")
    assert job.status == engine.FAILED


def test_cancel_during_retry_wait(win):
    job = add(win, status=engine.DOWNLOADING)
    win._on_failed(job.job_id, "timed out")
    win._on_row_action(job.job_id, "cancel")
    assert job.status == engine.CANCELLED and job.error == ""
    assert job.job_id not in win._retry_timers


def test_fire_retry_restarts(win, monkeypatch):
    started = []
    monkeypatch.setattr(
        win,
        "start_download",
        lambda jid, check_space=True: started.append((jid, check_space)),
    )
    job = add(win, status=engine.DOWNLOADING)
    win._on_failed(job.job_id, "timed out")
    win._fire_retry(job.job_id)
    assert started == [(job.job_id, False)] and job.status == engine.READY


def test_manual_start_resets_attempts(win):
    job = add(win, status=engine.FAILED)
    job.attempts = 3
    win._on_row_action(job.job_id, "retry")
    assert job.attempts == 0


def test_remove_during_retry_wait_clears_timer(win):
    job = add(win, status=engine.DOWNLOADING)
    win._on_failed(job.job_id, "timed out")
    win._remove_job(job.job_id)
    assert not win._retry_timers and not win.jobs


# -- reorder -------------------------------------------------------------------- #


def test_dragging_reranks_waiting_downloads(win, monkeypatch):
    seen = []
    monkeypatch.setattr(
        win.manager, "apply_order", lambda order: seen.append(order) or 0
    )
    a = add(win, "https://youtu.be/AAAAAAAAAAA")
    b = add(win, "https://youtu.be/BBBBBBBBBBB")
    win.queue.model().moveRow(QModelIndex(), 1, QModelIndex(), 0)
    assert seen == [[b.job_id, a.job_id]]


def test_start_passes_list_position_as_priority(win, monkeypatch):
    got = []
    monkeypatch.setattr(
        win.manager,
        "submit",
        lambda job, position=0: got.append(position) or _FakeWorker(),
    )
    add(win, "https://youtu.be/AAAAAAAAAAA")
    b = add(win, "https://youtu.be/BBBBBBBBBBB")
    win.start_download(b.job_id, check_space=False)
    assert got == [1]


def test_dragging_reorders_jobs_and_saves(win):
    a = add(win, "https://youtu.be/AAAAAAAAAAA")
    b = add(win, "https://youtu.be/BBBBBBBBBBB")
    c = add(win, "https://youtu.be/CCCCCCCCCCC")
    win.store.save_all(list(win.jobs.values()))
    assert win.queue.model().moveRow(QModelIndex(), 2, QModelIndex(), 0)
    assert list(win.jobs) == [c.job_id, a.job_id, b.job_id]
    assert [j.job_id for j in win.store.load()] == [c.job_id, a.job_id, b.job_id]
    # items still map to the right jobs
    assert win.items[c.job_id] is win.queue.item(0)


# -- history / redo -------------------------------------------------------------- #


def test_finishing_records_history(win):
    job = add(win, status=engine.DOWNLOADING, title="Lecture")
    win._on_finished(job.job_id, str(Path("/tmp") / "x.mp4"))
    rows = win.store.history()
    assert len(rows) == 1 and rows[0]["title"] == "Lecture"
    assert job.status == engine.DONE and job.attempts == 0


def test_history_outlives_queue_removal(win):
    job = add(win, status=engine.DOWNLOADING)
    win._on_finished(job.job_id, "/tmp/x.mp4")
    win._remove_job(job.job_id)
    assert len(win.store.history()) == 1


def test_download_again_resets_and_starts(win, monkeypatch):
    started = []
    monkeypatch.setattr(
        win, "start_download", lambda jid, check_space=True: started.append(jid)
    )
    job = add(win, status=engine.DONE, percent=100.0, filepath="/x.mp4")
    win._redownload(job.job_id)
    assert job.redo and job.status == engine.READY and job.percent == 0
    assert job.filepath == "" and started == [job.job_id]


def test_download_again_ignores_running_job(win):
    job = add(win, status=engine.DOWNLOADING)
    win._redownload(job.job_id)
    assert not job.redo


def test_add_again_from_history(win):
    win._add_from_history("https://youtu.be/FFFFFFFFFFF")
    assert len(win.jobs) == 1


# -- log ------------------------------------------------------------------------- #


def test_job_log_routes_to_the_right_job(win):
    a = add(win, "https://youtu.be/AAAAAAAAAAA")
    b = add(win, "https://youtu.be/BBBBBBBBBBB")
    win._on_job_log(a.job_id, "hello a")
    assert a.log == ["hello a"] and b.log == []
    assert "hello a" in win.log_view.toPlainText()


def test_log_for_unknown_job_is_harmless(win):
    win._on_job_log("nope", "line")


def test_failure_text_lands_in_job_log(win):
    job = add(win, status=engine.DOWNLOADING)
    win.settings.auto_retry = 0
    win._on_failed(job.job_id, "Video unavailable")
    assert any("Video unavailable" in line for line in job.log)


# -- keyboard --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "key,status,action",
    [
        (Qt.Key_Space, engine.DOWNLOADING, "pause"),
        (Qt.Key_Space, engine.PAUSED, "resume"),
        (Qt.Key_Space, engine.READY, "download"),
        (Qt.Key_Space, engine.FAILED, "retry"),
        (Qt.Key_Space, engine.DONE, None),
        (Qt.Key_Return, engine.DONE, "open"),
        (Qt.Key_Enter, engine.READY, "download"),
        (Qt.Key_Return, engine.DOWNLOADING, None),
        (Qt.Key_Delete, engine.READY, "remove"),
        (Qt.Key_Delete, engine.DONE, "remove"),
        (Qt.Key_Delete, engine.DOWNLOADING, None),
        (Qt.Key_Delete, "Cancelling", None),
        (Qt.Key_A, engine.READY, None),
    ],
)
def test_key_table(key, status, action):
    assert key_action(key, status) == action


def test_delete_key_removes_selected_ready_row(win):
    job = add(win)
    win.queue.setCurrentRow(0)
    win.queue.item(0).setSelected(True)
    QTest.keyClick(win.queue, Qt.Key_Delete)
    assert job.job_id not in win.jobs


def test_delete_key_leaves_running_download_alone(win):
    job = add(win, status=engine.DOWNLOADING)
    win.queue.setCurrentRow(0)
    win.queue.item(0).setSelected(True)
    QTest.keyClick(win.queue, Qt.Key_Delete)
    assert job.job_id in win.jobs


def test_space_pauses_downloading_row(win, monkeypatch):
    seen = []
    monkeypatch.setattr(win.manager, "pause", lambda jid: seen.append(jid))
    job = add(win, status=engine.DOWNLOADING)
    win.queue.setCurrentRow(0)
    win.queue.item(0).setSelected(True)
    QTest.keyClick(win.queue, Qt.Key_Space)
    assert seen == [job.job_id]


# -- options tag -------------------------------------------------------------------- #


def test_row_tag_shows_format_and_folder(win):
    job = add(win, fmt="video|1080p|mp4|av1", dest="/media/videos")
    assert appmod.row_tag(job) == "1080p MP4 AV1, to videos"
    assert appmod.row_tag(add(win, "https://youtu.be/Z")) == ""


def test_space_check_is_per_folder(win, monkeypatch):
    from ambaar import space

    asked = answer(monkeypatch, QMessageBox.No)
    a = add(
        win,
        "https://youtu.be/AAAAAAAAAAA",
        dest="/mnt/small",
        sizes=space.pack_sizes(
            {
                "duration": 10,
                "formats": [
                    {
                        "vcodec": "a",
                        "acodec": "none",
                        "height": 720,
                        "filesize": 5 * 2**30,
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(
        space, "free_bytes", lambda p: 1 * 2**30 if "small" in str(p) else 500 * 2**30
    )
    assert win._space_ok([a]) is False and "/mnt/small" in asked[0]
    b = add(win, "https://youtu.be/BBBBBBBBBBB", sizes=a.sizes)
    assert win._space_ok([b]) is True


# -- the link bar stages links without a second step ------------------------------- #
#
# The original complaint: paste a link, click away, and it just sat in the box.
# Nothing was checked and there was nothing to press. These pin the behaviour
# that replaced it.

LINK = "https://youtu.be/fzfDuKj9B6U"


def _staged(w) -> list[Job]:
    return list(w.jobs.values())


def test_pasting_a_link_stages_it_and_clears_the_box(win, qapp):
    win.url_input.insert(LINK)  # one jump of many characters = a paste
    qapp.processEvents()
    assert [j.url for j in _staged(win)] == [LINK]
    assert win.url_input.text() == ""
    assert win.queue.count() == 1


def test_typing_a_link_waits_until_it_is_finished(win, qapp):
    for ch in LINK:  # one character at a time is typing
        QTest.keyClick(win.url_input, ch)
    qapp.processEvents()
    assert _staged(win) == []
    assert win.url_input.text() == LINK


def test_enter_stages_a_typed_link(win, qapp):
    for ch in LINK:
        QTest.keyClick(win.url_input, ch)
    QTest.keyClick(win.url_input, Qt.Key_Return)
    qapp.processEvents()
    assert [j.url for j in _staged(win)] == [LINK]
    assert win.url_input.text() == ""


def test_leaving_the_box_stages_a_typed_link(win, qapp):
    for ch in LINK:
        QTest.keyClick(win.url_input, ch)
    win.url_input.editingFinished.emit()  # what focus moving away does
    qapp.processEvents()
    assert [j.url for j in _staged(win)] == [LINK]
    assert win.url_input.text() == ""


def test_add_button_stages_the_link(win, qapp):
    from PySide6.QtWidgets import QPushButton

    add = next(b for b in win.findChildren(QPushButton) if b.text() == "Add")
    win.url_input.setText(LINK)  # setText is not an edit: nothing yet
    qapp.processEvents()
    assert _staged(win) == []
    add.click()
    assert [j.url for j in _staged(win)] == [LINK]
    assert win.url_input.text() == ""


def test_add_button_is_not_called_download(win):
    from PySide6.QtWidgets import QPushButton

    labels = {b.text() for b in win.findChildren(QPushButton)}
    assert "Add" in labels
    # "Download" belongs to the row; the bar only checks and lists.
    assert "Download" not in labels


def test_losing_focus_with_plain_text_is_silent(win, qapp):
    win._status("ready")
    win.url_input.setText("not a link")
    win.url_input.editingFinished.emit()
    qapp.processEvents()
    assert _staged(win) == []
    assert win.url_input.text() == "not a link"  # left for the user to fix
    assert "does not look like a link" not in win.statusBar().currentMessage()


def test_enter_on_plain_text_says_so(win, qapp):
    win.url_input.setText("not a link")
    win.add_from_input()
    assert _staged(win) == []
    assert "does not look like a link" in win.statusBar().currentMessage()


def test_enter_does_not_stage_twice(win, qapp):
    # Enter fires returnPressed and then editingFinished; the box is already
    # empty by the second, so the link must land once.
    win.url_input.setText(LINK)
    QTest.keyClick(win.url_input, Qt.Key_Return)
    win.url_input.editingFinished.emit()
    qapp.processEvents()
    assert len(_staged(win)) == 1


def test_several_pasted_links_each_get_a_row(win, qapp):
    other = "https://youtu.be/AAAAAAAAAAA"
    win.url_input.insert(f"{LINK} {other}")
    qapp.processEvents()
    assert sorted(j.url for j in _staged(win)) == sorted([LINK, other])
    assert win.queue.count() == 2


def test_pasted_link_lands_on_the_queue_page(win, qapp):
    win._show_page(1, sync_nav=True)
    win.url_input.insert(LINK)
    qapp.processEvents()
    assert win.stack.currentIndex() == 0


# -- row buttons and the header menu ------------------------------------------------ #


def test_every_row_button_has_a_tooltip_and_an_icon():
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter
    from ambaar.widgets import JobDelegate, TOOLTIPS, paint_icon

    statuses = [
        engine.READY,
        engine.DOWNLOADING,
        engine.PAUSED,
        engine.QUEUED,
        engine.RESOLVING,
        "Processing (Merger)",
        engine.DONE,
        engine.FAILED,
        engine.CANCELLED,
    ]
    actions = {a for s in statuses for a, _l, _p in JobDelegate.buttons_for(s)}
    actions.add("items")
    for action in sorted(actions):
        assert TOOLTIPS.get(action), f"no tooltip for {action}"
        img = QImage(34, 28, QImage.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        paint_icon(p, action, QRect(0, 0, 34, 28), QColor("#ffffff"))
        p.end()
        drawn = sum(
            1
            for x in range(34)
            for y in range(28)
            if QColor(img.pixel(x, y)).alpha() > 0
        )
        assert drawn > 12, f"{action} drew nothing"


def test_ready_row_offers_download_and_remove_together():
    from ambaar.widgets import JobDelegate

    actions = [a for a, _l, _p in JobDelegate.buttons_for(engine.READY)]
    assert actions[0] == "download" and actions[-1] == "remove"


def test_running_rows_offer_pause_and_cancel():
    from ambaar.widgets import JobDelegate

    assert [a for a, *_ in JobDelegate.buttons_for(engine.DOWNLOADING)] == [
        "pause",
        "cancel",
    ]
    assert [a for a, *_ in JobDelegate.buttons_for(engine.PAUSED)] == [
        "resume",
        "cancel",
    ]


def test_clicking_a_row_icon_emits_its_action(win, qapp):
    from PySide6.QtCore import QPoint
    from ambaar.widgets import JobDelegate

    job = add(win, status=engine.READY)
    seen = []
    win._delegate.action.connect(lambda jid, act: seen.append((jid, act)))
    win.resize(1000, 640)
    win.show()
    qapp.processEvents()
    idx = win.queue.model().index(0, 0)
    row = win.queue.visualRect(idx)
    rects = JobDelegate.button_rects(row, engine.READY)
    dl = next(r for a, _l, _p, r in rects if a == "download")
    QTest.mouseClick(win.queue.viewport(), Qt.LeftButton, Qt.NoModifier, dl.center())
    assert seen == [(job.job_id, "download")]


def test_header_has_pause_all_and_a_more_menu(win):
    assert win.btn_start.text() == "Download all"
    assert win.btn_pause_all.text() == "Pause all"
    assert win.btn_resume_all.text() == "Resume all"
    labels = [a.text() for a in win.btn_more.menu().actions() if a.text()]
    assert labels == [
        "Cancel selected",
        "Retry selected",
        "Clear finished",
        "Clear queue",
    ]


def test_header_buttons_are_never_clipped(win, qapp):
    win.resize(900, 640)
    win.show()
    qapp.processEvents()
    for b in win.queue_actions:
        assert b.width() >= b.sizeHint().width(), b.text()
        assert b.isVisible()
