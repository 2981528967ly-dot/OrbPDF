"""PDF -> images, PDF -> text, extract embedded images."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from ..convert.base import ProgressFn, CancelFn, report, check_cancel
from ..naming import unique_path
from .info import open_pdf


def pdf_to_images(src: Path, out_dir: Path, *, fmt: str = "png", dpi: int = 150, indices: list[int] | None = None,
                  password: str | None = None, jpeg_quality: int = 90, progress: ProgressFn = None, cancel: CancelFn = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = open_pdf(src, password)
    outputs: list[Path] = []
    try:
        pages = indices if indices is not None else list(range(doc.page_count))
        width = len(str(doc.page_count))
        fmt = "jpg" if fmt.lower() in ("jpg", "jpeg") else "png"
        for k, pno in enumerate(pages):
            check_cancel(cancel)
            report(progress, k / max(1, len(pages)), f"渲染第 {pno + 1} 页")
            pix = doc[pno].get_pixmap(dpi=dpi, alpha=False)
            target = unique_path(out_dir / f"{src.stem}_p{str(pno + 1).zfill(width)}.{fmt}")
            if fmt == "jpg":
                pix.save(str(target), jpg_quality=jpeg_quality)
            else:
                pix.save(str(target))
            outputs.append(target)
    finally:
        doc.close()
    return outputs


def pdf_to_text(src: Path, out_path: Path, *, password: str | None = None, progress: ProgressFn = None, cancel: CancelFn = None) -> Path:
    doc = open_pdf(src, password)
    try:
        chunks = []
        for i, page in enumerate(doc):
            check_cancel(cancel)
            report(progress, i / max(1, doc.page_count), f"提取第 {i + 1} 页")
            chunks.append(f"===== 第 {i + 1} 页 =====\n{page.get_text()}")
    finally:
        doc.close()
    target = unique_path(Path(out_path))
    target.write_text("\n".join(chunks), encoding="utf-8")
    return target


def extract_images(src: Path, out_dir: Path, *, min_side: int = 64, password: str | None = None,
                   progress: ProgressFn = None, cancel: CancelFn = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = open_pdf(src, password)
    outputs: list[Path] = []
    seen: set[int] = set()
    try:
        for i, page in enumerate(doc):
            check_cancel(cancel)
            report(progress, i / max(1, doc.page_count), f"扫描第 {i + 1} 页")
            for info in page.get_images(full=True):
                xref = info[0]
                if xref in seen:
                    continue
                seen.add(xref)
                try:
                    if info[2] < min_side or info[3] < min_side:
                        continue
                    data = doc.extract_image(xref)
                    ext = data.get("ext", "png")
                    blob = data.get("image")
                    if not blob:
                        continue
                    if ext not in ("png", "jpg", "jpeg", "jpx", "bmp", "gif", "tif", "tiff", "webp"):
                        pix = pymupdf.Pixmap(doc, xref)
                        if pix.n - pix.alpha >= 4:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        blob = pix.tobytes("png")
                        ext = "png"
                    target = unique_path(out_dir / f"{src.stem}_p{i + 1}_{xref}.{ext}")
                    target.write_bytes(blob)
                    outputs.append(target)
                except Exception:
                    continue
    finally:
        doc.close()
    return outputs
