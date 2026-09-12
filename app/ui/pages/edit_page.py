"""修改 — one editing table for everything that changes an existing PDF.

Pages (delete / rotate / reorder / insert / extract / split) are edited visually; compress, watermark,
page numbers and encryption are *steps* toggled in the drawer, previewed live on the selected page,
and applied together on save. Several PDFs can be opened; the same steps can be applied to all of them.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pymupdf
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QScrollArea,
                               QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from ...core.convert.base import ConvertCancelled, ConvertError, NeedsPassword
from ...core.convert.registry import default_options, registry
from ...core.fileinfo import KIND_PDF, collect_files, human_size, kind_of
from ...core.naming import unique_path, with_suffix_name
from ...core.pdf.compress import PRESET_DESC, CompressSettings, compress_pdf, estimate_after
from ...core.pdf.info import is_password_protected, open_pdf
from ...core.pdf.numbering import FORMATS, POSITIONS, stamp_page_numbers
from ...core.pdf.pages import (PageRef, build_document, parse_split_ranges, save_document, split_by_bookmarks, split_each,
                               split_every, split_ranges)
from ...core.pdf.security import encrypt_pdf
from ...core.pdf.watermark import WatermarkSpec, apply_watermark
from ...core.settings import settings
from ...core.tasks.runner import runner
from ..dialogs.common import ErrorDialog, PasswordDialog, confirm, info
from ..widgets.controls import ClickableFrame, Panel, Pill, Segmented, ToggleSwitch, button, hbox, icon_button, label, tool_button
from ..widgets.drop import DropMixin, DropZone
from ..widgets.page_grid import PageGrid
from ..widgets.result_card import reveal_in_folder

LOG = logging.getLogger("orbpdf.ui.edit")


class _Doc:
    """An opened PDF with its editor state."""

    def __init__(self, path: Path, doc: pymupdf.Document, password: str | None) -> None:
        self.path = path
        self.password = password
        self.sources: dict[str, pymupdf.Document] = {"s0": doc}
        self.refs: list[PageRef] = [PageRef("s0", i) for i in range(doc.page_count)]
        self.history: list[list[PageRef]] = []
        self.future: list[list[PageRef]] = []
        self._counter = 0

    @property
    def modified(self) -> bool:
        return bool(self.history)

    def new_key(self) -> str:
        self._counter += 1
        return f"s{self._counter}"

    def close(self) -> None:
        for d in self.sources.values():
            try:
                d.close()
            except Exception:
                pass


class StepCard(QFrame):
    """Collapsible step in the drawer with an on/off switch."""
    toggled = Signal(bool)
    changed = Signal()

    def __init__(self, title: str, icon_name: str, switch: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.icon = QLabel()
        from .. import icons, theme
        self.icon.setPixmap(icons.pixmap(icon_name, theme.current().c("accent"), 18, self.devicePixelRatioF()))
        head.addWidget(self.icon)
        self.title = label(title, "Strong")
        head.addWidget(self.title)
        self.summary = label("", "Small")
        head.addWidget(self.summary, 1)
        self.switch: ToggleSwitch | None = None
        if switch:
            self.switch = ToggleSwitch()
            self.switch.toggled.connect(self._on_switch)
            head.addWidget(self.switch)
        lay.addLayout(head)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        lay.addWidget(self.body)
        if switch:
            self.body.setVisible(False)

    def _on_switch(self, on: bool) -> None:
        self.body.setVisible(on)
        self.toggled.emit(on)
        self.changed.emit()

    @property
    def on(self) -> bool:
        return bool(self.switch and self.switch.isChecked())

    def add(self, w: QWidget | None = None, layout=None) -> None:
        if w is not None:
            self.body_layout.addWidget(w)
        elif layout is not None:
            self.body_layout.addLayout(layout)


class EditPage(QWidget, DropMixin):
    key = "edit"

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ref = window
        self.setObjectName("Page")
        self._init_drop()
        self.docs: list[_Doc] = []
        self.current: _Doc | None = None
        self._task_id: str | None = None
        self._task_kind = ""
        self._pending_insert_at = 0
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._render_preview)
        self._build()
        runner().task_finished.connect(self._on_task_finished)
        runner().task_failed.connect(self._on_task_failed)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_dialog)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self.redo)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_new)
        QShortcut(QKeySequence("Ctrl+A"), self.grid, activated=self.grid.selectAll)
        QShortcut(QKeySequence("Delete"), self.grid, activated=self.delete_selected)

    # -- build ---------------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(label("修改", "ModuleTitle"))
        self.tabs_box = QHBoxLayout()
        self.tabs_box.setSpacing(6)
        head.addLayout(self.tabs_box)
        head.addStretch(1)
        head.addWidget(button("打开 PDF", "folder-open", on_click=self.open_dialog))
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(icon_button("select-all", "全选 (Ctrl+A)", lambda: self.grid.selectAll()))
        bar.addWidget(icon_button("invert", "反选", self.invert_selection))
        bar.addSpacing(6)
        bar.addWidget(tool_button("删除", "trash", "删除选中页 (Delete)", on_click=self.delete_selected))
        bar.addWidget(icon_button("rotate-left", "左转 90°", lambda: self.rotate(-90)))
        bar.addWidget(icon_button("rotate-right", "右转 90°", lambda: self.rotate(90)))
        bar.addSpacing(6)
        self.insert_btn = tool_button("插入 ▾", "insert", on_click=self._insert_menu)
        bar.addWidget(self.insert_btn)
        bar.addWidget(tool_button("提取所选", "extract", "把选中的页面另存为新 PDF", on_click=self.extract_selected))
        bar.addSpacing(6)
        bar.addWidget(icon_button("undo", "撤销 (Ctrl+Z)", self.undo))
        bar.addWidget(icon_button("redo", "重做 (Ctrl+Y)", self.redo))
        bar.addStretch(1)
        self.info_lbl = label("", "Muted")
        bar.addWidget(self.info_lbl)
        self.mod_pill = Pill("未修改", "mute")
        bar.addWidget(self.mod_pill)
        bar.addSpacing(8)
        bar.addWidget(label("缩略图", "Small"))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(90, 240)
        self.zoom.setValue(130)
        self.zoom.setFixedWidth(110)
        self.zoom.valueChanged.connect(lambda v: self.grid.set_thumb_size(v))
        bar.addWidget(self.zoom)
        root.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)
        self.grid_panel = Panel()
        self.grid_panel.body.setContentsMargins(8, 8, 8, 8)
        self.stack = QStackedWidget()
        self.drop_zone = DropZone("把 PDF 拖到这里，或点击打开\n拖入 Word / 图片也可以，会先转成 PDF")
        self.drop_zone.files_dropped.connect(self.add_files)
        self.drop_zone.clicked.connect(self.open_dialog)
        self.grid = PageGrid(130, reorderable=True)
        self.grid.order_changed.connect(self._grid_reordered)
        self.grid.itemSelectionChanged.connect(self._selection_changed)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        self.stack.addWidget(self.drop_zone)
        self.stack.addWidget(self.grid)
        self.grid_panel.add(self.stack, 1)
        body.addWidget(self.grid_panel, 1)

        # drawer
        self.drawer = QScrollArea()
        self.drawer.setWidgetResizable(True)
        self.drawer.setFixedWidth(380)
        self.drawer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        dl = QVBoxLayout(inner)
        dl.setContentsMargins(0, 0, 4, 0)
        dl.setSpacing(10)
        self.preview_card = QFrame()
        self.preview_card.setObjectName("Panel")
        pl = QVBoxLayout(self.preview_card)
        pl.setContentsMargins(12, 10, 12, 10)
        pl.setSpacing(6)
        ph = QHBoxLayout()
        ph.addWidget(label("效果预览", "PanelTitle"))
        self.preview_hint = label("", "Small")
        ph.addWidget(self.preview_hint, 1)
        pl.addLayout(ph)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(180)
        pl.addWidget(self.preview)
        dl.addWidget(self.preview_card)
        self._build_steps(dl)
        dl.addStretch(1)
        self.drawer.setWidget(inner)
        body.addWidget(self.drawer)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.apply_all = QCheckBox("应用到全部打开的文件")
        self.apply_all.setVisible(False)
        foot.addWidget(self.apply_all)
        foot.addStretch(1)
        self.split_btn = button("拆分…", "split", on_click=self._split_menu)
        foot.addWidget(self.split_btn)
        self.overwrite_btn = button("覆盖原文件", None, on_click=self.overwrite)
        foot.addWidget(self.overwrite_btn)
        self.save_btn = button("保存为新文件", "save", "PrimaryBig", on_click=self.save_new)
        foot.addWidget(self.save_btn)
        root.addLayout(foot)
        self._update_info()

    def _build_steps(self, dl: QVBoxLayout) -> None:
        # 压缩
        self.st_compress = StepCard("压缩", "compress")
        self.compress_preset = Segmented([("light", "轻度"), ("standard", "标准"), ("extreme", "极限")], settings().get("compress_preset", "standard"))
        self.st_compress.add(self.compress_preset)
        self.compress_gray = QCheckBox("转为灰度")
        self.st_compress.add(self.compress_gray)
        self.compress_est = label("", "Small")
        self.st_compress.add(self.compress_est)
        self.compress_preset.changed.connect(lambda _k: self._step_changed())
        self.compress_gray.toggled.connect(lambda _v: self._step_changed())
        dl.addWidget(self.st_compress)
        # 水印
        self.st_wm = StepCard("水印", "water")
        self.wm_mode = Segmented([("text", "文字"), ("image", "图片")], "text")
        self.st_wm.add(self.wm_mode)
        self.wm_text = QLineEdit("内部资料")
        self.wm_text.setPlaceholderText("水印文字")
        self.st_wm.add(self.wm_text)
        self.wm_image = QLineEdit()
        self.wm_image.setPlaceholderText("水印图片路径")
        self.wm_image_btn = button("选图…", None, "Small", on_click=self._pick_wm_image)
        self.wm_image_row = QWidget()
        wr = QHBoxLayout(self.wm_image_row)
        wr.setContentsMargins(0, 0, 0, 0)
        wr.addWidget(self.wm_image, 1)
        wr.addWidget(self.wm_image_btn)
        self.st_wm.add(self.wm_image_row)
        self.wm_image_row.hide()
        self.wm_size = QSpinBox()
        self.wm_size.setRange(8, 200)
        self.wm_size.setValue(48)
        self.wm_opacity = QSlider(Qt.Orientation.Horizontal)
        self.wm_opacity.setRange(5, 100)
        self.wm_opacity.setValue(25)
        self.wm_angle = QSpinBox()
        self.wm_angle.setRange(-90, 90)
        self.wm_angle.setValue(30)
        self.wm_angle.setSuffix("°")
        self.wm_tile = QCheckBox("平铺")
        self.wm_color = QComboBox()
        for k, tx in (("gray", "灰"), ("red", "红"), ("blue", "蓝"), ("black", "黑")):
            self.wm_color.addItem(tx, k)
        for w in (self.wm_size, self.wm_angle):
            w.setFixedWidth(66)
        self.wm_color.setFixedWidth(58)
        self.st_wm.add(layout=hbox(label("字号", "Small"), self.wm_size, label("角度", "Small"), self.wm_angle, label("颜色", "Small"), self.wm_color, "stretch"))
        self.st_wm.add(layout=hbox(label("透明度", "Small"), self.wm_opacity, self.wm_tile))
        for w in (self.wm_text, self.wm_image):
            w.textChanged.connect(lambda _t: self._step_changed())
        for w in (self.wm_size, self.wm_angle):
            w.valueChanged.connect(lambda _v: self._step_changed())
        self.wm_opacity.valueChanged.connect(lambda _v: self._step_changed())
        self.wm_tile.toggled.connect(lambda _v: self._step_changed())
        self.wm_color.currentIndexChanged.connect(lambda _i: self._step_changed())
        self.wm_mode.changed.connect(self._wm_mode_changed)
        dl.addWidget(self.st_wm)
        # 页码
        self.st_pn = StepCard("页码", "number")
        self.pn_fmt = QComboBox()
        for k, sample in FORMATS.items():
            self.pn_fmt.addItem(sample, k)
        self.pn_pos = QComboBox()
        for k, tx in POSITIONS.items():
            self.pn_pos.addItem(tx, k)
        self.pn_start = QSpinBox()
        self.pn_start.setRange(0, 99999)
        self.pn_start.setValue(1)
        self.pn_skip = QSpinBox()
        self.pn_skip.setRange(0, 999)
        for w in (self.pn_start, self.pn_skip):
            w.setFixedWidth(66)
        for cb in (self.pn_fmt, self.pn_pos):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(8)
        self.st_pn.add(layout=hbox(label("格式", "Small"), self.pn_fmt))
        self.st_pn.add(layout=hbox(label("位置", "Small"), self.pn_pos))
        self.st_pn.add(layout=hbox(label("起始号", "Small"), self.pn_start, label("跳过前", "Small"), self.pn_skip, label("页", "Small"), "stretch"))
        for w in (self.pn_fmt, self.pn_pos):
            w.currentIndexChanged.connect(lambda _i: self._step_changed())
        for w in (self.pn_start, self.pn_skip):
            w.valueChanged.connect(lambda _v: self._step_changed())
        dl.addWidget(self.st_pn)
        # 加密
        self.st_enc = StepCard("加密", "lock")
        self.enc_user = QLineEdit()
        self.enc_user.setPlaceholderText("打开密码")
        self.enc_user.setEchoMode(QLineEdit.EchoMode.Password)
        self.enc_owner = QLineEdit()
        self.enc_owner.setPlaceholderText("权限密码（可选）")
        self.enc_owner.setEchoMode(QLineEdit.EchoMode.Password)
        self.enc_print = QCheckBox("允许打印")
        self.enc_print.setChecked(True)
        self.enc_copy = QCheckBox("允许复制")
        self.enc_copy.setChecked(True)
        self.st_enc.add(self.enc_user)
        self.st_enc.add(self.enc_owner)
        self.st_enc.add(layout=hbox(self.enc_print, self.enc_copy, "stretch"))
        dl.addWidget(self.st_enc)
        for st in (self.st_compress, self.st_wm, self.st_pn, self.st_enc):
            st.toggled.connect(lambda _on: self._step_changed())

    def _wm_mode_changed(self, key: str) -> None:
        self.wm_text.setVisible(key == "text")
        self.wm_image_row.setVisible(key == "image")
        self._step_changed()

    def _pick_wm_image(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "选择水印图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if f:
            self.wm_image.setText(f)

    # -- documents ---------------------------------------------------------------------------
    def add_files(self, paths: list[Path]) -> None:
        paths = collect_files(paths)
        if not paths:
            return
        pdfs = [p for p in paths if kind_of(p) == KIND_PDF]
        others = [p for p in paths if kind_of(p) != KIND_PDF]
        for p in pdfs:
            self.open_pdf(p)
        if others:
            if self.current is None:
                self._convert_then(others, "open")
            else:
                self._insert_files(others, None)

    def open_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "打开 PDF", settings().get("last_dir", "") or "", "PDF 文件 (*.pdf);;所有支持的文件 (*.*)")
        if files:
            settings().set("last_dir", str(Path(files[0]).parent))
            self.add_files([Path(f) for f in files])

    def open_pdf(self, path: Path) -> None:
        for d in self.docs:
            if d.path.resolve() == Path(path).resolve():
                self._select_doc(d)
                return
        pw = None
        if is_password_protected(path):
            pw = PasswordDialog.ask(path.name, self)
            if pw is None:
                return
        try:
            doc = open_pdf(path, pw)
        except (ConvertError, NeedsPassword) as e:
            ErrorDialog.show_error("无法打开", str(e), parent=self)
            return
        d = _Doc(Path(path), doc, pw)
        self.docs.append(d)
        self._rebuild_tabs()
        self._select_doc(d)

    def close_doc(self, d: _Doc) -> None:
        if d.modified and not confirm(self, "放弃改动？", f"{d.path.name} 有未保存的改动。", "关闭", danger=True):
            return
        d.close()
        self.docs.remove(d)
        self._rebuild_tabs()
        self._select_doc(self.docs[-1] if self.docs else None)

    def _rebuild_tabs(self) -> None:
        while self.tabs_box.count():
            it = self.tabs_box.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for d in self.docs:
            chip = ClickableFrame()
            chip.setObjectName("Card")
            hl = QHBoxLayout(chip)
            hl.setContentsMargins(10, 3, 6, 3)
            hl.setSpacing(6)
            name = d.path.name
            hl.addWidget(label(name if len(name) <= 22 else name[:20] + "…", "Strong" if d is self.current else "Muted"))
            x = button("", "close", "IconBtn", "关闭", on_click=lambda _=False, dd=d: self.close_doc(dd))
            x.setFixedSize(20, 20)
            hl.addWidget(x)
            chip.clicked.connect(lambda dd=d: self._select_doc(dd))
            chip.setToolTip(str(d.path))
            self.tabs_box.addWidget(chip)
        self.apply_all.setVisible(len(self.docs) > 1)

    def _select_doc(self, d: _Doc | None) -> None:
        self.current = d
        for key, doc in (d.sources.items() if d else []):
            self.grid.register_doc(key, doc)
        self._rebuild_tabs()
        if d is None:
            self.grid.clear()
            self.stack.setCurrentIndex(0)
        else:
            self.stack.setCurrentIndex(1)
            self._reload_grid()
        self._update_info()
        self._refresh_estimate()

    # -- page editing --------------------------------------------------------------------------
    def _push(self) -> None:
        if self.current:
            self.current.history.append(list(self.current.refs))
            del self.current.history[:-60]
            self.current.future = []

    def _reload_grid(self, select_rows: list[int] | None = None) -> None:
        d = self.current
        if d is None:
            return
        for key, doc in d.sources.items():
            self.grid.register_doc(key, doc)
        labels = []
        for i, r in enumerate(d.refs):
            labels.append((r.src_id, r.page_no, str(i + 1), r.rotation))
        self.grid.load_pages(labels)
        if select_rows:
            for row in select_rows:
                if 0 <= row < self.grid.count():
                    self.grid.item(row).setSelected(True)
        self._update_info()
        self._preview_timer.start(200)

    def _grid_reordered(self) -> None:
        d = self.current
        if d is None:
            return
        order = self.grid.refs()
        lookup = {(r.src_id, r.page_no, r.rotation): r for r in d.refs}
        new_refs = [lookup[k] for k in order if k in lookup]
        if new_refs != d.refs and len(new_refs) == len(d.refs):
            self._push()
            d.refs = new_refs
            self._reload_grid()

    def invert_selection(self) -> None:
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            it.setSelected(not it.isSelected())

    def delete_selected(self) -> None:
        d = self.current
        rows = self.grid.selected_rows()
        if d is None or not rows:
            return
        if len(rows) >= len(d.refs):
            info(self, "至少保留一页", "")
            return
        self._push()
        d.refs = [r for i, r in enumerate(d.refs) if i not in set(rows)]
        self._reload_grid([min(rows[0], len(d.refs) - 1)])

    def rotate(self, deg: int) -> None:
        d = self.current
        rows = self.grid.selected_rows()
        if d is None:
            return
        if not rows:
            rows = list(range(len(d.refs)))
        self._push()
        for i in rows:
            r = d.refs[i]
            d.refs[i] = PageRef(r.src_id, r.page_no, (r.rotation + deg) % 360)
        self._reload_grid(rows)

    def undo(self) -> None:
        d = self.current
        if d is None or not d.history:
            return
        d.future.append(list(d.refs))
        d.refs = d.history.pop()
        self._reload_grid()

    def redo(self) -> None:
        d = self.current
        if d is None or not d.future:
            return
        d.history.append(list(d.refs))
        d.refs = d.future.pop()
        self._reload_grid()

    def _insert_menu(self) -> None:
        m = QMenu(self)
        m.addAction("空白页（在所选之后）").triggered.connect(self.insert_blank)
        m.addAction("从文件插入…（PDF / Word / 图片）").triggered.connect(self.insert_file_dialog)
        m.exec(self.insert_btn.mapToGlobal(self.insert_btn.rect().bottomLeft()))

    def _grid_menu(self, pos) -> None:
        if self.current is None:
            return
        m = QMenu(self)
        m.addAction("删除选中").triggered.connect(self.delete_selected)
        m.addAction("左转 90°").triggered.connect(lambda: self.rotate(-90))
        m.addAction("右转 90°").triggered.connect(lambda: self.rotate(90))
        m.addSeparator()
        m.addAction("在此之后插入空白页").triggered.connect(self.insert_blank)
        m.addAction("在此之后从文件插入…").triggered.connect(self.insert_file_dialog)
        m.addAction("提取所选为新 PDF…").triggered.connect(self.extract_selected)
        m.exec(self.grid.viewport().mapToGlobal(pos))

    def _insert_at(self) -> int:
        rows = self.grid.selected_rows()
        return (rows[-1] + 1) if rows else (len(self.current.refs) if self.current else 0)

    def insert_blank(self) -> None:
        d = self.current
        if d is None:
            return
        at = self._insert_at()
        ref = d.refs[max(0, at - 1)]
        rect = d.sources[ref.src_id][ref.page_no].rect
        blank = pymupdf.open()
        blank.new_page(width=rect.width, height=rect.height)
        key = d.new_key()
        d.sources[key] = blank
        self.grid.register_doc(key, blank)
        self._push()
        d.refs.insert(at, PageRef(key, 0))
        self._reload_grid([at])

    def insert_file_dialog(self) -> None:
        if self.current is None:
            info(self, "先打开一个 PDF", "")
            return
        files, _ = QFileDialog.getOpenFileNames(self, "从文件插入", settings().get("last_dir", "") or "",
                                                "所有支持的文件 (*.pdf *.docx *.pptx *.xlsx *.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp *.txt *.md);;所有文件 (*.*)")
        if files:
            self._insert_files([Path(f) for f in files], self._insert_at())

    def _insert_files(self, paths: list[Path], at: int | None) -> None:
        if at is None:
            at = self._insert_at()
        self._pending_insert_at = at
        self._convert_then(paths, "insert")

    def _convert_then(self, paths: list[Path], purpose: str) -> None:
        if runner().busy:
            info(self, "正在处理", "等当前任务结束后再试。")
            return
        passwords = {}
        for p in paths:
            if kind_of(p) == KIND_PDF and is_password_protected(p):
                pw = PasswordDialog.ask(p.name, self)
                if pw is None:
                    return
                passwords[str(p)] = pw
        reg = registry()

        def job(progress, cancel):
            out = []
            with reg.batch():
                for i, p in enumerate(paths):
                    if cancel():
                        raise ConvertCancelled("已取消")
                    progress(i / max(1, len(paths)), f"转换 {p.name}")
                    opts = default_options()
                    opts.password = passwords.get(str(p))
                    res = reg.convert(p, None, opts, cancel=cancel)
                    out.append((p, res.pdf_path, passwords.get(str(p))))
            return out

        self._task_kind = purpose
        names = [p.name for p in paths]
        self._task_id = runner().submit(f"转换 {names[0]}" if len(names) == 1 else f"转换 {len(names)} 个文件", job, kind="edit", meta={"files": names})

    # -- steps / preview --------------------------------------------------------------------------
    def _step_changed(self) -> None:
        self._update_step_summaries()
        self._preview_timer.start(250)
        self._refresh_estimate()

    def _update_step_summaries(self) -> None:
        self.st_compress.summary.setText(PRESET_DESC.get(self.compress_preset.value(), "").split("·")[0].strip() if self.st_compress.on else "")
        self.st_wm.summary.setText((self.wm_text.text()[:10] if self.wm_mode.value() == "text" else "图片") if self.st_wm.on else "")
        self.st_pn.summary.setText(self.pn_pos.currentText() if self.st_pn.on else "")
        self.st_enc.summary.setText("已设密码" if self.st_enc.on and self.enc_user.text() else ("需要密码" if self.st_enc.on else ""))

    def _wm_spec(self) -> WatermarkSpec | None:
        if not self.st_wm.on:
            return None
        colors = {"gray": (0.55, 0.55, 0.6), "red": (0.85, 0.15, 0.15), "blue": (0.1, 0.35, 0.8), "black": (0.1, 0.1, 0.1)}
        return WatermarkSpec(mode=self.wm_mode.value(), text=self.wm_text.text(), image_path=Path(self.wm_image.text()) if self.wm_image.text() else None,
                             fontsize=float(self.wm_size.value()), color=colors[self.wm_color.currentData()], opacity=self.wm_opacity.value() / 100.0,
                             angle=float(self.wm_angle.value()), tile=self.wm_tile.isChecked(), position="center")

    def _compress_cfg(self) -> CompressSettings | None:
        if not self.st_compress.on:
            return None
        cfg = CompressSettings.preset(self.compress_preset.value())
        cfg.grayscale = self.compress_gray.isChecked()
        return cfg

    def _refresh_estimate(self) -> None:
        d = self.current
        cfg = self._compress_cfg()
        if d is None or cfg is None:
            self.compress_est.setText("")
            return
        try:
            before = d.path.stat().st_size
            est = estimate_after(d.path, cfg)
            self.compress_est.setText(f"预计 {human_size(before)} → 约 {human_size(est)}" if est else f"当前 {human_size(before)}")
        except Exception:
            self.compress_est.setText("")

    def _selection_changed(self) -> None:
        self._update_info()
        self._preview_timer.start(120)

    def _render_preview(self) -> None:
        d = self.current
        if d is None or not d.refs:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("打开 PDF 后，这里显示选中页的最终效果")
            self.preview_hint.setText("")
            return
        rows = self.grid.selected_rows()
        idx = rows[0] if rows else 0
        idx = max(0, min(idx, len(d.refs) - 1))
        ref = d.refs[idx]
        try:
            tmp = pymupdf.open()
            src = d.sources[ref.src_id]
            tmp.insert_pdf(src, from_page=ref.page_no, to_page=ref.page_no)
            page = tmp[0]
            if ref.rotation:
                page.set_rotation((page.rotation + ref.rotation) % 360)
            spec = self._wm_spec()
            if spec is not None and (spec.mode == "text" and spec.text.strip() or spec.mode == "image" and spec.image_path and spec.image_path.exists()):
                spec.pages = [0]
                apply_watermark(tmp, spec)
            if self.st_pn.on and idx >= self.pn_skip.value():
                total = len(d.refs) - self.pn_skip.value()
                n = self.pn_start.value() + idx - self.pn_skip.value()
                fmt = self.pn_fmt.currentData().replace("{N}", str(self.pn_start.value() + total - 1))
                stamp_page_numbers(tmp, fmt, self.pn_pos.currentData(), start_index=0, first_number=n)
            dpr = self.devicePixelRatioF()
            width = max(200, self.drawer.viewport().width() - 40)
            scale = width / page.rect.width * dpr
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
            tmp.close()
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(dpr)
            self.preview.setPixmap(pm)
            self.preview.setText("")
            self.preview_hint.setText(f"第 {idx + 1} 页" + (f" · 旋转 {ref.rotation}°" if ref.rotation else ""))
        except Exception as e:  # noqa: BLE001
            LOG.warning("preview failed: %s", e)
            self.preview.setText("预览失败")

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._preview_timer.start(200)

    # -- outputs -------------------------------------------------------------------------------------
    def _recipe(self) -> dict:
        return {"compress": self._compress_cfg(), "wm": self._wm_spec(),
                "pn": (self.pn_fmt.currentData(), self.pn_pos.currentData(), self.pn_start.value(), self.pn_skip.value()) if self.st_pn.on else None,
                "enc": (self.enc_user.text(), self.enc_owner.text(), self.enc_print.isChecked(), self.enc_copy.isChecked()) if self.st_enc.on else None}

    def _apply_recipe(self, doc: pymupdf.Document, recipe: dict, dst: Path, progress=None, cancel=None) -> Path:
        """Watermark + numbers on ``doc`` (already page-edited), then compress / encrypt via temp files."""
        wm = recipe.get("wm")
        if wm is not None:
            wm.pages = None
            apply_watermark(doc, wm)
        pn = recipe.get("pn")
        if pn is not None:
            fmt, pos, start, skip = pn
            stamp_page_numbers(doc, fmt, pos, start_index=min(skip, doc.page_count), first_number=start)
        tmp = Path(str(dst) + ".step.pdf")
        doc.save(str(tmp), garbage=3, deflate=True)
        cur = tmp
        cfg = recipe.get("compress")
        if cfg is not None:
            tmp2 = Path(str(dst) + ".cmp.pdf")
            compress_pdf(cur, tmp2, cfg, progress=progress, cancel=cancel)
            cur.unlink(missing_ok=True)
            cur = tmp2
        enc = recipe.get("enc")
        if enc is not None and (enc[0] or enc[1]):
            tmp3 = Path(str(dst) + ".enc.pdf")
            encrypt_pdf(cur, tmp3, user_password=enc[0], owner_password=enc[1], allow_print=enc[2], allow_copy=enc[3], allow_modify=False)
            cur.unlink(missing_ok=True)
            cur = tmp3
        cur.replace(dst)
        return dst

    def save_new(self) -> None:
        d = self.current
        if d is None:
            return
        if self.st_enc.on and not (self.enc_user.text() or self.enc_owner.text()):
            info(self, "加密需要密码", "在「加密」里填一个密码，或关掉加密。")
            return
        default = d.path.parent / with_suffix_name(d.path, "_修改").name
        f, _ = QFileDialog.getSaveFileName(self, "保存为新文件", str(default), "PDF 文件 (*.pdf)")
        if not f:
            return
        self._save_to(Path(f), overwrite=False)

    def overwrite(self) -> None:
        d = self.current
        if d is None:
            return
        if not confirm(self, "覆盖原文件", f"用当前结果覆盖：\n{d.path}\n此操作不可撤销。", "覆盖", danger=True):
            return
        self._save_to(d.path, overwrite=True)

    def _save_to(self, target: Path, overwrite: bool) -> None:
        d = self.current
        if d is None or runner().busy:
            return
        recipe = self._recipe()
        apply_all = self.apply_all.isChecked() and len(self.docs) > 1
        jobs = [(d, target, True)]
        if apply_all:
            for other in self.docs:
                if other is not d:
                    jobs.append((other, other.path if overwrite else unique_path(other.path.parent / with_suffix_name(other.path, "_修改").name), False))
        pending = [(doc.refs, doc.sources, dst, doc.path, is_current) for doc, dst, is_current in jobs]

        def job(progress, cancel):
            outs: list[Path] = []
            for i, (refs, sources, dst, src_path, _cur) in enumerate(pending):
                if cancel():
                    raise ConvertCancelled("已取消")
                progress(i / len(pending), dst.name)
                built = build_document(refs, sources)
                try:
                    if dst.resolve() == src_path.resolve():
                        data = built.tobytes(garbage=3, deflate=True)
                        tmp = Path(str(dst) + ".new.pdf")
                        tmp.write_bytes(data)
                        built.close()
                        built = pymupdf.open(str(tmp))
                        out = self._apply_recipe(built, recipe, Path(str(dst) + ".final.pdf"), progress=lambda f, m: progress((i + f) / len(pending), m), cancel=cancel)
                        built.close()
                        tmp.unlink(missing_ok=True)
                        outs.append(("overwrite", out, dst))
                    else:
                        out = self._apply_recipe(built, recipe, unique_path(dst), progress=lambda f, m: progress((i + f) / len(pending), m), cancel=cancel)
                        built.close()
                        outs.append(("new", out, dst))
                except Exception:
                    try:
                        built.close()
                    except Exception:
                        pass
                    raise
            return outs

        self._task_kind = "save"
        self._task_id = runner().submit(f"保存 {target.name}", job, kind="edit", meta={"files": [doc.path.name for doc, _dst, _c in jobs]})

    def _split_menu(self) -> None:
        d = self.current
        if d is None:
            return
        m = QMenu(self)
        m.addAction("每 2 页一份").triggered.connect(lambda: self.split("every", 2))
        m.addAction("每 5 页一份").triggered.connect(lambda: self.split("every", 5))
        m.addAction("每页一份").triggered.connect(lambda: self.split("each", 1))
        m.addAction("按书签拆分").triggered.connect(lambda: self.split("bookmarks", 1))
        m.addAction("按范围拆分…").triggered.connect(self._split_ranges_dialog)
        m.exec(self.split_btn.mapToGlobal(self.split_btn.rect().bottomLeft()))

    def _split_ranges_dialog(self) -> None:
        from ..dialogs.common import ask_text
        spec = ask_text(self, "按范围拆分", "每份的页面范围，用逗号分开，例如 1-2, 3-4, 5-8", "")
        if spec:
            self.split("ranges", 0, spec)

    def split(self, mode: str, n: int, spec: str = "") -> None:
        d = self.current
        if d is None or runner().busy:
            return
        refs, sources = list(d.refs), d.sources
        out_dir = d.path.parent / f"{d.path.stem}_拆分"
        stem = d.path.stem
        if mode == "ranges":
            try:
                parse_split_ranges(spec, len(refs))
            except ValueError as e:
                ErrorDialog.show_error("范围无效", str(e), parent=self)
                return

        def job(progress, cancel):
            doc = build_document(refs, sources)
            try:
                if mode == "every":
                    return split_every(doc, n, out_dir, stem, progress, cancel)
                if mode == "ranges":
                    return split_ranges(doc, parse_split_ranges(spec, doc.page_count), out_dir, stem, progress, cancel)
                if mode == "bookmarks":
                    return split_by_bookmarks(doc, 1, out_dir, stem, progress, cancel)
                return split_each(doc, out_dir, stem, progress, cancel)
            finally:
                doc.close()

        self._task_kind = "split"
        self._task_id = runner().submit(f"拆分 {d.path.name}", job, kind="edit", meta={"files": [d.path.name]})

    def extract_selected(self) -> None:
        d = self.current
        rows = self.grid.selected_rows()
        if d is None or not rows:
            info(self, "先选中页面", "")
            return
        default = d.path.parent / f"{d.path.stem}_提取.pdf"
        f, _ = QFileDialog.getSaveFileName(self, "提取所选为新 PDF", str(default), "PDF 文件 (*.pdf)")
        if not f:
            return
        try:
            doc = build_document([d.refs[i] for i in rows], d.sources)
            target = save_document(doc, Path(f))
            doc.close()
        except Exception as e:  # noqa: BLE001
            ErrorDialog.show_error("提取失败", str(e), parent=self)
            return
        self.window_ref.notify_result(f"已提取 {len(rows)} 页", target.name, [target])

    # -- task results ----------------------------------------------------------------------------------
    def _on_task_finished(self, task_id: str, result) -> None:
        if task_id != self._task_id:
            return
        self._task_id = None
        kind = self._task_kind
        if kind == "open":
            for p, pdf, pw in result:
                self.open_pdf(pdf)
        elif kind == "insert":
            d = self.current
            if d is None:
                return
            at = self._pending_insert_at
            self._push()
            for p, pdf, pw in result:
                try:
                    doc = open_pdf(pdf, pw)
                except Exception as e:  # noqa: BLE001
                    ErrorDialog.show_error("无法插入", f"{p.name}: {e}", parent=self)
                    continue
                key = d.new_key()
                d.sources[key] = doc
                self.grid.register_doc(key, doc)
                for i in range(doc.page_count):
                    d.refs.insert(at, PageRef(key, i))
                    at += 1
            self._reload_grid(list(range(self._pending_insert_at, at)))
        elif kind == "split":
            files = result
            self.window_ref.notify_result(f"已拆分成 {len(files)} 份", str(files[0].parent) if files else "", files[:1])
            if files:
                reveal_in_folder(files[0])
        elif kind == "save":
            outs = result
            paths = []
            for mode, out, dst in outs:
                if mode == "overwrite":
                    for d in self.docs:
                        if d.path.resolve() == Path(dst).resolve():
                            d.close()
                            Path(out).replace(dst)
                            self.docs.remove(d)
                            was_current = d is self.current
                            self.current = None
                            self.open_pdf(dst)
                            break
                    paths.append(Path(dst))
                else:
                    paths.append(Path(out))
            self.window_ref.notify_result(f"已保存 {paths[0].name}" if len(paths) == 1 else f"已保存 {len(paths)} 个文件", str(paths[0].parent) if paths else "", paths[:1])
            if paths and settings().get("open_after", True):
                reveal_in_folder(paths[0])
            if self.current and outs and outs[0][0] == "new":
                self.current.history = []
                self.current.future = []
                self._update_info()

    def _on_task_failed(self, task_id: str, message: str, details: str) -> None:
        if task_id != self._task_id:
            return
        self._task_id = None
        ErrorDialog.show_error("处理失败", message, details, self)

    # -- info --------------------------------------------------------------------------------------------
    def _update_info(self) -> None:
        d = self.current
        has = d is not None and bool(d.refs)
        for w in (self.save_btn, self.overwrite_btn, self.split_btn):
            w.setEnabled(has)
        if not has:
            self.info_lbl.setText("")
            self.mod_pill.set("未打开", "mute")
            return
        rows = self.grid.selected_rows()
        orig = d.sources.get("s0")
        n0 = orig.page_count if orig else len(d.refs)
        txt = f"{len(d.refs)} 页" + (f"（原 {n0} 页）" if n0 != len(d.refs) else "") + (f" · 已选 {len(rows)} 页" if rows else "")
        self.info_lbl.setText(txt)
        steps = [n for n, st in (("压缩", self.st_compress), ("水印", self.st_wm), ("页码", self.st_pn), ("加密", self.st_enc)) if st.on]
        if d.modified or steps:
            self.mod_pill.set("待保存：" + "、".join((["页面"] if d.modified else []) + steps), "warn")
        else:
            self.mod_pill.set("未修改", "mute")

    def shutdown(self) -> None:
        self.grid.shutdown()
        for d in self.docs:
            d.close()
