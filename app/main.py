"""OrbPDF entry point."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from pathlib import Path


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="OrbPDF", add_help=False)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--screenshot", default=None, help="render the main window to this PNG and exit")
    ap.add_argument("--offscreen", action="store_true")
    ap.add_argument("--demo", action="store_true", help="load sample files into the canvas")
    ap.add_argument("--view", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--theme", default=None)
    ap.add_argument("--no-splash", action="store_true")
    ns, _unknown = ap.parse_known_args(argv)
    return ns


def _selftest() -> int:
    """Headless smoke test used to verify a frozen build: convert + merge a tiny document."""
    import pymupdf
    from .core.convert.registry import registry
    from .core.paths import session_dir, cleanup_session
    from .core.pdf.merge import MergeOptions, MergeSource, merge
    from PIL import Image
    d = session_dir() / "selftest"
    d.mkdir(parents=True, exist_ok=True)
    img = d / "图片.png"
    Image.new("RGB", (400, 300), (90, 216, 255)).save(img)
    txt = d / "说明.txt"
    txt.write_text("OrbPDF 自检 selftest", encoding="utf-8")
    reg = registry()
    r1 = reg.convert(img)
    r2 = reg.convert(txt)
    out = d / "out.pdf"
    res = merge([MergeSource("图片", "image", r1.pdf_path, rotation=90), MergeSource("说明", "text", r2.pdf_path)], MergeOptions(toc_title="自检"), out)
    doc = pymupdf.open(str(res.path))
    ok = doc.page_count == 3 and len(doc[0].get_links()) == 2 and doc[1].rotation == 90
    doc.close()
    print("SELFTEST", "OK" if ok else "FAIL", res.path, res.pages)
    cleanup_session()
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ns = _parse(argv)
    if ns.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        if fonts_dir.exists():
            os.environ.setdefault("QT_QPA_FONTDIR", str(fonts_dir))
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from .core.logging_setup import setup_logging
    setup_logging(ns.debug)
    if ns.selftest:
        return _selftest()

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from .core.settings import settings
    from .core.paths import cleanup_session
    from .version import APP_TITLE, __version__
    from .ui import assets, theme

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("OrbPDF")
    font = QFont("Microsoft YaHei UI", 10)
    if not font.exactMatch():
        font = QFont("Microsoft YaHei", 10)
    app.setFont(font)
    theme.set_theme(ns.theme or settings().get("theme", "dark"))
    app.setStyleSheet(theme.build_qss(theme.current()))
    app.setWindowIcon(assets.app_icon())

    splash = None
    if not ns.no_splash and not ns.screenshot:
        try:
            from .ui.splash import Splash
            splash = Splash()
            splash.show()
            splash.set_progress(0.12, "加载界面模块…")
        except Exception:
            splash = None
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
    except Exception:
        pass

    from .ui.main_window import MainWindow
    from .ui.dialogs.common import ErrorDialog
    if splash:
        splash.set_progress(0.35, "探测转换引擎…")
    try:
        from .core.convert.registry import registry
        registry().probe_all()
    except Exception:
        pass
    if splash:
        splash.set_progress(0.5, "准备工作台…")

    def excepthook(exc_type, exc, tb) -> None:
        details = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.getLogger("orbpdf").error("Unhandled exception:\n%s", details)
        try:
            ErrorDialog.show_error("出了点问题", f"{exc_type.__name__}: {exc}\n\n程序可以继续使用；如果反复出现，请导出诊断包。", details)
        except Exception:
            pass

    sys.excepthook = excepthook
    win = MainWindow(progress=(splash.set_progress if splash else None))
    if splash:
        splash.set_progress(1.0, "就绪")
    win.show()
    if splash:
        QTimer.singleShot(260, splash.close)

    if ns.demo:
        samples = Path(__file__).resolve().parents[1] / "tests" / "samples"
        if samples.exists():
            files = [samples / n for n in ("发票01-高铁票.jpg", "发票02-酒店住宿.docx", "发票03-出租车-竖拍.jpg", "发票04-餐饮.pdf") if (samples / n).exists()]
            win.pages["make"].add_files(files)
            win.pages["make"].title_edit.setText("2026年8月 出差报销凭证")
            if (samples / "发票04-餐饮.pdf").exists():
                win.pages["edit"].open_pdf(samples / "发票04-餐饮.pdf")
    if ns.files:
        pdfs = [Path(f) for f in ns.files if Path(f).exists() and Path(f).suffix.lower() == ".pdf"]
        others = [Path(f) for f in ns.files if Path(f).exists() and Path(f).suffix.lower() != ".pdf"]
        if others or len(pdfs) > 1:
            win.pages["make"].add_files(others + pdfs)
        elif pdfs:
            win.show_page("edit")
            win.pages["edit"].open_pdf(pdfs[0])
    if ns.view:
        win.show_page(ns.view, animate=False)

    if ns.screenshot:
        def grab() -> None:
            pm = win.grab()
            pm.save(ns.screenshot, "PNG")
            print("screenshot saved", ns.screenshot)
            app.quit()
        QTimer.singleShot(4500 if ns.demo else 1200, grab)

    rc = app.exec()
    cleanup_session()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
