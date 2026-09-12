"""Image -> PDF. Default is *full-bleed*: the page has exactly the image's aspect ratio, no margins.

Fit modes
  bleed    page = image aspect, long side scaled to A4's long side (842pt); no white edges
  original page = image size at its own DPI (96 if unknown); no white edges
  a4       A4 page (orientation follows the image), image fitted inside with small margins
"""
from __future__ import annotations

import io
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, ImageSequence

from ...fileinfo import KIND_IMAGE
from ..base import ConvertError, ConvertOptions, Engine, EngineInfo, ProgressFn, CancelFn, report, check_cancel

A4_LONG, A4_SHORT = 841.89, 595.28
_EXIF_ROT = {3: 180, 6: 270, 8: 90}   # EXIF orientation -> counter-clockwise rotation for PyMuPDF


class ImageEngine(Engine):
    id = "builtin-image"
    name = "内置图片引擎"
    kinds = frozenset({KIND_IMAGE})
    fidelity = "high"

    def probe(self) -> EngineInfo:
        return EngineInfo(self.id, self.name, True, "Pillow + PyMuPDF", set(self.kinds), self.fidelity)

    def convert(self, src: Path, dst: Path, opts: ConvertOptions, progress: ProgressFn = None, cancel: CancelFn = None) -> list[str]:
        doc = pymupdf.open()
        try:
            warnings = add_image_pages(doc, src, opts, progress=progress, cancel=cancel)
            doc.save(str(dst), garbage=2, deflate=True)
        finally:
            doc.close()
        return warnings


def _frames(im: Image.Image):
    """Yield frames: all pages of a multi-page TIFF, only the first frame of an animated GIF/WebP."""
    fmt = (im.format or "").upper()
    if fmt == "TIFF" and getattr(im, "n_frames", 1) > 1:
        for frame in ImageSequence.Iterator(im):
            yield frame.copy()
    else:
        yield im


def _page_size_for(w_px: int, h_px: int, dpi: tuple[float, float] | None, fit: str) -> tuple[float, float, bool]:
    """Return (page_w, page_h, image_fills_page)."""
    if fit == "a4":
        landscape = w_px > h_px
        return (A4_LONG, A4_SHORT, False) if landscape else (A4_SHORT, A4_LONG, False)
    if fit == "original":
        dx = dy = 96.0
        if dpi and 30 <= dpi[0] <= 2400:
            dx, dy = float(dpi[0]), float(dpi[1] if dpi[1] else dpi[0])
        return (w_px * 72.0 / dx, h_px * 72.0 / dy, True)
    # bleed (default): keep aspect, long side = A4 long side
    long_px = max(w_px, h_px)
    scale = A4_LONG / long_px
    return (w_px * scale, h_px * scale, True)


def add_image_pages(doc: pymupdf.Document, src: Path, opts: ConvertOptions, *, at: int | None = None,
                    progress: ProgressFn = None, cancel: CancelFn = None) -> list[str]:
    """Append (or insert at index ``at``) one page per image frame. Returns warnings."""
    warnings: list[str] = []
    try:
        im = Image.open(str(src))
        im.load()
    except Exception as e:
        raise ConvertError(f"无法读取图片：{e}") from e

    fmt = (im.format or "").upper()
    dpi = im.info.get("dpi")
    orientation = 1
    try:
        exif = im.getexif()
        orientation = int(exif.get(0x0112, 1) or 1)
    except Exception:
        orientation = 1

    frames = list(_frames(im))
    n = len(frames)
    for i, frame in enumerate(frames):
        check_cancel(cancel)
        report(progress, (i + 0.2) / n, f"处理图片 {i + 1}/{n}")
        stream: bytes | None = None
        rotate = 0
        needs_reencode = True
        # Fast path: JPEG straight from disk (no recompression) when nothing but orientation changes.
        if fmt == "JPEG" and n == 1 and frame.mode in ("RGB", "L") and opts.image_max_side <= 0 and orientation in (1, 3, 6, 8):
            stream = Path(src).read_bytes()
            rotate = _EXIF_ROT.get(orientation, 0)
            needs_reencode = False
            w_px, h_px = frame.size
            if orientation in (6, 8):
                w_px, h_px = h_px, w_px
        if needs_reencode:
            work = frame
            if orientation != 1:
                try:
                    work = ImageOps.exif_transpose(work) or work
                except Exception:
                    pass
            work = _normalize_mode(work)
            if opts.image_max_side and max(work.size) > opts.image_max_side:
                work.thumbnail((opts.image_max_side, opts.image_max_side), Image.LANCZOS)
            w_px, h_px = work.size
            buf = io.BytesIO()
            lossless = fmt in ("PNG", "BMP", "GIF", "TIFF", "WEBP") and _looks_like_graphics(work)
            if lossless:
                work.save(buf, format="PNG", optimize=False, compress_level=6)
            else:
                work.save(buf, format="JPEG", quality=int(opts.jpeg_quality), subsampling=0 if opts.jpeg_quality >= 90 else 2, optimize=True)
            stream = buf.getvalue()

        pw, ph, fills = _page_size_for(w_px, h_px, dpi, opts.image_fit)
        pno = -1 if at is None else at + i
        page = doc.new_page(pno=pno, width=pw, height=ph)
        if fills:
            rect = page.rect
        else:
            rect = page.rect + (24, 24, -24, -24)
        page.insert_image(rect, stream=stream, rotate=rotate, keep_proportion=True)
    if n > 1:
        warnings.append(f"多帧图片已按 {n} 页导入")
    return warnings


def _normalize_mode(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA", "P", "PA"):
        base = im.convert("RGBA")
        bg = Image.new("RGB", base.size, (255, 255, 255))
        bg.paste(base, mask=base.split()[-1])
        return bg
    if im.mode == "CMYK":
        return im.convert("RGB")
    if im.mode not in ("RGB", "L"):
        try:
            return im.convert("RGB")
        except Exception:
            return im.convert("L")
    return im


def _looks_like_graphics(im: Image.Image) -> bool:
    """Small palettes / screenshots stay lossless; photos go JPEG."""
    try:
        small = im.copy()
        small.thumbnail((128, 128))
        colors = small.convert("RGB").getcolors(maxcolors=4096)
        return colors is not None and len(colors) <= 1024
    except Exception:
        return False
