"""Single background worker that runs long jobs one after another and reports through Qt signals."""
from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from ..convert.base import ConvertCancelled, ConvertError, NeedsPassword

LOG = logging.getLogger("orbpdf.tasks")

TaskFn = Callable[[Callable[[float, str], None], Callable[[], bool]], Any]


@dataclass
class TaskRecord:
    id: str
    title: str
    kind: str
    status: str = "queued"       # queued | running | done | failed | cancelled
    result: Any = None
    error: str = ""
    details: str = ""
    started: float = 0.0
    finished: float = 0.0
    outputs: list = field(default_factory=list)   # paths produced (for the task centre)
    meta: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        if not self.started:
            return 0.0
        return (self.finished or time.time()) - self.started


class _Worker(QThread):
    progress = Signal(str, float, str)
    started_task = Signal(str)
    finished_task = Signal(str, object)
    failed_task = Signal(str, str, str)
    cancelled_task = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.queue: "queue.Queue[tuple[str, TaskFn, threading.Event] | None]" = queue.Queue()
        self._stop = False
        self.current_id: str | None = None
        self.current_cancel: threading.Event | None = None

    def run(self) -> None:  # noqa: C901
        while not self._stop:
            item = self.queue.get()
            if item is None:
                break
            task_id, fn, cancel_event = item
            self.current_id = task_id
            self.current_cancel = cancel_event
            if cancel_event.is_set():
                self.cancelled_task.emit(task_id)
                continue
            self.started_task.emit(task_id)

            def report(fraction: float, message: str = "", _tid=task_id) -> None:
                self.progress.emit(_tid, float(fraction), str(message))

            def is_cancelled(_ev=cancel_event) -> bool:
                return _ev.is_set()

            try:
                result = fn(report, is_cancelled)
                if cancel_event.is_set():
                    self.cancelled_task.emit(task_id)
                else:
                    self.finished_task.emit(task_id, result)
            except ConvertCancelled:
                self.cancelled_task.emit(task_id)
            except NeedsPassword as e:
                self.failed_task.emit(task_id, str(e), "")
            except ConvertError as e:
                LOG.warning("task %s failed: %s", task_id, e)
                self.failed_task.emit(task_id, str(e), "")
            except Exception as e:  # noqa: BLE001
                LOG.exception("task %s crashed", task_id)
                self.failed_task.emit(task_id, f"{type(e).__name__}: {e}", traceback.format_exc())
            finally:
                self.current_id = None
                self.current_cancel = None

    def stop(self) -> None:
        self._stop = True
        self.queue.put(None)


class TaskRunner(QObject):
    """Facade living in the GUI thread."""
    task_started = Signal(str)
    task_progress = Signal(str, float, str)
    task_finished = Signal(str, object)
    task_failed = Signal(str, str, str)
    task_cancelled = Signal(str)
    busy_changed = Signal(bool)
    history_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.records: dict[str, TaskRecord] = {}
        self.order: list[str] = []
        self._cancel_events: dict[str, threading.Event] = {}
        self._worker = _Worker()
        self._worker.progress.connect(self._on_progress)
        self._worker.started_task.connect(self._on_started)
        self._worker.finished_task.connect(self._on_finished)
        self._worker.failed_task.connect(self._on_failed)
        self._worker.cancelled_task.connect(self._on_cancelled)
        self._worker.start()
        self._running = 0

    # -- submit / cancel ---------------------------------------------------
    def submit(self, title: str, fn: TaskFn, kind: str = "task", meta: dict | None = None) -> str:
        task_id = uuid.uuid4().hex[:10]
        rec = TaskRecord(task_id, title, kind, meta=meta or {})
        self.records[task_id] = rec
        self.order.append(task_id)
        del self.order[:-50]
        ev = threading.Event()
        self._cancel_events[task_id] = ev
        self._worker.queue.put((task_id, fn, ev))
        self.history_changed.emit()
        return task_id

    def cancel(self, task_id: str | None = None) -> None:
        if task_id is None:
            task_id = self._worker.current_id
        if task_id and task_id in self._cancel_events:
            self._cancel_events[task_id].set()
            rec = self.records.get(task_id)
            if rec and rec.status == "queued":
                rec.status = "cancelled"
                self.history_changed.emit()

    def cancel_all(self) -> None:
        for tid, ev in list(self._cancel_events.items()):
            ev.set()

    @property
    def busy(self) -> bool:
        return self._running > 0 or not self._worker.queue.empty()

    @property
    def current_id(self) -> str | None:
        return self._worker.current_id

    def record(self, task_id: str) -> TaskRecord | None:
        return self.records.get(task_id)

    def shutdown(self) -> None:
        self.cancel_all()
        self._worker.stop()
        self._worker.wait(3000)

    # -- worker callbacks ------------------------------------------------
    def _on_started(self, task_id: str) -> None:
        rec = self.records.get(task_id)
        if rec:
            rec.status = "running"
            rec.started = time.time()
        self._running = 1
        self.busy_changed.emit(True)
        self.task_started.emit(task_id)
        self.history_changed.emit()

    def _on_progress(self, task_id: str, fraction: float, message: str) -> None:
        self.task_progress.emit(task_id, fraction, message)

    def _done(self, task_id: str, status: str) -> None:
        rec = self.records.get(task_id)
        if rec:
            rec.status = status
            rec.finished = time.time()
        self._cancel_events.pop(task_id, None)
        self._running = 0
        self.busy_changed.emit(self.busy)
        self.history_changed.emit()

    def _on_finished(self, task_id: str, result: object) -> None:
        rec = self.records.get(task_id)
        if rec:
            rec.result = result
        self._done(task_id, "done")
        self.task_finished.emit(task_id, result)

    def _on_failed(self, task_id: str, message: str, details: str) -> None:
        rec = self.records.get(task_id)
        if rec:
            rec.error = message
            rec.details = details
        self._done(task_id, "failed")
        self.task_failed.emit(task_id, message, details)

    def _on_cancelled(self, task_id: str) -> None:
        self._done(task_id, "cancelled")
        self.task_cancelled.emit(task_id)


_runner: TaskRunner | None = None


def runner() -> TaskRunner:
    global _runner
    if _runner is None:
        _runner = TaskRunner()
    return _runner
