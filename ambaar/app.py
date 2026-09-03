"""
Main window.

Layout is a fixed sidebar plus a stacked content area. The queue is a QListWidget
whose rows are painted by JobDelegate rather than composed from widgets -- see
widgets.py for why. Everything visual comes from theme.py; there are no colour
literals below this line.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEvent, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal, Slot,
)
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QStackedWidget, QStatusBar, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import branding
from . import ffmpeg as ffmpeg_tool
from . import jsruntime
from . import theme, updater
from .bootstrap import engine_source
from .engine import QUALITY_MAP, DownloadManager, Job, Settings
from .paths import data_dir
from .widgets import ROW_HEIGHT, ComboBox, EmptyState, EngineBadge, JobDelegate, SpinBox

BROWSERS = ["", "chrome", "firefox", "edge", "safari", "brave", "chromium", "opera", "vivaldi"]
ACTIVE = {"Queued", "Resolving", "Downloading", "Processing", "Cancelling"}
SECTIONS = ["Queue", "Settings", "Engine", "Activity"]


# --------------------------------------------------------------------------- #
# Background tasks
# --------------------------------------------------------------------------- #

class TaskSignals(QObject):
    progress = Signal(str)
    done = Signal(object)


class UpdateTask(QRunnable):
    """Engine check. Network plus a possible pip or wheel unpack, never on the GUI thread."""

    def __init__(self, *, force: bool, verify_only: bool, channel: str):
        super().__init__()
        self.signals = TaskSignals()
        self.force, self.verify_only, self.channel = force, verify_only, channel

    @Slot()
    def run(self) -> None:
        state = updater.UpdaterState.load()
        state.channel = self.channel  # type: ignore[assignment]
        outcome = updater.run_update(
            state, force=self.force, verify_only=self.verify_only,
            on_progress=self.signals.progress.emit,
        )
        self.signals.done.emit(outcome)


class ToolTask(QRunnable):
    """Downloads a managed tool (ffmpeg, Deno). Network work, never on the GUI thread."""

    def __init__(self, module, name: str) -> None:
        super().__init__()
        self.signals = TaskSignals()
        self.module = module
        self.name = name

    @Slot()
    def run(self) -> None:
        ok, message = self.module.fetch(
            on_progress=lambda msg, pct: self.signals.progress.emit(msg)
        )
        self.signals.done.emit((ok, message, self.name))


# --------------------------------------------------------------------------- #
# Layout helpers
# --------------------------------------------------------------------------- #

def _clip(text: str, limit: int = 190) -> str:
    """Keep a diagnostic readable in a fixed row. Full text goes in the tooltip."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def rule() -> QFrame:
    f = QFrame()
    f.setObjectName("Rule")
    f.setFrameShape(QFrame.NoFrame)
    f.setFixedHeight(1)
    return f


def label(text: str, role: str = "") -> QLabel:
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    return w


