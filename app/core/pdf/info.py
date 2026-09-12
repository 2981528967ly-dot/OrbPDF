"""Opening PDFs safely, page ranges, quick facts."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from ..convert.base import ConvertError, NeedsPassword


def open_pdf(path: str | Path, password: str | None = None) -> pymupdf.Document:
    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        raise ConvertError(f"无法打开 PDF：{e}") from e
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            raise NeedsPassword("该 PDF 已加密，需要密码")
    if not doc.is_pdf:
        # images / xps etc. opened by MuPDF -> convert on the fly
        try:
            data = doc.convert_to_pdf()
        finally:
            doc.close()
        doc = pymupdf.open("pdf", data)
    return doc


@dataclass
class PdfInfo:
    path: Path
    pages: int
    encrypted: bool
    size_bytes: int
    title: str = ""
    page_sizes: list[tuple[float, float]] = field(default_factory=list)
    has_outline: bool = False


def is_password_protected(path: str | Path) -> bool:
    try:
        d = pymupdf.open(str(path))
        try:
            return bool(d.needs_pass)
        finally:
            d.close()
    except Exception:
        return False


def inspect_pdf(path: str | Path, password: str | None = None) -> PdfInfo:
    p = Path(path)
    encrypted = is_password_protected(p)
    doc = open_pdf(p, password)   # do not touch doc.needs_pass after authentication (PyMuPDF quirk)
    try:
        sizes = [(pg.rect.width, pg.rect.height) for pg in doc]
        meta = doc.metadata or {}
        return PdfInfo(p, doc.page_count, encrypted, p.stat().st_size if p.exists() else 0,
                       (meta.get("title") or "").strip(), sizes, bool(doc.get_toc(simple=True)))
    finally:
        doc.close()


_RANGE_RE = re.compile(r"^\s*(\d*)\s*(?:-\s*(\d*))?\s*$")


def parse_page_range(spec: str | None, n_pages: int) -> list[int] | None:
    """'1-3,5,8-' -> [0,1,2,4,7,...]. Empty spec -> None (all pages). Raises ValueError on bad input."""
    if spec is None or not spec.strip():
        return None
    out: list[int] = []
    for part in re.split(r"[,，;；\s]+", spec.strip()):
        if not part:
            continue
        m = _RANGE_RE.match(part)
        if not m:
            raise ValueError(f"无法识别的页码：{part}")
        a, b = m.group(1), m.group(2)
        if "-" in part:
            start = int(a) if a else 1
            end = int(b) if b else n_pages
        else:
            start = end = int(a)
        if start < 1 or end > n_pages or start > end:
            raise ValueError(f"页码超出范围（共 {n_pages} 页）：{part}")
        out.extend(range(start - 1, end))
    # keep order but drop duplicates
    seen = set()
    result = []
    for i in out:
        if i not in seen:
            seen.add(i)
            result.append(i)
    return result or None


def format_page_range(indices: list[int] | None) -> str:
    if not indices:
        return ""
    idx = sorted(set(indices))
    runs: list[list[int]] = []
    for i in idx:
        if runs and i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return ",".join(f"{a + 1}-{b + 1}" if a != b else f"{a + 1}" for a, b in runs)


def contiguous_runs(indices: list[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for i in indices:
        if runs and i == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return runs
