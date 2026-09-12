"""转换 — batch to-PDF, and PDF to images / text / Word."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QSpinBox, QStackedWidget, QVBoxLayout, QWidget, QHBoxLayout

from ...core.convert.base import ConvertCancelled, ConvertError, ConvertOptions, NeedsPassword
from ...core.convert.registry import default_options, registry
from ...core.fileinfo import KIND_EXCEL, KIND_IMAGE, KIND_PDF, KIND_PPT, KIND_TEXT, KIND_WORD, human_size
from ...core.naming import unique_path
from ...core.pdf.images_out import extract_images, pdf_to_images, pdf_to_text
from ...core.pdf.info import parse_page_range
from ...core.settings import settings
from ..widgets.controls import Panel, Segmented, button, hbox, label
from .batch_page import BatchPage, FILTER_PDF, RowUpdater

TO_PDF_KINDS = {KIND_WORD, KIND_PPT, KIND_EXCEL, KIND_IMAGE, KIND_TEXT}


class ToPdfPage(BatchPage):
    key = "convert"
    title_text = "转换"
    hint_text = "批量转成 PDF，每个文件各自输出"
    kinds = TO_PDF_KINDS
    extra_columns = ["将使用的引擎"]
    action_text = "开始转换"

    def build_options(self, panel: Panel) -> None:
        s = settings()
        self.fit_combo = QComboBox()
        for k, tx in (("bleed", "无白边（默认）"), ("a4", "适配 A4 · 留边"), ("original", "原始尺寸")):
            self.fit_combo.addItem(tx, k)
        self.fit_combo.setCurrentIndex(max(0, ["bleed", "a4", "original"].index(s.get("image_fit", "bleed")) if s.get("image_fit", "bleed") in ("bleed", "a4", "original") else 0))
        self.quality = QSpinBox()
        self.quality.setRange(50, 100)
        self.quality.setValue(int(s.get("jpeg_quality", 90)))
        self.naming = QComboBox()
        self.naming.addItem("同名 .pdf", "same")
        self.naming.addItem("加后缀 _转换.pdf", "suffix")
        row = hbox(label("图片页面", "Muted"), self.fit_combo, 12, label("图片质量", "Muted"), self.quality, 12, label("命名", "Muted"), self.naming, "stretch")
        panel.add(layout=row)
        panel.add(label("没装 Office 的电脑会自动改用内置引擎：内容完整，排版会简化，绝不报错。", "Small", wrap=True))
        self.head_extra.addWidget(button("想合成一个 PDF？发送到合并 →", None, "Link", on_click=self._send_merge))

    def _send_merge(self) -> None:
        if self.table.rows:
            self.window_ref.send_to("merge", self.table.paths())

    def files_changed(self) -> None:
        reg = registry()
        for r, row in enumerate(self.table.rows):
            if not row.extra.get("engine"):
                row.extra["engine"] = reg.best_engine_name(row.path)
                self.table.set_extra(r, "将使用的引擎", row.extra["engine"])

    def make_job(self):
        rows = list(self.table.rows)
        opts = default_options()
        opts.image_fit = self.fit_combo.currentData()
        opts.jpeg_quality = self.quality.value()
        suffix = "_转换" if self.naming.currentData() == "suffix" else ""
        out_dir_custom = self.output.custom_dir()
        upd = RowUpdater(self)
        reg = registry()

        def job(progress, cancel):
            outputs: list[Path] = []
            errors: list[str] = []
            with reg.batch():
                for i, row in enumerate(rows):
                    if cancel():
                        raise ConvertCancelled("已取消")
                    progress(i / max(1, len(rows)), f"转换 {row.path.name}")
                    upd.status(i, "running")
                    out_dir = out_dir_custom or row.path.parent
                    dst = unique_path(out_dir / f"{row.path.stem}{suffix}.pdf")
                    try:
                        res = reg.convert(row.path, dst, opts, progress=lambda f, m, _i=i: progress((_i + f) / max(1, len(rows)), m), cancel=cancel)
                        outputs.append(res.pdf_path)
                        msg = f"{res.pages} 页 · {res.engine_name}" + ("（" + res.warnings[0] + "）" if res.warnings else "")
                        upd.status(i, "done", msg, res.pdf_path)
                    except ConvertCancelled:
                        raise
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"{row.path.name}：{e}")
                        upd.status(i, "failed", str(e))
            return {"outputs": outputs, "errors": errors}

        return job

    def on_finished(self, result) -> None:
        outs, errs = result["outputs"], result["errors"]
        title = f"已转换 {len(outs)} 个文件" + (f"，{len(errs)} 个失败" if errs else "")
        sub = "；".join(errs[:2]) if errs else (str(outs[0].parent) if outs else "")
        self.finish_with_toast(title, sub, outs, self.output.wants_open())


class FromPdfPage(BatchPage):
    key = "convert-out"
    title_text = "转换"
    hint_text = "把 PDF 转成图片、文本或 Word"
    kinds = {KIND_PDF}
    file_filter = FILTER_PDF
    extra_columns = ["结果"]
    action_text = "开始转换"

    def build_options(self, panel: Panel) -> None:
        self.mode = QComboBox()
        for k, tx in (("png", "PDF → 图片（PNG，每页一张）"), ("jpg", "PDF → 图片（JPG，每页一张）"), ("text", "PDF → 文本（txt）"),
                      ("images", "提取 PDF 里嵌入的图片"), ("docx", "PDF → Word（需要本机 Office / WPS）")):
            self.mode.addItem(tx, k)
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 600)
        self.dpi.setValue(150)
        self.dpi.setSuffix(" DPI")
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText("页面范围，留空 = 全部")
        self.range_edit.setFixedWidth(160)
        self.subfolder = QCheckBox("每个 PDF 单独一个文件夹")
        self.subfolder.setChecked(True)
        self.docx_engine = QComboBox()
        for k, tx in (("builtin", "内置引擎：几秒出结果，排版简化"), ("word", "本机 Word：保真，可能要几分钟")):
            self.docx_engine.addItem(tx, k)
        panel.add(layout=hbox(label("模式", "Muted"), self.mode, 12, self.dpi, 12, self.range_edit, self.docx_engine, "stretch"))
        panel.add(self.subfolder)
        self.note = label("", "Small", wrap=True)
        panel.add(self.note)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def _mode_changed(self) -> None:
        m = self.mode.currentData()
        self.dpi.setVisible(m in ("png", "jpg"))
        self.range_edit.setVisible(m in ("png", "jpg", "text"))
        self.subfolder.setVisible(m in ("png", "jpg", "images"))
        has_rows = bool(getattr(self, "table", None) and self.table.rows)
        self.docx_engine.setVisible(m == "docx")
        if m == "docx":
            info = registry().probe_all()
            ok = any(info[k].available and KIND_WORD in info[k].kinds for k in ("msoffice", "wps") if k in info)
            self.note.setText("内置引擎：文字、表格、图片都在，排版简化，几秒完成。本机 Word：重新识别版面，保真，但每个文件可能要几分钟，转换时会短暂弹一下 Word 的提示框。"
                              if ok else "没检测到 Word / WPS，用内置引擎：文字、表格、图片都在，排版简化。")
            enabled = has_rows
        else:
            self.note.setText("")
            enabled = has_rows
        if hasattr(self, "output"):
            self.output.set_enabled_run(enabled)

    def set_mode(self, key: str) -> None:
        for i in range(self.mode.count()):
            if self.mode.itemData(i) == key:
                self.mode.setCurrentIndex(i)

    def files_changed(self) -> None:
        self._mode_changed()

    def make_job(self):
        rows = list(self.table.rows)
        mode = self.mode.currentData()
        docx_engine = self.docx_engine.currentData()
        dpi = self.dpi.value()
        rng = self.range_edit.text().strip()
        sub = self.subfolder.isChecked()
        out_dir_custom = self.output.custom_dir()
        upd = RowUpdater(self)
        passwords = {}
        # ask for passwords up-front (GUI thread)
        from ...core.pdf.info import is_password_protected
        for row in rows:
            if is_password_protected(row.path):
                pw = self.ask_password(row.path)
                if pw is None:
                    return None
                passwords[str(row.path)] = pw
        reg = registry()

        def job(progress, cancel):
            outputs: list[Path] = []
            errors: list[str] = []
            with reg.batch():
                for i, row in enumerate(rows):
                    if cancel():
                        raise ConvertCancelled("已取消")
                    progress(i / max(1, len(rows)), row.path.name)
                    upd.status(i, "running")
                    base_dir = out_dir_custom or row.path.parent
                    pw = passwords.get(str(row.path))
                    try:
                        if mode in ("png", "jpg", "images"):
                            out_dir = (base_dir / row.path.stem) if sub else base_dir
                            if mode == "images":
                                files = extract_images(row.path, out_dir, password=pw, progress=lambda f, m: progress((i + f) / len(rows), m), cancel=cancel)
                            else:
                                import pymupdf
                                n = pymupdf.open(str(row.path)).page_count
                                idx = parse_page_range(rng, n) if rng else None
                                files = pdf_to_images(row.path, out_dir, fmt=mode, dpi=dpi, indices=idx, password=pw,
                                                      progress=lambda f, m: progress((i + f) / len(rows), m), cancel=cancel)
                            outputs.extend(files)
                            upd.status(i, "done", f"{len(files)} 个文件", out_dir)
                            upd.extra(i, "结果", str(out_dir))
                        elif mode == "text":
                            dst = pdf_to_text(row.path, base_dir / f"{row.path.stem}.txt", password=pw, progress=lambda f, m: progress((i + f) / len(rows), m), cancel=cancel)
                            outputs.append(dst)
                            upd.status(i, "done", dst.name, dst)
                            upd.extra(i, "结果", dst.name)
                        else:
                            dst = unique_path(base_dir / f"{row.path.stem}.docx")
                            word = reg.msoffice if reg.msoffice.probe().available else (reg.wps if reg.wps.probe().available else None)
                            note = ""
                            done = False
                            if docx_engine == "word" and word is not None:
                                try:
                                    upd.status(i, "running", "Word 转换中，大文件可能要几分钟")
                                    word.pdf_to_docx(row.path, dst, timeout=600, progress=lambda f, m: progress((i + f) / len(rows), m))
                                    done = True
                                    note = f"{word.name} 转换"
                                except ConvertCancelled:
                                    raise
                                except Exception as e:  # noqa: BLE001
                                    note = f"Word 失败，已改用内置引擎（{str(e)[:40]}）"
                            if not done:
                                from ...core.convert.pdf_to_docx import pdf_to_docx as builtin_pdf_to_docx
                                warns = builtin_pdf_to_docx(row.path, dst, password=pw, progress=lambda f, m: progress((i + f) / len(rows), m), cancel=cancel)
                                note = note or (warns[0] if warns else "内置引擎")
                            outputs.append(dst)
                            upd.status(i, "done", note, dst)
                            upd.extra(i, "结果", dst.name)
                    except ConvertCancelled:
                        raise
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"{row.path.name}：{e}")
                        upd.status(i, "failed", str(e))
            return {"outputs": outputs, "errors": errors}

        return job

    def on_finished(self, result) -> None:
        outs, errs = result["outputs"], result["errors"]
        title = f"完成，共 {len(outs)} 个输出文件" + (f"，{len(errs)} 个失败" if errs else "")
        sub = "；".join(errs[:2]) if errs else (str(outs[0].parent) if outs else "")
        self.finish_with_toast(title, sub, outs[:1] if outs else [], self.output.wants_open())


class ConvertPage(QWidget):
    key = "convert"

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ref = window
        self.setObjectName("Page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.to_pdf = ToPdfPage(window)
        self.from_pdf = FromPdfPage(window)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.to_pdf)
        self.stack.addWidget(self.from_pdf)
        lay.addWidget(self.stack)
        self.seg = Segmented([("to", "转为 PDF"), ("from", "PDF 转出")], "to")
        self.seg.changed.connect(lambda k: self.stack.setCurrentIndex(0 if k == "to" else 1))
        for pg in (self.to_pdf, self.from_pdf):
            pg.head_extra.insertWidget(0, self._seg_proxy(pg))

    def _seg_proxy(self, pg) -> QWidget:
        # one Segmented widget cannot live in two layouts; give each page its own synced copy
        seg = Segmented([("to", "转为 PDF"), ("from", "PDF 转出")], "to" if pg is self.to_pdf else "from")
        seg.changed.connect(lambda k: (self.stack.setCurrentIndex(0 if k == "to" else 1)))
        return seg

    def add_files(self, paths: list[Path]) -> None:
        paths = [Path(p) for p in paths]
        if paths and all(p.suffix.lower() == ".pdf" for p in paths):
            self.stack.setCurrentIndex(1)
            self.from_pdf.add_files(paths)
        else:
            self.stack.setCurrentIndex(0)
            self.to_pdf.add_files(paths)
