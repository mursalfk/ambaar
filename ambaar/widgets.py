# ambaar/widgets.py
"""
Custom widgets and painting.

Every mark in this interface is drawn, not typed. That is partly a design rule
and partly practical: glyph icons depend on the user having a font that ships
them, which is exactly the assumption that breaks on a fresh Windows machine
with no DM Mono installed. Painted paths render identically everywhere and
inherit colour from the palette for free.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QToolTip,
    QWidget,
)

from . import engine, theme

# Three text lines plus room for buttons. The row got taller when it gained a
# kind tag and inline controls; cramming those into the old 66px meant 11px
# gaps everywhere, which reads as broken rather than dense.
ROW_HEIGHT = 84
ROW_PAD_X = 16
MARK_SIZE = 14
MARK_INSET = 16
THUMB_W = 96
THUMB_H = 54
THUMB_INSET = 14
BUTTON_H = 28
BUTTON_W = 34  # row buttons are icons: square-ish, no label to size by
BUTTON_GAP = 6
CHIP_H = 17

STATE_COLOR = {
    engine.STAGED: "text_faint",
    engine.RESOLVING: "accent",
    engine.READY: "text",
    engine.QUEUED: "text_faint",
    engine.DOWNLOADING: "accent",
    engine.PAUSED: "warn",
    engine.PROCESSING: "warn",
    engine.DONE: "ok",
    engine.FAILED: "bad",
    engine.CANCELLED: "text_faint",
    "Cancelling": "text_faint",
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
        p.drawLine(
            QPointF(x + w * 0.14, y + h * 0.88), QPointF(x + w * 0.86, y + h * 0.88)
        )

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


def paint_chevron(
    p: QPainter,
    rect: QRectF,
    color: QColor,
    direction: str = "down",
    width: float = 1.3,
) -> None:
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

# What each row icon says when hovered. Icons carry no text, so these are the
# only labels a user gets; they also name the action in the right-click menu.
TOOLTIPS = {
    "download": "Download",
    "pause": "Pause",
    "resume": "Resume",
    "cancel": "Cancel",
    "retry": "Retry",
    "remove": "Remove from list",
    "folder": "Open folder",
    "items": "Choose playlist items",
    "format": "Format and folder",
}


def paint_icon(p: QPainter, action: str, rect: QRect, color: QColor) -> None:
    """
    Draw a row button's icon.

    Everything is drawn from lines and rectangles rather than typed as glyphs,
    for the same reason the status marks are: a glyph depends on the user's
    fonts and a painted path does not. Square caps and mitred joins keep the
    set consistent with the app's zero-radius corners.
    """
    s = 7.0
    cx, cy = rect.center().x() + 0.5, rect.center().y() + 0.5
    P = QPointF

    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, 1.6)
    pen.setCapStyle(Qt.SquareCap)
    pen.setJoinStyle(Qt.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    def line(*pts):
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)

    if action == "download":
        line(P(cx, cy - s), P(cx, cy + 2.5))
        line(P(cx - 4.5, cy - 1.5), P(cx, cy + 3), P(cx + 4.5, cy - 1.5))
        line(
            P(cx - s, cy + 2.5),
            P(cx - s, cy + s),
            P(cx + s, cy + s),
            P(cx + s, cy + 2.5),
        )
    elif action == "pause":
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRect(QRectF(cx - 4.5, cy - s, 3.2, 2 * s))
        p.drawRect(QRectF(cx + 1.3, cy - s, 3.2, 2 * s))
    elif action == "resume":
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        path = QPainterPath()
        path.moveTo(cx - 3.5, cy - s)
        path.lineTo(cx - 3.5, cy + s)
        path.lineTo(cx + s - 0.5, cy)
        path.closeSubpath()
        p.drawPath(path)
    elif action == "cancel":
        d = s * 0.8
        line(P(cx - d, cy - d), P(cx + d, cy + d))
        line(P(cx - d, cy + d), P(cx + d, cy - d))
    elif action == "retry":
        r = 6.0
        p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), 40 * 16, 290 * 16)
        # Arrowhead at the arc's end (330 degrees), pointing along its travel.
        end = math.radians(330)
        tip = P(cx + r * math.cos(end), cy - r * math.sin(end))
        tx, ty = -math.sin(end), -math.cos(end)
        for sign in (1, -1):
            a = math.radians(145) * sign
            hx = tx * math.cos(a) - ty * math.sin(a)
            hy = tx * math.sin(a) + ty * math.cos(a)
            p.drawLine(tip, P(tip.x() + hx * 4.5, tip.y() + hy * 4.5))
    elif action == "folder":
        poly = [
            P(cx - s, cy - s * 0.6),
            P(cx - s, cy + s * 0.75),
            P(cx + s, cy + s * 0.75),
            P(cx + s, cy - s * 0.35),
            P(cx + 0.5, cy - s * 0.35),
            P(cx - 1.5, cy - s * 0.6),
        ]
        line(*poly, poly[0])
    elif action == "remove":
        top = cy - s * 0.5
        line(P(cx - s * 0.85, top), P(cx + s * 0.85, top))
        line(
            P(cx - 2.5, top),
            P(cx - 2.5, cy - s * 0.9),
            P(cx + 2.5, cy - s * 0.9),
            P(cx + 2.5, top),
        )
        line(
            P(cx - s * 0.6, top),
            P(cx - s * 0.5, cy + s * 0.9),
            P(cx + s * 0.5, cy + s * 0.9),
            P(cx + s * 0.6, top),
        )
        line(P(cx - 1.8, top + 3), P(cx - 1.8, cy + s * 0.5))
        line(P(cx + 1.8, top + 3), P(cx + 1.8, cy + s * 0.5))
    elif action == "items":
        p.setBrush(color)
        for i in (-1, 0, 1):
            y = cy + i * 4.5
            p.drawRect(QRectF(cx - s, y - 1.2, 2.6, 2.4))
            p.drawLine(P(cx - s + 5, y), P(cx + s, y))
    elif action == "format":
        p.drawLine(P(cx - s, cy - 3.2), P(cx + s, cy - 3.2))
        p.drawLine(P(cx - s, cy + 3.2), P(cx + s, cy + 3.2))
        p.setBrush(color)
        p.drawRect(QRectF(cx - 3.5, cy - 5.2, 3, 4))
        p.drawRect(QRectF(cx + 1.5, cy + 1.2, 3, 4))
    p.restore()


class JobDelegate(QStyledItemDelegate):
    """
    Paints one job as a row and handles its inline buttons.

    The buttons are painted and hit-tested here rather than being real widgets
    in each row. Qt can host a widget per row, but with a hundred rows that is a
    hundred live widgets to create, style, and keep in sync with job state --
    and the row's typography (title, source line, status line) is already drawn
    as one surface, so the buttons may as well join it. The cost is that
    geometry must be computed identically for painting and for clicking, which
    is why both go through `button_rects()` and neither computes its own.
    """

    # job_id, action. Actions: download, items, format (shown as Options), pause, resume, cancel, retry, remove, folder
    action = Signal(str, str)

    def __init__(self, view=None) -> None:
        super().__init__(view)
        self._view = view
        self._hover: tuple[int, int] | None = None  # (row, button index)
        # Decoded thumbnails, keyed by path. paint() runs on every scroll frame;
        # re-decoding a JPEG each time would make scrolling stutter.
        self._pixmaps: dict[str, QPixmap] = {}

    def _thumbnail(self, path: str) -> QPixmap | None:
        if not path:
            return None
        hit = self._pixmaps.get(path)
        if hit is not None:
            return hit if not hit.isNull() else None
        pm = QPixmap(path)
        if not pm.isNull():
            pm = pm.scaled(
                THUMB_W * 2,
                THUMB_H * 2,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            pm.setDevicePixelRatio(2)
        self._pixmaps[path] = pm  # cache the miss too, so it is tried once
        return pm if not pm.isNull() else None

    def _paint_thumbnail(
        self, p: QPainter, rect: QRect, job: dict, status: str, colour: QColor
    ) -> QRect:
        """Draw the picture, or a placeholder carrying the status mark."""
        box = QRect(
            rect.left() + THUMB_INSET,
            rect.top() + (rect.height() - THUMB_H) // 2,
            THUMB_W,
            THUMB_H,
        )

        pm = self._thumbnail(job.get("thumb") or "")
        if pm is not None:
            # Centre-crop: the scaled pixmap is at least as large as the box in
            # both directions, so this trims rather than letterboxes.
            sx = max(0, (pm.width() / pm.devicePixelRatio() - THUMB_W) / 2)
            sy = max(0, (pm.height() / pm.devicePixelRatio() - THUMB_H) / 2)
            p.drawPixmap(
                box,
                pm,
                QRectF(
                    sx * pm.devicePixelRatio(),
                    sy * pm.devicePixelRatio(),
                    THUMB_W * pm.devicePixelRatio(),
                    THUMB_H * pm.devicePixelRatio(),
                ).toRect(),
            )
        else:
            p.fillRect(box, theme.c("track"))
            mark = QRectF(
                box.center().x() - MARK_SIZE / 2,
                box.center().y() - MARK_SIZE / 2,
                MARK_SIZE,
                MARK_SIZE,
            )
            paint_mark(p, mark, status, colour)

        p.setPen(QPen(theme.c("line_soft"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(box.adjusted(0, 0, -1, -1))
        return box

    # -- geometry ------------------------------------------------------------ #

    @staticmethod
    def buttons_for(status: str, kind: str = "") -> list[tuple[str, str, bool]]:
        """
        (action, label, is_primary) for a status.

        One source of truth for which buttons exist. The painter, the hit test
        and the context menu all read this, so a row can never show a button
        that does nothing or hide one that should be there.
        """
        if status == engine.READY:
            extra = [("items", "Items", False)] if kind == engine.KIND_PLAYLIST else []
            return [
                ("download", "Download", True),
                *extra,
                ("format", "Options", False),
                ("remove", "Remove", False),
            ]
        if status == engine.DOWNLOADING:
            return [("pause", "Pause", False), ("cancel", "Cancel", False)]
        if status == engine.PAUSED:
            return [("resume", "Resume", True), ("cancel", "Cancel", False)]
        if status in (engine.QUEUED, engine.RESOLVING):
            return [("cancel", "Cancel", False)]
        if status.startswith(engine.PROCESSING):
            # No pause here: ffmpeg cannot resume a half-written merge, so
            # offering it would quietly mean redoing the work.
            return [("cancel", "Cancel", False)]
        if status == engine.DONE:
            return [("folder", "Open folder", False), ("remove", "Remove", False)]
        if status in (engine.FAILED, engine.CANCELLED):
            return [("retry", "Retry", True), ("remove", "Remove", False)]
        return []  # Staged: nothing to press while it resolves

    @classmethod
    def button_rects(
        cls, rect: QRect, status: str, kind: str = ""
    ) -> list[tuple[str, str, bool, QRect]]:
        """Lay buttons out right to left, vertically centred."""
        out = []
        x = rect.right() - ROW_PAD_X
        y = rect.top() + (rect.height() - BUTTON_H) // 2
        for action, label, primary in reversed(cls.buttons_for(status, kind)):
            w = BUTTON_W
            x -= w
            out.insert(0, (action, label, primary, QRect(x, y, w, BUTTON_H)))
            x -= BUTTON_GAP
        return out

    @classmethod
    def buttons_left_edge(cls, rect: QRect, status: str, kind: str = "") -> int:
        """Where the text must stop so it never runs under a button."""
        rects = cls.button_rects(rect, status, kind)
        return rects[0][3].left() if rects else rect.right() - ROW_PAD_X

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    # -- interaction --------------------------------------------------------- #

    def editorEvent(self, event, model, option, index) -> bool:
        etype = event.type()
        if etype not in (
            QEvent.MouseMove,
            QEvent.MouseButtonRelease,
            QEvent.MouseButtonPress,
        ):
            return False

        job = index.data(Qt.UserRole) or {}
        status = job.get("status", "")
        rects = self.button_rects(option.rect, status, job.get("kind", ""))
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()

        hit = next((i for i, (_, _, _, r) in enumerate(rects) if r.contains(pos)), None)

        if etype == QEvent.MouseMove:
            new_hover = (index.row(), hit) if hit is not None else None
            if new_hover != self._hover:
                self._hover = new_hover
                if self._view is not None:
                    self._view.viewport().update()
            return hit is not None

        if hit is None:
            return False

        # Swallow the press so a click on a button does not also start a
        # selection drag, and act on the release so a drag off the button
        # cancels the click, as every other button on the platform does.
        if etype == QEvent.MouseButtonPress:
            return True

        job_id = index.data(Qt.UserRole + 1)
        if job_id:
            self.action.emit(job_id, rects[hit][0])
        return True

    # -- painting ------------------------------------------------------------ #

    def _paint_button(
        self, p: QPainter, rect: QRect, action: str, primary: bool, hovered: bool
    ) -> None:
        if primary:
            bg = theme.c("accent_hi") if hovered else theme.c("accent")
            p.fillRect(rect, bg)
            p.setPen(QPen(bg, 1))
            p.drawRect(rect.adjusted(0, 0, -1, -1))
            ink = theme.c("on_accent")
        else:
            if hovered:
                p.fillRect(rect, theme.c("hover"))
            p.setPen(QPen(theme.c("text_faint") if hovered else theme.c("line"), 1))
            p.drawRect(rect.adjusted(0, 0, -1, -1))
            ink = theme.c("text") if hovered else theme.c("text_dim")
        paint_icon(p, action, rect, ink)

    def helpEvent(self, event, view, option, index) -> bool:
        """Name an icon when the pointer rests on it."""
        if event.type() == QEvent.ToolTip:
            job = index.data(Qt.UserRole) or {}
            rects = self.button_rects(
                option.rect, job.get("status", ""), job.get("kind", "")
            )
            for action, label, _primary, r in rects:
                if r.contains(event.pos()):
                    QToolTip.showText(
                        event.globalPos(), TOOLTIPS.get(action, label), view
                    )
                    return True
            QToolTip.hideText()
            return False
        return super().helpEvent(event, view, option, index)

    def _paint_kind_chip(self, p: QPainter, x: int, y: int, job: dict) -> int:
        """Draw the VIDEO / PLAYLIST tag. Returns the x to continue from."""
        kind = job.get("kind", engine.KIND_UNKNOWN)
        if kind == engine.KIND_UNKNOWN:
            return x

        label = "PLAYLIST" if kind == engine.KIND_PLAYLIST else "VIDEO"
        colour = (
            theme.c("accent") if kind == engine.KIND_PLAYLIST else theme.c("text_dim")
        )

        font = theme.font(theme.SIZE["xs"], mono=True, weight=600, tracking=10)
        fm = QFontMetrics(font)
        w = fm.horizontalAdvance(label) + 14
        chip = QRect(x, y, w, CHIP_H)

        p.setPen(QPen(colour, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(chip.adjusted(0, 0, -1, -1))
        p.setFont(font)
        p.drawText(chip, Qt.AlignCenter, label)
        return x + w + 10

    def paint(self, p: QPainter, option, index) -> None:
        job = index.data(Qt.UserRole) or {}
        status = job.get("status", engine.STAGED)
        title = job.get("title") or job.get("url", "")
        url = job.get("url", "")
        pct = float(job.get("percent") or 0.0)
        error = job.get("error") or ""

        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered_row = bool(option.state & QStyle.State_MouseOver)

        p.save()
        p.setRenderHint(QPainter.Antialiasing)

        if selected:
            p.fillRect(rect, theme.c("raised"))
        elif hovered_row:
            p.fillRect(rect, theme.c("surface"))
        else:
            p.fillRect(rect, theme.c("ink"))

        if selected:
            p.fillRect(
                QRect(rect.left(), rect.top(), 2, rect.height()), theme.c("accent")
            )

        p.fillRect(
            QRect(rect.left(), rect.bottom(), rect.width(), 1), theme.c("line_soft")
        )

        base_status = status.split(" (")[0]
        state_colour = theme.c(STATE_COLOR.get(base_status, "text_faint"))

        box = self._paint_thumbnail(p, rect, job, base_status, state_colour)
        text_left = box.right() + 16
        text_right = self.buttons_left_edge(rect, status, job.get("kind", "")) - 20
        text_w = max(60, text_right - text_left)

        # line 1: title
        title_font = theme.font(theme.SIZE["body"], weight=600)
        fm_title = QFontMetrics(title_font)
        p.setFont(title_font)
        p.setPen(theme.c("text") if status != engine.FAILED else theme.c("text_dim"))
        p.drawText(
            QRect(text_left, rect.top() + 11, text_w, fm_title.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            fm_title.elidedText(title, Qt.ElideRight, text_w),
        )

        # line 2: kind chip, then what the link is
        chip_y = rect.top() + 36
        after_chip = self._paint_kind_chip(p, text_left, chip_y, job)

        sub_font = theme.font(theme.SIZE["sm"], mono=True)
        fm_sub = QFontMetrics(sub_font)
        p.setFont(sub_font)
        p.setPen(theme.c("text_faint"))

        bits = []
        if job.get("kind") == engine.KIND_PLAYLIST and job.get("item_count"):
            picked = job.get("selected")
            total = job["item_count"]
            bits.append(
                f"{picked} of {total} items"
                if picked not in (None, total)
                else f"{total} items"
            )
        dur = engine.human_duration(job.get("duration"))
        if dur:
            bits.append(dur)
        if job.get("uploader"):
            bits.append(str(job["uploader"]))
        if job.get("fmt_label"):
            bits.append(f"[{job['fmt_label']}]")
        meta = "  ".join(bits) if bits else url

        meta_w = max(40, text_right - after_chip)
        p.drawText(
            QRect(after_chip, chip_y, meta_w, CHIP_H),
            Qt.AlignLeft | Qt.AlignVCenter,
            fm_sub.elidedText(meta, Qt.ElideRight, meta_w),
        )

        # line 3: status word, then live metrics or the error
        # A small mark leads the status word. Shape carries the state as well as
        # colour, so the row stays readable without relying on hue alone.
        line3_y = rect.top() + 58
        small = 11
        paint_mark(
            p, QRectF(text_left, line3_y + 3, small, small), base_status, state_colour
        )

        status_font = theme.font(theme.SIZE["xs"], mono=True, tracking=10, caps=True)
        fm_status = QFontMetrics(status_font)
        p.setFont(status_font)
        p.setPen(state_colour)
        status_x = text_left + small + 8
        status_w = fm_status.horizontalAdvance(status) + 14
        p.drawText(
            QRect(status_x, line3_y, status_w, fm_status.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            status,
        )

        detail_font = theme.font(theme.SIZE["sm"], mono=True)
        fm_detail = QFontMetrics(detail_font)
        p.setFont(detail_font)
        # A retry countdown is news, not a failure: warn colour, not red.
        waiting = status == engine.QUEUED and bool(error)
        p.setPen(
            theme.c("warn")
            if waiting
            else theme.c("bad") if error else theme.c("text_dim")
        )
        if error:
            detail = error.replace("\n", "  ")
        else:
            parts = [
                x
                for x in (
                    job.get("size"),
                    job.get("speed"),
                    job.get("eta") and f"{job['eta']} left",
                )
                if x and x != "--"
            ]
            detail = "   ".join(parts)
        detail_x = status_x + status_w
        detail_w = max(40, text_right - detail_x)
        if detail:
            p.drawText(
                QRect(detail_x, line3_y, detail_w, fm_detail.height()),
                Qt.AlignLeft | Qt.AlignVCenter,
                fm_detail.elidedText(detail, Qt.ElideRight, detail_w),
            )

        # buttons
        rects = self.button_rects(rect, status, job.get("kind", ""))
        for i, (action, _label, primary, brect) in enumerate(rects):
            self._paint_button(
                p, brect, action, primary, self._hover == (index.row(), i)
            )

        # progress hairline, bottom edge
        # Only states that have actually moved bytes get a track. A Ready row
        # carrying a stale percentage from an earlier attempt would otherwise
        # look like it had started on its own.
        if status in (
            engine.DOWNLOADING,
            engine.PAUSED,
            engine.RESOLVING,
        ) or status.startswith(engine.PROCESSING):
            track = QRect(rect.left(), rect.bottom() - 2, rect.width(), 2)
            p.fillRect(track, theme.c("track"))
            if pct > 0:
                fill_colour = (
                    theme.c("warn") if status == engine.PAUSED else theme.c("accent")
                )
                p.fillRect(
                    QRect(
                        track.left(),
                        track.top(),
                        int(track.width() * min(pct, 100) / 100),
                        2,
                    ),
                    fill_colour,
                )
            elif status == engine.RESOLVING:
                p.fillRect(
                    QRect(track.left(), track.top(), 40, 2), theme.c("accent_low")
                )

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
        p.drawLine(
            QPointF(cx - s * 0.7, cy + s * 0.55), QPointF(cx + s * 0.7, cy + s * 0.55)
        )
        p.drawLine(
            QPointF(cx - s * 0.7, cy + s * 0.55), QPointF(cx - s * 0.7, cy + s * 0.25)
        )
        p.drawLine(
            QPointF(cx + s * 0.7, cy + s * 0.55), QPointF(cx + s * 0.7, cy + s * 0.25)
        )

        p.setFont(theme.font(theme.SIZE["md"], weight=600))
        p.setPen(theme.c("text_dim"))
        p.drawText(
            QRect(0, int(cy + 48), self.width(), 26),
            Qt.AlignHCenter | Qt.AlignVCenter,
            self._title,
        )

        p.setFont(theme.font(theme.SIZE["sm"]))
        p.setPen(theme.c("text_faint"))
        p.drawText(
            QRect(0, int(cy + 74), self.width(), 22),
            Qt.AlignHCenter | Qt.AlignVCenter,
            self._body,
        )
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
        color = {
            "ok": theme.c("ok"),
            "bad": theme.c("bad"),
            "busy": theme.c("warn"),
        }.get(self._state, theme.c("text_faint"))

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


# --------------------------------------------------------------------------- #
# Keyboard
# --------------------------------------------------------------------------- #


def key_action(key, status: str) -> str | None:
    """
    The row action a key press means for a job in `status`, or None.

    One table, tested on its own, so the shortcuts cannot drift from what the
    buttons offer. Space is the "do the obvious thing" key; Enter additionally
    opens a finished download, matching a double-click.
    """
    if key == Qt.Key_Space:
        return {
            engine.DOWNLOADING: "pause",
            engine.PAUSED: "resume",
            engine.READY: "download",
            engine.FAILED: "retry",
            engine.CANCELLED: "retry",
        }.get(status)
    if key in (Qt.Key_Return, Qt.Key_Enter):
        return {
            engine.DONE: "open",
            engine.READY: "download",
            engine.PAUSED: "resume",
            engine.FAILED: "retry",
            engine.CANCELLED: "retry",
        }.get(status)
    if key in (Qt.Key_Delete, Qt.Key_Backspace):
        # Deleting a running download is more likely a slip than an intent;
        # Cancel is a deliberate button.
        busy = status in engine.BUSY or status == "Cancelling"
        return None if busy else "remove"
    return None


# --------------------------------------------------------------------------- #
# Clipboard offer
# --------------------------------------------------------------------------- #


class OfferBar(QFrame):
    """
    A one-line, non-modal offer shown above the queue.

    Used by the clipboard watcher. A dialog would steal focus from whatever the
    user was doing when they copied the link; this sits quietly until it is
    taken or dismissed.
    """

    accepted = Signal(str)
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OfferBar")
        self._url = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 9, 18, 9)
        lay.setSpacing(10)
        self._text = QLabel("")
        self._text.setProperty("role", "mono")
        lay.addWidget(self._text, 1)
        add = QPushButton("Add to queue")
        add.setProperty("variant", "primary")
        add.clicked.connect(self._accept)
        no = QPushButton("Dismiss")
        no.setProperty("variant", "ghost")
        no.clicked.connect(self.dismiss)
        lay.addWidget(add)
        lay.addWidget(no)
        self.hide()

    def show_offer(self, url: str) -> None:
        self._url = url
        fm = QFontMetrics(self._text.font())
        self._text.setText("Link copied   " + fm.elidedText(url, Qt.ElideMiddle, 520))
        self._text.setToolTip(url)
        self.show()

    def _accept(self) -> None:
        url, self._url = self._url, ""
        self.hide()
        if url:
            self.accepted.emit(url)

    def dismiss(self) -> None:
        self._url = ""
        self.hide()
        self.dismissed.emit()
