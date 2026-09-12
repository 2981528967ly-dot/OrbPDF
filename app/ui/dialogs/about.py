"""About + the orb easter egg."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from .. import assets, theme


class OrbBurstDialog(QDialog):
    """Ten clicks on the robot: the orbs come out to play."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("充能球")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(420, 320)
        self.t = 0.0
        self.orbs = []
        for i, key in enumerate(assets.ORB_KEYS):
            self.orbs.append({"key": key, "phase": i * 2 * math.pi / 5, "r": 96 + random.randint(-8, 8), "speed": 1.0 + random.random() * 0.3})
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(30)
        QTimer.singleShot(6000, self.accept)
        if parent:
            g = parent.geometry()
            self.move(g.center().x() - 210, g.center().y() - 160)

    def _tick(self) -> None:
        self.t += 0.05
        self.update()

    def mousePressEvent(self, _e) -> None:
        self.accept()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        th = theme.current()
        bg = QColor(th.c("bg"))
        bg.setAlphaF(0.92)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(self.rect(), 16, 16)
        c = QPointF(self.width() / 2, self.height() / 2)
        head = assets.robot_head(120, self.devicePixelRatioF())
        p.drawPixmap(int(c.x() - 60), int(c.y() - 60), head)
        for o in self.orbs:
            ang = o["phase"] + self.t * o["speed"]
            x = c.x() + math.cos(ang) * o["r"]
            y = c.y() + math.sin(ang) * o["r"] * 0.55
            size = 34 + 10 * math.sin(ang)
            pm = assets.orb(o["key"], int(size), self.devicePixelRatioF())
            p.drawPixmap(int(x - size / 2), int(y - size / 2), pm)
        p.setPen(QColor(th.c("muted")))
        p.drawText(self.rect().adjusted(0, self.height() - 40, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "充能球槽已满 · 点击关闭")
        p.end()
