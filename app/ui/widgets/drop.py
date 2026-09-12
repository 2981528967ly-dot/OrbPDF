"""Drag & drop helpers."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget, QApplication

from ...core.fileinfo import collect_files, kind_of
from .robot import RobotBadge


def paths_from_mime(mime: QMimeData) -> list[Path]:
    out: list[Path] = []
    if mime.hasUrls():
        for url in mime.urls():
            if url.isLocalFile():
                out.append(Path(url.toLocalFile()))
    elif mime.hasText():
        for line in mime.text().splitlines():
            line = line.strip().strip('"')
            if line and Path(line).exists():
                out.append(Path(line))
    return out


def mime_has_files(mime: QMimeData) -> bool:
    if mime.hasUrls():
        return any(u.isLocalFile() for u in mime.urls())
    return False


def clipboard_paths_or_image(tmp_dir: Path) -> list[Path]:
    """Paths from the clipboard; a raw image on the clipboard is saved as PNG and returned."""
    cb = QApplication.clipboard()
    mime = cb.mimeData()
    paths = paths_from_mime(mime)
    if paths:
        return [p for p in paths if p.exists()]
    img = cb.image()
    if not img.isNull():
        tmp_dir.mkdir(parents=True, exist_ok=True)
        import time
        p = tmp_dir / f"剪贴板截图-{time.strftime('%H%M%S')}.png"
        img.save(str(p), "PNG")
        return [p]
    return []


class DropZone(QFrame):
    """Dashed drop area with the robot and a hint. Emits files_dropped(list[Path])."""
    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, hint: str, kinds: set[str] | None = None, compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kinds = kinds
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(10)
        if not compact:
            self.badge = RobotBadge(96)
            lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignHCenter)
        self.hint = QLabel(hint)
        self.hint.setObjectName("Muted")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if mime_has_files(e.mimeData()):
            e.acceptProposedAction()
            self.setObjectName("DropZoneActive")
            self._repolish()

    def dragLeaveEvent(self, _e) -> None:
        self.setObjectName("DropZone")
        self._repolish()

    def dropEvent(self, e: QDropEvent) -> None:
        self.setObjectName("DropZone")
        self._repolish()
        paths = collect_files(paths_from_mime(e.mimeData()), kinds=self.kinds)
        if paths:
            self.files_dropped.emit(paths)
        e.acceptProposedAction()

    def _repolish(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class DropMixin:
    """Mixin for pages: accept file drops anywhere on the page and route to ``add_files``."""

    def _init_drop(self: QWidget, kinds: set[str] | None = None) -> None:  # type: ignore[misc]
        self.setAcceptDrops(True)
        self._drop_kinds = kinds

    def dragEnterEvent(self: QWidget, e: QDragEnterEvent) -> None:  # type: ignore[misc]
        if mime_has_files(e.mimeData()):
            e.acceptProposedAction()

    def dragMoveEvent(self: QWidget, e) -> None:  # type: ignore[misc]
        if mime_has_files(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self: QWidget, e: QDropEvent) -> None:  # type: ignore[misc]
        paths = collect_files(paths_from_mime(e.mimeData()), kinds=getattr(self, "_drop_kinds", None))
        if paths and hasattr(self, "add_files"):
            self.add_files(paths)  # type: ignore[attr-defined]
        e.acceptProposedAction()