def row(*widgets, spacing: int = 8, stretch: int = -1) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for i, w in enumerate(widgets):
        lay.addWidget(w, 1 if i == stretch else 0)
    if stretch < 0:
        lay.addStretch(1)
    return box


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.manager = DownloadManager(self.settings)
        self.jobs: dict[str, Job] = {}
        self.items: dict[str, QListWidgetItem] = {}
        self.tasks = QThreadPool()
        self.tasks.setMaxThreadCount(1)

        self.setWindowTitle("Ambaar")
        self.setWindowIcon(branding.app_icon())
        self.resize(1120, 720)
        self.setMinimumSize(QSize(900, 560))

        self._build_menu()
        self._build_ui()
        self._refresh_engine()

        QTimer.singleShot(250, self._first_run_checks)
        if self.settings.auto_update:
            QTimer.singleShot(1600, self._maybe_auto_update)

    # -- chrome -------------------------------------------------------------- #

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&Engine")
        for text, fn in (
            ("Check for updates", lambda: self._run_update(force=True)),
            ("Verify installation", lambda: self._run_update(verify_only=True)),
        ):
            a = QAction(text, self)
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        a = QAction("Install ffmpeg", self)
        a.triggered.connect(self._install_ffmpeg)
        m.addAction(a)

        m2 = self.menuBar().addMenu("&Folders")
        for text, path_fn in (
            ("Open downloads", lambda: Path(self.settings.output_dir).expanduser()),
            ("Open app data", data_dir),
        ):
            a = QAction(text, self)
            a.triggered.connect(
                lambda _=False, f=path_fn: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(f()))))
            m2.addAction(a)

    def _build_ui(self) -> None:
        shell = QWidget()
        outer = QHBoxLayout(shell)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())

        right = QWidget()
        col = QVBoxLayout(right)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._header())
        self.url_row = self._url_bar()
        col.addWidget(self.url_row)
        col.addWidget(rule())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_queue())
        self.stack.addWidget(self._page_settings())
        self.stack.addWidget(self._page_engine())
        self.stack.addWidget(self._page_activity())
        col.addWidget(self.stack, 1)

        outer.addWidget(right, 1)
        self.setCentralWidget(shell)
        self.setStatusBar(QStatusBar())
        self._status("Ready")

    def _sidebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(190)
        col = QVBoxLayout(bar)
        col.setContentsMargins(0, 22, 0, 14)
        col.setSpacing(0)

        brand = QWidget()
        bl = QVBoxLayout(brand)
        bl.setContentsMargins(18, 0, 18, 22)
        bl.setSpacing(3)
        wm = QLabel("Ambaar")
        wm.setObjectName("Wordmark")
        sub = QLabel("DOWNLOAD MANAGER")
        sub.setObjectName("WordmarkSub")
        bl.addWidget(wm)
        bl.addWidget(sub)
        col.addWidget(brand)

        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for i, name in enumerate(SECTIONS):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setCursor(Qt.PointingHandCursor)
            self.nav.addButton(b, i)
            col.addWidget(b)
        self.nav.idClicked.connect(self._show_page)

        col.addStretch(1)

        self.badge = EngineBadge()
        self.badge.clicked.connect(lambda: self._show_page(2, sync_nav=True))
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.addWidget(self.badge)
        col.addWidget(holder)
        return bar

    def _header(self) -> QWidget:
        head = QWidget()
        head.setObjectName("Header")
        lay = QHBoxLayout(head)
        lay.setContentsMargins(22, 16, 18, 16)
        lay.setSpacing(9)

        self.page_title = label("Queue", "title")
        lay.addWidget(self.page_title)
        lay.addStretch(1)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_retry = QPushButton("Retry")
        self.btn_clear = QPushButton("Clear finished")
        for b, fn in ((self.btn_cancel, self.cancel_selected),
                      (self.btn_retry, self.retry_selected),
                      (self.btn_clear, self.clear_finished)):
            b.setProperty("variant", "ghost")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            lay.addWidget(b)
        self.queue_actions = [self.btn_cancel, self.btn_retry, self.btn_clear]
        return head

    def _url_bar(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(22, 14, 18, 14)
        lay.setSpacing(8)

        self.url_input = QLineEdit()
        self.url_input.setObjectName("UrlBar")
        self.url_input.setPlaceholderText("Paste a video or playlist link")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self.add_from_input)
        lay.addWidget(self.url_input, 1)

        paste = QPushButton("Paste")
        paste.setProperty("variant", "ghost")
        paste.setCursor(Qt.PointingHandCursor)
        paste.clicked.connect(self.paste_and_add)
        lay.addWidget(paste)

        add = QPushButton("Download")
        add.setProperty("variant", "primary")
        add.setCursor(Qt.PointingHandCursor)
        add.setDefault(True)
        add.clicked.connect(self.add_from_input)
        lay.addWidget(add)
        return wrap

    # -- pages --------------------------------------------------------------- #

    def _scroll(self, inner: QWidget) -> QWidget:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(inner)
        return area

    def _page_queue(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)

        self.queue = QListWidget()
        self.queue.setItemDelegate(JobDelegate(self.queue))
        self.queue.setSelectionMode(QListWidget.ExtendedSelection)
        self.queue.setMouseTracking(True)
        self.queue.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.queue.setFrameShape(QFrame.NoFrame)
        self.queue.setUniformItemSizes(True)
        self.queue.itemDoubleClicked.connect(self._open_item_file)
        lay.addWidget(self.queue)

        self.empty = EmptyState(self.queue)
        self.queue.installEventFilter(self)
        return page

    def _page_settings(self) -> QWidget:
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(22, 20, 22, 24)
        col.setSpacing(20)

        col.addWidget(label("OUTPUT", "label"))
        f1 = QFormLayout()
        f1.setSpacing(11)
        f1.setLabelAlignment(Qt.AlignLeft)

        self.out_dir = QLineEdit(self.settings.output_dir)
        self.out_dir.setMinimumWidth(320)
        self.out_dir.editingFinished.connect(self._save)
        browse = QPushButton("Browse")
        browse.setProperty("variant", "ghost")
        browse.clicked.connect(self._pick_dir)
        f1.addRow("Folder", row(self.out_dir, browse, stretch=0))

        self.quality = ComboBox()
        self.quality.addItems(QUALITY_MAP.keys())
        self.quality.setCurrentText(self.settings.quality)
        self.quality.currentTextChanged.connect(self._save)
        f1.addRow("Quality", row(self.quality))

        self.container = ComboBox()
        self.container.addItems(["mp4", "mkv", "webm"])
        self.container.setCurrentText(self.settings.container)
        self.container.currentTextChanged.connect(self._save)
        f1.addRow("Container", row(self.container))

        self.playlist = QCheckBox("Download every item in a playlist")
        self.playlist.setChecked(self.settings.playlist)
        self.playlist.toggled.connect(self._save)
        f1.addRow("", self.playlist)
        col.addLayout(f1)
        col.addWidget(rule())

        col.addWidget(label("AUDIO", "label"))
        f2 = QFormLayout()
        f2.setSpacing(11)
        self.audio_only = QCheckBox("Extract audio only")
        self.audio_only.setChecked(self.settings.audio_only)
        self.audio_only.toggled.connect(self._on_audio_toggled)
        f2.addRow("", self.audio_only)

        self.audio_format = ComboBox()
        self.audio_format.addItems(["mp3", "m4a", "opus", "flac", "wav"])
        self.audio_format.setCurrentText(self.settings.audio_format)
        self.audio_format.setEnabled(self.settings.audio_only)
        self.audio_format.currentTextChanged.connect(self._save)
        f2.addRow("Format", row(self.audio_format))

        self.thumb = QCheckBox("Embed thumbnail as cover art")
        self.thumb.setChecked(self.settings.embed_thumbnail)
        self.thumb.toggled.connect(self._save)
        f2.addRow("", self.thumb)
        col.addLayout(f2)
        col.addWidget(rule())

        col.addWidget(label("SUBTITLES", "label"))
        f3 = QFormLayout()
        f3.setSpacing(11)
        self.subs = QCheckBox("Embed subtitles")
        self.subs.setChecked(self.settings.embed_subs)
        self.subs.toggled.connect(self._on_subs_toggled)
        f3.addRow("", self.subs)

        self.sub_langs = QLineEdit(self.settings.sub_langs)
        self.sub_langs.setPlaceholderText("en, it, ur")
        self.sub_langs.setEnabled(self.settings.embed_subs)
        self.sub_langs.editingFinished.connect(self._save)
        f3.addRow("Languages", row(self.sub_langs, stretch=0))

        self.auto_subs = QCheckBox("Fall back to auto-generated captions")
        self.auto_subs.setChecked(self.settings.auto_subs)
        self.auto_subs.setEnabled(self.settings.embed_subs)
        self.auto_subs.toggled.connect(self._save)
        f3.addRow("", self.auto_subs)
        col.addLayout(f3)
        col.addWidget(rule())

        col.addWidget(label("NETWORK AND ACCESS", "label"))
        f4 = QFormLayout()
        f4.setSpacing(11)

        self.cookies = ComboBox()
        self.cookies.addItems(BROWSERS)
        self.cookies.setCurrentText(self.settings.cookies_from_browser)
        self.cookies.currentTextChanged.connect(self._save)
        f4.addRow("Cookies from", row(self.cookies))
        hint = label("Needed for age-restricted, private, or members-only videos.", "hint")
        hint.setWordWrap(True)
        f4.addRow("", hint)

        self.parallel = SpinBox()
        self.parallel.setRange(1, 8)
        self.parallel.setValue(self.settings.max_parallel_jobs)
        self.parallel.valueChanged.connect(self._on_parallel_changed)
        f4.addRow("Parallel downloads", row(self.parallel))

        self.frag = SpinBox()
        self.frag.setRange(1, 16)
        self.frag.setValue(self.settings.concurrency)
        self.frag.valueChanged.connect(self._save)
        f4.addRow("Fragment threads", row(self.frag))

        self.rate = QLineEdit(self.settings.limit_rate)
        self.rate.setPlaceholderText("2M or 500K, blank for unlimited")
        self.rate.editingFinished.connect(self._save)
        f4.addRow("Speed limit", row(self.rate, stretch=0))

        self.archive = QCheckBox("Skip anything already downloaded")
        self.archive.setChecked(self.settings.archive_enabled)
        self.archive.toggled.connect(self._save)
        f4.addRow("", self.archive)
        col.addLayout(f4)
        col.addStretch(1)
        return self._scroll(body)

    def _page_engine(self) -> QWidget:
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(22, 20, 22, 24)
        col.setSpacing(16)

        col.addWidget(label("YT-DLP ENGINE", "label"))
        f1 = QFormLayout()
        f1.setSpacing(11)
        self.lbl_version = label("--", "mono")
        f1.addRow("Version", self.lbl_version)
        self.lbl_source = label("--", "mono")
        self.lbl_source.setWordWrap(True)
        f1.addRow("Source", self.lbl_source)
        self.lbl_checked = label("--", "mono")
        f1.addRow("Last checked", self.lbl_checked)
        self.lbl_health = QLabel("--")
        self.lbl_health.setWordWrap(True)
        f1.addRow("Verification", self.lbl_health)

        self.channel = ComboBox()
        self.channel.addItems(["stable", "nightly"])
        self.channel.setCurrentText(self.settings.update_channel)
        self.channel.currentTextChanged.connect(self._save)
        f1.addRow("Channel", row(self.channel))

        self.auto_update = QCheckBox("Check weekly when the app starts")
        self.auto_update.setChecked(self.settings.auto_update)
        self.auto_update.toggled.connect(self._save)
        f1.addRow("", self.auto_update)
        col.addLayout(f1)

        self.btn_update = QPushButton("Check for updates")
        self.btn_update.setProperty("variant", "primary")
        self.btn_update.clicked.connect(lambda: self._run_update(force=True))
        self.btn_verify = QPushButton("Verify only")
        self.btn_verify.setProperty("variant", "ghost")
        self.btn_verify.clicked.connect(lambda: self._run_update(verify_only=True))
        col.addWidget(row(self.btn_update, self.btn_verify))

        explain = label(
            "Verification resolves a real media URL and issues a ranged request "
            "against it. A 403 there means signature deciphering is broken, which "
            "a version number alone would never reveal. If an update regresses, "
            "the previous working version is restored automatically.", "hint")
        explain.setWordWrap(True)
        col.addWidget(explain)
        col.addWidget(rule())

        col.addWidget(label("FFMPEG", "label"))
        f2 = QFormLayout()
        f2.setSpacing(11)
        self.lbl_ffmpeg = QLabel("--")
        self.lbl_ffmpeg.setWordWrap(True)
        f2.addRow("Status", self.lbl_ffmpeg)
        col.addLayout(f2)

        self.btn_ffmpeg = QPushButton("Install ffmpeg")
        self.btn_ffmpeg.setProperty("variant", "ghost")
        self.btn_ffmpeg.clicked.connect(self._install_ffmpeg)
        col.addWidget(row(self.btn_ffmpeg))

        ff_hint = label(
            "Required for anything above 360p and for audio extraction. Without "
            "it, downloads quietly fall back to a low-quality single stream.", "hint")
        ff_hint.setWordWrap(True)
        col.addWidget(ff_hint)
        col.addWidget(rule())

        col.addWidget(label("JAVASCRIPT RUNTIME", "label"))
        f3 = QFormLayout()
        f3.setSpacing(11)
        self.lbl_deno = QLabel("--")
        self.lbl_deno.setWordWrap(True)
        f3.addRow("Status", self.lbl_deno)
        col.addLayout(f3)

        self.btn_deno = QPushButton("Install runtime")
        self.btn_deno.setProperty("variant", "ghost")
        self.btn_deno.clicked.connect(self._install_deno)
        col.addWidget(row(self.btn_deno))

        js_hint = label(
            "YouTube obfuscates its format URLs behind a JavaScript challenge. "
            "yt-dlp needs a runtime to solve it; without one it falls back to "
            "weaker extraction and some formats never appear. Downloads still "
            "succeed, they are just worse.", "hint")
        js_hint.setWordWrap(True)
        col.addWidget(js_hint)

        self.update_log = QTextEdit()
        self.update_log.setReadOnly(True)
        self.update_log.setMinimumHeight(130)
        col.addWidget(self.update_log, 1)
        return self._scroll(body)

    def _page_activity(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(22, 20, 22, 20)
        col.setSpacing(12)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Engine output appears here during downloads.")
        col.addWidget(self.log_view, 1)
        clear = QPushButton("Clear")
        clear.setProperty("variant", "ghost")
        clear.clicked.connect(self.log_view.clear)
        col.addWidget(row(clear))
        return page

    # -- navigation ---------------------------------------------------------- #

    def _show_page(self, index: int, sync_nav: bool = False) -> None:
        self.stack.setCurrentIndex(index)
        self.page_title.setText(SECTIONS[index])
        for b in self.queue_actions:
            b.setVisible(index == 0)
        # The add bar belongs to the queue; carrying it onto Settings just
        # competes with whatever the user came to that page to change.
        self.url_row.setVisible(index == 0)
        if sync_nav:
            button = self.nav.button(index)
            if button:
                button.setChecked(True)

    def eventFilter(self, obj, event):
        if obj is self.queue and event.type() in (QEvent.Resize, QEvent.Show):
            self.empty.setGeometry(self.queue.rect())
        return super().eventFilter(obj, event)

    # -- settings ------------------------------------------------------------ #

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose download folder",
                                             self.out_dir.text())
        if d:
            self.out_dir.setText(d)
            self._save()

    def _on_audio_toggled(self, on: bool) -> None:
        self.audio_format.setEnabled(on)
        self._save()

    def _on_subs_toggled(self, on: bool) -> None:
        self.sub_langs.setEnabled(on)
        self.auto_subs.setEnabled(on)
        self._save()

    def _on_parallel_changed(self, n: int) -> None:
        self.manager.set_parallelism(n)
        self._save()

    def _save(self) -> None:
        s = self.settings
        s.output_dir = self.out_dir.text().strip() or s.output_dir
        s.quality = self.quality.currentText()
        s.container = self.container.currentText()
        s.audio_only = self.audio_only.isChecked()
        s.audio_format = self.audio_format.currentText()
        s.embed_thumbnail = self.thumb.isChecked()
        s.embed_subs = self.subs.isChecked()
        s.sub_langs = self.sub_langs.text().strip() or "en"
        s.auto_subs = self.auto_subs.isChecked()
        s.playlist = self.playlist.isChecked()
        s.concurrency = self.frag.value()
        s.max_parallel_jobs = self.parallel.value()
        s.limit_rate = self.rate.text().strip()
        s.cookies_from_browser = self.cookies.currentText()
        s.archive_enabled = self.archive.isChecked()
        s.update_channel = self.channel.currentText()
        s.auto_update = self.auto_update.isChecked()
        s.save()

    # -- queue --------------------------------------------------------------- #

    def paste_and_add(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if text:
            self.url_input.setText(text)
        self.add_from_input()

    def add_from_input(self) -> None:
        raw = self.url_input.text().strip()
        if not raw:
            return
        urls = [u for u in raw.replace(",", " ").split() if u.startswith("http")]
        if not urls:
            self._status("That does not look like a link.")
            return
        self.url_input.clear()
        for url in urls:
            self.add_job(url)
        self._show_page(0, sync_nav=True)

    def add_job(self, url: str) -> None:
        self._save()
        job = Job(url=url, title="")
        self.jobs[job.job_id] = job

        item = QListWidgetItem()
        item.setSizeHint(QSize(0, ROW_HEIGHT))
        item.setData(Qt.UserRole, self._job_data(job))
        item.setData(Qt.UserRole + 1, job.job_id)
        self.queue.addItem(item)
        self.items[job.job_id] = item
        self._sync_empty()

        worker = self.manager.submit(job)
        s = worker.signals
        s.title.connect(self._on_title)
        s.status.connect(self._on_status)
        s.progress.connect(self._on_progress)
        s.finished.connect(self._on_finished)
        s.failed.connect(self._on_failed)
        s.cancelled.connect(self._on_cancelled)
        s.log.connect(self._append_log)

    @staticmethod
    def _job_data(job: Job) -> dict:
        return {"url": job.url, "title": job.title, "status": job.status,
                "percent": job.percent, "speed": job.speed, "eta": job.eta,
                "size": job.size, "error": job.error}

    def _refresh(self, job_id: str) -> None:
        item = self.items.get(job_id)
        if item:
            item.setData(Qt.UserRole, self._job_data(self.jobs[job_id]))

    @Slot(str, str)
    def _on_title(self, job_id: str, title: str) -> None:
        self.jobs[job_id].title = title
        self._refresh(job_id)

    @Slot(str, str)
    def _on_status(self, job_id: str, status: str) -> None:
        self.jobs[job_id].status = status
        self._refresh(job_id)

    @Slot(str, float, str, str, str)
    def _on_progress(self, job_id: str, pct: float, speed: str, eta: str, size: str) -> None:
        job = self.jobs[job_id]
        job.percent, job.speed, job.eta, job.size = pct, speed, eta, size
        self._refresh(job_id)

    @Slot(str, str)
    def _on_finished(self, job_id: str, path: str) -> None:
        job = self.jobs[job_id]
        job.status, job.filepath, job.percent = "Done", path, 100.0
        job.speed = job.eta = ""
        self._refresh(job_id)
        self.manager.release(job_id)
        self._status(f"Finished: {job.title or job.url}")

    @Slot(str, str)
    def _on_failed(self, job_id: str, error: str) -> None:
        job = self.jobs[job_id]
        job.status, job.error = "Failed", error
        job.speed = job.eta = ""
        self._refresh(job_id)
        self.manager.release(job_id)
        self._append_log(f"FAILED  {job.url}\n{error}\n")
        self._status("A download failed. See Activity for detail.")

    @Slot(str)
    def _on_cancelled(self, job_id: str) -> None:
        job = self.jobs[job_id]
        job.status, job.speed, job.eta = "Cancelled", "", ""
        self._refresh(job_id)
        self.manager.release(job_id)

    def _selected_ids(self) -> list[str]:
        return [i.data(Qt.UserRole + 1) for i in self.queue.selectedItems()]

    def cancel_selected(self) -> None:
        ids = self._selected_ids() or list(self.jobs)
        for jid in ids:
            job = self.jobs.get(jid)
            if job and job.status in ACTIVE:
                self.manager.cancel(jid)
                job.status = "Cancelling"
                self._refresh(jid)

    def retry_selected(self) -> None:
        for jid in self._selected_ids():
            job = self.jobs.get(jid)
            if job and job.status in {"Failed", "Cancelled"}:
                self.add_job(job.url)

    def clear_finished(self) -> None:
        for jid in [j for j, job in self.jobs.items()
                    if job.status in {"Done", "Cancelled"}]:
            item = self.items.pop(jid, None)
            if item:
                self.queue.takeItem(self.queue.row(item))
            self.jobs.pop(jid, None)
        self._sync_empty()

    def _open_item_file(self, item: QListWidgetItem) -> None:
        job = self.jobs.get(item.data(Qt.UserRole + 1))
        if job and job.filepath and Path(job.filepath).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(job.filepath))

    def _sync_empty(self) -> None:
        self.empty.setVisible(self.queue.count() == 0)
        self.empty.setGeometry(self.queue.rect())

    # -- engine -------------------------------------------------------------- #

    def _maybe_auto_update(self) -> None:
        if updater.UpdaterState.load().due():
            self._append_update_log("Weekly check is due.")
            self._run_update(force=False)

    def _run_update(self, *, force: bool = False, verify_only: bool = False) -> None:
        self.btn_update.setEnabled(False)
        self.btn_verify.setEnabled(False)
        self.badge.set_state("busy", self.lbl_version.text(), "checking")
        self._status("Checking the engine")

        task = UpdateTask(force=force, verify_only=verify_only,
                          channel=self.channel.currentText())
        task.signals.progress.connect(self._append_update_log)
        task.signals.done.connect(self._on_update_done)
        self.tasks.start(task)

    @Slot(object)
    def _on_update_done(self, outcome) -> None:
        self.btn_update.setEnabled(True)
        self.btn_verify.setEnabled(True)
        self._append_update_log(f"{outcome.action.upper()}: {outcome.message}")
        self._refresh_engine()
        self._status(outcome.message.split(".")[0])

        if outcome.action == "rolled-back":
            QMessageBox.warning(
                self, "Update rolled back",
                f"{outcome.message}\n\nThe previous working version is still in "
                "place, so downloads keep working. The next check tries again.")
        elif outcome.action == "blocked":
            self._python_dialog(outcome.message)
        elif outcome.action == "updated" and outcome.from_version:
            QMessageBox.information(
                self, "Engine updated",
                f"{outcome.message}\n\nRestart Ambaar to load it.")

    def _refresh_engine(self) -> None:
        state = updater.UpdaterState.load()
        version = state.installed_version or updater.installed_version() or "unknown"
        self.lbl_version.setText(version)
        self.lbl_source.setText(engine_source())

        if state.last_check:
            try:
                dt = datetime.fromisoformat(state.last_check)
                self.lbl_checked.setText(dt.astimezone().strftime("%Y-%m-%d %H:%M"))
            except ValueError:
                self.lbl_checked.setText(state.last_check)
        else:
            self.lbl_checked.setText("never")

        if state.last_probe_ok is None:
            self.lbl_health.setText("not yet verified")
            self.lbl_health.setProperty("state", "")
            self.badge.set_state("unknown", version, "not verified")
        elif state.last_probe_ok:
            self.lbl_health.setText(f"passing: {_clip(state.last_probe_detail)}")
            self.lbl_health.setProperty("state", "ok")
            self.badge.set_state("ok", version, "verified working")
        else:
            self.lbl_health.setText(f"failing: {_clip(state.last_probe_detail)}")
            self.lbl_health.setProperty("state", "bad")
            self.badge.set_state("bad", version, "verification failing")
        self.lbl_health.setToolTip(state.last_probe_detail or "")
        self.lbl_health.setStyle(self.lbl_health.style())
        self._refresh_ffmpeg()
        self._refresh_deno()

    def _refresh_ffmpeg(self) -> None:
        if ffmpeg_tool.available():
            self.lbl_ffmpeg.setText(f"installed: {ffmpeg_tool.location_hint()}")
            self.lbl_ffmpeg.setProperty("state", "ok")
            self.btn_ffmpeg.setText("Reinstall ffmpeg")
        else:
            self.lbl_ffmpeg.setText("not found. Downloads above 360p will fall "
                                    "back to a low-quality single stream.")
            self.lbl_ffmpeg.setProperty("state", "bad")
            self.btn_ffmpeg.setText("Install ffmpeg")
        self.lbl_ffmpeg.setStyle(self.lbl_ffmpeg.style())

    def _install_ffmpeg(self) -> None:
        if not ffmpeg_tool.can_fetch():
            QMessageBox.information(
                self, "Install ffmpeg",
                "No automatic download is available for this platform.\n\n"
                f"Install it with:\n\n    {ffmpeg_tool.install_instructions()}")
            return
        self.btn_ffmpeg.setEnabled(False)
        self._show_page(2, sync_nav=True)
        task = ToolTask(ffmpeg_tool, "ffmpeg")
        task.signals.progress.connect(self._append_update_log)
        task.signals.done.connect(self._on_tool_done)
        self.tasks.start(task)

    def _install_deno(self) -> None:
        if not jsruntime.can_fetch():
            QMessageBox.information(
                self, "Install a JavaScript runtime",
                "No automatic download is available for this platform.\n\n"
                f"Install it with:\n\n    {jsruntime.install_instructions()}")
            return
        self.btn_deno.setEnabled(False)
        self._show_page(2, sync_nav=True)
        task = ToolTask(jsruntime, "deno")
        task.signals.progress.connect(self._append_update_log)
        task.signals.done.connect(self._on_tool_done)
        self.tasks.start(task)

    @Slot(object)
    def _on_tool_done(self, result) -> None:
        ok, message, name = result
        self.btn_ffmpeg.setEnabled(True)
        self.btn_deno.setEnabled(True)
        self._append_update_log(message)
        self._refresh_ffmpeg()
        self._refresh_deno()
        self._status(message if ok else f"{name} install failed")
        if not ok:
            QMessageBox.warning(self, name, message)

    def _refresh_deno(self) -> None:
        if jsruntime.available():
            v = jsruntime.version() or "installed"
            self.lbl_deno.setText(f"installed: {v}")
            self.lbl_deno.setProperty("state", "ok")
            self.btn_deno.setText("Reinstall runtime")
        else:
            self.lbl_deno.setText(
                "not found. yt-dlp cannot solve YouTube's nsig challenge without "
                "one, so some higher-quality formats will be missing.")
            self.lbl_deno.setProperty("state", "warn")
            self.btn_deno.setText("Install runtime")
        self.lbl_deno.setStyle(self.lbl_deno.style())

    # -- first run ----------------------------------------------------------- #

    def _first_run_checks(self) -> None:
        problem = updater.python_problem()
        if problem:
            self._python_dialog(problem)
            return
        if not ffmpeg_tool.available():
            reply = QMessageBox.question(
                self, "ffmpeg is required",
                "ffmpeg was not found.\n\nYouTube serves video and audio as "
                "separate streams above 360p, so without it every download "
                "quietly falls back to a low-quality single stream.\n\n"
                "Download and install it now?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                self._install_ffmpeg()
                return

        if not jsruntime.available() and jsruntime.can_fetch():
            reply = QMessageBox.question(
                self, "JavaScript runtime recommended",
                "No JavaScript runtime was found.\n\nYouTube hides its format "
                "URLs behind a JavaScript challenge. Without a runtime, some "
                "higher-quality formats will silently never appear.\n\n"
                "Download Deno now? It is about 40 MB.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                self._install_deno()

    def _python_dialog(self, problem: str) -> None:
        need = ".".join(str(x) for x in updater.MIN_PYTHON)
        if sys.platform == "win32":
            steps = (f"    rmdir /s /q .venv\n"
                     f"    py -{need} -m venv .venv\n"
                     f"    .venv\\Scripts\\activate\n"
                     f"    pip install -r requirements.txt\n\n"
                     f"In Git Bash:  source .venv/Scripts/activate\n"
                     f"Open a new terminal first. An installer's PATH changes "
                     f"do not reach a shell that was already running.")
        else:
            steps = (f"    rm -rf .venv\n"
                     f"    python{need} -m venv .venv\n"
                     f"    source .venv/bin/activate\n"
                     f"    pip install -r requirements.txt")
        QMessageBox.critical(
            self, "Unsupported Python version",
            f"{problem}\n\nRebuild the environment:\n\n{steps}\n\n"
            f"Updating the engine will not help until this is fixed.")

    # -- misc ---------------------------------------------------------------- #

    def _append_log(self, line: str) -> None:
        self.log_view.append(line)

    def _append_update_log(self, line: str) -> None:
        self.update_log.append(line)

    def _status(self, text: str) -> None:
        self.statusBar().showMessage(text, 9000)

    def closeEvent(self, event) -> None:
        active = [j for j in self.jobs.values() if j.status in ACTIVE]
        if active:
            reply = QMessageBox.question(
                self, "Downloads in progress",
                f"{len(active)} download(s) still running. Quit anyway?\n\n"
                "Partial files are kept and resume if you add the link again.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        self.manager.cancel_all()
        self._save()
        event.accept()


# --------------------------------------------------------------------------- #

def main() -> int:
    # Must precede QApplication and any window. Windows groups taskbar buttons
    # by AppUserModelID, so without this the shell treats the process as Python
    # and draws the Python icon no matter what setWindowIcon says.
    branding.set_windows_app_id()

    app = QApplication(sys.argv)
    app.setApplicationName("Ambaar")
    app.setApplicationDisplayName("Ambaar")
    app.setOrganizationName("ambaar")
    app.setDesktopFileName("ambaar")   # Linux: matches the .desktop entry
    # Fusion gives the stylesheet a predictable base on every platform; the
    # native styles ignore several of the properties used here.
    app.setStyle("Fusion")

    theme.load_fonts()
    theme.apply_palette(app)
    app.setStyleSheet(theme.stylesheet())
    branding.apply(app)

    window = MainWindow()
    window.show()
    window._sync_empty()

    # CI launches the packaged binary with this set. Starting the GUI is the
    # only way to prove Qt actually loaded inside the bundle -- a failure there
    # is invisible to every build-time check.
    if os.environ.get("AMBAAR_SELFTEST") == "1":
        QTimer.singleShot(1200, app.quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
