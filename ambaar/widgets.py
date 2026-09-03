"""
Custom widgets and painting.

Every mark in this interface is drawn, not typed. That is partly a design rule
and partly practical: glyph icons depend on the user having a font that ships
them, which is exactly the assumption that breaks on a fresh Windows machine
with no DM Mono installed. Painted paths render identically everywhere and
inherit colour from the palette for free.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QSpinBox, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from . import theme

ROW_HEIGHT = 66
ROW_PAD_X = 16
MARK_SIZE = 14
MARK_INSET = 16

STATE_COLOR = {
    "Queued": "text_faint",
    "Resolving": "accent",
    "Downloading": "accent",
    "Processing": "warn",
    "Cancelling": "text_faint",
    "Done": "ok",
    "Failed": "bad",
    "Cancelled": "text_faint",
}


# --------------------------------------------------------------------------- #
# Painted marks
# --------------------------------------------------------------------------- #

def paint_mark(p: QPainter, rect: QRectF, status: str, color: QColor) -> None:
    """
    Status mark for a queue row. One shape per state, all stroked paths.

    Shapes are distinguishable without colour, which keeps the queue readable
    for anyone who cannot separate the ember from the green.
    """
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.SquareCap)
    pen.setJoinStyle(Qt.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    cx, cy = x + w / 2, y + h / 2

    if status == "Done":
        # check
        path = QPainterPath(QPointF(x + w * 0.16, cy))
        path.lineTo(QPointF(x + w * 0.42, y + h * 0.76))
        path.lineTo(QPointF(x + w * 0.86, y + h * 0.22))
        p.drawPath(path)

    elif status == "Failed":
        p.drawLine(QPointF(x + w * 0.2, y + h * 0.2), QPointF(x + w * 0.8, y + h * 0.8))
        p.drawLine(QPointF(x + w * 0.8, y + h * 0.2), QPointF(x + w * 0.2, y + h * 0.8))

    elif status in {"Cancelled", "Cancelling"}:
        p.drawLine(QPointF(x + w * 0.18, cy), QPointF(x + w * 0.82, cy))

    elif status in {"Downloading", "Resolving"}:
        # downward arrow into a baseline, drawn rather than glyphed
        p.drawLine(QPointF(cx, y + h * 0.12), QPointF(cx, y + h * 0.62))
        path = QPainterPath(QPointF(cx - w * 0.22, y + h * 0.4))
        path.lineTo(QPointF(cx, y + h * 0.66))
        path.lineTo(QPointF(cx + w * 0.22, y + h * 0.4))
        p.drawPath(path)
        p.drawLine(QPointF(x + w * 0.14, y + h * 0.88), QPointF(x + w * 0.86, y + h * 0.88))

    elif status == "Processing":
        # gear-ish: square rotated inside a square
        p.drawRect(QRectF(x + w * 0.22, y + h * 0.22, w * 0.56, h * 0.56))
        p.save()
        p.translate(cx, cy)
        p.rotate(45)
        p.drawRect(QRectF(-w * 0.2, -h * 0.2, w * 0.4, h * 0.4))
        p.restore()

    else:  # Queued
        p.drawRect(QRectF(x + w * 0.24, y + h * 0.24, w * 0.52, h * 0.52))

    p.restore()


def paint_chevron(p: QPainter, rect: QRectF, color: QColor,
                  direction: str = "down", width: float = 1.3) -> None:
    """Two-segment chevron. Replaces the glyph a QComboBox would otherwise draw."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.SquareCap)
    pen.setJoinStyle(Qt.MiterJoin)
    p.setPen(pen)
    cx, cy = rect.center().x(), rect.center().y()
    s = min(rect.width(), rect.height()) * 0.34
    if direction == "down":
        p.drawLine(QPointF(cx - s, cy - s * 0.5), QPointF(cx, cy + s * 0.5))
        p.drawLine(QPointF(cx, cy + s * 0.5), QPointF(cx + s, cy - s * 0.5))
    else:
        p.drawLine(QPointF(cx - s, cy + s * 0.5), QPointF(cx, cy - s * 0.5))
        p.drawLine(QPointF(cx, cy - s * 0.5), QPointF(cx + s, cy + s * 0.5))
    p.restore()


def paint_stepper(p: QPainter, up: QRectF, down: QRectF, color: QColor) -> None:
    paint_chevron(p, up, color, "up", 1.2)
    paint_chevron(p, down, color, "down", 1.2)


# --------------------------------------------------------------------------- #
# Controls with painted affordances
# --------------------------------------------------------------------------- #

