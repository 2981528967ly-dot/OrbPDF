"""The Defect's head, with an electronic eye that breathes while the app is working."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from .. import assets, theme


class RobotWidget(QWidget):
    clicked = Signal()

    def __init__(self, size: int = 48, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self._working = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(4200)
        self._blink_timer.timeout.connect(self._blink)
        self._blink_level =0.0
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._blink_timer.start()

    def set_working(self, on: bool) -> None:
        if on == self._working:
            return
        self._working = on
        if on:
            self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.08) % (2 * math.pi)
        self.update()

    def _blink(self) -> None:
        if self._working:
            return
        self._blink_level =1.0
        QTimer.singleShot(90, self._unblink)
        self.update()

    def _unblink(self) -> None:
        self._blink_level =0.0
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        s = self._size
        dpr = self.devicePixelRatioF()
        pm = assets.robot_head(s, dpr)
        p.drawPixmap(0, 0, pm)
        c = assets.eye_center(s)
        r = assets.eye_radius(s)
        accent = QColor(theme.current().c("accent"))
        if self._working:
            glow = 0.55 + 0.45 * math.sin(self._phase)
            grad = QRadialGradient(c, r * 1.9)
            col = QColor(accent)
            col.setAlphaF(0.55 * glow)
            grad.setColorAt(0.0, col)
            col2 = QColor(accent)
            col2.setAlphaF(0.0)
            grad.setColorAt(1.0, col2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawEllipse(c, r * 1.9, r * 1.9)
            # bright core
            core = QColor(255, 255, 255, int(120 * glow))
            p.setBrush(core)
            p.drawEllipse(c, r * 0.35, r * 0.35)
        elif self._blink_level > 0:
            # a quick "blink": darken the lens for a few frames
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(6, 21, 32, 200))
            p.drawEllipse(c, r * 0.92, r * 0.92)
        p.end()


class RobotBadge(QWidget):
    """Robot head + a soft ring, used for empty states."""

    def __init__(self, size: int = 120, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size + 24, size + 24)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        t = theme.current()
        s = self._size
        ring = QColor(t.c("accent"))
        ring.setAlphaF(0.18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ring)
        p.drawEllipse(QRectF(0, 0, s + 24, s + 24))
        inner = QColor(t.c("surface3"))
        p.setBrush(inner)
        p.drawEllipse(QRectF(10, 10, s + 4, s + 4))
        p.drawPixmap(12, 12, assets.robot_head(s, self.devicePixelRatioF()))
        p.end()
