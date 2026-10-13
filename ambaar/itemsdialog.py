# ambaar/itemsdialog.py
"""
Playlist item picker.

Opened from a Ready playlist row's Items button. Lists every video with a
checkbox so a 200-episode playlist can become "just episodes 12 to 20".
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import engine


class ItemsDialog(QDialog):
    def __init__(
        self,
        title: str,
        entries: list[dict],
        selected: set[int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Playlist items")
        self.resize(560, 520)
        self.spec = ""  # result; read after exec()
        self._entries = entries
        self._total = len(entries)

        col = QVBoxLayout(self)
        col.setContentsMargins(22, 20, 22, 20)
        col.setSpacing(14)

        heading = QLabel("Playlist items")
        heading.setProperty("role", "title")
        col.addWidget(heading)

        what = QLabel(title)
        what.setProperty("role", "hint")
        what.setWordWrap(True)
        col.addWidget(what)

        tools = QHBoxLayout()
        all_btn = QPushButton("Select all")
        all_btn.setProperty("variant", "ghost")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = QPushButton("Select none")
        none_btn.setProperty("variant", "ghost")
        none_btn.clicked.connect(lambda: self._set_all(False))
        self.summary = QLabel("")
        self.summary.setProperty("role", "mono")
        tools.addWidget(all_btn)
        tools.addWidget(none_btn)
        tools.addStretch(1)
        tools.addWidget(self.summary)
        col.addLayout(tools)

        self.list = QListWidget()
        # Rows need air around the checkbox; the global list style is tuned for
        # the queue, whose rows are painted by a delegate and have no padding.
        self.list.setStyleSheet(
            "QListWidget::item { padding: 6px 8px; }"
            "QListWidget::indicator { width: 14px; height: 14px; }"
        )
        width = len(str(max((e["i"] for e in entries), default=1)))
        for e in entries:
            dur = engine.human_duration(e["d"])
            text = f"{e['i']:>{width}}   {e['t'] or '(untitled)'}"
            if dur:
                text += f"   [{dur}]"
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if e["i"] in selected else Qt.Unchecked)
            item.setData(Qt.UserRole, e["i"])
            self.list.addItem(item)
        self.list.itemChanged.connect(lambda _i: self._refresh())
        col.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("variant", "ghost")
        cancel.clicked.connect(self.reject)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setProperty("variant", "primary")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self._apply)
        buttons.addWidget(cancel)
        buttons.addWidget(self.apply_btn)
        col.addLayout(buttons)

        self._refresh()

    def chosen(self) -> set[int]:
        return {
            self.list.item(r).data(Qt.UserRole)
            for r in range(self.list.count())
            if self.list.item(r).checkState() == Qt.Checked
        }

    def _set_all(self, on: bool) -> None:
        self.list.blockSignals(True)  # one refresh, not one per row
        state = Qt.Checked if on else Qt.Unchecked
        for r in range(self.list.count()):
            self.list.item(r).setCheckState(state)
        self.list.blockSignals(False)
        self._refresh()

    def _refresh(self) -> None:
        picked = self.chosen()
        secs = sum(e["d"] for e in self._entries if e["i"] in picked)
        dur = engine.human_duration(secs)
        self.summary.setText(
            f"{len(picked)} of {self._total} selected" + (f"   {dur}" if dur else "")
        )
        # Nothing selected would download nothing; make that impossible rather
        # than an error after the fact.
        self.apply_btn.setEnabled(bool(picked))

    def _apply(self) -> None:
        picked = self.chosen()
        # Every item chosen is the default state, so store "" and let the row
        # follow the playlist if it ever grows.
        self.spec = "" if len(picked) == self._total else engine.compress_items(picked)
        self.accept()
