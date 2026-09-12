"""Engine registry: detection, ordering, fallback chain, caching."""
from __future__ import annotations

import logging
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

import pymupdf

from ..fileinfo import (KIND_PDF, KIND_WORD, KIND_PPT, KIND_EXCEL, KIND_IMAGE, KIND_TEXT, LEGACY_OFFICE_EXTS, kind_of)
from ..settings import settings
from .base import (ConvertCancelled, ConvertError, ConvertOptions, ConvertResult, Engine, EngineInfo, EngineUnavailable,
                   NeedsPassword, ProgressFn, CancelFn, report)
from .builtin.docx_engine import DocxEngine
from .builtin.images import ImageEngine
from .builtin.mupdf_native import MuPdfNativeEngine
from .builtin.pptx_engine import PptxEngine
from .builtin.text import TextEngine
from .builtin.xlsx_engine import XlsxEngine
from .cache import ConversionCache
from .libreoffice import LibreOfficeEngine
from .office_com import make_ms_office, make_wps

LOG = logging.getLogger("orbpdf.convert")

OFFICE_KINDS = {KIND_WORD, KIND_PPT, KIND_EXCEL}


class BuiltinEngine(Engine):
    """Composite zero-dependency engine; dispatches by kind, MuPDF native as the very last resort."""
    id = "builtin"
    name = "内置引擎"
    kinds = frozenset({KIND_WORD, KIND_PPT, KIND_EXCEL, KIND_IMAGE, KIND_TEXT})
    fidelity = "basic"

    def __init__(self) -> None:
        self.image = ImageEngine()
        self.text = TextEngine()
        self.docx = DocxEngine()
        self.pptx = PptxEngine()
        self.xlsx = XlsxEngine()
        self.native = MuPdfNativeEngine()

    def probe(self) -> EngineInfo:
        return EngineInfo(self.id, self.name, True, "图片 · 文本 · Word / PPT / Excel 基础排版", set(self.kinds), "basic", True)

    def supports(self, src: Path) -> bool:
        k = kind_of(src)
        if k in (KIND_IMAGE, KIND_TEXT):
            return True
        return any(e.supports(src) for e in (self.docx, self.pptx, self.xlsx, self.native))

    def convert(self, src, dst, opts, progress=None, cancel=None):
        k = kind_of(src)
        if k == KIND_IMAGE:
            return self.image.convert(src, dst, opts, progress, cancel)
        if k == KIND_TEXT:
            return self.text.convert(src, dst, opts, progress, cancel)
        primary = {KIND_WORD: self.docx, KIND_PPT: self.pptx, KIND_EXCEL: self.xlsx}.get(k)
        errors = []
        if primary is not None and primary.supports(src):
            try:
                return primary.convert(src, dst, opts, progress, cancel)
            except ConvertCancelled:
                raise
            except Exception as e:  # noqa: BLE001
                LOG.warning("builtin %s failed for %s: %s", primary.id, src.name, e)
                errors.append(str(e))
        if self.native.supports(src):
            try:
                w = self.native.convert(src, dst, opts, progress, cancel)
                return w
            except ConvertCancelled:
                raise
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
        if src.suffix.lower() in LEGACY_OFFICE_EXTS:
            raise ConvertError(f"旧版 {src.suffix} 格式需要本机安装 Office 或 WPS，或先另存为 {_modern_ext(src.suffix)}")
        raise ConvertError("；".join(errors) if errors else "内置引擎不支持该文件")


def _modern_ext(ext: str) -> str:
    return {".doc": ".docx", ".rtf": ".docx", ".odt": ".docx", ".wps": ".docx", ".ppt": ".pptx", ".odp": ".pptx", ".dps": ".pptx",
            ".xls": ".xlsx", ".ods": ".xlsx", ".et": ".xlsx"}.get(ext.lower(), ".docx")


