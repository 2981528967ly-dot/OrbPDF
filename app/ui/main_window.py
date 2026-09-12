"""Main window: three verbs (生成 · 修改 · 转换) + settings, crossfading pages, footer, toast."""
from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from ..core.convert.registry import registry
from ..core.fileinfo import collect_files
from ..core.paths import cleanup_session
from ..core.settings import settings
from ..core.tasks.runner import runner
from ..version import APP_TITLE
from . import assets, icons, theme
from .widgets.drop import mime_has_files, paths_from_mime
from .widgets.progress_footer import ProgressFooter
from .widgets.result_card import ResultCard
from .widgets.robot import RobotWidget

LOG = logging.getLogger("orbpdf.ui")

NAV = [
    ("make", "生成", "merge", "把文件变成 PDF"),
    ("edit", "修改", "pages", "改一个已有的 PDF"),
    ("export", "转换", "convert", "PDF 变成别的格式"),
]


class NavButton(QToolButton):
    def __init__(self, key: str, text: str, icon_name: str, tip: str, window: "MainWindow") -> None:
        super().__init__()
        self.key = key
        self.window_ref = window
        self.setObjectName("NavButton")
        self.setText(text)
        self.setToolTip(tip)
        self.setIcon(icons.icon(icon_name, size=22))
        self.setIconSize(QSize(22, 22))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setFixedWidth(72)

    def dragEnterEvent(self, e) -> None:
        if mime_has_files(e.mimeData()):
            e.acceptProposedAction()
            self.setChecked(True)

    def dropEvent(self, e) -> None:
        paths = collect_files(paths_from_mime(e.mimeData()))
        if paths:
            self.window_ref.send_to(self.key, paths)
        e.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self, progress=None) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} · 全能 PDF 工作台")
        self.setWindowIcon(assets.app_icon())
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(88)
        sb = QVBoxLayout(self.sidebar)
        sb.setContentsMargins(8, 12, 8, 10)
        sb.setSpacing(6)
        self.logo = RobotWidget(44)
        self.logo.setToolTip("OrbPDF")
        sb.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        brand = QLabel("OrbPDF")
        brand.setObjectName("Strong")
        brand.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        brand.setStyleSheet("font-size: 11px; letter-spacing: 1px;")
        sb.addWidget(brand)
        sb.addSpacing(8)
        self.nav: dict[str, NavButton] = {}
        for key, text, ic, tip in NAV:
            b = NavButton(key, text, ic, tip, self)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            sb.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
            self.nav[key] = b
        sb.addStretch(1)
        b = NavButton("settings", "设置", "settings", "设置", self)
        b.clicked.connect(lambda _=False: self.show_page("settings"))
        sb.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        self.nav["settings"] = b
        outer.addWidget(self.sidebar)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        outer.addLayout(col, 1)
        self.stack = QStackedWidget()
        col.addWidget(self.stack, 1)
        self.footer = ProgressFooter()
        col.addWidget(self.footer)
        self.footer.tasks_clicked.connect(self.show_tasks)

        self.pages: dict[str, QWidget] = {}
        self._build_pages(progress)
        self.toast = ResultCard(root)
        self.toast.send_to.connect(self.send_to)
        self._shortcuts()
        self._restore_geometry()
        self._fade_anim: QPropertyAnimation | None = None
        self.show_page("make", animate=False)
        self.logo.clicked.connect(self._logo_clicked)
        self._logo_clicks = 0
        QTimer.singleShot(200, self._probe_engines)

    # -- pages ----------------------------------------------------------------
    def _build_pages(self, progress=None) -> None:
        from .pages.make_page import MakePage
        from .pages.edit_page import EditPage
        from .pages.export_page import ExportPage
        from .pages.settings_page import SettingsPage
        for i, cls in enumerate((MakePage, EditPage, ExportPage, SettingsPage)):
            if progress:
                progress(0.55 + 0.1 * i, {"MakePage": "准备画布", "EditPage": "准备编辑台", "ExportPage": "准备转换", "SettingsPage": "读取设置"}.get(cls.__name__, ""))
            page = cls(self)
            self.pages[page.key] = page
            self.stack.addWidget(page)

    def show_page(self, key: str, animate: bool = True) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        if self.stack.currentWidget() is page:
            return
        self.stack.setCurrentWidget(page)
        if key in self.nav:
            self.nav[key].setChecked(True)
        if animate:
            effect = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", self)
            anim.setDuration(180)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            def done() -> None:
                page.setGraphicsEffect(None)

            anim.finished.connect(done)
            self._fade_anim = anim
            anim.start()

    def send_to(self, key: str, paths: list[Path]) -> None:
        if key in ("merge", "compress", "tools", "pages", "convert"):
            key = {"merge": "make", "compress": "edit", "tools": "edit", "pages": "edit", "convert": "export"}[key]
        page = self.pages.get(key)
        if page is None:
            return
        self.show_page(key)
        if hasattr(page, "add_files"):
            page.add_files([Path(p) for p in paths])

    def notify_result(self, title: str, subtitle: str, paths: list[Path], ok: bool = True) -> None:
        self.toast.show_result(title, subtitle, paths, ok)

    def show_tasks(self) -> None:
        from .dialogs.tasks import TaskCenterDialog
        TaskCenterDialog(self).exec()

    def apply_theme(self, name: str) -> None:
        theme.set_theme(name)
        QApplication.instance().setStyleSheet(theme.build_qss(theme.current()))
        icons.pixmap.cache_clear()
        for key, b in self.nav.items():
            ic = next((n[2] for n in NAV if n[0] == key), "settings")
            b.setIcon(icons.icon(ic, size=22))
        self._dark_title_bar(theme.current().is_dark)
        for p in self.pages.values():
            if hasattr(p, "retheme"):
                p.retheme()
        self.update()

    def _shortcuts(self) -> None:
        for i, key in enumerate(["make", "edit", "export", "settings"], start=1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, activated=lambda k=key: self.show_page(k))
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self.show_page("settings"))

    def dragEnterEvent(self, e) -> None:
        if mime_has_files(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = collect_files(paths_from_mime(e.mimeData()))
        page = self.stack.currentWidget()
        if paths and page is not None and hasattr(page, "add_files"):
            page.add_files(paths)
        e.acceptProposedAction()

    def _probe_engines(self) -> None:
        try:
            infos = registry().probe_all()
            names = [i.name for i in infos.values() if i.available and i.id != "builtin"]
            self.footer.set_engine_text("引擎 " + (" · ".join(names) if names else "内置"))
        except Exception as e:  # noqa: BLE001
            LOG.warning("probe failed: %s", e)

    def _logo_clicked(self) -> None:
        self._logo_clicks += 1
        if self._logo_clicks >= 10:
            self._logo_clicks = 0
            from .dialogs.about import OrbBurstDialog
            OrbBurstDialog(self).exec()

    def _dark_title_bar(self, dark: bool) -> None:
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            value = ctypes.c_int(1 if dark else 0)
            for attr in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
        except Exception:
            pass

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._dark_title_bar(theme.current().is_dark)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast._reposition()

    def _restore_geometry(self) -> None:
        geo = settings().get("window_geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
                return
            except Exception:
                pass
        self.resize(1240, 800)

    def closeEvent(self, e) -> None:
        try:
            settings().set("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        except Exception:
            pass
        for p in self.pages.values():
            if hasattr(p, "shutdown"):
                try:
                    p.shutdown()
                except Exception:
                    pass
        try:
            runner().shutdown()
            registry().end_batch()
        except Exception:
            pass
        cleanup_session()
        super().closeEvent(e)
