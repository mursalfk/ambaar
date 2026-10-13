# ambaar/app.py
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
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMenu, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QStatusBar,
    QSystemTrayIcon, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import branding
from . import ffmpeg as ffmpeg_tool
from . import jsruntime, links, space
from . import theme, updater
from .bootstrap import engine_source
from . import engine
from .formatdialog import FormatDialog
from .historypage import HistoryPage, when
from .itemsdialog import ItemsDialog
from .logdialog import LogDialog
from .store import QueueStore, discard_incomplete
from .engine import QUALITY_MAP, DownloadManager, Job, Settings
from .paths import data_dir
from .widgets import (ROW_HEIGHT, ComboBox, EmptyState, EngineBadge, JobDelegate,
                      OfferBar, SpinBox, key_action)

BROWSERS = ["", "chrome", "firefox", "edge", "safari", "brave", "chromium", "opera", "vivaldi"]
# Busy states come from the engine so the UI and the workers cannot disagree.
ACTIVE = engine.BUSY | {"Cancelling"}
SECTIONS = ["Queue", "History", "Settings", "Engine", "Activity"]


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

def row_tag(job: Job) -> str:
    """The bracketed tag on a row: its format choice and any folder override."""
    bits = [engine.describe_format(job.fmt)]
    if job.dest:
        bits.append(f"to {Path(job.dest).name or job.dest}")
    return ", ".join(b for b in bits if b)


