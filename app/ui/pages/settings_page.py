"""设置 — general, engines, images, cache & logs, about."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout, QWidget,
                               QAbstractItemView)

from ...core.convert.registry import registry
from ...core.fileinfo import human_size
from ...core.logging_setup import export_diagnostics
from ...core.paths import appdata_dir, cache_dir, logs_dir, settings_path, temp_base
from ...core.settings import settings
from ...version import __version__
from ..strings import strings
from ..widgets.controls import Panel, Segmented, ToggleSwitch, button, hbox, label, vbox, Pill
from ..widgets.result_card import open_path
from ..widgets.robot import RobotBadge

SECTIONS = [("general", "通用"), ("engines", "转换引擎"), ("images", "图片"), ("cache", "缓存与日志"), ("about", "关于")]


class SettingsPage(QWidget):
    key = "settings"

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ref = window
        self.setObjectName("Page")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label("设置", "ModuleTitle"))
        head.addWidget(label("引擎、主题、输出习惯、诊断", "ModuleHint"))
        head.addStretch(1)
        root.addLayout(head)
        body = QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)
        self.nav = QListWidget()
        self.nav.setObjectName("SettingsNav")
        self.nav.setFixedWidth(150)
        for key, text in SECTIONS:
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.nav.addItem(it)
        body.addWidget(self.nav)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.stack.addWidget(self._general())
        self.stack.addWidget(self._engines())
        self.stack.addWidget(self._images())
        self.stack.addWidget(self._cache())
        self.stack.addWidget(self._about())
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

    # -- 通用 ------------------------------------------------------------
    def _general(self) -> QWidget:
        p = Panel("通用")
        s = settings()
        self.theme_seg = Segmented([("dark", "深色 · 故障机器人"), ("light", "浅色 · 简洁")], s.get("theme", "dark"))
        self.theme_seg.changed.connect(self._theme_changed)
        p.add(layout=hbox(label("主题", "Muted"), self.theme_seg, "stretch"))
        self.egg = ToggleSwitch()
        self.egg.setChecked(bool(s.get("egg_mode", False)))
        self.egg.toggled.connect(lambda on: strings().set_egg(on))
        p.add(layout=hbox(label("彩蛋模式", "Muted"), self.egg, label("添加 → 充能 · 队列 → 球槽 · 导出 → 激发 · 选项 → 聚焦", "Small"), "stretch"))
        self.open_after = QCheckBox("任务完成后打开所在文件夹（各模块可单独勾选）")
        self.open_after.setChecked(bool(s.get("open_after", True)))
        self.open_after.toggled.connect(lambda on: s.set("open_after", on))
        p.add(self.open_after)
        self.prefer_office = QCheckBox("优先使用本机 Office / WPS 转换 Word、PPT、Excel（关闭则一律用内置引擎）")
        self.prefer_office.setChecked(bool(s.get("prefer_office", True)))
        self.prefer_office.toggled.connect(lambda on: s.set("prefer_office", on))
        p.add(self.prefer_office)
        p.add(label("快捷键：Ctrl+1…5 切换模块 · Ctrl+O 添加文件 · Ctrl+Enter 执行 · F2 重命名 · Delete 移除 · Ctrl+←/→ 调整顺序", "Small", wrap=True))
        p.add_stretch()
        return p

    def _theme_changed(self, key: str) -> None:
        settings().set("theme", key)
        self.window_ref.apply_theme(key)

    # -- 转换引擎 ----------------------------------------------------------
    def _engines(self) -> QWidget:
        p = Panel("转换引擎", count="启动时只查注册表，第一次转换时才拉起 Office")
        p.add_action(button("重新探测", "refresh", on_click=lambda: self._fill_engines(True)))
        self.engine_table = QTableWidget(0, 4)
        self.engine_table.setHorizontalHeaderLabels(["引擎", "探测结果", "状态", "说明"])
        self.engine_table.verticalHeader().setVisible(False)
        self.engine_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.engine_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.engine_table.setShowGrid(False)
        hh = self.engine_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.engine_table.verticalHeader().setDefaultSectionSize(34)
        p.add(self.engine_table, 1)
        s = settings()
        self.fallback = QCheckBox("某个引擎失败时自动降级到下一个引擎")
        self.fallback.setChecked(bool(s.get("fallback_on_error", True)))
        self.fallback.toggled.connect(lambda on: s.set("fallback_on_error", on))
        self.timeout = QSpinBox()
        self.timeout.setRange(20, 900)
        self.timeout.setValue(int(s.get("engine_timeout", 120)))
        self.timeout.setSuffix(" 秒")
        self.timeout.valueChanged.connect(lambda v: s.set("engine_timeout", v))
        p.add(layout=hbox(self.fallback, "stretch", label("单文件超时", "Muted"), self.timeout))
        p.add(label("顺序：Microsoft Office → WPS Office → LibreOffice → 内置引擎。内置引擎零依赖，Word / PPT / Excel 只做基础排版。", "Small", wrap=True))
        self._fill_engines(False)
        return p

    def _fill_engines(self, force: bool) -> None:
        infos = registry().probe_all(force=force)
        notes = {"msoffice": "高保真，等同 Office 自己导出", "wps": "按接口规范实现，未在本机验证", "libreoffice": "可选，安装后自动识别",
                 "builtin": "图片 · 文本 · Office 文档基础排版"}
        self.engine_table.setRowCount(0)
        for eid in ("msoffice", "wps", "libreoffice", "builtin"):
            info = infos.get(eid)
            if info is None:
                continue
            r = self.engine_table.rowCount()
            self.engine_table.insertRow(r)
            self.engine_table.setItem(r, 0, QTableWidgetItem(info.name))
            self.engine_table.setItem(r, 1, QTableWidgetItem(info.detail))
            pill = Pill("始终可用" if eid == "builtin" else ("已就绪" if info.available else "未安装"), "ok" if info.available else "mute")
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(6, 0, 6, 0)
            lay.addWidget(pill)
            lay.addStretch(1)
            self.engine_table.setCellWidget(r, 2, w)
            self.engine_table.setItem(r, 3, QTableWidgetItem(notes.get(eid, "")))
        self.window_ref._probe_engines()

    # -- 图片 -----------------------------------------------------------------
    def _images(self) -> QWidget:
        p = Panel("图片")
        s = settings()
        self.fit = QComboBox()
        for k, tx in (("bleed", "无白边：页面尺寸 = 图片比例（默认）"), ("a4", "适配 A4：A4 页面，四周留边"), ("original", "原始尺寸：按图片 DPI")):
            self.fit.addItem(tx, k)
        for i in range(self.fit.count()):
            if self.fit.itemData(i) == s.get("image_fit", "bleed"):
                self.fit.setCurrentIndex(i)
        self.fit.currentIndexChanged.connect(lambda _i: s.set("image_fit", self.fit.currentData()))
        p.add(layout=hbox(label("图片页面", "Muted"), self.fit, "stretch"))
        self.max_side = QSpinBox()
        self.max_side.setRange(0, 12000)
        self.max_side.setSingleStep(500)
        self.max_side.setSpecialValueText("不限制")
        self.max_side.setValue(int(s.get("image_max_side", 0) or 0))
        self.max_side.setSuffix(" px")
        self.max_side.valueChanged.connect(lambda v: s.set("image_max_side", v))
        self.quality = QSpinBox()
        self.quality.setRange(50, 100)
        self.quality.setValue(int(s.get("jpeg_quality", 90)))
        self.quality.valueChanged.connect(lambda v: s.set("jpeg_quality", v))
        p.add(layout=hbox(label("图片最长边", "Muted"), self.max_side, 12, label("重编码 JPEG 质量", "Muted"), self.quality, "stretch"))
        p.add(label("JPEG 原图在不需要旋转以外的处理时会原样嵌入，不会二次压缩；PNG 等无损图片保持无损。需要更小的文件请用「压缩」模块。", "Small", wrap=True))
        p.add_stretch()
        return p

    # -- 缓存与日志 --------------------------------------------------------------
    def _cache(self) -> QWidget:
        p = Panel("缓存与日志")
        p.add(label(f"设置：{settings_path()}", "Muted", wrap=True))
        p.add(label(f"日志：{logs_dir()}", "Muted", wrap=True))
        p.add(label(f"缓存：{temp_base()}（退出时自动清理）", "Muted", wrap=True))
        p.add(label("程序所在的文件夹永远不会被写入，exe 可以随意移动或发给朋友。", "Small", wrap=True))
        self.cache_lbl = label("", "Muted")
        p.add(self.cache_lbl)
        row = hbox(button("打开设置文件夹", "folder-open", on_click=lambda: open_path(appdata_dir())),
                   button("打开日志文件夹", "folder-open", on_click=lambda: open_path(logs_dir())),
                   button("清理缓存", "trash", on_click=self._clear_cache),
                   button("导出诊断包…", None, on_click=self._diag), "stretch")
        p.add(layout=row)
        p.add(label("朋友遇到问题时，让他点「导出诊断包」把 zip 发给你：里面有日志、设置和环境信息，不含文档内容。", "Small", wrap=True))
        p.add_stretch()
        self._refresh_cache()
        return p

    def _refresh_cache(self) -> None:
        try:
            size = registry().cache.size_bytes()
        except Exception:
            size = 0
        self.cache_lbl.setText(f"当前缓存：{human_size(size)}")

    def _clear_cache(self) -> None:
        n = registry().cache.clear()
        self._refresh_cache()
        QMessageBox.information(self, "已清理", f"清理了 {n} 个缓存文件。队列里的文件会在需要时重新转换。")

    def _diag(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出诊断包", str(Path.home() / "Desktop" / "OrbPDF-诊断.zip"), "Zip (*.zip)")
        if path:
            try:
                infos = registry().probe_all()
                export_diagnostics(Path(path), {f"engine.{k}": f"{v.available} {v.detail}" for k, v in infos.items()})
                QMessageBox.information(self, "已导出", f"诊断包已保存到：\n{path}")
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "导出失败", str(e))

    # -- 关于 ----------------------------------------------------------------------
    def _about(self) -> QWidget:
        p = Panel("关于")
        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(RobotBadge(96), 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(label(f"OrbPDF {__version__}", "ModuleTitle"))
        col.addWidget(label("一个 exe 的全能 PDF 工作台。把 PDF / Word / PPT / Excel / 图片按你的顺序串起来，一键导出带目录的 PDF。", "Muted", wrap=True))
        col.addWidget(label("充能球是文件，球槽是队列，导出就是激发。连点左上角的机器人十下有惊喜。", "Small", wrap=True))
        col.addStretch(1)
        top.addLayout(col, 1)
        p.add(layout=top)
        p.add(label("首次运行提示：exe 没有数字签名，Windows 可能弹出 SmartScreen；点「更多信息 → 仍要运行」即可。", "Small", wrap=True))
        p.add(label("开源组件：PySide6（LGPL）· PyMuPDF（AGPL）· Pillow · python-docx · python-pptx · openpyxl · pywin32 · PyInstaller。"
                    "本程序源码依 AGPL 提供。", "Small", wrap=True))
        p.add_stretch()
        return p

    def retheme(self) -> None:
        self._fill_engines(False)
