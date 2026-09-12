"""Thumbnail grid of PDF pages with lazy, HiDPI-aware rendering, multi-select and optional drag reordering."""
from __future__ import annotations

import queue
import threading

import pymupdf
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QWidget

from ...core.pdf.render import render_page


class _Renderer(QThread):
    rendered = Signal(str, int, int, object)   # doc key, page index, rotation, QImage

    def __init__(self) -> None:
        super().__init__()
        self.queue: "queue.Queue[tuple[str, pymupdf.Document, int, int, int] | None]" = queue.Queue()
        self._lock = threading.Lock()

    def request(self, key: str, doc: pymupdf.Document, pno: int, rotation: int, size: int) -> None:
        self.queue.put((key, doc, pno, rotation, size))

    def stop(self) -> None:
        self.queue.put(None)

    def run(self) -> None:
        while True:
            job = self.queue.get()
            if job is None:
                break
            key, doc, pno, rotation, size = job
            try:
                with self._lock:
                    img = render_page(doc, pno, size, rotation)
                qimg = QImage(img.samples, img.width, img.height, img.stride, QImage.Format.Format_RGB888).copy()
                self.rendered.emit(key, pno, rotation, qimg)
            except Exception:
                continue


class PageGrid(QListWidget):
    """Items carry (doc_key, page_no, rotation) in UserRole. Emits order_changed after internal drag moves."""
    order_changed = Signal()
    check_changed = Signal()

    def __init__(self, thumb_size: int = 120, reorderable: bool = True, checkable: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageGrid")
        self.thumb_size = thumb_size
        self.checkable = checkable
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap if reorderable else QListWidget.Movement.Static)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setSpacing(10)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setIconSize(QSize(thumb_size, thumb_size))
        self.setWordWrap(True)
        if reorderable:
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._renderer = _Renderer()
        self._renderer.rendered.connect(self._on_rendered)
        self._renderer.start()
        self._docs: dict[str, pymupdf.Document] = {}
        self._cache: dict[tuple[str, int, int, int], QPixmap] = {}
        if checkable:
            self.itemChanged.connect(lambda _it: self.check_changed.emit())

    def _dpr(self) -> float:
        return float(self.devicePixelRatioF() or 1.0)

    def set_thumb_size(self, size: int) -> None:
        self.thumb_size = size
        self.setIconSize(QSize(size, size))
        for i in range(self.count()):
            self.item(i).setSizeHint(QSize(size + 24, size + 34))
            self._request(self.item(i))

    def register_doc(self, key: str, doc: pymupdf.Document) -> None:
        self._docs[key] = doc

    def load_pages(self, refs: list[tuple], selected_pages: set[int] | None = None) -> None:
        """refs: (doc_key, page_no, label) or (doc_key, page_no, label, rotation)."""
        self.blockSignals(True)
        self.clear()
        for ref in refs:
            key, pno, label_text = ref[0], ref[1], ref[2]
            rotation = int(ref[3]) if len(ref) > 3 else 0
            item = QListWidgetItem(label_text)
            item.setData(Qt.ItemDataRole.UserRole, (key, pno, rotation))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            item.setSizeHint(QSize(self.thumb_size + 24, self.thumb_size + 34))
            if self.checkable:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if (selected_pages is None or pno in selected_pages) else Qt.CheckState.Unchecked)
            self.addItem(item)
            self._request(item)
        self.blockSignals(False)

    def _request(self, item: QListWidgetItem) -> None:
        key, pno, rotation = item.data(Qt.ItemDataRole.UserRole)
        px = int(self.thumb_size * self._dpr())
        pm = self._cache.get((key, pno, rotation, px))
        if pm is not None:
            item.setIcon(QIcon(pm))
            return
        placeholder = QPixmap(self.thumb_size, self.thumb_size)
        placeholder.fill(Qt.GlobalColor.transparent)
        item.setIcon(QIcon(placeholder))
        doc = self._docs.get(key)
        if doc is not None:
            self._renderer.request(key, doc, pno, rotation, px)

    def _on_rendered(self, key: str, pno: int, rotation: int, qimg: QImage) -> None:
        pm = QPixmap.fromImage(qimg)
        pm.setDevicePixelRatio(self._dpr())
        px = int(self.thumb_size * self._dpr())
        self._cache[(key, pno, rotation, px)] = pm
        for i in range(self.count()):
            it = self.item(i)
            k, p, r = it.data(Qt.ItemDataRole.UserRole)
            if (k, p, r) == (key, pno, rotation):
                it.setIcon(QIcon(pm))

    def refs(self) -> list[tuple[str, int, int]]:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def selected_rows(self) -> list[int]:
        return sorted({self.row(it) for it in self.selectedItems()})

    def checked_pages(self) -> list[int]:
        out = []
        for i in range(self.count()):
            it = self.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole)[1])
        return out

    def set_all_checked(self, on: bool) -> None:
        self.blockSignals(True)
        for i in range(self.count()):
            self.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.blockSignals(False)
        self.check_changed.emit()

    def dropEvent(self, e) -> None:
        super().dropEvent(e)
        self.order_changed.emit()

    def shutdown(self) -> None:
        self._renderer.stop()
        self._renderer.wait(1500)