def _clip(text: str, limit: int = 190) -> str:
    """Keep a diagnostic readable in a fixed row. Full text goes in the tooltip."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _parse_speed(text: str) -> float:
    """
    Turn a display speed such as "4.2 MB/s" back into bytes per second.

    Reads the formatted string rather than tracking a parallel raw value: one
    number, one place it is set, no chance of the two disagreeing.
    """
    if not text or text == "--":
        return 0.0
    units = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
    parts = text.replace("/s", "").strip().split()
    if len(parts) != 2:
        return 0.0
    try:
        return float(parts[0]) * units.get(parts[1].upper(), 0)
    except ValueError:
        return 0.0


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

        self.store = QueueStore()
        self.tray: QSystemTrayIcon | None = None
        self._retry_timers: dict[str, QTimer] = {}
        self._last_offered = ""

        self.setWindowTitle("Ambaar")
        self.setWindowIcon(branding.app_icon())
        self.resize(1120, 720)
        self.setMinimumSize(QSize(900, 560))

        self._build_menu()
        self._build_ui()
        self._refresh_engine()

        QGuiApplication.clipboard().dataChanged.connect(self._on_clipboard)

        QTimer.singleShot(0, self._restore_queue)
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

        mq = self.menuBar().addMenu("&Queue")
        for text, keys, fn in (
            ("Add link from clipboard", "Ctrl+Shift+V", self.paste_and_add),
            ("Focus the link bar", "Ctrl+L", self._focus_url),
            ("Download all", "Ctrl+Shift+D", self.start_all_ready),
            ("Pause all", "Ctrl+Shift+P", self.pause_all),
            ("Resume all", "Ctrl+Shift+R", self.resume_all),
        ):
            a = QAction(text, self)
            a.setShortcut(QKeySequence(keys))
            a.triggered.connect(lambda _=False, f=fn: f())
            mq.addAction(a)
        mq.addSeparator()
        for i, name in enumerate(SECTIONS):
            a = QAction(f"Go to {name}", self)
            a.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            a.triggered.connect(lambda _=False, n=i: self._show_page(n, sync_nav=True))
            mq.addAction(a)

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
        self.history_page = HistoryPage(self.store)
        self.history_page.open_file.connect(self._open_history_file)
        self.history_page.open_folder.connect(self._open_history_folder)
        self.history_page.add_again.connect(self._add_from_history)
        self.stack.addWidget(self.history_page)
        self.stack.addWidget(self._page_settings())
        self.stack.addWidget(self._page_engine())
        self.stack.addWidget(self._page_activity())
        col.addWidget(self.stack, 1)

        outer.addWidget(right, 1)
        self.setCentralWidget(shell)
        self.setStatusBar(QStatusBar())
        # Permanent widget, so a transient status message never wipes the
        # running totals the user is watching.
        self.totals = label("", "mono")
        self.statusBar().addPermanentWidget(self.totals)
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
        self.badge.clicked.connect(
            lambda: self._show_page(SECTIONS.index("Engine"), sync_nav=True))
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

        self.btn_start = QPushButton("Download all")
        self.btn_pause_all = QPushButton("Pause all")
        self.btn_resume_all = QPushButton("Resume all")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_retry = QPushButton("Retry")
        self.btn_clear = QPushButton("Clear finished")
        self.btn_clear_all = QPushButton("Clear queue")
        for b, fn in ((self.btn_start, self.start_all_ready),
                      (self.btn_pause_all, self.pause_all),
                      (self.btn_resume_all, self.resume_all),
                      (self.btn_cancel, self.cancel_selected),
                      (self.btn_retry, self.retry_selected),
                      (self.btn_clear, self.clear_finished),
                      (self.btn_clear_all, self.clear_queue)):
            b.setProperty("variant", "ghost")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            lay.addWidget(b)
        self.btn_start.setProperty("variant", "primary")
        self.queue_actions = [self.btn_start, self.btn_pause_all, self.btn_resume_all,
                              self.btn_cancel, self.btn_retry,
                              self.btn_clear, self.btn_clear_all]
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
        lay.setSpacing(0)

        self.offer = OfferBar()
        self.offer.accepted.connect(self._add_offered)
        lay.addWidget(self.offer)

        self.queue = QListWidget()
        self._delegate = JobDelegate(self.queue)
        self._delegate.action.connect(self._on_row_action)
        self.queue.setItemDelegate(self._delegate)
        self.queue.setSelectionMode(QListWidget.ExtendedSelection)
        self.queue.setMouseTracking(True)
        self.queue.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.queue.setFrameShape(QFrame.NoFrame)
        self.queue.setUniformItemSizes(True)
        self.queue.itemDoubleClicked.connect(self._open_item_file)
        self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self._queue_menu)
        # Dragging rows reorders the queue. Order decides what "Download all"
        # starts first and is saved with the queue.
        self.queue.setDragDropMode(QListWidget.InternalMove)
        self.queue.setDefaultDropAction(Qt.MoveAction)
        self.queue.model().rowsMoved.connect(self._on_rows_moved)
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
        self.container.addItems(engine.CONTAINERS)
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
        self.audio_format.addItems(engine.AUDIO_FORMATS)
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

        self.restore_queue = QCheckBox("Restore the queue when Ambaar starts")
        self.restore_queue.setChecked(self.settings.restore_queue)
        self.restore_queue.toggled.connect(self._save)
        f4.addRow("", self.restore_queue)

        self.watch = QCheckBox("Offer to add video links I copy")
        self.watch.setChecked(self.settings.watch_clipboard)
        self.watch.toggled.connect(self._save)
        f4.addRow("", self.watch)

        self.retries = SpinBox()
        self.retries.setRange(0, 10)
        self.retries.setValue(self.settings.auto_retry)
        self.retries.valueChanged.connect(self._save)
        f4.addRow("Automatic retries", row(self.retries))
        hint2 = label("Network failures are retried after 15 s, 1 min, then 5 min. "
                      "0 turns it off.", "hint")
        hint2.setWordWrap(True)
        f4.addRow("", hint2)

        self.notify = QCheckBox("Notify me when a download finishes")
        self.notify.setChecked(self.settings.notify_on_finish)
        self.notify.toggled.connect(self._save)
        f4.addRow("", self.notify)
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
        if SECTIONS[index] == "History":
            self.history_page.refresh()
        if sync_nav:
            button = self.nav.button(index)
            if button:
                button.setChecked(True)

    def eventFilter(self, obj, event):
        if obj is self.queue:
            if event.type() in (QEvent.Resize, QEvent.Show):
                self.empty.setGeometry(self.queue.rect())
            elif event.type() == QEvent.KeyPress and self._queue_key(event):
                return True
        return super().eventFilter(obj, event)

    def _queue_key(self, event) -> bool:
        """Keyboard control of the queue. True when the key was handled."""
        if event.matches(QKeySequence.Paste):
            self.paste_and_add()
            return True
        ids = self._selected_ids()
        if not ids:
            return False
        handled = False
        for jid in ids:
            job = self.jobs.get(jid)
            action = key_action(event.key(), job.status) if job else None
            if action:
                self._on_row_action(jid, action)
                handled = True
        return handled

    def _focus_url(self) -> None:
        self._show_page(0, sync_nav=True)
        self.url_input.setFocus()
        self.url_input.selectAll()

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
        s.restore_queue = self.restore_queue.isChecked()
        s.notify_on_finish = self.notify.isChecked()
        s.watch_clipboard = self.watch.isChecked()
        s.auto_retry = self.retries.value()
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
            if self._confirm_duplicate(url):
                self.add_job(url)
        self._show_page(0, sync_nav=True)

    # -- duplicates and the clipboard ---------------------------------------- #

    def _duplicate_reason(self, url: str) -> str:
        """Why this link is a repeat, or "" when it is new."""
        twin = links.find_duplicate(url, self.jobs.values())
        if twin is not None:
            return f"It is already in the queue as \u201c{twin.title or twin.url}\u201d."
        if self.settings.archive_enabled and links.archive_has(
                url, Path.home() / ".ambaar" / "archive.txt"):
            return ("Your download archive lists it as downloaded, so the engine "
                    "will skip it.")
        past = self.store.history_find(url)
        if past:
            return (f"You downloaded \u201c{past['title']}\u201d on "
                    f"{when(past['finished_at']).split('  ')[0]}.")
        return ""

    def _confirm_duplicate(self, url: str) -> bool:
        reason = self._duplicate_reason(url)
        if not reason:
            return True
        reply = QMessageBox.question(
            self, "Already added", f"{reason}\n\nAdd it again?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return reply == QMessageBox.Yes

    def _on_clipboard(self) -> None:
        if not self.settings.watch_clipboard:
            return
        text = QGuiApplication.clipboard().text().strip()
        if not links.is_clipboard_candidate(text) or text == self._last_offered:
            return
        self._last_offered = text
        # A repeat is not worth interrupting for; the user can still paste it by
        # hand and will be asked then.
        if self._duplicate_reason(text):
            return
        self.offer.show_offer(text)

    def _add_offered(self, url: str) -> None:
        self.add_job(url)
        self._show_page(0, sync_nav=True)

    def _add_from_history(self, url: str) -> None:
        self.add_job(url)
        self._show_page(0, sync_nav=True)

    def add_job(self, url: str) -> None:
        """
        Stage a link and resolve it. Nothing downloads yet.

        Adding used to start a download immediately, which meant a mistyped or
        dead link only announced itself after the queue had already committed a
        thread to it. Resolving first costs a second and tells the user what
        they actually pasted.
        """
        self._save()
        job = Job(url=url, title=url, status=engine.STAGED)
        self.jobs[job.job_id] = job

        item = QListWidgetItem()
        item.setSizeHint(QSize(0, ROW_HEIGHT))
        item.setData(Qt.UserRole, self._job_data(job))
        item.setData(Qt.UserRole + 1, job.job_id)
        self.queue.addItem(item)
        self.items[job.job_id] = item
        self._sync_empty()

        self._resolve(job)

    def _resolve(self, job: Job) -> None:
        """Start classification for one job. Used on add and on restore."""
        job.status = engine.RESOLVING
        self._refresh(job.job_id)
        self._persist(job.job_id)

        resolver = self.manager.resolve(job)
        resolver.signals.resolved.connect(self._on_resolved)
        resolver.signals.failed.connect(self._on_resolve_failed)
        resolver.signals.cancelled.connect(self._on_cancelled)
        resolver.signals.log.connect(self._on_job_log)

    def start_download(self, job_id: str, check_space: bool = True) -> None:
        """Move a Ready, Paused or finished job into the download pool."""
        job = self.jobs.get(job_id)
        if job is None or job.status not in engine.STARTABLE:
            return
        if check_space and not self._space_ok([job]):
            return

        self._save()
        job.status = engine.QUEUED
        job.error = ""
        self._refresh(job_id)
        self._persist(job_id)
        self._update_totals()

        worker = self.manager.submit(job, list(self.jobs).index(job_id))
        s = worker.signals
        s.status.connect(self._on_status)
        s.progress.connect(self._on_progress)
        s.finished.connect(self._on_finished)
        s.failed.connect(self._on_failed)
        s.cancelled.connect(self._on_cancelled)
        s.paused.connect(self._on_paused)
        s.log.connect(self._on_job_log)

    @Slot(str, str)
    def _on_row_action(self, job_id: str, action: str) -> None:
        """Every inline button arrives here. One place, so states cannot drift."""
        job = self.jobs.get(job_id)
        if job is None:
            return

        if action in ("download", "resume", "retry"):
            job.attempts = 0
            self.start_download(job_id)
        elif action == "open":
            item = self.items.get(job_id)
            if item is not None:
                self._open_item_file(item)
        elif action == "pause":
            self.manager.pause(job_id)
            self._status("Pausing after the current chunk")
        elif action == "cancel":
            self._cancel_job(job_id)
        elif action == "format":
            self._choose_format(job_id)
        elif action == "items":
            self._choose_items(job_id)
        elif action == "remove":
            self._remove_job(job_id)
        elif action == "folder":
            self._open_folder(job)

    def _choose_format(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is None or job.status != engine.READY:
            return
        avail = space.available_formats(job.sizes) if not job.is_playlist() else ([], [])
        dlg = FormatDialog(job.title or job.url, job.fmt, self.settings, avail,
                           job.dest, self)
        if dlg.exec() != FormatDialog.Accepted:
            return
        job.fmt, job.dest = dlg.choice, dlg.dest
        self._refresh(job_id)
        self._persist(job_id)

    def _choose_items(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is None or job.status != engine.READY or not job.is_playlist():
            return
        entries = engine.unpack_entries(job.entries)
        if not entries:
            self._status("This playlist's contents were not saved; remove it and add it again")
            return
        dlg = ItemsDialog(job.title, entries, engine.selected_positions(job), self)
        if dlg.exec() != ItemsDialog.Accepted:
            return
        job.items = dlg.spec
        self._refresh(job_id)
        self._persist(job_id)

    # -- persistence ---------------------------------------------------------- #

    def _persist(self, job_id: str) -> None:
        """Write one job back to disk. Called on every state change."""
        job = self.jobs.get(job_id)
        if job is None or not self.store.available:
            return
        position = list(self.jobs).index(job_id) if job_id in self.jobs else 0
        self.store.save(job, position)

    def _restore_queue(self) -> None:
        """
        Put back whatever the last session left behind.

        Jobs that were mid-flight come back Paused rather than Downloading --
        their worker died with the process -- so the user chooses when to pick
        them up again. Ones that never finished resolving resolve again now.
        """
        if not self.settings.restore_queue or not self.store.available:
            return

        restored = discard_incomplete(self.store.load())
        if not restored:
            return

        for job in restored:
            self.jobs[job.job_id] = job
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, ROW_HEIGHT))
            item.setData(Qt.UserRole, self._job_data(job))
            item.setData(Qt.UserRole + 1, job.job_id)
            self.queue.addItem(item)
            self.items[job.job_id] = item

        self._sync_empty()
        self.store.save_all(list(self.jobs.values()))

        # Anything that never got classified needs resolving before it can show
        # a Download button.
        for job in restored:
            if job.status == engine.STAGED:
                self._resolve(job)

        paused = sum(1 for j in restored if j.status == engine.PAUSED)
        tail = f", {paused} paused mid-download" if paused else ""
        self._status(f"Restored {len(restored)} item(s) from last session{tail}")

    # -- bulk actions ---------------------------------------------------------- #

    def pause_all(self) -> None:
        running = [j for j in self.jobs.values() if j.status == engine.DOWNLOADING]
        if not running:
            self._status("Nothing is downloading.")
            return
        self.manager.pause_all()
        self._status(f"Pausing {len(running)} download(s)")

    def resume_all(self) -> None:
        paused = [jid for jid, j in self.jobs.items() if j.status == engine.PAUSED]
        self._start_many(paused)
        self._status(f"Resuming {len(paused)} download(s)" if paused
                     else "Nothing is paused.")

    def _update_totals(self) -> None:
        """
        Aggregate speed and remaining work, shown in the status bar.

        Per-row numbers answer "how is this one doing"; this answers "can I walk
        away yet", which is the question a long queue actually raises.
        """
        running = [j for j in self.jobs.values()
                   if j.status in (engine.DOWNLOADING, engine.PROCESSING)]
        ready = sum(1 for j in self.jobs.values() if j.status == engine.READY)
        paused = sum(1 for j in self.jobs.values() if j.status == engine.PAUSED)
        done = sum(1 for j in self.jobs.values() if j.status == engine.DONE)

        bits = []
        if running:
            total = 0.0
            for job in running:
                # job.speed is already formatted for display, so parse it back
                # rather than keeping a second raw copy in sync.
                total += _parse_speed(job.speed)
            bits.append(f"{len(running)} running")
            if total > 0:
                bits.append(f"{engine.human_bytes(total)}/s total")
        if ready:
            bits.append(f"{ready} ready")
        if paused:
            bits.append(f"{paused} paused")
        if done:
            bits.append(f"{done} done")

        self.totals.setText("   ".join(bits) if bits else "")

    # -- notifications --------------------------------------------------------- #

    def _ensure_tray(self) -> QSystemTrayIcon | None:
        """
        Lazily create the tray icon used for completion notices.

        Created on demand rather than at startup: on a desktop with no system
        tray, constructing one early puts a permanently dead icon in the
        session for no benefit.
        """
        if self.tray is not None:
            return self.tray
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        icon = branding.app_icon()
        self.tray = QSystemTrayIcon(icon if not icon.isNull() else QIcon(), self)
        self.tray.setToolTip("Ambaar")
        self.tray.show()
        return self.tray

    def _notify(self, title: str, body: str) -> None:
        if not self.settings.notify_on_finish:
            return
        tray = self._ensure_tray()
        if tray is not None:
            tray.showMessage(title, body, QSystemTrayIcon.Information, 6000)

    def start_all_ready(self) -> None:
        self._start_many([jid for jid, j in self.jobs.items()
                          if j.status == engine.READY])

    def _start_many(self, job_ids: list[str]) -> None:
        """Start a batch behind one space question rather than one per row."""
        jobs = [self.jobs[j] for j in job_ids if j in self.jobs]
        if not jobs or not self._space_ok(jobs):
            return
        for job in jobs:
            self.start_download(job.job_id, check_space=False)

    def _space_ok(self, jobs: list[Job]) -> bool:
        """
        Check the output drive has room, and ask before going ahead if not.

        A shortfall is a question rather than a refusal: the estimates are
        approximate, and a user who knows better (a second drive mounted at the
        folder, a quota that is not the real limit) should not be locked out.
        """
        # Each distinct folder is its own drive as far as we can tell, so tally
        # what is headed for each and check them separately.
        per_dir: dict[str, int] = {}
        for j in jobs:
            d = engine.output_dir_for(j, self.settings)
            per_dir[d] = per_dir.get(d, 0) + engine.estimate_job_bytes(j, self.settings)

        for folder, needed in per_dir.items():
            free = space.free_bytes(folder)
            if not space.shortfall(needed, free):
                continue
            if needed:
                detail = (f"These downloads need about {engine.human_bytes(needed)} "
                          f"and {engine.human_bytes(free)} is free.")
            else:
                detail = f"Only {engine.human_bytes(free)} is free."
            reply = QMessageBox.warning(
                self, "Low disk space",
                f"{detail}\n\nThe drive holding {folder} may fill "
                "up mid-download. Partial files are kept, so a stopped download "
                "resumes once there is room.\n\nDownload anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return False
        return True

    @staticmethod
    def _job_data(job: Job) -> dict:
        # For a playlist the row describes what will download, not the whole list.
        selected, duration = None, job.duration
        if job.is_playlist():
            selected, _, duration = engine.selection_summary(job)
        return {"url": job.url, "title": job.title, "status": job.status,
                "kind": job.kind, "item_count": job.item_count,
                "selected": selected,
                "duration": duration, "uploader": job.uploader,
                "thumb": job.thumb, "fmt_label": row_tag(job),
                "percent": job.percent, "speed": job.speed, "eta": job.eta,
                "size": job.size, "error": job.error}

    def _refresh(self, job_id: str) -> None:
        item = self.items.get(job_id)
        if item:
            item.setData(Qt.UserRole, self._job_data(self.jobs[job_id]))

    # -- resolve results ------------------------------------------------------ #

    @Slot(str, dict)
    def _on_resolved(self, job_id: str, facts: dict) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        job.kind = facts.get("kind", engine.KIND_UNKNOWN)
        job.title = facts.get("title") or job.url
        job.item_count = int(facts.get("item_count") or 0)
        job.duration = int(facts.get("duration") or 0)
        job.uploader = facts.get("uploader") or ""
        job.status = engine.READY
        job.thumb = facts.get("thumb") or ""
        job.entries = facts.get("entries") or ""
        job.sizes = facts.get("sizes") or ""
        self._refresh(job_id)
        self._persist(job_id)
        self._update_totals()
        self.manager.release_resolver(job_id)

        what = "Playlist" if job.is_playlist() else "Video"
        self._status(f"{what} ready: {job.title}")

    @Slot(str, str)
    def _on_resolve_failed(self, job_id: str, error: str) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        job.status, job.error = engine.FAILED, error
        self._refresh(job_id)
        self._persist(job_id)
        self._update_totals()
        self.manager.release_resolver(job_id)
        self._append_log(f"COULD NOT RESOLVE  {job.url}\n{error}\n")
        self._status("That link could not be read. See Activity.")

    # -- download results ----------------------------------------------------- #

    @Slot(str, str)
    def _on_status(self, job_id: str, status: str) -> None:
        self.jobs[job_id].status = status
        self._refresh(job_id)

    @Slot(str, float, str, str, str)
    def _on_progress(self, job_id: str, pct: float, speed: str, eta: str, size: str) -> None:
        job = self.jobs[job_id]
        job.percent, job.speed, job.eta, job.size = pct, speed, eta, size
        self._refresh(job_id)
        self._update_totals()
        # Persisted on whole-percent steps only: writing on every callback would
        # mean a disk write several times a second per download for no gain.
        if int(pct) != int(getattr(job, "_last_saved_pct", -1)):
            job._last_saved_pct = pct
            self._persist(job_id)

    @Slot(str, str)
    def _on_finished(self, job_id: str, path: str) -> None:
        job = self.jobs[job_id]
        job.status, job.filepath, job.percent = engine.DONE, path, 100.0
        job.folder = str(Path(path).parent) if path else self.settings.output_dir
        job.speed = job.eta = ""
        job.redo, job.attempts = False, 0
        self._refresh(job_id)
        self._persist(job_id)
        self.store.add_history(job)
        self._update_totals()
        self.manager.release(job_id)
        self._status(f"Finished: {job.title or job.url}")
        self._notify("Download finished", job.title or job.url)

    @Slot(str, str)
    def _on_failed(self, job_id: str, error: str) -> None:
        job = self.jobs[job_id]
        engine.append_log(job, f"FAILED: {error}")
        if self._schedule_retry(job, error):
            return
        job.status, job.error = engine.FAILED, error
        job.speed = job.eta = ""
        self._refresh(job_id)
        self._persist(job_id)
        self._update_totals()
        self.manager.release(job_id)
        self._append_log(f"FAILED  {job.url}\n{error}\n")
        self._status("A download failed. See Activity for detail.")

    def _schedule_retry(self, job: Job, error: str) -> bool:
        """
        Wait out a transient failure and try again. True when a retry is set.

        The job sits in Queued with a countdown in its detail line, so the
        failure is visible rather than hidden, and Cancel works because it has
        a timer to stop.
        """
        limit = self.settings.auto_retry
        if not engine.should_retry(error, job.attempts, limit):
            return False
        job.attempts += 1
        delay = engine.retry_delay(job.attempts)
        reason = error.strip().splitlines()[0][:80] if error.strip() else "network error"
        job.status = engine.QUEUED
        job.error = f"Retrying in {delay} s ({job.attempts} of {limit}): {reason}"
        job.speed = job.eta = ""
        engine.append_log(job, job.error)
        self._refresh(job.job_id)
        self._persist(job.job_id)
        self._update_totals()
        self.manager.release(job.job_id)

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda jid=job.job_id: self._fire_retry(jid))
        self._retry_timers[job.job_id] = timer
        timer.start(delay * 1000)
        return True

    def _fire_retry(self, job_id: str) -> None:
        self._stop_retry(job_id)
        job = self.jobs.get(job_id)
        if job is None or job.status != engine.QUEUED:
            return
        job.status, job.error = engine.READY, ""
        # The space question was answered when the download first started.
        self.start_download(job_id, check_space=False)

    @Slot(str)
    def _on_paused(self, job_id: str) -> None:
        job = self.jobs[job_id]
        job.status, job.speed, job.eta = engine.PAUSED, "", ""
        self._refresh(job_id)
        self._persist(job_id)
        self._update_totals()
        self.manager.release(job_id)
        self._status(f"Paused at {job.percent:.0f}% -- Resume picks up where it stopped")

    @Slot(str)
    def _on_cancelled(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        job.status, job.speed, job.eta = engine.CANCELLED, "", ""
        self._refresh(job_id)
        self._persist(job_id)
        self._update_totals()
        self.manager.release(job_id)
        self.manager.release_resolver(job_id)

    def _on_rows_moved(self, *_args) -> None:
        """Rebuild job order from the list after a drag, and save it."""
        order = [self.queue.item(r).data(Qt.UserRole + 1)
                 for r in range(self.queue.count())]
        self.jobs = {jid: self.jobs[jid] for jid in order if jid in self.jobs}
        # Rows already waiting for a download slot follow the new order too, so a
        # drag changes what runs next and not only what Download all starts.
        self.manager.apply_order(list(self.jobs))
        if self.store.available:
            self.store.save_all(list(self.jobs.values()))

    def _redownload(self, job_id: str) -> None:
        """Fetch a finished item again, replacing the file."""
        job = self.jobs.get(job_id)
        if job is None or job.status not in (engine.DONE, engine.FAILED,
                                             engine.CANCELLED):
            return
        job.redo, job.attempts = True, 0
        job.status, job.percent, job.error, job.filepath = engine.READY, 0.0, "", ""
        self._refresh(job_id)
        self.start_download(job_id)

    def _show_log(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is not None:
            LogDialog(job.title or job.url, job.log, job.error, self).exec()

    def _open_history_file(self, entry: dict) -> None:
        path = entry.get("filepath") or ""
        if entry.get("kind") != "playlist" and path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            self._open_history_folder(entry)

    def _open_history_folder(self, entry: dict) -> None:
        folder = entry.get("folder") or ""
        if folder and Path(folder).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            self._status("That folder no longer exists.")

    def _selected_ids(self) -> list[str]:
        return [i.data(Qt.UserRole + 1) for i in self.queue.selectedItems()]

    def cancel_selected(self) -> None:
        ids = self._selected_ids() or list(self.jobs)
        for jid in ids:
            job = self.jobs.get(jid)
            if job and job.status in ACTIVE:
                self._cancel_job(jid)

    def _cancel_job(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        # A job waiting out a retry delay has no worker to stop, only a timer.
        if self._stop_retry(job_id):
            job.status, job.error = engine.CANCELLED, ""
            self._refresh(job_id)
            self._persist(job_id)
            self._update_totals()
            return
        self.manager.cancel(job_id)
        job.status = "Cancelling"
        self._refresh(job_id)

    def _stop_retry(self, job_id: str) -> bool:
        timer = self._retry_timers.pop(job_id, None)
        if timer is None:
            return False
        timer.stop()
        timer.deleteLater()
        return True

    def retry_selected(self) -> None:
        """Restart in place rather than adding a second row for the same link."""
        self._start_many([jid for jid in self._selected_ids()
                          if self.jobs.get(jid)
                          and self.jobs[jid].status in engine.STARTABLE])

    def clear_finished(self) -> None:
        self._remove(set(engine.TERMINAL))

    def clear_queue(self) -> None:
        """Cancel everything in flight and empty the list."""
        active = [j for j in self.jobs.values() if j.status in ACTIVE]
        if active:
            reply = QMessageBox.question(
                self, "Clear the queue",
                f"{len(active)} job(s) are still running. Cancel them and clear "
                "the list?\n\nPartial files are kept, so adding a link again "
                "resumes rather than starting over.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self.manager.cancel_all()
        self.queue.clear()
        self.items.clear()
        self.jobs.clear()
        self.store.clear()
        self._sync_empty()
        self._update_totals()
        self._status("Queue cleared")

    def _remove(self, statuses: set[str]) -> None:
        for jid in [j for j, job in self.jobs.items() if job.status in statuses]:
            self._remove_job(jid)
        self._sync_empty()

    def _remove_job(self, job_id: str) -> None:
        """Drop one row, stopping its worker first if it is still running."""
        job = self.jobs.get(job_id)
        if job is None:
            return
        self._stop_retry(job_id)
        if job.status in ACTIVE:
            self.manager.cancel(job_id)
        item = self.items.pop(job_id, None)
        if item is not None:
            self.queue.takeItem(self.queue.row(item))
        self.jobs.pop(job_id, None)
        self.store.remove(job_id)
        self._sync_empty()
        self._update_totals()

    def remove_selected(self) -> None:
        for jid in self._selected_ids():
            self._remove_job(jid)

    def _open_folder(self, job: Job) -> None:
        folder = job.folder or str(Path(self.settings.output_dir).expanduser())
        if Path(folder).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            self._status("That folder no longer exists.")

    def _queue_menu(self, pos) -> None:
        """
        Right-click actions.

        The primary actions come from the same table the row buttons use, so
        the menu can never offer something the buttons do not, or miss one they
        do. Everything below the separator is menu-only: useful, but not worth
        a button on every row.
        """
        item = self.queue.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.queue.setCurrentItem(item)

        job = self.jobs.get(item.data(Qt.UserRole + 1))
        if job is None:
            return

        menu = QMenu(self)
        for action, label, _ in JobDelegate.buttons_for(job.status, job.kind):
            if action == "pause":
                label = "Pause (keeps the partial file)"
            act = menu.addAction(label)
            act.triggered.connect(
                lambda _=False, a=action, j=job.job_id: self._on_row_action(j, a))

        if job.status == engine.DONE and not job.is_playlist():
            a_play = menu.addAction("Play")
            a_play.triggered.connect(lambda: self._open_item_file(item))

        if job.status in (engine.DONE, engine.FAILED, engine.CANCELLED):
            a_again = menu.addAction("Download again")
            a_again.triggered.connect(lambda: self._redownload(job.job_id))

        menu.addSeparator()
        a_copy = menu.addAction("Copy link")
        a_copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(job.url))

        a_log = menu.addAction("View log")
        a_log.triggered.connect(lambda: self._show_log(job.job_id))

        if job.error:
            a_err = menu.addAction("Copy error")
            a_err.triggered.connect(lambda: QGuiApplication.clipboard().setText(job.error))

        if job.status not in ACTIVE:
            menu.addSeparator()
            a_rm = menu.addAction("Remove from list")
            a_rm.triggered.connect(self.remove_selected)

        menu.exec(self.queue.mapToGlobal(pos))

    def _open_item_file(self, item: QListWidgetItem) -> None:
        """
        Double-click opens the result the way the user expects it.

        A video plays in whatever the system uses for video. A playlist has no
        single file to play, so it opens the folder its episodes landed in.
        """
        job = self.jobs.get(item.data(Qt.UserRole + 1))
        if job is None:
            return

        if job.status != engine.DONE:
            if job.status == engine.READY:
                self.start_download(job.job_id)
            return

        if job.is_playlist():
            self._open_folder(job)
            return

        if job.filepath and Path(job.filepath).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(job.filepath))
        else:
            self._open_folder(job)

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

    @Slot(str, str)
    def _on_job_log(self, job_id: str, line: str) -> None:
        job = self.jobs.get(job_id)
        if job is not None:
            engine.append_log(job, line)
        self._append_log(line)

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
        # Save the list as it stands before the workers are torn down, so a
        # download interrupted by quitting comes back as Paused rather than
        # whatever it happened to be mid-write.
        if self.store.available:
            self.store.save_all(list(self.jobs.values()))
            self.store.close()
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
