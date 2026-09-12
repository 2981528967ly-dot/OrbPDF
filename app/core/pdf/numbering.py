"""Page number stamps."""
from __future__ import annotations

import pymupdf

from .text import text_width, write_text

POSITIONS = {
    "bottom-center": "底部居中", "bottom-right": "底部右侧", "bottom-left": "底部左侧",
    "top-center": "顶部居中", "top-right": "顶部右侧", "top-left": "顶部左侧",
}
FORMATS = {
    "{n} / {N}": "1 / 10", "第 {n} 页": "第 1 页", "第 {n} 页 / 共 {N} 页": "第 1 页 / 共 10 页", "{n}": "1", "- {n} -": "- 1 -",
}


def stamp_page_numbers(doc: pymupdf.Document, fmt: str = "{n} / {N}", position: str = "bottom-center", *,
                       start_index: int = 0, first_number: int = 1, fontsize: float = 9.5, margin: float = 28.0,
                       color=(0.25, 0.27, 0.32), indices: list[int] | None = None) -> int:
    """Stamp pages [start_index:] (or the given indices). Returns number of pages stamped."""
    targets = indices if indices is not None else list(range(start_index, doc.page_count))
    total = len(targets)
    count = 0
    for k, pno in enumerate(targets):
        page = doc[pno]
        text = fmt.replace("{n}", str(first_number + k)).replace("{N}", str(first_number + total - 1))
        w = text_width(text, fontsize)
        rect = page.rect
        pw, ph = rect.width, rect.height
        y = margin if position.startswith("top") else ph - margin + fontsize * 0.35
        if position.endswith("center"):
            x = (pw - w) / 2
        elif position.endswith("right"):
            x = pw - margin - w
        else:
            x = margin
        try:
            rot = page.rotation
            if rot:
                # draw in unrotated coordinates, then rotate the text with the page
                point = pymupdf.Point(x, y) * page.derotation_matrix
                mat = pymupdf.Matrix(1, 1).prerotate(rot)
                write_text(page, point.x, point.y, text, fontsize, color, morph=(point, mat))
            else:
                write_text(page, x, y, text, fontsize, color)
            count += 1
        except Exception:
            continue
    return count
