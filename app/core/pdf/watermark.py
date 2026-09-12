"""Text / image watermarks."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from ..convert.base import ConvertError, ProgressFn, CancelFn, report, check_cancel
from .text import text_width, write_text

FONT = "china-s"


@dataclass
class WatermarkSpec:
    mode: str = "text"               # text | image
    text: str = "机密"
    image_path: Path | None = None
    fontsize: float = 48.0
    color: tuple[float, float, float] = (0.55, 0.55, 0.6)
    opacity: float = 0.25
    angle: float = 30.0
    tile: bool = False               # repeat across the page
    position: str = "center"         # center | top-left | top-right | bottom-left | bottom-right
    scale: float = 0.4               # image width as fraction of page width
    pages: list[int] | None = None   # None = all


def apply_watermark(doc: pymupdf.Document, spec: WatermarkSpec, progress: ProgressFn = None, cancel: CancelFn = None) -> int:
    targets = spec.pages if spec.pages is not None else list(range(doc.page_count))
    img_bytes: bytes | None = None
    if spec.mode == "image":
        if not spec.image_path or not Path(spec.image_path).exists():
            raise ConvertError("请选择水印图片")
        img_bytes = _prepare_image(Path(spec.image_path), spec.opacity)
    font = pymupdf.Font(FONT)
    for k, pno in enumerate(targets):
        check_cancel(cancel)
        report(progress, k / max(1, len(targets)), f"第 {pno + 1} 页")
        page = doc[pno]
        rect = page.rect
        if spec.mode == "text":
            _text_watermark(page, spec, font, rect)
        else:
            _image_watermark(page, spec, img_bytes or b"", rect)
    return len(targets)


def _positions(rect: pymupdf.Rect, spec: WatermarkSpec, w: float, h: float) -> list[pymupdf.Point]:
    if spec.tile:
        pts = []
        step_x = max(w * 1.6, 120)
        step_y = max(h * 4.0, 120)
        y = step_y / 2
        row = 0
        while y < rect.height + step_y:
            x = (step_x / 2) if row % 2 == 0 else step_x
            while x < rect.width + step_x:
                pts.append(pymupdf.Point(x, y))
                x += step_x
            y += step_y
            row += 1
        return pts
    m = 36
    return {
        "center": [pymupdf.Point(rect.width / 2, rect.height / 2)],
        "top-left": [pymupdf.Point(m + w / 2, m + h / 2)],
        "top-right": [pymupdf.Point(rect.width - m - w / 2, m + h / 2)],
        "bottom-left": [pymupdf.Point(m + w / 2, rect.height - m - h / 2)],
        "bottom-right": [pymupdf.Point(rect.width - m - w / 2, rect.height - m - h / 2)],
    }.get(spec.position, [pymupdf.Point(rect.width / 2, rect.height / 2)])


def _text_watermark(page: pymupdf.Page, spec: WatermarkSpec, font: pymupdf.Font, rect: pymupdf.Rect) -> None:
    text = spec.text or ""
    if not text.strip():
        return
    tw = text_width(text, spec.fontsize, bold=True)
    th = spec.fontsize
    mat = pymupdf.Matrix(1, 1).prerotate(spec.angle)
    for center in _positions(rect, spec, tw, th):
        x = center.x - tw / 2
        y = center.y + th * 0.35
        try:
            write_text(page, x, y, text, spec.fontsize, spec.color, bold=True, opacity=spec.opacity, morph=(center, mat))
        except Exception:
            write_text(page, x, y, text, spec.fontsize, spec.color, bold=True, opacity=spec.opacity)


def _image_watermark(page: pymupdf.Page, spec: WatermarkSpec, img: bytes, rect: pymupdf.Rect) -> None:
    if not img:
        return
    try:
        pix = pymupdf.Pixmap(img)
        aspect = pix.height / pix.width if pix.width else 1
    except Exception:
        aspect = 1
    w = rect.width * max(0.05, min(1.0, spec.scale))
    h = w * aspect
    for center in _positions(rect, spec, w, h):
        r = pymupdf.Rect(center.x - w / 2, center.y - h / 2, center.x + w / 2, center.y + h / 2)
        try:
            page.insert_image(r, stream=img, rotate=int(spec.angle) if spec.angle % 90 == 0 else 0, overlay=True, keep_proportion=True)
        except Exception:
            continue


def _prepare_image(path: Path, opacity: float) -> bytes:
    from PIL import Image
    im = Image.open(str(path)).convert("RGBA")
    if opacity < 1.0:
        alpha = im.split()[-1].point(lambda a: int(a * max(0.0, min(1.0, opacity))))
        im.putalpha(alpha)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
