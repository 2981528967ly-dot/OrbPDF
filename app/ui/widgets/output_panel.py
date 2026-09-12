"""Step ③: where the result goes."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QRadioButton, QWidget)

from ...core.settings import settings
from .controls import Panel, button, hbox, label


class OutputPanel(Panel):
    """Location (same folder / custom) + optional file name + open-after checkbox + primary action button."""
    run_clicked = Signal()

    def __init__(self, title: str = "输出", step: int | None = 3, action_text: str = "开始", with_filename: bool = False,
                 filename_default: str = "", suffix_ext: str = ".pdf", extra_checks: list[tuple[str, str, bool]] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(title, step, parent=parent)
        self.suffix_ext = suffix_ext
        mode = settings().get("output_mode", "source")
        self.rb_source = QRadioButton("同源文件夹")
        self.rb_custom = QRadioButton("自定义")
        self.group = QButtonGroup(self)
        self.group.addButton(self.rb_source)
        self.group.addButton(self.rb_custom)
        (self.rb_custom if mode == "custom" else self.rb_source).setChecked(True)
        row = hbox(label("位置", "Muted"), self.rb_source, self.rb_custom, "stretch")
        self.add(layout=row)
        self.dir_edit = QLineEdit(settings().get("output_dir", "") or "")
        self.dir_edit.setPlaceholderText("选择输出文件夹…")
        self.browse_btn = button("浏览…", None, "Small", on_click=self._browse)
        drow = hbox(self.dir_edit, self.browse_btn)
        self.add(layout=drow)
        self.filename_edit: QLineEdit | None = None
        if with_filename:
            self.filename_edit = QLineEdit(filename_default)
            self.filename_edit.setPlaceholderText("文件名")
            ext = QLabel(suffix_ext)
            ext.setObjectName("Muted")
            self.add(layout=hbox(label("文件名", "Muted"), self.filename_edit, ext))
        self.open_after = QCheckBox("完成后打开文件夹")
        self.open_after.setChecked(bool(settings().get("open_after", True)))
        self.add(self.open_after)
        self.extra: dict[str, QCheckBox] = {}
        for key, text, default in (extra_checks or []):
            cb = QCheckBox(text)
            cb.setChecked(default)
            self.extra[key] = cb
            self.add(cb)
        self.run_btn = button(action_text, None, "PrimaryBig", on_click=self.run_clicked.emit)
        self.add(self.run_btn)
        self.hint = label("", "Small")
        self.hint.setWordWrap(True)
        self.add(self.hint)
        self.rb_source.toggled.connect(self._mode_changed)
        self._mode_changed()

    def _mode_changed(self, *_a) -> None:
        custom = self.rb_custom.isChecked()
        self.dir_edit.setVisible(custom)
        self.browse_btn.setVisible(custom)
        settings().set("output_mode", "custom" if custom else "source")

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出文件夹", self.dir_edit.text() or str(Path.home()))
        if d:
            self.dir_edit.setText(d)
            settings().set("output_dir", d)

    # -- API -----------------------------------------------------------------
    def output_dir_for(self, source: Path | None) -> Path:
        if self.rb_custom.isChecked() and self.dir_edit.text().strip():
            return Path(self.dir_edit.text().strip())
        if source is not None:
            return Path(source).parent
        return Path.home() / "Desktop"

    def custom_dir(self) -> Path | None:
        if self.rb_custom.isChecked() and self.dir_edit.text().strip():
            return Path(self.dir_edit.text().strip())
        return None

    def filename(self) -> str:
        return (self.filename_edit.text().strip() if self.filename_edit else "")

    def set_filename(self, name: str) -> None:
        if self.filename_edit:
            self.filename_edit.setText(name)

    def wants_open(self) -> bool:
        return self.open_after.isChecked()

    def set_action_text(self, text: str) -> None:
        self.run_btn.setText(text)

    def set_enabled_run(self, on: bool) -> None:
        self.run_btn.setEnabled(on)

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)
