"""Line icons rendered from inline SVG, tinted with theme colours."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

_PATHS: dict[str, str] = {
    "merge": '<path d="M4 5h6v5H4zM4 14h6v5H4z"/><path d="M10 7.5h3v9h-3"/><path d="M13 12h6"/><path d="M16.5 9.5l2.5 2.5-2.5 2.5"/>',
    "convert": '<path d="M20 11a8 8 0 0 0-14.5-4.5"/><path d="M4 4v4.5h4.5"/><path d="M4 13a8 8 0 0 0 14.5 4.5"/><path d="M20 20v-4.5h-4.5"/>',
    "pages": '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
    "compress": '<path d="M9 4v5H4"/><path d="M4 4l5 5"/><path d="M15 4v5h5"/><path d="M20 4l-5 5"/><path d="M9 20v-5H4"/><path d="M4 20l5-5"/><path d="M15 20v-5h5"/><path d="M20 20l-5-5"/>',
    "tools": '<path d="M4 7h16M4 12h16M4 17h16"/><circle cx="9" cy="7" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="8" cy="17" r="2"/>',
    "settings": '<circle cx="12" cy="12" r="3.2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
    "add": '<path d="M12 5v14M5 12h14"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "folder-open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1H7l-3 8"/><path d="M3 7v11a2 2 0 0 0 2 2h13l3-9H7"/>',
    "paste": '<rect x="6" y="5" width="12" height="15" rx="2"/><path d="M9 5V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1"/><path d="M9 11h6M9 15h4"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "up": '<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>',
    "down": '<path d="M12 5v14"/><path d="M6 13l6 6 6-6"/>',
    "left": '<path d="M19 12H5"/><path d="M11 6l-6 6 6 6"/>',
    "right": '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "rotate-left": '<path d="M4 12a8 8 0 1 0 2.3-5.7"/><path d="M4 4v4.5h4.5"/>',
    "rotate-right": '<path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v4.5h-4.5"/>',
    "split": '<circle cx="7" cy="6" r="2.5"/><circle cx="7" cy="18" r="2.5"/><path d="M9 7.5L20 16M9 16.5L20 8"/>',
    "extract": '<rect x="4" y="4" width="11" height="14" rx="1.5"/><path d="M15 9h5v11H9v-2"/>',
    "insert": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M12 8v8M8 12h8"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
    "save": '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    "open": '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 13v6H5V6h6"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7"/>',
    "drag": '<circle cx="9" cy="6" r="1.4"/><circle cx="15" cy="6" r="1.4"/><circle cx="9" cy="12" r="1.4"/><circle cx="15" cy="12" r="1.4"/><circle cx="9" cy="18" r="1.4"/><circle cx="15" cy="18" r="1.4"/>',
    "edit": '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M13 7l3 3"/>',
    "image": '<rect x="4" y="5" width="16" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l5-5 4 4 3-3 4 4"/>',
    "lock": '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "unlock": '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 7.5-2"/>',
    "number": '<path d="M9 4L7 20M17 4l-2 16M4 9h16M4 15h16"/>',
    "water": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    "meta": '<path d="M4 12V5h7l9 9-7 7z"/><circle cx="8" cy="9" r="1.2"/>',
    "zoom-in": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5M11 8v6M8 11h6"/>',
    "zoom-out": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5M8 11h6"/>',
    "play": '<path d="M7 5l12 7-12 7z"/>',
    "refresh": '<path d="M20 12a8 8 0 0 1-14.5 4.5"/><path d="M4 20v-4.5h4.5"/><path d="M4 12a8 8 0 0 1 14.5-4.5"/><path d="M20 4v4.5h-4.5"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8v.5"/>',
    "warning": '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "more": '<circle cx="6" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18" cy="12" r="1.6"/>',
    "send": '<path d="M4 12l16-8-6 16-2.5-6.5z"/>',
    "task": '<path d="M5 6h14M5 12h14M5 18h9"/>',
    "file": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    "pdf": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 16v-5h1.6a1.5 1.5 0 0 1 0 3H9"/>',
    "text": '<path d="M5 6h14M5 11h14M5 16h8"/>',
    "clear": '<path d="M5 6l14 12M19 6L5 18"/>',
    "orb": '<circle cx="12" cy="12" r="7"/><path d="M9 9.5a3 3 0 0 1 3-1.5"/>',
    "sidebar": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M9 5v14"/>',
    "star": '<path d="M12 4l2.4 5 5.6.7-4 3.9 1 5.4-5-2.7-5 2.7 1-5.4-4-3.9 5.6-.7z"/>',
    "list": '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
    "grid": '<rect x="4" y="4" width="6" height="6"/><rect x="14" y="4" width="6" height="6"/><rect x="4" y="14" width="6" height="6"/><rect x="14" y="14" width="6" height="6"/>',
    "select-all": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 12l3 3 5-6"/>',
    "invert": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 12h16"/>',
    "range": '<path d="M4 8h16M4 16h16"/><circle cx="8" cy="8" r="2" fill="currentColor"/><circle cx="16" cy="16" r="2" fill="currentColor"/>',
}


def svg_source(name: str, color: str, stroke_width: float = 1.8) -> str:
    body = _PATHS.get(name, _PATHS["file"])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').replace("currentColor", color)


@lru_cache(maxsize=1024)
def pixmap(name: str, color: str, size: int = 20, dpr: float = 1.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_source(name, color).encode("utf-8")))
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str | None = None, size: int = 20, checked_color: str | None = None, disabled_color: str | None = None) -> QIcon:
    t = theme.current()
    color = color or t.c("text2")
    ic = QIcon()
    for dpr in (1.0, 2.0):
        ic.addPixmap(pixmap(name, color, size, dpr), QIcon.Mode.Normal, QIcon.State.Off)
        ic.addPixmap(pixmap(name, checked_color or t.c("accent"), size, dpr), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(pixmap(name, disabled_color or t.c("muted"), size, dpr), QIcon.Mode.Disabled, QIcon.State.Off)
        ic.addPixmap(pixmap(name, checked_color or t.c("accent"), size, dpr), QIcon.Mode.Active, QIcon.State.On)
        ic.addPixmap(pixmap(name, checked_color or t.c("accent"), size, dpr), QIcon.Mode.Selected, QIcon.State.On)
    return ic


def qcolor(token: str) -> QColor:
    v = theme.current().c(token)
    if v.startswith("rgba"):
        parts = v[5:-1].split(",")
        return QColor(int(parts[0]), int(parts[1]), int(parts[2]), int(float(parts[3]) * 255))
    return QColor(v)
