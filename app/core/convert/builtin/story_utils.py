"""Helpers for laying out HTML into paged PDFs with PyMuPDF's Story engine."""
from __future__ import annotations

import html as _html
from pathlib import Path
from typing import Iterable

import pymupdf

from ..base import ProgressFn, CancelFn, report, check_cancel

A4_PORTRAIT = (595.28, 841.89)
A4_LANDSCAPE = (841.89, 595.28)

BASE_CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.5; color: #111; }
h1 { font-size: 22pt; margin: 14pt 0 8pt 0; }
h2 { font-size: 17pt; margin: 12pt 0 6pt 0; }
h3 { font-size: 14pt; margin: 10pt 0 5pt 0; }
h4, h5, h6 { font-size: 12pt; margin: 8pt 0 4pt 0; }
p { margin: 0 0 6pt 0; }
table { border-collapse: collapse; }
td, th { padding: 3pt 5pt; vertical-align: top; }
pre, code { font-family: monospace; font-size: 9.5pt; }
blockquote { margin: 6pt 0 6pt 16pt; color: #444; }
ul, ol { margin: 0 0 6pt 0; }
.pb { page-break-before: always; }
"""


def esc(text: str) -> str:
    return _html.escape(text or "", quote=False)


def html_to_pdf(html_body: str, dst: Path, *, css: str = "", archive: pymupdf.Archive | None = None,
                page_size: tuple[float, float] = A4_PORTRAIT,
                margins: tuple[float, float, float, float] = (56, 56, 56, 56),
                progress: ProgressFn = None, cancel: CancelFn = None, max_pages: int = 2000) -> int:
    """Lay ``html_body`` out over as many pages as needed. Returns the page count."""
    story = pymupdf.Story(html=html_body, user_css=BASE_CSS + "\n" + css, archive=archive)
    writer = pymupdf.DocumentWriter(str(dst))
    w, h = page_size
    mediabox = pymupdf.Rect(0, 0, w, h)
    left, top, right, bottom = margins
    where = pymupdf.Rect(left, top, w - right, h - bottom)
    more = True
    pages = 0
    try:
        while more and pages < max_pages:
            check_cancel(cancel)
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            pages += 1
            if pages % 5 == 0:
                report(progress, 0.9, f"排版第 {pages} 页")
    finally:
        writer.close()
    return pages


def html_sections_to_pdf(sections: Iterable[tuple[str, tuple[float, float], str]], dst: Path, *,
                         archive: pymupdf.Archive | None = None,
                         margins: tuple[float, float, float, float] = (40, 40, 40, 40),
                         progress: ProgressFn = None, cancel: CancelFn = None) -> int:
    """Each section (html, page_size, css) starts on a fresh page and may use its own page size.
    Sections are rendered separately and concatenated."""
    out = pymupdf.open()
    total = 0
    tmp_files: list[Path] = []
    try:
        for i, (html_body, size, css) in enumerate(sections):
            check_cancel(cancel)
            tmp = Path(str(dst) + f".part{i}.pdf")
            tmp_files.append(tmp)
            n = html_to_pdf(html_body, tmp, css=css, archive=archive, page_size=size, margins=margins, cancel=cancel)
            part = pymupdf.open(str(tmp))
            out.insert_pdf(part)
            part.close()
            total += n
        out.save(str(dst), garbage=3, deflate=True)
    finally:
        out.close()
        for t in tmp_files:
            try:
                t.unlink(missing_ok=True)
            except OSError:
                pass
    return total


def pt(emu: int | float | None, default: float = 0.0) -> float:
    """EMU -> points."""
    if emu is None:
        return default
    return float(emu) / 12700.0


def css_color(rgb) -> str | None:
    try:
        if rgb is None:
            return None
        s = str(rgb)
        if len(s) == 6:
            return "#" + s
    except Exception:
        pass
    return None
