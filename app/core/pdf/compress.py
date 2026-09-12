"""PDF size reduction: image re-encoding, font subsetting, metadata cleanup, object garbage collection."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from ..convert.base import ConvertError, ProgressFn, CancelFn, report, check_cancel
from ..naming import unique_path
from .info import open_pdf


@dataclass
class CompressSettings:
    dpi_threshold: int = 200     # only images above this DPI are touched
    dpi_target: int = 150
    quality: int = 75
    grayscale: bool = False
    strip_metadata: bool = True
    subset_fonts: bool = True
    keep_if_larger: bool = True

    @classmethod
    def preset(cls, name: str) -> "CompressSettings":
        if name == "light":
            return cls(dpi_threshold=260, dpi_target=200, quality=85)
        if name == "extreme":
            return cls(dpi_threshold=120, dpi_target=96, quality=50)
        return cls()


PRESET_LABELS = {"light": "轻度", "standard": "标准", "extreme": "极限"}
PRESET_DESC = {
    "light": "图片 200 DPI · 质量 85 · 保画质",
    "standard": "图片 150 DPI · 质量 75 · 屏幕阅读够用",
    "extreme": "图片 96 DPI · 质量 50 · 适合邮件附件",
}


@dataclass
class CompressResult:
    src: Path
    dst: Path
    before: int
    after: int
    kept_original: bool = False

    @property
    def ratio(self) -> float:
        return (1 - self.after / self.before) if self.before else 0.0


def compress_pdf(src: Path, dst: Path, cfg: CompressSettings, *, password: str | None = None,
                 progress: ProgressFn = None, cancel: CancelFn = None) -> CompressResult:
    src, dst = Path(src), Path(dst)
    before = src.stat().st_size
    doc = open_pdf(src, password)
    try:
        report(progress, 0.1, "重新编码图片")
        check_cancel(cancel)
        _rewrite_images(doc, cfg)
        check_cancel(cancel)
        if cfg.subset_fonts:
            report(progress, 0.6, "字体子集化")
            try:
                doc.subset_fonts(fallback=False)
            except TypeError:
                try:
                    doc.subset_fonts()
                except Exception:
                    pass
            except Exception:
                pass
        if cfg.strip_metadata:
            try:
                doc.set_metadata({"producer": "OrbPDF", "creator": "OrbPDF"})
                doc.del_xml_metadata()
            except Exception:
                pass
        report(progress, 0.8, "保存")
        tmp = Path(str(dst) + ".part.pdf")
        doc.save(str(tmp), garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True, use_objstms=1)
    finally:
        doc.close()
    after = tmp.stat().st_size
    if cfg.keep_if_larger and after >= before:
        tmp.unlink(missing_ok=True)
        if dst.resolve() != src.resolve():
            shutil.copy2(src, dst)
        return CompressResult(src, dst, before, before, kept_original=True)
    target = dst
    if dst.resolve() == src.resolve():
        tmp.replace(dst)
    else:
        target = unique_path(dst) if _locked(dst) else dst
        tmp.replace(target)
    return CompressResult(src, target, before, after)


def _rewrite_images(doc: pymupdf.Document, cfg: CompressSettings) -> None:
    fn = getattr(doc, "rewrite_images", None)
    if fn is None:
        return _rewrite_images_manual(doc, cfg)
    kwargs = dict(dpi_threshold=cfg.dpi_threshold, dpi_target=cfg.dpi_target, quality=cfg.quality,
                  lossy=True, lossless=True, bitonal=True, color=True, gray=True, set_to_gray=cfg.grayscale)
    try:
        fn(**kwargs)
    except TypeError:
        kwargs.pop("set_to_gray", None)
        try:
            fn(**kwargs)
        except Exception:
            _rewrite_images_manual(doc, cfg)
    except Exception:
        _rewrite_images_manual(doc, cfg)


def _rewrite_images_manual(doc: pymupdf.Document, cfg: CompressSettings) -> None:
    """Fallback for older PyMuPDF: shrink & JPEG-encode large images with Pillow."""
    import io
    from PIL import Image
    seen: set[int] = set()
    for page in doc:
        for info in page.get_images(full=True):
            xref = info[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                pix = pymupdf.Pixmap(doc, xref)
                disp_w = max(r.width for r in rects)
                dpi = pix.width / (disp_w / 72.0) if disp_w else 0
                if dpi <= cfg.dpi_threshold and not cfg.grayscale:
                    continue
                if pix.n - pix.alpha >= 4:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                img = Image.frombytes("RGBA" if pix.alpha else ("RGB" if pix.n >= 3 else "L"), (pix.width, pix.height), pix.samples)
                if img.mode == "RGBA":
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img, mask=img.split()[-1])
                    img = bg
                if cfg.grayscale:
                    img = img.convert("L")
                if dpi > cfg.dpi_threshold:
                    scale = cfg.dpi_target / dpi
                    img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=cfg.quality, optimize=True)
                page.replace_image(xref, stream=buf.getvalue())
            except Exception:
                continue


def estimate_after(src: Path, cfg: CompressSettings) -> int | None:
    """Rough estimate without writing to disk: counts image bytes above the DPI threshold."""
    try:
        doc = pymupdf.open(str(src))
    except Exception:
        return None
    try:
        total = src.stat().st_size
        img_bytes = 0
        saved = 0
        seen = set()
        for page in doc:
            for info in page.get_images(full=True):
                xref = info[0]
                if xref in seen:
                    continue
                seen.add(xref)
                try:
                    length = int(doc.xref_get_key(xref, "Length")[1])
                except Exception:
                    continue
                img_bytes += length
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                w = info[2]
                disp_w = max(r.width for r in rects)
                dpi = w / (disp_w / 72.0) if disp_w else 0
                if dpi > cfg.dpi_threshold:
                    factor = (cfg.dpi_target / dpi) ** 2
                    saved += length * (1 - factor * (cfg.quality / 85.0))
                elif cfg.quality < 70:
                    saved += length * 0.25
        est = max(int(total * 0.15), total - int(saved))
        return min(est, total)
    except Exception:
        return None
    finally:
        doc.close()


def _locked(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with open(path, "ab"):
            return False
    except OSError:
        return True
