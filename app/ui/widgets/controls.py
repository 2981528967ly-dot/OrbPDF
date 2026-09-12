"""Small reusable widgets: panels, step headers, segmented control, toggle switch, tags."""
from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Property, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget, QToolButton)

from .. import icons, theme


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("Divider")
    f.setFrameShape(QFrame.Shape.NoFrame)
    return f


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def button(text: str = "", icon_name: str | None = None, name: str | None = None, tooltip: str = "",
           on_click: Callable | None = None, icon_color: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if icon_name:
        b.setIcon(icons.icon(icon_name, icon_color))
        b.setIconSize(QSize(16, 16))
    if name:
        b.setObjectName(name)
    if tooltip:
        b.setToolTip(tooltip)
    if on_click:
        b.clicked.connect(on_click)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def icon_button(icon_name: str, tooltip: str = "", on_click: Callable | None = None, checkable: bool = False, size: int = 18) -> QToolButton:
    b = QToolButton()
    b.setIcon(icons.icon(icon_name))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tooltip)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        b.clicked.connect(on_click)
    return b


def tool_button(text: str, icon_name: str, tooltip: str = "", on_click: Callable | None = None) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setIcon(icons.icon(icon_name))
    b.setIconSize(QSize(16, 16))
    b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    b.setToolTip(tooltip or text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        b.clicked.connect(on_click)
    return b


class Panel(QFrame):
    """Rounded surface with an optional header row: [step badge] title  count ... actions."""

    def __init__(self, title: str = "", step: int | None = None, count: str = "", accent: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PanelAccent" if accent else "Panel")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(10)
        self.step_label: QLabel | None = None
        if step is not None:
            self.step_label = QLabel(str(step))
            self.step_label.setObjectName("Step")
            self.step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.header.addWidget(self.step_label)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PanelTitle")
        self.header.addWidget(self.title_label)
        self.count_label = QLabel(count)
        self.count_label.setObjectName("Muted")
        self.header.addWidget(self.count_label)
        self.header.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        self.header.addLayout(self.actions)
        if title or step is not None:
            self._layout.addLayout(self.header)

    def add_action(self, w: QWidget) -> QWidget:
        self.actions.addWidget(w)
        return w

    def add(self, w: QWidget | None = None, layout=None, stretch: int = 0) -> None:
        if w is not None:
            self._layout.addWidget(w, stretch)
        elif layout is not None:
            self._layout.addLayout(layout, stretch)

    def add_stretch(self) -> None:
        self._layout.addStretch(1)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_count(self, text: str) -> None:
        self.count_label.setText(text)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout


class Segmented(QWidget):
    """Horizontal exclusive choice: [A | B | C]. Emits changed(key)."""
    changed = Signal(str)

    def __init__(self, items: Iterable[tuple[str, str]], current: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        frame = QFrame(self)
        frame.setObjectName("SegFrame")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(frame)
        self._inner = QHBoxLayout(frame)
        self._inner.setContentsMargins(3, 3, 3, 3)
        self._inner.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in items:
            b = QPushButton(text)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self._inner.addWidget(b)
            self.group.addButton(b)
            self._buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        if current and current in self._buttons:
            self._buttons[current].setChecked(True)
        elif self._buttons:
            next(iter(self._buttons.values())).setChecked(True)

    def value(self) -> str:
        for k, b in self._buttons.items():
            if b.isChecked():
                return k
        return ""

    def set_value(self, key: str, emit: bool = False) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)
            if emit:
                self.changed.emit(key)

    def set_text(self, key: str, text: str) -> None:
        if key in self._buttons:
            self._buttons[key].setText(text)


class ToggleSwitch(QAbstractButton):
    """iOS-style switch, animated."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on: bool) -> None:  # type: ignore[override]
        super().setChecked(on)
        self._pos = 1.0 if on else 0.0
        self.update()

    def paintEvent(self, _event) -> None:
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        on = self._pos
        track = icons.qcolor("accent_dim") if on > 0.5 else QColor(t.c("surface3"))
        border = icons.qcolor("accent_line") if on > 0.5 else QColor(t.c("border2"))
        p.setPen(QPen(border, 1))
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        kn = self.height() - 6
        x = 3 + (self.width() - kn - 6) * on
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.c("accent")) if on > 0.5 else QColor(t.c("muted")))
        p.drawEllipse(QRectF(x, 3, kn, kn))
        p.end()


class ClickableFrame(QFrame):
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()) and self.isEnabled():
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class Tag(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Tag")


class Pill(QLabel):
    """Status pill: ok / busy / warn / err / mute."""

    def __init__(self, text: str = "", kind: str = "mute", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.kind = kind
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        t = theme.current()
        self.kind = kind
        col = {"ok": ("ok", "ok_dim"), "busy": ("warn", "warn_dim"), "warn": ("warn", "warn_dim"), "err": ("danger", "danger_dim")}.get(kind, ("muted", "surface3"))
        self.setStyleSheet(f"QLabel {{ color: {t.c(col[0])}; background: {t.c(col[1])}; border-radius: 9px; padding: 1px 8px; font-size: 11px; }}")

    def set(self, text: str, kind: str) -> None:
        self.setText(text)
        self.set_kind(kind)


class Kbd(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Kbd")


def hbox(*widgets: QWidget | int | str, spacing: int = 8, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w == "stretch":
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        else:
            lay.addWidget(w)
    return lay


def vbox(*widgets: QWidget | int | str, spacing: int = 8, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w == "stretch":
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        else:
            lay.addWidget(w)
    return lay


def expanding(w: QWidget) -> QWidget:
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return w
