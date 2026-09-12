"""Task centre: recent jobs, what files they touched, live durations, open / folder for every result."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ...core.tasks.runner import TaskRecord, runner
from ..widgets.controls import Pill, button, label
from ..widgets.result_card import open_path, reveal_in_folder

_STATUS = {"queued": ("排队中", "mute"), "running": ("进行中", "busy"), "done": ("完成", "ok"), "failed": ("失败", "err"), "cancelled": ("已取消", "mute")}


def _collect_paths(obj, out: list[Path], depth: int = 0) -> None:
    if obj is None or depth > 4:
        return
    if isinstance(obj, Path):
        out.append(obj)
    elif isinstance(obj, str):
        if len(obj) < 400 and ("\\" in obj or "/" in obj):
            p = Path(obj)
            if p.suffix:
                out.append(p)
    elif isinstance(obj, dict):
        for key in ("outputs", "path", "dst", "pdf_path", "results"):
            if key in obj:
                _collect_paths(obj[key], out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            _collect_paths(x, out, depth + 1)
    else:
        for attr in ("path", "dst", "pdf_path"):
            if hasattr(obj, attr):
                _collect_paths(getattr(obj, attr), out, depth + 1)


def outputs_of(rec: TaskRecord) -> list[Path]:
    found: list[Path] = []
    _collect_paths(rec.result, found)
    seen: set[str] = set()
    out: list[Path] = []
    for p in found:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        if p.exists():
            out.append(p)
    return out


def _files_line(rec: TaskRecord) -> str:
    names = [str(n) for n in (rec.meta or {}).get("files", []) if n]
    if not names:
        return ""
    text = " · ".join(names[:4])
    if len(names) > 4:
        text += f" 等 {len(names)} 个"
    return text if len(text) <= 70 else text[:68] + "…"


class TaskCenterDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("任务")
        self.resize(620, 460)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label("最近的任务", "PanelTitle"))
        self.summary = label("", "Muted")
        top.addWidget(self.summary)
        top.addStretch(1)
        top.addWidget(button("取消当前任务", None, "Small", on_click=lambda: runner().cancel()))
        lay.addLayout(top)
        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        self.list_layout = QVBoxLayout(inner)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch(1)
        area.setWidget(inner)
        lay.addWidget(area, 1)
        self._live: list[tuple[TaskRecord, QLabel, Pill]] = []
        self._fill()
        runner().history_changed.connect(self._fill)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _status_text(self, rec: TaskRecord) -> str:
        if rec.status == "running":
            return f"进行中 · {rec.duration:.0f} 秒"
        if rec.status == "queued":
            return "排队中"
        if rec.error:
            return rec.error
        if rec.status == "done":
            return f"用时 {rec.duration:.1f} 秒"
        return ""

    def _tick(self) -> None:
        active = 0
        for rec, lbl, pill in self._live:
            if rec.status in ("running", "queued"):
                active += 1
                lbl.setText(self._status_text(rec))
        self.summary.setText(f"{active} 个进行中" if active else "")

    def _fill(self) -> None:
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._live = []
        recs = [runner().records[i] for i in reversed(runner().order) if i in runner().records]
        if not recs:
            self.list_layout.insertWidget(0, label("还没有任务。", "Muted"))
            return
        for rec in recs[:40]:
            card = QFrame()
            card.setObjectName("Card")
            h = QHBoxLayout(card)
            h.setContentsMargins(12, 8, 12, 8)
            h.setSpacing(10)
            text, kind = _STATUS.get(rec.status, (rec.status, "mute"))
            pill = Pill(text, kind)
            h.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(label(rec.title, "Strong"))
            files = _files_line(rec)
            if files:
                fl = label(files, "Muted", wrap=True)
                fl.setToolTip("\n".join(str(n) for n in (rec.meta or {}).get("files", [])))
                col.addWidget(fl)
            status_lbl = label(self._status_text(rec), "Small", wrap=True)
            col.addWidget(status_lbl)
            h.addLayout(col, 1)
            paths = outputs_of(rec)
            if paths:
                first = paths[0]
                open_btn = button("打开", "open", "Small", "打开 " + first.name, on_click=lambda _=False, p=first: open_path(p))
                folder_btn = button("文件夹", "folder-open", "Small", str(first.parent), on_click=lambda _=False, p=first: reveal_in_folder(p))
                h.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignTop)
                h.addWidget(folder_btn, 0, Qt.AlignmentFlag.AlignTop)
            self._live.append((rec, status_lbl, pill))
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)
        self._tick()
