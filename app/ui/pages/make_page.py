"""生成 — drop anything, get a PDF. One PDF (with TOC) or one per file, arranged on a node canvas."""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf
from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtGui import QImage, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QGraphicsProxyWidget, QHBoxLayout, QLineEdit, QMenu, QPushButton,
                               QToolButton, QVBoxLayout, QWidget, QFrame, QLabel)

from ...core.convert.base import ConvertCancelled, ConvertError
from ...core.convert.registry import default_options, registry
from ...core.fileinfo import KIND_BLANK, KIND_DIVIDER, KIND_PDF, collect_files, human_size
from ...core.naming import default_merge_name, sanitize_filename, unique_path
from ...core.paths import session_dir
from ...core.pdf.merge import MergeOptions, merge
from ...core.pdf.toc import TocEntry, TocSpec, insert_toc_pages, toc_page_count
from ...core.settings import settings
from ...core.tasks.runner import runner
from ..dialogs.batch_rename import BatchRenameDialog
from ..dialogs.common import ErrorDialog, PasswordDialog, confirm, info
from ..dialogs.page_range import PageRangeDialog
from ..strings import strings, t
from ..widgets.canvas import Canvas, HEADER_H, NODE_W
from ..widgets.controls import Segmented, button, hbox, label
from ..widgets.drop import DropMixin, clipboard_paths_or_image
from ..widgets.result_card import open_path, reveal_in_folder
from .merge_model import MergeModel

LOG = logging.getLogger("orbpdf.ui.make")
A4 = (595.28, 841.89)


