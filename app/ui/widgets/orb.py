"""Orb sprite with a status ring (ready / busy / error)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import assets, theme


def draw_orb(p: QPainter, x: float, y: float, size: float, key: str, status: str = "ready", angle: float = 0.0, dpr: float = 1.0) -> None:
    """Paint helper shared by widgets and graphics items."""
    pm = assets.orb(key, int(size), dpr)
    p.drawPixmap(int(x), int(y), pm)
    t = theme.current()
    if status == "busy":
        pen = QPen(QColor(t.c("warn")), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = QRectF(x - 2, y - 2, size + 4, size + 4)
        p.drawArc(r, int(-angle * 16), 110 * 16)
    elif status == "error":
        pen = QPen(QColor(t.c("danger")), 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(x - 2, y - 2, size + 4, size + 4))
    elif status == "pending":
        pen = QPen(QColor(t.c("muted")), 1.2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(x - 2, y - 2, size + 4, size + 4))


class OrbWidget(QWidget):
    def __init__(self, key: str = "blue", size: int = 18, status: str = "ready", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._size = size
        self.status = status
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._spin)
        self.setFixedSize(size + 6, size + 6)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.set_status(status)

    def set_key(self, key: str) -> None:
        self.key = key
        self.update()

    def set_status(self, status: str) -> None:
        self.status = status
        if status == "busy":
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _spin(self) -> None:
        self._angle = (self._angle + 9) % 360
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        draw_orb(p, 3, 3, self._size, self.key, self.status, self._angle, self.devicePixelRatioF())
        p.end()
