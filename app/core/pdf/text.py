"""Mixed-script text drawing: Latin glyphs from Helvetica, everything else from the built-in CJK font.
No system fonts involved, so output is identical on every machine."""
from __future__ import annotations

from functools import lru_cache

import pymupdf

_LATIN = pymupdf.Font("helv")
_LATIN_BOLD = pymupdf.Font("hebo")
_CJK = pymupdf.Font("china-s")


def _latin_ok(ch: str, font: pymupdf.Font) -> bool:
    o = ord(ch)
    if o < 0x2E80 and o not in (0x2014, 0x2026):    # keep em-dash / ellipsis on the CJK side for width consistency
        try:
            return font.has_glyph(o) != 0
        except Exception:
            return o < 0x250
    return False


def runs(text: str, bold: bool = False) -> list[tuple[pymupdf.Font, str]]:
    """Split text into (font, chunk) runs."""
    latin = _LATIN_BOLD if bold else _LATIN
    out: list[tuple[pymupdf.Font, str]] = []
    cur_font = None
    buf: list[str] = []
    for ch in text:
        f = latin if _latin_ok(ch, latin) else _CJK
        if f is not cur_font and buf:
            out.append((cur_font, "".join(buf)))
            buf = []
        cur_font = f
        buf.append(ch)
    if buf:
        out.append((cur_font, "".join(buf)))
    return out


@lru_cache(maxsize=4096)
def text_width(text: str, size: float, bold: bool = False) -> float:
    return sum(f.text_length(chunk, fontsize=size) for f, chunk in runs(text, bold))


def fit_text(text: str, size: float, max_w: float, bold: bool = False) -> str:
    if text_width(text, size, bold) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if text_width(text[:mid] + ell, size, bold) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell


def write_text(page: pymupdf.Page, x: float, y: float, text: str, size: float, color=(0, 0, 0), *, bold: bool = False,
               opacity: float = 1.0, morph=None, faux_bold: bool = False) -> float:
    """Draw ``text`` with its baseline at (x, y). Returns the advance width."""
    if not text:
        return 0.0
    tw = pymupdf.TextWriter(page.rect, opacity=opacity, color=color)
    pos = pymupdf.Point(x, y)
    for f, chunk in runs(text, bold):
        try:
            _rect, pos = tw.append(pos, chunk, font=f, fontsize=size)
        except Exception:
            continue
    kwargs = {"overlay": True}
    if morph is not None:
        kwargs["morph"] = morph
    if faux_bold:
        try:
            tw.write_text(page, render_mode=2, **kwargs)
            return pos.x - x
        except TypeError:
            pass
    tw.write_text(page, **kwargs)
    return pos.x - x


def write_centered(page: pymupdf.Page, cx: float, y: float, text: str, size: float, color=(0, 0, 0), bold: bool = False) -> float:
    w = text_width(text, size, bold)
    return write_text(page, cx - w / 2, y, text, size, color, bold=bold)


def write_right(page: pymupdf.Page, right_x: float, y: float, text: str, size: float, color=(0, 0, 0), bold: bool = False) -> float:
    w = text_width(text, size, bold)
    return write_text(page, right_x - w, y, text, size, color, bold=bold)