class EngineRegistry:
    def __init__(self) -> None:
        self.msoffice = make_ms_office()
        self.wps = make_wps()
        self.libreoffice = LibreOfficeEngine()
        self.builtin = BuiltinEngine()
        self.engines: dict[str, Engine] = {
            "msoffice": self.msoffice, "wps": self.wps, "libreoffice": self.libreoffice, "builtin": self.builtin,
        }
        self.cache = ConversionCache()
        self._infos: dict[str, EngineInfo] | None = None

    # -- detection -------------------------------------------------------
    def probe_all(self, force: bool = False) -> dict[str, EngineInfo]:
        if self._infos is None or force:
            infos = {}
            for eid, eng in self.engines.items():
                try:
                    infos[eid] = eng.probe(force=True) if eid != "builtin" else eng.probe()  # type: ignore[call-arg]
                except TypeError:
                    infos[eid] = eng.probe()
                except Exception as e:  # noqa: BLE001
                    infos[eid] = EngineInfo(eid, eng.name, False, f"探测失败：{e}")
            self._infos = infos
        return self._infos

    def best_engine_name(self, src: Path) -> str:
        chain = self.chain_for(src)
        return chain[0].name if chain else "—"

    def chain_for(self, src: Path) -> list[Engine]:
        k = kind_of(src)
        if k is None or k == KIND_PDF:
            return []
        if k in (KIND_IMAGE, KIND_TEXT):
            return [self.builtin]
        order = list(settings().get("engine_order") or ["msoffice", "wps", "libreoffice", "builtin"])
        if not settings().get("prefer_office", True):
            order = ["builtin"] + [o for o in order if o != "builtin"]
        chain: list[Engine] = []
        for eid in order:
            eng = self.engines.get(eid)
            if eng is None:
                continue
            try:
                if eng.supports(src):
                    chain.append(eng)
            except Exception:
                continue
        if self.builtin not in chain and self.builtin.supports(src):
            chain.append(self.builtin)
        if not settings().get("fallback_on_error", True) and chain:
            chain = chain[:1]
        return chain

    # -- batches -----------------------------------------------------------
    @contextmanager
    def batch(self):
        try:
            yield self
        finally:
            self.end_batch()

    def end_batch(self) -> None:
        for eng in self.engines.values():
            try:
                eng.end_batch()
            except Exception:
                pass

    # -- conversion --------------------------------------------------------
    def convert(self, src: Path, dst: Path | None = None, opts: ConvertOptions | None = None, *,
                progress: ProgressFn = None, cancel: CancelFn = None, use_cache: bool = True,
                forced_engine: str | None = None) -> ConvertResult:
        src = Path(src)
        opts = opts or default_options()
        k = kind_of(src)
        if k is None:
            raise ConvertError(f"不支持的文件类型：{src.suffix or '(无扩展名)'}")
        if not src.exists():
            raise ConvertError("文件不存在或已被移动")
        t0 = time.time()
        if k == KIND_PDF:
            pages = pdf_page_count(src, opts.password)
            out = dst or src
            if dst and Path(dst) != src:
                shutil.copy2(src, dst)
            return ConvertResult(Path(out), "pdf", "PDF", pages, [], time.time() - t0)

        cached = self.cache.get(src, opts) if use_cache and not forced_engine else None
        if cached:
            out = dst or cached.pdf_path
            if dst and Path(dst) != cached.pdf_path:
                shutil.copy2(cached.pdf_path, dst)
            return ConvertResult(Path(out), cached.engine_id, cached.engine_name, cached.pages, list(cached.warnings), 0.0, True)

        target = Path(dst) if dst else self.cache.target_path(src, opts)
        chain = self.chain_for(src)
        if forced_engine:
            eng = self.engines.get(forced_engine)
            chain = [eng] if eng and eng.supports(src) else []
        if not chain:
            if src.suffix.lower() in LEGACY_OFFICE_EXTS:
                raise ConvertError(f"旧版 {src.suffix} 格式需要本机安装 Office 或 WPS，或先另存为 {_modern_ext(src.suffix)}")
            raise ConvertError("没有可用的转换引擎")
        errors: list[str] = []
        warnings: list[str] = []
        for i, eng in enumerate(chain):
            if cancel and cancel():
                raise ConvertCancelled("已取消")
            report(progress, 0.02, f"使用 {eng.name}")
            try:
                w = eng.convert(src, target, opts, progress, cancel)
                warnings.extend(w or [])
                if i > 0:
                    warnings.insert(0, f"{chain[0].name} 失败，已改用 {eng.name}")
                if eng.fidelity == "basic" and k in OFFICE_KINDS:
                    warnings.append("已用内置引擎，排版可能简化")
                pages = pdf_page_count(target)
                res = ConvertResult(target, eng.id, eng.name, pages, _dedupe(warnings), time.time() - t0)
                if use_cache and not dst:
                    self.cache.put(src, opts, eng.id, eng.name, pages, res.warnings)
                elif use_cache and dst:
                    # also keep a cached copy for later reuse by the merge module
                    try:
                        cpath = self.cache.target_path(src, opts)
                        shutil.copy2(target, cpath)
                        self.cache.put(src, opts, eng.id, eng.name, pages, res.warnings)
                    except OSError:
                        pass
                return res
            except ConvertCancelled:
                raise
            except NeedsPassword:
                raise
            except EngineUnavailable as e:
                LOG.info("engine %s unavailable for %s: %s", eng.id, src.name, e)
                errors.append(f"{eng.name}：{e}")
            except ConvertError as e:
                LOG.warning("engine %s failed for %s: %s", eng.id, src.name, e)
                errors.append(f"{eng.name}：{e}")
            except Exception as e:  # noqa: BLE001
                LOG.exception("engine %s crashed for %s", eng.id, src.name)
                errors.append(f"{eng.name}：{type(e).__name__} {e}")
        raise ConvertError("；".join(errors) if errors else "转换失败")


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for s in items:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def pdf_page_count(path: Path, password: str | None = None) -> int:
    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        raise ConvertError(f"无法打开 PDF：{e}") from e
    try:
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                raise NeedsPassword("该 PDF 已加密，需要密码")
        return doc.page_count
    finally:
        doc.close()


def default_options() -> ConvertOptions:
    s = settings()
    return ConvertOptions(
        image_fit=s.get("image_fit", "bleed"),
        image_max_side=int(s.get("image_max_side", 0) or 0),
        jpeg_quality=int(s.get("jpeg_quality", 90) or 90),
        timeout=int(s.get("engine_timeout", 120) or 120),
    )


_registry: EngineRegistry | None = None


def registry() -> EngineRegistry:
    global _registry
    if _registry is None:
        _registry = EngineRegistry()
    return _registry