class ComboBox(QComboBox):
    """QComboBox whose drop indicator is a painted chevron."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        zone = QRectF(self.width() - 28, 0, 28, self.height())
        paint_chevron(p, zone, theme.c("text_faint"))
        p.end()


class SpinBox(QSpinBox):
    """QSpinBox with painted steppers, clickable in the right-hand gutter."""

    GUTTER = 26

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QSpinBox.NoButtons)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        h = self.height()
        x = self.width() - self.GUTTER
        paint_stepper(
            p,
            QRectF(x, 2, self.GUTTER, h / 2 - 2),
            QRectF(x, h / 2, self.GUTTER, h / 2 - 2),
            theme.c("text_faint"),
        )
        p.end()

    def mousePressEvent(self, event) -> None:
        if event.position().x() >= self.width() - self.GUTTER:
            if event.position().y() < self.height() / 2:
                self.stepBy(1)
            else:
                self.stepBy(-1)
            event.accept()
            return
        super().mousePressEvent(event)


# --------------------------------------------------------------------------- #
# Queue row delegate
# --------------------------------------------------------------------------- #

class JobDelegate(QStyledItemDelegate):
    """
    Paints one download as a row: status mark, title, source line, metrics,
    and a hairline progress track pinned to the bottom edge.

    A default QTableWidget cannot express this without four columns of widgets,
    each of which would need styling and none of which would align. Painting the
    row directly is both faster and the only way to get the typographic
    hierarchy right.
    """

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, p: QPainter, option, index) -> None:
        job = index.data(Qt.UserRole) or {}
        status = job.get("status", "Queued")
        title = job.get("title") or job.get("url", "")
        url = job.get("url", "")
        pct = float(job.get("percent") or 0.0)
        speed = job.get("speed") or ""
        eta = job.get("eta") or ""
        size = job.get("size") or ""
        error = job.get("error") or ""

        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        p.save()
        p.setRenderHint(QPainter.Antialiasing)

        # background
        if selected:
            p.fillRect(rect, theme.c("raised"))
        elif hovered:
            p.fillRect(rect, theme.c("surface"))
        else:
            p.fillRect(rect, theme.c("ink"))

        # selection edge, ember, full-bleed left
        if selected:
            p.fillRect(QRect(rect.left(), rect.top(), 2, rect.height()), theme.c("accent"))

        # bottom hairline separating rows
        p.fillRect(QRect(rect.left(), rect.bottom(), rect.width(), 1), theme.c("line_soft"))

        state_color = theme.c(STATE_COLOR.get(status, "text_faint"))

        # status mark
        mark = QRectF(rect.left() + MARK_INSET,
                      rect.top() + (rect.height() - MARK_SIZE) / 2 - 4,
                      MARK_SIZE, MARK_SIZE)
        paint_mark(p, mark, status, state_color)

        text_left = int(mark.right() + 16)

        # right-hand metrics, measured first so the title can be elided to fit
        metrics_font = theme.font(theme.SIZE["sm"], mono=True)
        fm_meta = QFontMetrics(metrics_font)
        parts = [x for x in (size, speed, eta and f"{eta} left") if x]
        metrics_text = "   ".join(parts)
        metrics_w = fm_meta.horizontalAdvance(metrics_text) if metrics_text else 0

        status_font = theme.font(theme.SIZE["xs"], mono=True, tracking=10, caps=True)
        fm_status = QFontMetrics(status_font)
        status_w = fm_status.horizontalAdvance(status)

        right_edge = rect.right() - ROW_PAD_X
        title_w = right_edge - text_left - max(metrics_w, status_w) - 24

        # title
        title_font = theme.font(theme.SIZE["body"], weight=600)
        fm_title = QFontMetrics(title_font)
        p.setFont(title_font)
        p.setPen(theme.c("text") if status != "Failed" else theme.c("text_dim"))
        p.drawText(
            QRect(text_left, rect.top() + 13, max(title_w, 60), fm_title.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            fm_title.elidedText(title, Qt.ElideRight, max(title_w, 60)),
        )

        # second line: error if failed, else the source URL
        sub_font = theme.font(theme.SIZE["sm"], mono=True)
        fm_sub = QFontMetrics(sub_font)
        p.setFont(sub_font)
        p.setPen(theme.c("bad") if error else theme.c("text_faint"))
        sub_text = error.replace("\n", "  ") if error else url
        p.drawText(
            QRect(text_left, rect.top() + 34, max(title_w, 60), fm_sub.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            fm_sub.elidedText(sub_text, Qt.ElideRight, max(title_w, 60)),
        )

        # status word, right aligned on the first line
        p.setFont(status_font)
        p.setPen(state_color)
        p.drawText(
            QRect(right_edge - status_w, rect.top() + 13, status_w, fm_status.height()),
            Qt.AlignRight | Qt.AlignVCenter, status,
        )

        # metrics, right aligned on the second line
        if metrics_text:
            p.setFont(metrics_font)
            p.setPen(theme.c("text_dim"))
            p.drawText(
                QRect(right_edge - metrics_w, rect.top() + 34, metrics_w, fm_meta.height()),
                Qt.AlignRight | Qt.AlignVCenter, metrics_text,
            )

        # progress track, 2px, bottom edge, only while there is progress to show
        if status in {"Downloading", "Processing", "Resolving"} or 0 < pct < 100:
            track = QRect(rect.left(), rect.bottom() - 2, rect.width(), 2)
            p.fillRect(track, theme.c("track"))
            if pct > 0:
                fill = QRect(track.left(), track.top(),
                             int(track.width() * min(pct, 100) / 100), 2)
                p.fillRect(fill, theme.c("accent"))
            elif status == "Resolving":
                # indeterminate: a short ember tick at the left edge
                p.fillRect(QRect(track.left(), track.top(), 40, 2), theme.c("accent_low"))

        p.restore()


# --------------------------------------------------------------------------- #
# Empty state
# --------------------------------------------------------------------------- #

class EmptyState(QWidget):
    """Shown over the queue when nothing has been added yet."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._title = "Nothing queued"
        self._body = "Paste a video or playlist link above to begin."

    def set_text(self, title: str, body: str) -> None:
        self._title, self._body = title, body
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2 - 30

        # drawn mark: a tray with an arrow descending into it
        pen = QPen(theme.c("line"), 1.5)
        pen.setCapStyle(Qt.SquareCap)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        s = 34
        p.drawLine(QPointF(cx, cy - s * 0.75), QPointF(cx, cy + s * 0.1))
        path = QPainterPath(QPointF(cx - s * 0.35, cy - s * 0.25))
        path.lineTo(QPointF(cx, cy + s * 0.15))
        path.lineTo(QPointF(cx + s * 0.35, cy - s * 0.25))
        p.drawPath(path)
        p.drawLine(QPointF(cx - s * 0.7, cy + s * 0.55), QPointF(cx + s * 0.7, cy + s * 0.55))
        p.drawLine(QPointF(cx - s * 0.7, cy + s * 0.55), QPointF(cx - s * 0.7, cy + s * 0.25))
        p.drawLine(QPointF(cx + s * 0.7, cy + s * 0.55), QPointF(cx + s * 0.7, cy + s * 0.25))

        p.setFont(theme.font(theme.SIZE["md"], weight=600))
        p.setPen(theme.c("text_dim"))
        p.drawText(QRect(0, int(cy + 48), self.width(), 26),
                   Qt.AlignHCenter | Qt.AlignVCenter, self._title)

        p.setFont(theme.font(theme.SIZE["sm"]))
        p.setPen(theme.c("text_faint"))
        p.drawText(QRect(0, int(cy + 74), self.width(), 22),
                   Qt.AlignHCenter | Qt.AlignVCenter, self._body)
        p.end()


