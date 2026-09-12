"""Password prompt, error dialog with details, simple text input."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget, QFileDialog)

from ...core.logging_setup import export_diagnostics
from ..widgets.controls import button, label


class PasswordDialog(QDialog):
    def __init__(self, filename: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("需要密码")
        self.setModal(True)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(label(f"「{filename}」已加密，请输入打开密码：", wrap=True))
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addWidget(self.edit)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.edit.setFocus()

    @staticmethod
    def ask(filename: str, parent: QWidget | None = None) -> str | None:
        d = PasswordDialog(filename, parent)
        if d.exec() == QDialog.DialogCode.Accepted and d.edit.text():
            return d.edit.text()
        return None


class ErrorDialog(QDialog):
    def __init__(self, title: str, message: str, details: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(560, 360 if details else 160)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        msg = label(message, wrap=True)
        lay.addWidget(msg)
        self.details = QPlainTextEdit(details)
        self.details.setReadOnly(True)
        self.details.setVisible(bool(details))
        lay.addWidget(self.details, 1)
        row = QHBoxLayout()
        if details:
            row.addWidget(button("复制详情", "copy", on_click=self._copy))
        row.addWidget(button("导出诊断包", None, on_click=self._diag))
        row.addStretch(1)
        ok = button("关闭", None, "Primary", on_click=self.accept)
        row.addWidget(ok)
        lay.addLayout(row)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.details.toPlainText())

    def _diag(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出诊断包", str(Path.home() / "Desktop" / "OrbPDF-诊断.zip"), "Zip (*.zip)")
        if path:
            try:
                export_diagnostics(Path(path), {"last_error": self.details.toPlainText()[:4000]})
                QMessageBox.information(self, "已导出", f"诊断包已保存到：\n{path}")
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "导出失败", str(e))

    @staticmethod
    def show_error(title: str, message: str, details: str = "", parent: QWidget | None = None) -> None:
        ErrorDialog(title, message, details, parent).exec()


def confirm(parent: QWidget | None, title: str, text: str, ok_text: str = "确定", danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    ok = box.addButton(ok_text, QMessageBox.ButtonRole.AcceptRole)
    box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    if danger:
        ok.setObjectName("Danger")
    box.exec()
    return box.clickedButton() is ok


def info(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def ask_text(parent: QWidget | None, title: str, prompt: str, default: str = "") -> str | None:
    d = QDialog(parent)
    d.setWindowTitle(title)
    lay = QVBoxLayout(d)
    lay.addWidget(label(prompt, wrap=True))
    edit = QLineEdit(default)
    lay.addWidget(edit)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
    bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    lay.addWidget(bb)
    edit.selectAll()
    edit.setFocus()
    if d.exec() == QDialog.DialogCode.Accepted:
        return edit.text()
    return None
