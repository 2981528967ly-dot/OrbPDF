"""Shared skeleton for batch pages (转换 / 压缩 / 工具): ① file table → ② options → ③ output, run as one task."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from ...core.fileinfo import collect_files
from ...core.settings import settings
from ...core.tasks.runner import runner
from ..dialogs.common import ErrorDialog, PasswordDialog, info
from ..widgets.controls import Panel, button, label
from ..widgets.drop import DropMixin, DropZone
from ..widgets.file_table import FileTable
from ..widgets.output_panel import OutputPanel
from ..widgets.result_card import reveal_in_folder

FILTER_ALL = "所有支持的文件 (*.pdf *.docx *.doc *.pptx *.ppt *.xlsx *.xls *.csv *.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp *.txt *.md *.html);;所有文件 (*.*)"
FILTER_PDF = "PDF 文件 (*.pdf)"


class BatchPage(QWidget, DropMixin):
    key = "batch"
    title_text = ""
    hint_text = ""
    kinds: set[str] | None = None
    file_filter = FILTER_ALL
    extra_columns: list[str] = []
    action_text = "开始"

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ref = window
        self.setObjectName("Page")
        self._init_drop(self.kinds)
        self._task_id: str | None = None
        self._build()
        runner().task_finished.connect(self._on_finished)
        runner().task_failed.connect(self._on_failed)
        runner().task_cancelled.connect(self._on_cancelled)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.add_files_dialog)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.run)

    # -- layout ---------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label(self.title_text, "ModuleTitle"))
        head.addWidget(label(self.hint_text, "ModuleHint"))
        head.addStretch(1)
        self.head_extra = QHBoxLayout()
        head.addLayout(self.head_extra)
        root.addLayout(head)
        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)
        left = QVBoxLayout()
        left.setSpacing(12)
        body.addLayout(left, 1)
        self.files_panel = Panel("文件", 1)
        self.files_panel.add_action(button("添加文件", "add", on_click=self.add_files_dialog))
        self.files_panel.add_action(button("添加文件夹", "folder", on_click=self.add_folder_dialog))
        self.files_panel.add_action(button("移除选中", None, "Ghost", on_click=lambda: self.table.remove_selected()))
        self.files_panel.add_action(button("清空", None, "Ghost", on_click=lambda: self.table.clear_all()))
        self.table = FileTable(self.extra_columns)
        self.table.changed.connect(self._files_changed)
        self.drop_zone = DropZone("把文件拖到这里，或点击添加", self.kinds)
        self.drop_zone.files_dropped.connect(self.add_files)
        self.drop_zone.clicked.connect(self.add_files_dialog)
        self.files_panel.add(self.drop_zone, 1)
        self.files_panel.add(self.table, 1)
        self.table.hide()
        left.addWidget(self.files_panel, 1)
        self.options_panel = Panel("选项", 2)
        self.build_options(self.options_panel)
        left.addWidget(self.options_panel)
        right = QVBoxLayout()
        right.setSpacing(12)
        body.addLayout(right)
        self.output = OutputPanel("输出", 3, self.action_text, **self.output_kwargs())
        self.output.setFixedWidth(340)
        self.output.run_clicked.connect(self.run)
        right.addWidget(self.output)
        self.side = QVBoxLayout()
        right.addLayout(self.side)
        self.build_side(right)
        right.addStretch(1)

    def output_kwargs(self) -> dict:
        return {}

    def build_options(self, panel: Panel) -> None:  # override
        pass

    def build_side(self, layout: QVBoxLayout) -> None:  # override
        pass

    # -- files ------------------------------------------------------------------
    def add_files(self, paths: list[Path]) -> None:
        paths = collect_files(paths, kinds=self.kinds)
        if not paths:
            info(self, "没有可用的文件", "这个模块不支持这些文件类型。")
            return
        self.table.add_paths(paths, self.kinds)

    def add_files_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "添加文件", settings().get("last_dir", "") or "", self.file_filter)
        if files:
            settings().set("last_dir", str(Path(files[0]).parent))
            self.add_files([Path(f) for f in files])

    def add_folder_dialog(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "添加文件夹", settings().get("last_dir", "") or "")
        if d:
            settings().set("last_dir", d)
            self.add_files([Path(d)])

    def _files_changed(self) -> None:
        n = len(self.table.rows)
        self.table.setVisible(n > 0)
        self.drop_zone.setVisible(n == 0)
        self.files_panel.set_count(f"{n} 个文件" if n else "")
        self.output.set_enabled_run(n > 0)
        self.files_changed()

    def files_changed(self) -> None:  # override hook
        pass

    # -- running ---------------------------------------------------------------
    def run(self) -> None:
        if not self.table.rows:
            info(self, "没有文件", "先添加要处理的文件。")
            return
        if runner().busy:
            info(self, "正在处理", "等当前任务结束后再开始。")
            return
        job = self.make_job()
        if job is None:
            return
        self.table.reset_status()
        names = [r.path.name for r in self.table.rows]
        self._task_id = runner().submit(self.task_title(), job, kind=self.key, meta={"open": self.output.wants_open(), "files": names})

    def task_title(self) -> str:
        rows = self.table.rows
        return f"{self.title_text} {rows[0].path.name}" if len(rows) == 1 else f"{self.title_text} {len(rows)} 个文件"

    def make_job(self) -> Callable | None:  # override: return fn(progress, cancel) -> result
        return None

    def _on_finished(self, task_id: str, result) -> None:
        if task_id != self._task_id:
            return
        self._task_id = None
        self.on_finished(result)

    def on_finished(self, result) -> None:  # override
        pass

    def _on_failed(self, task_id: str, message: str, details: str) -> None:
        if task_id != self._task_id:
            return
        self._task_id = None
        ErrorDialog.show_error("处理失败", message, details, self)

    def _on_cancelled(self, task_id: str) -> None:
        if task_id == self._task_id:
            self._task_id = None

    def ask_password(self, path: Path) -> str | None:
        return PasswordDialog.ask(path.name, self)

    def finish_with_toast(self, title: str, subtitle: str, outputs: list[Path], open_folder: bool) -> None:
        self.window_ref.notify_result(title, subtitle, outputs, ok=bool(outputs))
        if open_folder and outputs:
            reveal_in_folder(outputs[0])


class RowUpdater:
    """Thread-safe helper: task code calls ``status(i, ...)`` and the table updates on the GUI thread."""

    def __init__(self, page: BatchPage) -> None:
        from PySide6.QtCore import QObject, Signal

        class _Bridge(QObject):
            sig = Signal(int, str, str, object)
            extra = Signal(int, str, str)

        self.bridge = _Bridge()
        self.bridge.sig.connect(lambda r, s, m, res: page.table.set_status(r, s, m, res))
        self.bridge.extra.connect(lambda r, c, t: page.table.set_extra(r, c, t, True))

    def status(self, r: int, status: str, message: str = "", result: Path | None = None) -> None:
        self.bridge.sig.emit(r, status, message, result)

    def extra(self, r: int, col: str, text: str) -> None:
        self.bridge.extra.emit(r, col, text)
