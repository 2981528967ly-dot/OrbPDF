"""Pick pages of a PDF by clicking thumbnails or typing a range."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ...core.pdf.info import format_page_range, open_pdf, parse_page_range
from ..widgets.controls import button, label
from ..widgets.page_grid import PageGrid


class PageRangeDialog(QDialog):
    def __init__(self, pdf_path: Path, current_spec: str = "", password: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择页面范围")
        self.resize(760, 560)
        self.doc = open_pdf(pdf_path, password)
        n = self.doc.page_count
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label(f"共 {n} 页 · 勾选要包含的页面，或直接输入范围（如 1-3,5）", "Muted"))
        top.addStretch(1)
        top.addWidget(button("全选", None, "Small", on_click=lambda: self.grid.set_all_checked(True)))
        top.addWidget(button("全不选", None, "Small", on_click=lambda: self.grid.set_all_checked(False)))
        lay.addLayout(top)
        self.grid = PageGrid(thumb_size=110, reorderable=False, checkable=True)
        self.grid.register_doc("doc", self.doc)
        try:
            idx = parse_page_range(current_spec, n)
        except ValueError:
            idx = None
        selected = set(idx) if idx else None
        self.grid.load_pages([("doc", i, f"{i + 1}") for i in range(n)], selected)
        lay.addWidget(self.grid, 1)
        row = QHBoxLayout()
        row.addWidget(label("范围", "Muted"))
        self.edit = QLineEdit(current_spec)
        self.edit.setPlaceholderText("留空 = 全部页面")
        row.addWidget(self.edit, 1)
        self.err = label("", "Danger")
        row.addWidget(self.err)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._syncing = False
        self.grid.check_changed.connect(self._from_grid)
        self.edit.textEdited.connect(self._from_text)
        self.result_spec = current_spec

    def _from_grid(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        pages = self.grid.checked_pages()
        spec = "" if len(pages) == self.doc.page_count else format_page_range(pages)
        self.edit.setText(spec)
        self.err.setText("")
        self._syncing = False

    def _from_text(self, text: str) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            idx = parse_page_range(text, self.doc.page_count)
            self.err.setText("")
            sel = set(idx) if idx else set(range(self.doc.page_count))
            self.grid.blockSignals(True)
            for i in range(self.grid.count()):
                it = self.grid.item(i)
                it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole)[1] in sel else Qt.CheckState.Unchecked)
            self.grid.blockSignals(False)
        except ValueError as e:
            self.err.setText(str(e))
        self._syncing = False

    def _accept(self) -> None:
        text = self.edit.text().strip()
        try:
            parse_page_range(text, self.doc.page_count)
        except ValueError as e:
            self.err.setText(str(e))
            return
        if not text and not self.grid.checked_pages():
            self.err.setText("至少选择一页")
            return
        self.result_spec = text
        self.accept()

    def done(self, r: int) -> None:
        try:
            self.grid.shutdown()
            self.doc.close()
        except Exception:
            pass
        super().done(r)
