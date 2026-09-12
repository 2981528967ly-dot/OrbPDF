"""Toast shown bottom-right after a task finishes: open / folder / send to."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget, QGraphicsOpacityEffect

from .controls import button, label
from .orb import OrbWidget


def open_path(p: Path) -> None:
    try:
        os.startfile(str(p))  # type: ignore[attr-defined]
    except Exception:
        pass


def reveal_in_folder(p: Path) -> None:
    p = Path(p)
    try:
        if p.exists() and p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p if p.is_dir() else p.parent))  # type: ignore[attr-defined]
    except Exception:
        pass


class ResultCard(QFrame):
    send_to = Signal(str, list)   # module key, paths

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setFixedWidth(420)
        self.hide()
        self._paths: list[Path] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 12, 12)
        lay.setSpacing(12)
        self.orb = OrbWidget("green", 22)
        lay.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.title = label("", "Strong")
        self.title.setWordWrap(True)
        self.sub = label("", "Muted")
        self.sub.setWordWrap(True)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.open_btn = button("打开", None, "Small", on_click=self._open)
        self.folder_btn = button("打开文件夹", None, "Small", on_click=self._reveal)
        self.send_btn = button("发送到 ▾", None, "Small", on_click=self._send_menu)
        row.addWidget(self.open_btn)
        row.addWidget(self.folder_btn)
        row.addWidget(self.send_btn)
        row.addStretch(1)
        col.addLayout(row)
        lay.addLayout(col, 1)
        self.close_btn = button("", "close", "IconBtn", on_click=self.hide)
        lay.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def show_result(self, title: str, subtitle: str, paths: list[Path], ok: bool = True, timeout_ms: int = 15000) -> None:
        self._paths = [Path(p) for p in paths]
        self.title.setText(title)
        self.sub.setText(subtitle)
        self.orb.set_key("green" if ok else "purple")
        self.orb.set_status("ready" if ok else "error")
        has = bool(self._paths)
        self.open_btn.setVisible(has and len(self._paths) == 1)
        self.folder_btn.setVisible(has)
        self.send_btn.setVisible(has and all(p.suffix.lower() == ".pdf" for p in self._paths))
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(timeout_ms)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        x = 104
        y = parent.height() - self.height() - 52
        self.move(QPoint(max(0, x), max(0, y)))

    def enterEvent(self, e: QEvent) -> None:
        self._timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e: QEvent) -> None:
        self._timer.start(6000)
        super().leaveEvent(e)

    def _open(self) -> None:
        if self._paths:
            open_path(self._paths[0])

    def _reveal(self) -> None:
        if self._paths:
            reveal_in_folder(self._paths[0])

    def _send_menu(self) -> None:
        m = QMenu(self)
        for key, text in (("make", "生成 · 继续合并"), ("edit", "修改 · 页面 / 压缩 / 水印"), ("export", "转换 · 转成图片或 Word")):
            act = m.addAction(text)
            act.triggered.connect(lambda _=False, k=key: self.send_to.emit(k, list(self._paths)))
        m.exec(self.send_btn.mapToGlobal(QPoint(0, self.send_btn.height())))
