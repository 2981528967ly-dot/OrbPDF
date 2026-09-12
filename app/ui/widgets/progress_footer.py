"""Bottom status bar: robot, status text, progress, engine badge, task centre button."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from ...core.tasks.runner import runner
from .. import theme
from ..strings import strings, t
from .controls import button, label
from .robot import RobotWidget


class ProgressFooter(QWidget):
    tasks_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Footer")
        self.setFixedHeight(38)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(12)
        self.robot = RobotWidget(26)
        lay.addWidget(self.robot)
        self.status = QLabel(t("status_ready"))
        lay.addWidget(self.status)
        self.detail = label("", "Small")
        lay.addWidget(self.detail, 1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setFixedWidth(180)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.cancel_btn = button("取消", None, "Small", on_click=lambda: runner().cancel())
        self.cancel_btn.setVisible(False)
        lay.addWidget(self.cancel_btn)
        self.engine = label("", "Small")
        lay.addWidget(self.engine)
        self.tasks_btn = button(t("tasks"), "task", "Small", on_click=self.tasks_clicked.emit)
        lay.addWidget(self.tasks_btn)
        r = runner()
        r.task_started.connect(self._on_started)
        r.task_progress.connect(self._on_progress)
        r.task_finished.connect(self._on_done)
        r.task_failed.connect(self._on_failed)
        r.task_cancelled.connect(self._on_cancelled)
        r.history_changed.connect(self._refresh_tasks)
        strings().changed.connect(self._retranslate)
        self._idle_text = ""
        self._refresh_tasks()

    def set_idle_text(self, text: str) -> None:
        self._idle_text = text
        if not runner().busy:
            self.status.setText(t("status_ready") + (f" · {text}" if text else ""))

    def set_engine_text(self, text: str) -> None:
        self.engine.setText(text)

    def _retranslate(self) -> None:
        self.tasks_btn.setText(t("tasks"))
        self.set_idle_text(self._idle_text)

    def _refresh_tasks(self) -> None:
        n = sum(1 for rec in runner().records.values() if rec.status in ("queued", "running"))
        self.tasks_btn.setText(f"{t('tasks')} ({n})" if n else t("tasks"))

    def _on_started(self, task_id: str) -> None:
        rec = runner().record(task_id)
        self.robot.set_working(True)
        self.status.setText(f"{t('status_working')} · {rec.title if rec else ''}")
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.cancel_btn.setVisible(True)
        self.detail.setText("")

    def _on_progress(self, _task_id: str, fraction: float, message: str) -> None:
        self.bar.setValue(int(fraction * 1000))
        if message:
            self.detail.setText(message)

    def _finish(self, text: str, name: str = "Small") -> None:
        self.robot.set_working(False)
        self.bar.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.status.setText(t("status_ready") + (f" · {self._idle_text}" if self._idle_text else ""))
        self.detail.setText(text)
        self.detail.setObjectName(name)
        self.detail.style().unpolish(self.detail)
        self.detail.style().polish(self.detail)

    def _on_done(self, task_id: str, _result) -> None:
        rec = runner().record(task_id)
        self._finish(f"上次任务：{rec.title} · {rec.duration:.1f} 秒" if rec else "")

    def _on_failed(self, task_id: str, message: str, _details: str) -> None:
        self._finish(f"失败：{message}", "Danger")

    def _on_cancelled(self, _task_id: str) -> None:
        self._finish("已取消")
