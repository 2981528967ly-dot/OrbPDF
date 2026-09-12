"""Qt splash shown while the heavy modules load: robot with breathing eye + a real progress bar."""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, QTimer, Qt, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from . import assets


class Splash(QWidget):
    W, H = 460, 280

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.W, self.H)
        self._value = 0.05
        self._target = 0.05
        self._text = "启动中…"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            self.move(g.center().x() - self.W // 2, g.center().y() - self.H // 2)

    def set_progress(self, fraction: float, text: str = "") -> None:
        self._target = max(self._target, min(1.0, fraction))
        if text:
            self._text = text
        self._tick()
        QApplication.processEvents()

    def _tick(self) -> None:
        self._phase += 0.12
        if self._value < self._target:
            self._value = min(self._target, self._value + max(0.004, (self._target - self._value) * 0.18))
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(0.5, 0.5, self.W - 1, self.H - 1)
        p.setPen(QPen(QColor(47, 62, 92), 1))
        p.setBrush(QColor(10, 15, 28))
        p.drawRoundedRect(r, 14, 14)
        # glow behind the head
        c = QPointF(130, 122)
        glow = 0.6 + 0.4 * math.sin(self._phase)
        grad = QRadialGradient(c, 110)
        g0 = QColor(90, 216, 255, int(70 * glow))
        g1 = QColor(90, 216, 255, 0)
        grad.setColorAt(0, g0)
        grad.setColorAt(1, g1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(c, 110, 110)
        head = assets.robot_head(150, self.devicePixelRatioF())
        p.drawPixmap(56, 48, head)
        # eye glow
        eye = assets.eye_center(150) + QPointF(56, 48)
        er = assets.eye_radius(150)
        eg = QRadialGradient(eye, er * 1.6)
        eg.setColorAt(0, QColor(140, 235, 255, int(150 * glow)))
        eg.setColorAt(1, QColor(140, 235, 255, 0))
        p.setBrush(eg)
        p.drawEllipse(eye, er * 1.6, er * 1.6)
        # text
        f = QFont("Microsoft YaHei UI", 26)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(228, 236, 247))
        p.drawText(QRectF(236, 66, 210, 44), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "OrbPDF")
        f2 = QFont("Microsoft YaHei UI", 12)
        p.setFont(f2)
        p.setPen(QColor(180, 191, 210))
        p.drawText(QRectF(238, 112, 210, 24), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "全能 PDF 工作台")
        f3 = QFont("Microsoft YaHei UI", 9)
        p.setFont(f3)
        p.setPen(QColor(127, 140, 165))
        p.drawText(QRectF(238, 150, 210, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)
        # progress bar
        bar = QRectF(238, 196, 182, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(30, 42, 66))
        p.drawRoundedRect(bar, 3, 3)
        fill = QRectF(bar.x(), bar.y(), bar.width() * self._value, bar.height())
        p.setBrush(QColor(90, 216, 255))
        p.drawRoundedRect(fill, 3, 3)
        # moving highlight
        hx = bar.x() + (self._phase * 18) % (bar.width() * self._value + 1)
        p.setBrush(QColor(255, 255, 255, 90))
        p.drawRoundedRect(QRectF(min(hx, fill.right() - 12), bar.y(), 12, bar.height()), 3, 3)
        p.setPen(QColor(90, 216, 255))
        p.drawText(QRectF(238, 208, 182, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{int(self._value * 100)}%")
        p.end()