class MakePage(QWidget, DropMixin):
    key = "make"

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ref = window
        self.setObjectName("Page")
        self._init_drop()
        self.model = MergeModel()
        self._pending_export: str | None = None
        self._filename_touched = False
        self._build()
        self._wire()
        strings().changed.connect(self._retranslate)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._render_preview)
        runner().task_finished.connect(self._on_task_finished)
        runner().task_failed.connect(self._on_task_failed)
        self._refresh()

    # -- build ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.canvas = Canvas()
        root.addWidget(self.canvas, 1)
        # floating toolbar over the canvas
        self.bar = QFrame(self.canvas)
        self.bar.setObjectName("Panel")
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(10, 6, 10, 6)
        bl.setSpacing(6)
        self.title_lbl = label("生成", "ModuleTitle")
        bl.addWidget(self.title_lbl)
        bl.addSpacing(6)
        self.btn_add = button(t("add_files"), "add", on_click=lambda: self.add_files_dialog(None))
        self.btn_folder = button(t("add_folder"), "folder", on_click=lambda: self.add_folder_dialog(None))
        self.btn_paste = button("", "paste", "IconBtn", t("paste") + "（文件或截图）", on_click=lambda: self.paste(None))
        bl.addWidget(self.btn_add)
        bl.addWidget(self.btn_folder)
        bl.addWidget(self.btn_paste)
        bl.addSpacing(8)
        self.mode = Segmented([("merge", "合成一个"), ("each", "各自一个")], "merge")
        self.mode.setToolTip("合成一个：所有文件串成一个 PDF\n各自一个：每个文件单独转成 PDF")
        bl.addWidget(self.mode)
        bl.addSpacing(8)
        bl.addWidget(button("", "grid", "IconBtn", "整理排列", on_click=self.canvas.tidy))
        bl.addWidget(button("", "zoom-out", "IconBtn", "适应窗口", on_click=self.canvas.fit_all))
        self.btn_more = button("", "more", "IconBtn", "更多", on_click=self._more_menu)
        bl.addWidget(self.btn_more)
        self.btn_clear = button("", "trash", "IconBtn", t("clear"), on_click=self.clear)
        bl.addWidget(self.btn_clear)
        self.bar.move(14, 12)
        self.bar.adjustSize()
        self.bar.raise_()

        # --- start node widgets (live inside the node) ---
        s = settings()
        start = self.canvas.start
        self.title_edit = QLineEdit(s.get("last_toc_title", "") or "")
        self.title_edit.setPlaceholderText("目录标题")
        self.title_edit.setFixedWidth(int(NODE_W - 28))
        self.title_edit.setFixedHeight(26)
        self._proxy(start, self.title_edit, 14, HEADER_H + 8)
        chips = QWidget()
        chips.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        chips.setStyleSheet("background: transparent;")
        cl = QHBoxLayout(chips)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(3)
        self.chip_toc = self._chip("目录", "首页生成目录页，条目可点击跳转", bool(s.get("toc_enabled", True)))
        self.chip_bm = self._chip("书签", "写入 PDF 书签（阅读器左侧大纲）", bool(s.get("bookmarks", True)))
        self.chip_div = self._chip("分隔", "每份文件前加一页标题页", bool(s.get("dividers", False)))
        self.chip_pn = self._chip("页码", "页脚加页码", bool(s.get("page_numbers", False)))
        for c in (self.chip_toc, self.chip_bm, self.chip_div, self.chip_pn):
            cl.addWidget(c)
        chips.setFixedWidth(int(NODE_W - 28))
        self._proxy(start, chips, 14, HEADER_H + 44)

        # --- end node widgets ---
        end = self.canvas.end
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("文件名")
        self.filename_edit.setFixedWidth(int(NODE_W - 28))
        self.filename_edit.setFixedHeight(26)
        self._proxy(end, self.filename_edit, 14, HEADER_H + 8)
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self.folder_btn = QToolButton()
        self.folder_btn.setText("同源文件夹 ▾")
        self.folder_btn.setToolTip("输出到哪里")
        self.folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_btn.clicked.connect(self._folder_menu)
        rl.addWidget(self.folder_btn)
        self.open_after = QCheckBox("打开")
        self.open_after.setToolTip("完成后打开所在文件夹")
        self.open_after.setChecked(bool(s.get("open_after", True)))
        rl.addWidget(self.open_after)
        rl.addStretch(1)
        row.setFixedWidth(int(NODE_W - 28))
        self._proxy(end, row, 14, HEADER_H + 42)
        self.export_btn = QPushButton(t("export"))
        self.export_btn.setObjectName("PrimaryBig")
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn.setFixedWidth(int(NODE_W - 28))
        self.export_btn.setFixedHeight(40)
        self.export_btn.clicked.connect(self.export)
        self._proxy(end, self.export_btn, 14, HEADER_H + 82)
        self.custom_dir: Path | None = Path(s.get("output_dir")) if s.get("output_mode") == "custom" and s.get("output_dir") else None
        self._update_folder_btn()

        self.canvas.set_model(self.model)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=lambda: self.add_files_dialog(None))
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.export)
        QShortcut(QKeySequence("Ctrl+V"), self.canvas, activated=lambda: self.paste(None))

    def _proxy(self, node, widget: QWidget, x: float, y: float) -> QGraphicsProxyWidget:
        proxy = QGraphicsProxyWidget(node)
        proxy.setWidget(widget)
        proxy.setPos(x, y)
        proxy.setZValue(5)
        return proxy

    def _chip(self, text: str, tip: str, on: bool) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(True)
        b.setChecked(on)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedSize(43, 24)
        b.toggled.connect(self._options_changed)
        return b

    def _wire(self) -> None:
        c = self.canvas
        c.rename_requested.connect(self.model.rename)
        c.insert_files_requested.connect(self.add_files_dialog)
        c.insert_folder_requested.connect(self.add_folder_dialog)
        c.insert_paste_requested.connect(self.paste)
        c.insert_special_requested.connect(lambda gap, kind: self.model.add_special(kind, gap))
        c.files_dropped.connect(lambda paths, gap: self.add_files(paths, gap))
        c.reorder_requested.connect(self.model.move)
        c.remove_requested.connect(self.model.remove)
        c.range_requested.connect(self.pick_range)
        c.fit_requested.connect(self.model.set_fit)
        c.password_requested.connect(self.ask_password)
        c.reconvert_requested.connect(self.model.reconvert)
        c.rotate_requested.connect(self.model.rotate)
        c.toc_toggled_requested.connect(self.model.set_in_toc)
        c.duplicate_requested.connect(self.duplicate)
        c.open_source_requested.connect(lambda iid: open_path(self.model.get(iid).path) if self.model.get(iid) and self.model.get(iid).path else None)
        c.reveal_source_requested.connect(lambda iid: reveal_in_folder(self.model.get(iid).path) if self.model.get(iid) and self.model.get(iid).path else None)
        c.export_requested.connect(self.export)
        c.batch_rename_requested.connect(self.batch_rename)
        c.start_clicked.connect(lambda: self.title_edit.setFocus())
        self.model.changed.connect(self._refresh)
        self.model.item_changed.connect(lambda _id: self._refresh_summary())
        self.title_edit.textChanged.connect(self._title_changed)
        self.filename_edit.textEdited.connect(lambda _t: setattr(self, "_filename_touched", True))
        self.mode.changed.connect(lambda _k: self._refresh_summary())
        self.open_after.toggled.connect(lambda on: settings().set("open_after", on))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.bar.move(14, 12)

    def _retranslate(self) -> None:
        self.btn_add.setText(t("add_files"))
        self.btn_folder.setText(t("add_folder"))
        self.export_btn.setText(t("export"))
        self.canvas.viewport().update()

    # -- files -------------------------------------------------------------------
    def add_files(self, paths: list[Path], at: int | None = None) -> None:
        paths = collect_files(paths)
        if not paths:
            info(self, "没有可用的文件", "支持 PDF、Word、PPT、Excel、图片和文本。")
            return
        self.model.add_paths(paths, at)
        self._auto_names()

    def add_files_dialog(self, at: int | None = None) -> None:
        filt = "所有支持的文件 (*.pdf *.docx *.doc *.pptx *.ppt *.xlsx *.xls *.csv *.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp *.txt *.md *.html);;所有文件 (*.*)"
        files, _ = QFileDialog.getOpenFileNames(self, "添加文件", settings().get("last_dir", "") or "", filt)
        if files:
            settings().set("last_dir", str(Path(files[0]).parent))
            self.add_files([Path(f) for f in files], at)

    def add_folder_dialog(self, at: int | None = None) -> None:
        d = QFileDialog.getExistingDirectory(self, "添加文件夹（按文件名自然排序）", settings().get("last_dir", "") or "")
        if d:
            settings().set("last_dir", d)
            self.add_files([Path(d)], at)

    def paste(self, at: int | None = None) -> None:
        paths = clipboard_paths_or_image(session_dir() / "clipboard")
        if not paths:
            info(self, "剪贴板里没有文件", "先复制文件或截图，再点粘贴。")
            return
        self.add_files(paths, at)

    def clear(self) -> None:
        if self.model.items and confirm(self, "清空画布", "移除全部卡片？不会删除原文件。", "清空", danger=True):
            self.model.clear()

    def duplicate(self, item_id: str) -> None:
        it = self.model.get(item_id)
        if not it:
            return
        idx = self.model.index_of(item_id)
        if it.is_special:
            self.model.add_special(it.kind, idx + 1, it.display_name)
        elif it.path:
            ids = self.model.add_paths([it.path], idx + 1)
            if ids:
                self.model.rename(ids[0], it.display_name + " (副本)")
                if it.page_range:
                    self.model.set_range(ids[0], it.page_range)

    def batch_rename(self) -> None:
        names = [it.path.stem for it in self.model.real_items() if it.path]
        d = BatchRenameDialog(names, self)
        if d.exec() == QDialog.DialogCode.Accepted:
            pat, start = d.values()
            self.model.batch_rename(pat, start)

    def pick_range(self, item_id: str) -> None:
        it = self.model.get(item_id)
        if not it or not it.pdf_path:
            info(self, "还没准备好", "等这个文件转换完成后再选页面。")
            return
        try:
            d = PageRangeDialog(it.pdf_path, it.page_range, it.password, self)
        except Exception as e:  # noqa: BLE001
            ErrorDialog.show_error("无法打开", str(e), parent=self)
            return
        if d.exec() == QDialog.DialogCode.Accepted:
            err = self.model.set_range(item_id, d.result_spec)
            if err:
                ErrorDialog.show_error("页面范围无效", err, parent=self)

    def ask_password(self, item_id: str) -> None:
        it = self.model.get(item_id)
        if not it:
            return
        pw = PasswordDialog.ask(it.path.name if it.path else it.display_name, self)
        if pw:
            self.model.set_password(item_id, pw)

    def _more_menu(self) -> None:
        s = settings()
        m = QMenu(self)
        m.addAction("批量重命名…").triggered.connect(self.batch_rename)
        m.addAction("恢复为文件名").triggered.connect(self.model.restore_names)
        m.addAction("按名称排序").triggered.connect(self.model.sort_by_name)
        m.addSeparator()
        m.addAction("末尾加空白页").triggered.connect(lambda: self.model.add_special(KIND_BLANK))
        m.addAction("末尾加分隔页").triggered.connect(lambda: self.model.add_special(KIND_DIVIDER))
        m.addSeparator()
        adv = m.addMenu("高级")
        a = adv.addAction("目录显示原文件名")
        a.setCheckable(True)
        a.setChecked(bool(s.get("toc_show_source", False)))
        a.triggered.connect(lambda on: (s.set("toc_show_source", bool(on)), self._refresh_summary()))
        a2 = adv.addAction("全部统一为 A4")
        a2.setCheckable(True)
        a2.setChecked(s.get("page_size_mode", "keep") == "a4")
        a2.triggered.connect(lambda on: s.set("page_size_mode", "a4" if on else "keep"))
        fit = adv.addMenu("图片页面")
        for key, text in (("bleed", "无白边（默认）"), ("a4", "适配 A4 留边"), ("original", "原始尺寸")):
            act = fit.addAction(text)
            act.setCheckable(True)
            act.setChecked(s.get("image_fit", "bleed") == key)
            act.triggered.connect(lambda _=False, k=key: (s.set("image_fit", k), self.model.reconvert_all_images()))
        pn = adv.addMenu("页码位置")
        for key, text in (("bottom-center", "底部居中"), ("bottom-right", "底部右侧"), ("bottom-left", "底部左侧"), ("top-center", "顶部居中")):
            act = pn.addAction(text)
            act.setCheckable(True)
            act.setChecked(s.get("pn_position", "bottom-center") == key)
            act.triggered.connect(lambda _=False, k=key: s.set("pn_position", k))
        m.exec(self.btn_more.mapToGlobal(self.btn_more.rect().bottomLeft()))

    def _folder_menu(self) -> None:
        m = QMenu(self)
        a = m.addAction("同源文件夹（和第一个文件放一起）")
        a.triggered.connect(lambda: self._set_dir(None))
        b = m.addAction("自定义文件夹…")
        b.triggered.connect(self._choose_dir)
        if self.custom_dir:
            m.addSeparator()
            m.addAction(f"当前：{self.custom_dir}").setEnabled(False)
        m.exec(self.folder_btn.mapToGlobal(self.folder_btn.rect().bottomLeft()))

    def _choose_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "输出文件夹", str(self.custom_dir or Path.home()))
        if d:
            self._set_dir(Path(d))

    def _set_dir(self, d: Path | None) -> None:
        self.custom_dir = d
        settings().update(output_mode="custom" if d else "source", output_dir=str(d) if d else "")
        self._update_folder_btn()

    def _update_folder_btn(self) -> None:
        if self.custom_dir:
            name = self.custom_dir.name or str(self.custom_dir)
            self.folder_btn.setText((name[:10] + "…" if len(name) > 10 else name) + " ▾")
            self.folder_btn.setToolTip(str(self.custom_dir))
        else:
            self.folder_btn.setText("同源文件夹 ▾")
            self.folder_btn.setToolTip("输出到第一个文件所在的文件夹")

    # -- options / summary -----------------------------------------------------------
    def _options_changed(self, *_a) -> None:
        settings().update(toc_enabled=self.chip_toc.isChecked(), bookmarks=self.chip_bm.isChecked(),
                          dividers=self.chip_div.isChecked(), page_numbers=self.chip_pn.isChecked())
        self._refresh_summary()

    def _title_changed(self, text: str) -> None:
        settings().set("last_toc_title", text)
        self._auto_names()
        self._refresh_summary()

    def _first_name(self) -> str | None:
        for it in self.model.items:
            if not it.is_special:
                return it.display_name
        return None

    def _auto_names(self) -> None:
        if not self._filename_touched:
            self.filename_edit.setText(default_merge_name(self.title_edit.text(), self._first_name()))

    def _current_options(self) -> MergeOptions:
        s = settings()
        return MergeOptions(
            toc_enabled=self.chip_toc.isChecked(),
            toc_title=self.title_edit.text().strip() or "合并文档",
            toc_style="simple",
            toc_show_kind=False,
            toc_show_source=bool(s.get("toc_show_source", False)),
            bookmarks=self.chip_bm.isChecked(),
            dividers=self.chip_div.isChecked(),
            page_size=s.get("page_size_mode", "keep"),
            page_numbers=self.chip_pn.isChecked(),
            pn_position=s.get("pn_position", "bottom-center"),
        )

    def _plan(self) -> tuple[list[TocEntry], int, int]:
        opts = self._current_options()
        listed = [it for it in self.model.items if it.in_toc and it.kind != KIND_BLANK]
        spec = TocSpec(opts.toc_title, "simple", False, opts.toc_show_source, True, "", 0, len(listed))
        n_toc = toc_page_count(len(listed), spec, A4) if opts.toc_enabled else 0
        entries: list[TocEntry] = []
        page = n_toc
        for it in self.model.items:
            count = max(1, it.pages)
            divider = opts.dividers and it.in_toc and not it.is_special
            start = page
            if divider:
                page += 1
            if it.in_toc and it.kind != KIND_BLANK:
                entries.append(TocEntry(it.display_name, start, "", it.path.name if it.path else "", count))
            page += count
        return entries, n_toc, page

    def _refresh_summary(self) -> None:
        entries, n_toc, total = self._plan()
        merge_mode = self.mode.value() == "merge"
        self.canvas.set_state(self.chip_toc.isChecked() and merge_mode, merge_mode, total)
        busy = self.model.count_status("converting") + self.model.count_status("pending")
        errors = self.model.count_status("error")
        n = len(self.model.real_items())
        self.export_btn.setText((t("export_skip") if errors and not busy else t("export")) if merge_mode else f"导出 {n} 个 PDF")
        self.export_btn.setEnabled(bool(self.model.items) and busy == 0)
        self.export_btn.setToolTip("先添加文件" if not self.model.items else ("还在转换…" if busy else "Ctrl+Enter"))
        self.window_ref.footer.set_idle_text(f"{n} 个文件 · 约 {total} 页" if self.model.items else "")
        self._preview_timer.start(300)

    def _refresh(self) -> None:
        self._auto_names()
        self._refresh_summary()

    def _render_preview(self) -> None:
        if not self.chip_toc.isChecked() or self.mode.value() != "merge":
            self.canvas.start.set_preview(None)
            return
        try:
            entries, _n_toc, total = self._plan()
            opts = self._current_options()
            spec = TocSpec(opts.toc_title, "simple", False, opts.toc_show_source, True, "", total, len(entries))
            doc = pymupdf.open()
            insert_toc_pages(doc, entries, spec, A4, links=False)
            dpr = self.canvas.dpr()
            scale = (NODE_W - 38) / 595.28 * dpr * 2.0
            pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
            doc.close()
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr * 2.0)
            self.canvas.start.set_preview(pm)
        except Exception as e:  # noqa: BLE001
            LOG.warning("preview failed: %s", e)

    # -- export -------------------------------------------------------------------------
    def export(self) -> None:
        if not self.model.items:
            info(self, "还没有文件", "把文件拖进画布，或点「添加文件」。")
            return
        busy = self.model.count_status("converting") + self.model.count_status("pending")
        if busy:
            info(self, "还在转换", f"还有 {busy} 个文件在转换，稍等一下。")
            return
        if runner().busy:
            info(self, "正在处理", "等当前任务结束后再导出。")
            return
        first = next((it.path for it in self.model.items if it.path), None)
        out_dir = self.custom_dir or (first.parent if first else Path.home() / "Desktop")
        want_open = self.open_after.isChecked()
        if self.mode.value() == "each":
            self._export_each(out_dir, want_open)
            return
        errors = self.model.count_status("error")
        try:
            sources = self.model.to_sources(skip_errors=errors > 0)
        except ConvertError as e:
            ErrorDialog.show_error("无法导出", str(e), parent=self)
            return
        if not [s for s in sources if s.kind not in (KIND_BLANK, KIND_DIVIDER)]:
            info(self, "没有可导出的内容", "画布里没有已就绪的文件。")
            return
        opts = self._current_options()
        name = sanitize_filename(self.filename_edit.text() or default_merge_name(opts.toc_title, self._first_name()))
        out_path = unique_path(out_dir / f"{name}.pdf")

        def job(progress, cancel):
            with registry().batch():
                return merge(sources, opts, out_path, progress=progress, cancel=cancel)

        self._pending_export = runner().submit(f"合成 {out_path.name}", job, kind="make",
                                               meta={"open": want_open, "each": False, "files": [s.display_name for s in sources]})
        self.canvas.play_export_animation()

    def _export_each(self, out_dir: Path, want_open: bool) -> None:
        items = [(it.path, it.display_name, it.rotation, it.password) for it in self.model.real_items() if it.path]
        if not items:
            info(self, "没有可导出的文件", "")
            return
        opts = default_options()
        reg = registry()

        def job(progress, cancel):
            outs: list[Path] = []
            errs: list[str] = []
            with reg.batch():
                for i, (path, name, rotation, pw) in enumerate(items):
                    if cancel():
                        raise ConvertCancelled("已取消")
                    progress(i / len(items), path.name)
                    try:
                        o = default_options()
                        o.password = pw
                        dst = unique_path(out_dir / f"{sanitize_filename(name)}.pdf")
                        res = reg.convert(path, dst, o, cancel=cancel)
                        if rotation:
                            d = pymupdf.open(str(res.pdf_path))
                            for pg in d:
                                pg.set_rotation((pg.rotation + rotation) % 360)
                            d.save(str(res.pdf_path) + ".rot.pdf", garbage=2, deflate=True)
                            d.close()
                            Path(str(res.pdf_path) + ".rot.pdf").replace(res.pdf_path)
                        outs.append(res.pdf_path)
                    except ConvertCancelled:
                        raise
                    except Exception as e:  # noqa: BLE001
                        errs.append(f"{path.name}：{e}")
            return {"outputs": outs, "errors": errs}

        self._pending_export = runner().submit(f"各自导出 {len(items)} 个 PDF", job, kind="make",
                                               meta={"open": want_open, "each": True, "files": [p.name for p, _n, _r, _pw in items]})
        self.canvas.play_export_animation()

    def _on_task_finished(self, task_id: str, result) -> None:
        if task_id != self._pending_export:
            return
        self._pending_export = None
        rec = runner().record(task_id)
        if rec and rec.meta.get("each"):
            outs, errs = result["outputs"], result["errors"]
            title = f"已导出 {len(outs)} 个 PDF" + (f"，{len(errs)} 个失败" if errs else "")
            sub = "；".join(errs[:2]) if errs else (str(outs[0].parent) if outs else "")
            self.window_ref.notify_result(title, sub, outs[:1] if outs else [])
            if rec.meta.get("open") and outs:
                reveal_in_folder(outs[0])
            return
        res = result
        sub = f"{res.pages} 页 · {human_size(res.size_bytes)}"
        if res.warnings:
            sub += " · " + res.warnings[0]
        self.window_ref.notify_result(f"已导出 {res.path.name}", sub, [res.path])
        if rec and rec.meta.get("open"):
            reveal_in_folder(res.path)

    def _on_task_failed(self, task_id: str, message: str, details: str) -> None:
        if task_id != self._pending_export:
            return
        self._pending_export = None
        ErrorDialog.show_error("导出失败", message, details, self)

    def shutdown(self) -> None:
        self.model.shutdown()
