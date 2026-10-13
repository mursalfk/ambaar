# ambaar/logdialog.py
"""Per-item engine log. Opened from a row's context menu."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                               QTextEdit, QVBoxLayout, QWidget)


class LogDialog(QDialog):
    def __init__(self, title: str, lines: list[str], error: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Log")
        self.resize(720, 480)

        col = QVBoxLayout(self)
        col.setContentsMargins(22, 20, 22, 20)
        col.setSpacing(12)

        heading = QLabel("Log")
        heading.setProperty("role", "title")
        col.addWidget(heading)
        what = QLabel(title)
        what.setProperty("role", "hint")
        what.setWordWrap(True)
        col.addWidget(what)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        parts = list(lines)
        if error:
            parts += ["", "--- last error ---", error]
        self.view.setPlainText("\n".join(parts) if parts else
                               "Nothing was logged for this item in this session.")
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())
        col.addWidget(self.view, 1)

        buttons = QHBoxLayout()
        copy = QPushButton("Copy")
        copy.setProperty("variant", "ghost")
        copy.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.view.toPlainText()))
        close = QPushButton("Close")
        close.setProperty("variant", "primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        buttons.addWidget(close)
        col.addLayout(buttons)
