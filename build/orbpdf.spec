# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: single-file, windowed OrbPDF.exe with a splash screen."""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
ASSETS = ROOT / "app" / "assets"

block_cipher = None

hidden = [
    "win32com", "win32com.client", "win32com.client.dynamic", "pythoncom", "pywintypes", "win32api", "win32process",
    "docx", "pptx", "openpyxl", "markdown", "PIL.Image", "PIL.ImageOps", "PIL.ImageSequence", "PIL.ImageFilter",
    "pymupdf", "PySide6.QtSvg",
]
hidden += collect_submodules("markdown.extensions")
hidden += collect_submodules("openpyxl")

datas = [(str(ASSETS), "app/assets")]
datas += collect_data_files("pymupdf")
datas += collect_data_files("docx")
datas += collect_data_files("pptx")

EXCLUDED_MODULES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2", "PySide6.QtNetwork",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtWebSockets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtDBus", "PySide6.QtConcurrent", "PySide6.QtPrintSupport",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtNfc", "PySide6.QtBluetooth",
    "tkinter.test", "unittest", "pydoc", "doctest", "xmlrpc", "numpy", "scipy", "matplotlib", "IPython", "jedi",
    "setuptools", "pip", "wheel", "distutils",
]

a = Analysis(
    [str(ROOT / "app" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ---- trim Qt payload we never use -------------------------------------------------------------
DROP_BIN_PATTERNS = (
    "Qt6Qml", "Qt6Quick", "Qt6Network", "Qt6OpenGL", "Qt6Pdf", "Qt6WebSockets", "Qt6Sql", "Qt6Test", "Qt6Xml", "Qt6DBus",
    "Qt6Concurrent", "Qt6PrintSupport", "Qt6Designer", "Qt6Help", "Qt6UiTools", "Qt6Nfc", "Qt6Bluetooth", "Qt6Labs",
    "Qt6VirtualKeyboard", "Qt6Multimedia", "Qt6Positioning", "Qt6Sensors", "Qt6SerialPort", "Qt6RemoteObjects", "Qt6Scxml",
    "Qt6StateMachine", "Qt6TextToSpeech", "Qt6Charts", "Qt6DataVisualization", "Qt6Graphs", "Qt6Location", "Qt6WebChannel",
    "Qt6WebEngine", "Qt6WebView", "Qt63D", "Qt6ShaderTools", "Qt6SpatialAudio", "Qt6HttpServer", "Qt6Svg" if False else "Qt6SvgWidgets",
    "opengl32sw", "d3dcompiler_47", "Qt6Quick3D", "Qt6QmlModels", "Qt6QmlWorkerScript", "Qt6QmlMeta", "Qt6QmlCore",
    "Qt6QuickTemplates2", "Qt6QuickControls2", "Qt6QuickLayouts", "Qt6QuickDialogs2", "Qt6QuickShapes", "Qt6QuickTest",
    "Qt6QuickParticles", "Qt6QuickEffects", "Qt6QuickTimeline", "Qt6QuickWidgets", "Qt6QuickVectorImage", "Qt6QuickShapes",
    "Qt6Widgets" if False else "Qt6OpenGLWidgets", "Qt6ExampleIcons", "Qt6PdfQuick", "Qt6PdfWidgets", "Qt6NetworkAuth",
    "Qt6SerialBus", "Qt6WebSocket", "Qt6MultimediaWidgets", "Qt6MultimediaQuick", "Qt6QuickTest", "Qt6QuickControls2Impl",
)
DROP_DATA_DIRS = ("PySide6/qml", "PySide6\\qml", "PySide6/translations", "PySide6\\translations", "PySide6/plugins/qmltooling",
                  "PySide6/plugins/networkinformation", "PySide6/plugins/tls", "PySide6/plugins/multimedia", "PySide6/plugins/sqldrivers",
                  "PySide6/plugins/position", "PySide6/plugins/sensors", "PySide6/plugins/scenegraph", "PySide6/plugins/canbus",
                  "PySide6/plugins/texttospeech", "PySide6/plugins/webview", "PySide6/plugins/printsupport", "PySide6/plugins/designer",
                  "PySide6/plugins/generic", "PySide6/plugins/egldeviceintegrations", "PySide6/plugins/renderers", "PySide6/plugins/qmllint",
                  "PySide6/plugins/assetimporters", "PySide6/plugins/geometryloaders", "PySide6/plugins/tls")


def _keep(entry):
    name = entry[0].replace("\\", "/")
    base = os.path.basename(name)
    for pat in DROP_BIN_PATTERNS:
        if base.startswith(pat) or ("/" + pat) in name:
            # keep the SVG module itself
            if base.startswith("Qt6Svg.") or base.startswith("Qt6Svg"):
                return True
            return False
    for d in DROP_DATA_DIRS:
        dd = d.replace("\\", "/")
        if name.startswith(dd) or ("/" + dd) in name:
            return False
    if "PySide6/plugins/imageformats" in name and not any(k in base for k in ("qsvg", "qjpeg", "qico", "qgif", "qwebp")):
        return False
    return True


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

splash = Splash(
    str(ASSETS / "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=False,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="OrbPDF",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ASSETS / "app.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
)
