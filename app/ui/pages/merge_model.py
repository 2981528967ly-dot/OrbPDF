"""Merge queue model + background pre-conversion worker."""
from __future__ import annotations

import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ...core.convert.base import ConvertCancelled, ConvertError, ConvertOptions, NeedsPassword
from ...core.convert.registry import default_options, registry
from ...core.fileinfo import KIND_BLANK, KIND_DIVIDER, KIND_IMAGE, KIND_PDF, kind_of, kind_label, KIND_ORBS
from ...core.pdf.info import open_pdf, parse_page_range
from ...core.pdf.merge import MergeSource
from ...core.pdf.render import render_page_png

LOG = logging.getLogger("orbpdf.merge")

STATUS_LABELS = {"pending": "待处理", "converting": "转换中", "ready": "就绪", "error": "出错"}


@dataclass
class MergeItem:
    id: str
    kind: str
    path: Path | None
    display_name: str
    page_range: str = ""
    page_indices: list[int] | None = None
    fit: str | None = None                # image fit override
    password: str | None = None
    status: str = "pending"
    pages: int = 0                        # pages after range selection
    total_pages: int = 0                  # pages in the converted PDF
    pdf_path: Path | None = None
    engine_name: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    needs_password: bool = False
    thumb_png: bytes | None = None
    size_bytes: int = 0
    in_toc: bool = True
    rotation: int = 0                     # 0/90/180/270, applied to all pages of the item
    pos: tuple[float, float] | None = None   # canvas position (None = auto place)

    @property
    def orb(self) -> str:
        return KIND_ORBS.get(self.kind, "blue")

    @property
    def kind_text(self) -> str:
        return kind_label(self.kind)

    @property
    def is_special(self) -> bool:
        return self.kind in (KIND_BLANK, KIND_DIVIDER)

    @property
    def status_text(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


class ConvertWorker(QThread):
    converted = Signal(str, object)     # item id, dict
    failed = Signal(str, str, bool)     # item id, message, needs_password

    def __init__(self) -> None:
        super().__init__()
        self.queue: "queue.Queue[tuple[str, Path, ConvertOptions, str | None] | None]" = queue.Queue()
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def enqueue(self, item_id: str, path: Path, opts: ConvertOptions, password: str | None) -> None:
        with self._lock:
            self._cancelled.discard(item_id)
        self.queue.put((item_id, path, opts, password))

    def cancel(self, item_id: str) -> None:
        with self._lock:
            self._cancelled.add(item_id)

    def stop(self) -> None:
        self.queue.put(None)

    def _is_cancelled(self, item_id: str) -> bool:
        with self._lock:
            return item_id in self._cancelled

    def run(self) -> None:
        reg = registry()
        while True:
            job = self.queue.get()
            if job is None:
                break
            item_id, path, opts, password = job
            if self._is_cancelled(item_id):
                continue
            try:
                opts.password = password
                res = reg.convert(path, None, opts, cancel=lambda: self._is_cancelled(item_id))
                if self._is_cancelled(item_id):
                    continue
                thumb = None
                try:
                    doc = open_pdf(res.pdf_path, password)
                    try:
                        thumb = render_page_png(doc, 0, 360)
                    finally:
                        doc.close()
                except Exception:
                    thumb = None
                self.converted.emit(item_id, {"pdf_path": res.pdf_path, "pages": res.pages, "engine_name": res.engine_name,
                                              "warnings": res.warnings, "thumb": thumb})
            except ConvertCancelled:
                continue
            except NeedsPassword as e:
                self.failed.emit(item_id, str(e), True)
            except ConvertError as e:
                self.failed.emit(item_id, str(e), False)
            except Exception as e:  # noqa: BLE001
                LOG.exception("pre-conversion crashed for %s", path)
                self.failed.emit(item_id, f"{type(e).__name__}: {e}", False)
            finally:
                if self.queue.empty():
                    try:
                        reg.end_batch()
                    except Exception:
                        pass


class MergeModel(QObject):
    changed = Signal()
    item_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.items: list[MergeItem] = []
        self.worker = ConvertWorker()
        self.worker.converted.connect(self._on_converted)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    # -- queries ---------------------------------------------------------
    def get(self, item_id: str) -> MergeItem | None:
        for it in self.items:
            if it.id == item_id:
                return it
        return None

    def index_of(self, item_id: str) -> int:
        for i, it in enumerate(self.items):
            if it.id == item_id:
                return i
        return -1

    def total_pages(self) -> int:
        return sum(it.pages for it in self.items)

    def count_status(self, status: str) -> int:
        return sum(1 for it in self.items if it.status == status)

    def real_items(self) -> list[MergeItem]:
        return [it for it in self.items if not it.is_special]

    # -- mutations -------------------------------------------------------
    def add_paths(self, paths: list[Path], at: int | None = None) -> list[str]:
        ids: list[str] = []
        pos = len(self.items) if at is None else max(0, min(at, len(self.items)))
        for p in paths:
            kind = kind_of(p)
            if kind is None:
                continue
            item = MergeItem(uuid.uuid4().hex[:8], kind, Path(p), Path(p).stem)
            item.pos = None
            try:
                item.size_bytes = Path(p).stat().st_size
            except OSError:
                pass
            self.items.insert(pos, item)
            pos += 1
            ids.append(item.id)
            self._queue_conversion(item)
        if ids:
            self.changed.emit()
        return ids

    def add_special(self, kind: str, at: int | None = None, name: str | None = None) -> str:
        pos = len(self.items) if at is None else max(0, min(at, len(self.items)))
        if name is None:
            name = "空白页" if kind == KIND_BLANK else "分隔页"
        item = MergeItem(uuid.uuid4().hex[:8], kind, None, name, status="ready", pages=1, total_pages=1, in_toc=(kind == KIND_DIVIDER))
        self.items.insert(pos, item)
        self.changed.emit()
        return item.id

    def remove(self, ids: list[str]) -> None:
        idset = set(ids)
        for it in self.items:
            if it.id in idset:
                self.worker.cancel(it.id)
        self.items = [it for it in self.items if it.id not in idset]
        self.changed.emit()

    def clear(self) -> None:
        for it in self.items:
            self.worker.cancel(it.id)
        self.items = []
        self.changed.emit()

    def move(self, item_id: str, gap: int) -> None:
        """Move item so that it sits at insertion gap ``gap`` (0..len)."""
        i = self.index_of(item_id)
        if i < 0:
            return
        it = self.items.pop(i)
        if gap > i:
            gap -= 1
        gap = max(0, min(gap, len(self.items)))
        self.items.insert(gap, it)
        self.changed.emit()

    def move_by(self, item_id: str, delta: int) -> None:
        i = self.index_of(item_id)
        if i < 0:
            return
        j = max(0, min(len(self.items) - 1, i + delta))
        if j == i:
            return
        it = self.items.pop(i)
        self.items.insert(j, it)
        self.changed.emit()

    def sort_by_name(self) -> None:
        from ...core.fileinfo import natural_key
        self.items.sort(key=lambda it: natural_key(it.display_name))
        self.changed.emit()

    def rename(self, item_id: str, name: str) -> None:
        it = self.get(item_id)
        if it and name.strip() and it.display_name != name.strip():
            it.display_name = name.strip()
            self.item_changed.emit(item_id)

    def batch_rename(self, pattern: str, start: int = 1) -> None:
        """pattern with {n} and optional {name}; e.g. '发票{n}'."""
        n = start
        for it in self.items:
            if it.is_special:
                continue
            it.display_name = pattern.replace("{n}", str(n)).replace("{name}", it.path.stem if it.path else it.display_name)
            n += 1
        self.changed.emit()

    def restore_names(self) -> None:
        for it in self.items:
            if it.path:
                it.display_name = it.path.stem
        self.changed.emit()

    def set_range(self, item_id: str, spec: str) -> str | None:
        """Returns an error message or None."""
        it = self.get(item_id)
        if not it or it.kind != KIND_PDF:
            return None
        try:
            idx = parse_page_range(spec, it.total_pages or 1)
        except ValueError as e:
            return str(e)
        it.page_range = spec.strip()
        it.page_indices = idx
        it.pages = len(idx) if idx else it.total_pages
        self.item_changed.emit(item_id)
        return None

    def rotate(self, item_id: str, delta: int) -> None:
        it = self.get(item_id)
        if it and not it.is_special:
            it.rotation = (it.rotation + delta) % 360
            self.item_changed.emit(item_id)

    def set_pos(self, item_id: str, x: float, y: float) -> None:
        it = self.get(item_id)
        if it:
            it.pos = (x, y)

    def set_in_toc(self, item_id: str, on: bool) -> None:
        it = self.get(item_id)
        if it:
            it.in_toc = on
            self.item_changed.emit(item_id)

    def set_fit(self, item_id: str, fit: str | None) -> None:
        it = self.get(item_id)
        if it and it.kind == KIND_IMAGE and it.fit != fit:
            it.fit = fit
            self._queue_conversion(it)
            self.item_changed.emit(item_id)

    def set_password(self, item_id: str, password: str) -> None:
        it = self.get(item_id)
        if it:
            it.password = password
            it.needs_password = False
            self._queue_conversion(it)
            self.item_changed.emit(item_id)

    def reconvert(self, item_id: str) -> None:
        it = self.get(item_id)
        if it and not it.is_special:
            self._queue_conversion(it)
            self.item_changed.emit(item_id)

    def reconvert_all_images(self) -> None:
        for it in self.items:
            if it.kind == KIND_IMAGE and it.fit is None:
                self._queue_conversion(it)
                self.item_changed.emit(it.id)

    # -- conversion --------------------------------------------------------
    def options_for(self, it: MergeItem) -> ConvertOptions:
        opts = default_options()
        if it.fit:
            opts.image_fit = it.fit
        return opts

    def _queue_conversion(self, it: MergeItem) -> None:
        if it.is_special or not it.path:
            return
        it.status = "converting"
        it.error = ""
        it.pdf_path = None
        self.worker.enqueue(it.id, it.path, self.options_for(it), it.password)

    def _on_converted(self, item_id: str, info: dict) -> None:
        it = self.get(item_id)
        if not it:
            return
        it.pdf_path = Path(info["pdf_path"])
        it.total_pages = int(info["pages"])
        it.engine_name = info.get("engine_name", "")
        it.warnings = list(info.get("warnings", []))
        it.thumb_png = info.get("thumb")
        it.status = "ready"
        it.needs_password = False
        if it.page_range:
            err = self.set_range(item_id, it.page_range)
            if err:
                it.page_range = ""
                it.page_indices = None
        if not it.page_indices:
            it.pages = it.total_pages
        self.item_changed.emit(item_id)

    def _on_failed(self, item_id: str, message: str, needs_password: bool) -> None:
        it = self.get(item_id)
        if not it:
            return
        it.status = "error"
        it.error = message
        it.needs_password = needs_password
        it.pages = 0
        self.item_changed.emit(item_id)

    # -- export ----------------------------------------------------------
    def to_sources(self, skip_errors: bool = False) -> list[MergeSource]:
        out: list[MergeSource] = []
        for it in self.items:
            if it.is_special:
                out.append(MergeSource(it.display_name, it.kind, None, None, None, "", it.in_toc))
                continue
            if it.status != "ready" or not it.pdf_path:
                if skip_errors and it.status == "error":
                    continue
                raise ConvertError(f"「{it.display_name}」尚未就绪（{it.status_text}{'：' + it.error if it.error else ''}）")
            out.append(MergeSource(it.display_name, it.kind, it.pdf_path, it.page_indices, it.password,
                                   it.path.name if it.path else "", it.in_toc, it.rotation))
        return out

    def shutdown(self) -> None:
        self.worker.stop()
        self.worker.wait(2000)
