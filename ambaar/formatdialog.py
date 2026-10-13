# ambaar/formatdialog.py
"""
Per-item options: format and destination folder.

Opened from a Ready row's Options button. Everything here applies to that row
only; everything else keeps following Settings. "Use defaults" clears both.

The quality and codec lists are limited to what the video actually offers when
that is known, so the picker never promises a 4K stream the source lacks.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from . import engine
from .widgets import ComboBox


def qualities_for(heights: list[int]) -> list[str]:
    """
    Quality choices worth showing for a video offering `heights`.

    Quality is a ceiling, so a choice is useful when it is at or below the
    tallest stream, plus the first one above it (which just means "everything").
    Unknown availability shows every choice.
    """
    names = list(engine.QUALITY_MAP)
    if not heights:
        return names
    top = max(heights)
    out = ["Best available"]
    for name in names[1:]:
        cap = int(name.split("p")[0])
        if cap <= top:
            out.append(name)
    return out


class FormatDialog(QDialog):
    def __init__(self, title: str, choice: str, settings: engine.Settings,
                 avail: tuple[list[int], list[str]] = ([], []),
                 dest: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Options")
        self.setMinimumWidth(460)
        self.choice = choice          # results; read after exec()
        self.dest = dest
        heights, codecs = avail

        start = engine.decode_format(choice) or {
            "audio": settings.audio_only,
            "audio_format": settings.audio_format,
            "quality": settings.quality,
            "container": settings.container,
            "codec": "any",
        }

        col = QVBoxLayout(self)
        col.setContentsMargins(22, 20, 22, 20)
        col.setSpacing(16)

        heading = QLabel("Options")
        heading.setProperty("role", "title")
        col.addWidget(heading)

        what = QLabel(title)
        what.setProperty("role", "hint")
        what.setWordWrap(True)
        col.addWidget(what)

        form = QFormLayout()
        form.setSpacing(11)

        self.audio = QCheckBox("Extract audio only")
        self.audio.setChecked(bool(start.get("audio")))
        form.addRow("", self.audio)

        self.quality = ComboBox()
        self.quality.addItems(qualities_for(heights))
        want = start.get("quality", settings.quality)
        if self.quality.findText(want) < 0:
            want = "Best available"
        self.quality.setCurrentText(want)
        form.addRow("Quality", self.quality)

        self.codec = ComboBox()
        offered = ["any"] + [c for c in ("h264", "vp9", "av1") if c in codecs] \
            if codecs else list(engine.CODECS)
        for c in offered:
            self.codec.addItem(engine.CODEC_LABEL[c], c)
        idx = self.codec.findData(start.get("codec", "any"))
        self.codec.setCurrentIndex(max(0, idx))
        form.addRow("Codec", self.codec)

        self.container = ComboBox()
        self.container.addItems(engine.CONTAINERS)
        self.container.setCurrentText(start.get("container", settings.container))
        form.addRow("Container", self.container)

        self.audio_format = ComboBox()
        self.audio_format.addItems(engine.AUDIO_FORMATS)
        self.audio_format.setCurrentText(start.get("audio_format", settings.audio_format))
        form.addRow("Audio format", self.audio_format)

        self.folder = QLineEdit(dest)
        self.folder.setPlaceholderText(settings.output_dir)
        browse = QPushButton("Browse")
        browse.setProperty("variant", "ghost")
        browse.clicked.connect(self._browse)
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(self.folder, 1)
        h.addWidget(browse)
        form.addRow("Save to", box)
        col.addLayout(form)

        notes = []
        if heights:
            notes.append(f"This video offers up to {max(heights)}p.")
        notes.append("Quality is a ceiling. A codec is a preference: if the video "
                     "has no such stream, the best available is used.")
        note = QLabel(" ".join(notes))
        note.setProperty("role", "hint")
        note.setWordWrap(True)
        col.addWidget(note)

        buttons = QHBoxLayout()
        reset = QPushButton("Use defaults")
        reset.setProperty("variant", "ghost")
        reset.clicked.connect(self._use_defaults)
        cancel = QPushButton("Cancel")
        cancel.setProperty("variant", "ghost")
        cancel.clicked.connect(self.reject)
        apply_ = QPushButton("Apply")
        apply_.setProperty("variant", "primary")
        apply_.setDefault(True)
        apply_.clicked.connect(self._apply)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(apply_)
        col.addLayout(buttons)

        self.audio.toggled.connect(self._sync)
        self.codec.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        audio = self.audio.isChecked()
        self.quality.setEnabled(not audio)
        self.codec.setEnabled(not audio)
        self.container.setEnabled(not audio)
        self.audio_format.setEnabled(audio)
        # H.264 cannot live in webm; the engine would quietly switch to mkv, so
        # show that choice here rather than let the dialog disagree with it.
        if not audio and self.codec.currentData() == "h264" \
                and self.container.currentText() == "webm":
            self.container.setCurrentText("mkv")

    def _browse(self) -> None:
        start = self.folder.text().strip() or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "Save this download to", start)
        if d:
            self.folder.setText(d)

    def value(self) -> str:
        return engine.encode_format(
            self.audio.isChecked(),
            self.quality.currentText(),
            self.container.currentText(),
            self.audio_format.currentText(),
            self.codec.currentData() or "any")

    def _apply(self) -> None:
        self.choice = self.value()
        self.dest = self.folder.text().strip()
        self.accept()

    def _use_defaults(self) -> None:
        self.choice = ""
        self.dest = ""
        self.accept()
