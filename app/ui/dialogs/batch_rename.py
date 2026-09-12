"""Batch rename merge entries with a pattern."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from ..widgets.controls import label


class BatchRenameDialog(QDialog):
    def __init__(self, sample_names: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量重命名")
        self.resize(420, 200)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(label("模式里可以用 {n} 表示序号、{name} 表示原文件名。", "Muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(label("模式"))
        self.pattern = QLineEdit("发票{n}")
        row.addWidget(self.pattern, 1)
        row.addWidget(label("起始"))
        self.start = QSpinBox()
        self.start.setRange(0, 9999)
        self.start.setValue(1)
        row.addWidget(self.start)
        lay.addLayout(row)
        self.preview = label("", "Small", wrap=True)
        lay.addWidget(self.preview)
        self._samples = sample_names[:3]
        self.pattern.textChanged.connect(self._update)
        self.start.valueChanged.connect(self._update)
        self._update()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("应用")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _update(self) -> None:
        pat = self.pattern.text()
        n = self.start.value()
        out = []
        for i, name in enumerate(self._samples):
            out.append(pat.replace("{n}", str(n + i)).replace("{name}", name))
        self.preview.setText("预览：" + " · ".join(out) if out else "")

    def values(self) -> tuple[str, int]:
        return self.pattern.text(), self.start.value()
