"""Generic batch file table used by 转换 / 压缩 / 工具箱: orb, name, kind, extra columns, status."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QMenu, QTableWidget, QTableWidgetItem, QWidget)

from ...core.fileinfo import KIND_ORBS, file_size, human_size, kind_label, kind_of
from .. import theme
from .orb import OrbWidget
from .result_card import open_path, reveal_in_folder


@dataclass
class FileRow:
    path: Path
    kind: str
    status: str = "pending"        # pending | running | done | failed | skipped
    message: str = ""
    result: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    password: str | None = None


class FileTable(QTableWidget):
    """Columns: [orb] 文件 | 类型 | 大小 | <extra...> | 状态. Emits changed() when rows are added/removed."""
    changed = Signal()
    activated_row = Signal(int)

    def __init__(self, extra_columns: list[str] | None = None, parent: QWidget | None = None) -> None:
        self.extra_columns = extra_columns or []
        cols = ["", "文件", "类型", "大小"] + self.extra_columns + ["状态"]
        super().__init__(0, len(cols), parent)
        self.setHorizontalHeaderLabels(cols)
        self.rows: list[FileRow] = []
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setWordWrap(False)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setStretchLastSection(False)
        self.setColumnWidth(0, 30)
        self.verticalHeader().setDefaultSectionSize(34)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemDoubleClicked.connect(lambda it: self.activated_row.emit(it.row()))

    # -- rows ---------------------------------------------------------------
    def add_paths(self, paths: list[Path], kinds: set[str] | None = None) -> int:
        existing = {str(r.path).lower() for r in self.rows}
        added = 0
        for p in paths:
            k = kind_of(p)
            if k is None or (kinds and k not in kinds) or str(p).lower() in existing:
                continue
            row = FileRow(Path(p), k)
            self.rows.append(row)
            self._append_row(row)
            existing.add(str(p).lower())
            added += 1
        if added:
            self.changed.emit()
        return added

    def _append_row(self, row: FileRow) -> None:
        r = self.rowCount()
        self.insertRow(r)
        orb = OrbWidget(KIND_ORBS.get(row.kind, "blue"), 16)
        self.setCellWidget(r, 0, _center(orb))
        name = QTableWidgetItem(row.path.name)
        name.setToolTip(str(row.path))
        self.setItem(r, 1, name)
        self.setItem(r, 2, QTableWidgetItem(kind_label(row.kind)))
        size = QTableWidgetItem(human_size(file_size(row.path)))
        size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setItem(r, 3, size)
        for i, _c in enumerate(self.extra_columns):
            self.setItem(r, 4 + i, QTableWidgetItem(""))
        self.setItem(r, self.columnCount() - 1, QTableWidgetItem("待处理"))
        self._style_status(r)

    def set_extra(self, r: int, col_name: str, text: str, align_right: bool = False) -> None:
        if col_name not in self.extra_columns:
            return
        c = 4 + self.extra_columns.index(col_name)
        it = self.item(r, c)
        if it is None:
            it = QTableWidgetItem("")
            self.setItem(r, c, it)
        it.setText(text)
        if align_right:
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def set_status(self, r: int, status: str, message: str = "", result: Path | None = None) -> None:
        if r < 0 or r >= len(self.rows):
            return
        row = self.rows[r]
        row.status = status
        row.message = message
        if result is not None:
            row.result = result
        text = {"pending": "待处理", "running": "处理中…", "done": "完成", "failed": "失败", "skipped": "已跳过"}.get(status, status)
        if message:
            text = f"{text} · {message}"
        it = self.item(r, self.columnCount() - 1)
        it.setText(text)
        it.setToolTip(message)
        self._style_status(r)
        w = self.cellWidget(r, 0)
        orb = w.findChild(OrbWidget) if w else None
        if orb:
            orb.set_status({"running": "busy", "failed": "error", "done": "ready"}.get(status, "pending"))

    def _style_status(self, r: int) -> None:
        t = theme.current()
        row = self.rows[r]
        col = {"done": t.c("ok"), "failed": t.c("danger"), "running": t.c("warn"), "skipped": t.c("muted")}.get(row.status, t.c("muted"))
        it = self.item(r, self.columnCount() - 1)
        if it:
            from PySide6.QtGui import QColor
            it.setForeground(QColor(col))

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.selectedIndexes()}, reverse=True)
        for r in rows:
            self.removeRow(r)
            del self.rows[r]
        if rows:
            self.changed.emit()

    def clear_all(self) -> None:
        self.setRowCount(0)
        self.rows = []
        self.changed.emit()

    def reset_status(self) -> None:
        for r in range(len(self.rows)):
            self.set_status(r, "pending")
            self.rows[r].result = None

    def paths(self) -> list[Path]:
        return [r.path for r in self.rows]

    def total_size(self) -> int:
        return sum(file_size(r.path) for r in self.rows)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_selected()
            return
        super().keyPressEvent(e)

    def _menu(self, pos) -> None:
        idx = self.indexAt(pos)
        m = QMenu(self)
        if idx.isValid():
            row = self.rows[idx.row()]
            m.addAction("打开源文件").triggered.connect(lambda: open_path(row.path))
            m.addAction("打开所在文件夹").triggered.connect(lambda: reveal_in_folder(row.path))
            if row.result and Path(row.result).exists():
                m.addAction("打开结果").triggered.connect(lambda: open_path(row.result))
            m.addSeparator()
            m.addAction("移除选中").triggered.connect(self.remove_selected)
        m.addAction("清空列表").triggered.connect(self.clear_all)
        m.exec(self.viewport().mapToGlobal(pos))


def _center(w: QWidget) -> QWidget:
    from PySide6.QtWidgets import QHBoxLayout
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(w)
    return box