# --------------------------------------------------------------------------- #
# Engine health badge
# --------------------------------------------------------------------------- #

class EngineBadge(QWidget):
    """
    Compact engine status: a state dot, the version in mono, and a verdict.

    Clicking it jumps to the Engine section, so a failing probe is one click
    from the thing that fixes it.
    """

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setCursor(Qt.PointingHandCursor)
        self._version = "unknown"
        self._state = "unknown"  # ok | bad | busy | unknown
        self._verdict = "not verified"
        self.setToolTip("Engine status. Click to open the Engine section.")

    def set_state(self, state: str, version: str, verdict: str) -> None:
        self._state, self._version, self._verdict = state, version, verdict
        self.setToolTip(f"yt-dlp {version} — {verdict}")
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(120, 30)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        event.accept()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = {"ok": theme.c("ok"), "bad": theme.c("bad"),
                 "busy": theme.c("warn")}.get(self._state, theme.c("text_faint"))

        p.fillRect(self.rect(), theme.c("raised"))
        p.setPen(QPen(theme.c("line"), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

        # state dot, square to match the zero-radius language
        p.fillRect(QRect(11, self.height() // 2 - 3, 6, 6), color)

        # The sidebar is narrow, so the prefix goes in the tooltip and only the
        # version is drawn -- elided rather than clipped mid-digit.
        font = theme.font(theme.SIZE["sm"], mono=True)
        p.setFont(font)
        p.setPen(theme.c("text_dim"))
        box = QRect(25, 0, self.width() - 33, self.height())
        text = QFontMetrics(font).elidedText(self._version, Qt.ElideRight, box.width())
        p.drawText(box, Qt.AlignLeft | Qt.AlignVCenter, text)
        p.end()
