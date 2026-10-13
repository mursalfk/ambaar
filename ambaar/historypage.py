# ambaar/historypage.py
"""
History: everything that finished, kept after the row leaves the queue.

The queue is for what is happening; this is for what happened. Searching it
answers "where did I put that lecture?" and "did I already get this?".
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from . import theme
from .store import QueueStore


def when(ts: float | None) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%d %b %Y  %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


class HistoryPage(QWidget):
    open_file = Signal(dict)       # entry
    open_folder = Signal(dict)
    add_again = Signal(str)        # url

    def __init__(self, store: QueueStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store

        col = QVBoxLayout(self)
        col.setContentsMargins(22, 18, 22, 18)
        col.setSpacing(12)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search finished downloads")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.refresh())
        col.addWidget(self.search)

        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        # The global list style makes selection invisible because the queue
        # paints its own; this list uses the stock delegate and needs it back.
        self.list.setStyleSheet(
            "QListWidget::item { padding: 8px 10px; border-bottom: 1px solid "
            f"{theme.c('line_soft').name()}; }}"
            f"QListWidget::item:selected {{ background: {theme.c('raised').name()}; }}")
        self.list.itemDoubleClicked.connect(lambda _i: self._emit(self.open_file))
        self.list.itemSelectionChanged.connect(self._sync)
        col.addWidget(self.list, 1)

        self.empty = QLabel("Nothing has finished yet.")
        self.empty.setProperty("role", "hint")
        self.empty.setAlignment(Qt.AlignCenter)
        col.addWidget(self.empty)

        bar = QHBoxLayout()
        self.b_open = QPushButton("Open")
        self.b_folder = QPushButton("Open folder")
        self.b_again = QPushButton("Add again")
        self.b_remove = QPushButton("Remove entry")
        self.b_clear = QPushButton("Clear history")
        for b in (self.b_open, self.b_folder, self.b_again, self.b_remove, self.b_clear):
            b.setProperty("variant", "ghost")
            bar.addWidget(b)
        bar.addStretch(1)
        col.addLayout(bar)

        self.b_open.clicked.connect(lambda: self._emit(self.open_file))
        self.b_folder.clicked.connect(lambda: self._emit(self.open_folder))
        self.b_again.clicked.connect(self._again)
        self.b_remove.clicked.connect(self._remove)
        self.b_clear.clicked.connect(self._clear)
        self.refresh()

    def refresh(self) -> None:
        keep = self._current_id()
        self.list.clear()
        entries = self.store.history(self.search.text())
        for e in entries:
            parts = [when(e["finished_at"]), e.get("size") or "",
                     Path(e["folder"]).name if e.get("folder") else ""]
            kind = "PLAYLIST  " if e.get("kind") == "playlist" else ""
            item = QListWidgetItem(
                f"{e['title'] or e['url']}\n{kind}{'   '.join(p for p in parts if p)}")
            item.setData(Qt.UserRole, e)
            item.setSizeHint(QSize(0, 56))
            self.list.addItem(item)
            if e["id"] == keep:
                self.list.setCurrentItem(item)
        self.empty.setVisible(not entries)
        self.empty.setText("No matches." if self.search.text().strip()
                           else "Nothing has finished yet.")
        self._sync()

    def _current(self) -> dict | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item and item.isSelected() else None

    def _current_id(self) -> int | None:
        e = self._current()
        return e["id"] if e else None

    def _sync(self) -> None:
        on = self._current() is not None
        for b in (self.b_open, self.b_folder, self.b_again, self.b_remove):
            b.setEnabled(on)
        self.b_clear.setEnabled(self.list.count() > 0)

    def _emit(self, signal) -> None:
        e = self._current()
        if e:
            signal.emit(e)

    def _again(self) -> None:
        e = self._current()
        if e:
            self.add_again.emit(e["url"])

    def _remove(self) -> None:
        e = self._current()
        if e:
            self.store.history_remove(e["id"])
            self.refresh()

    def _clear(self) -> None:
        reply = QMessageBox.question(
            self, "Clear history",
            "Remove every entry from the history?\n\nDownloaded files are not "
            "touched.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.store.history_clear()
            self.refresh()
