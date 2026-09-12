"""Table-of-contents page(s) with clickable entries (built-in fonts only)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pymupdf

from .text import fit_text, text_width, write_text, write_centered, write_right

MARGIN = 56.0
TITLE_SIZE = 22.0
ENTRY_SIZE = 11.5
SMALL_SIZE = 8.5
ROW_H = 24.0
ROW_H_WITH_SOURCE = 34.0
ACCENT = (0.118, 0.533, 0.710)   # printed cyan-blue
MUTED = (0.46, 0.50, 0.58)
INK = (0.08, 0.10, 0.14)
LEADER = (0.62, 0.66, 0.72)


@dataclass
class TocEntry:
    title: str
    page: int              # 0-based page index in the final document
    kind_label: str = ""
    source: str = ""
    pages: int = 0
    children: list["TocEntry"] = field(default_factory=list)


@dataclass
class TocSpec:
    title: str = "合并文档"
    style: str = "simple"          # simple | formal | table
    show_kind: bool = False
    show_source: bool = False
    footer: bool = True
    subtitle: str | None = ""      # "" -> no subtitle line; None -> auto ("共 N 个文件 · M 页 · 日期")
    total_pages: int = 0
    file_count: int = 0


def rows_per_page(spec: TocSpec, page_h: float, first: bool) -> int:
    top = (168.0 if spec.subtitle != "" else 150.0) if first else 96.0
    bottom = MARGIN + (18 if spec.footer else 0)
    row_h = ROW_H_WITH_SOURCE if spec.show_source else ROW_H
    if spec.style == "table":
        row_h += 4
    return max(1, int((page_h - top - bottom) // row_h))


def toc_page_count(n_entries: int, spec: TocSpec, page_size: tuple[float, float]) -> int:
    if n_entries <= 0:
        return 1
    h = page_size[1]
    left = n_entries - rows_per_page(spec, h, True)
    pages = 1
    while left > 0:
        left -= rows_per_page(spec, h, False)
        pages += 1
    return pages


def insert_toc_pages(doc: pymupdf.Document, entries: list[TocEntry], spec: TocSpec, page_size: tuple[float, float],
                     links: bool = True) -> int:
    """Insert the TOC pages at the *front* of ``doc``. Entry page numbers must already be final
    (i.e. include the TOC pages themselves), so links can be validated by PyMuPDF. Returns page count.
    ``links=False`` draws a preview without link annotations (targets need not exist)."""
    w, h = page_size
    row_h = (ROW_H_WITH_SOURCE if spec.show_source else ROW_H) + (4 if spec.style == "table" else 0)
    idx = 0
    page_no = 0
    n_pages = toc_page_count(len(entries), spec, page_size)
    while page_no < n_pages:
        first = page_no == 0
        page = doc.new_page(pno=page_no, width=w, height=h)
        y = _draw_header(page, spec, first)
        cap = rows_per_page(spec, h, first)
        chunk = entries[idx: idx + cap]
        if spec.style == "table":
            y = _draw_table_header(page, y)
        for k, e in enumerate(chunk):
            _draw_entry(page, e, idx + k + 1, y, row_h, spec, links)
            y += row_h
        idx += len(chunk)
        if spec.footer:
            _draw_footer(page, spec, page_no + 1, n_pages)
        page_no += 1
    return n_pages


def _auto_subtitle(spec: TocSpec) -> str:
    parts = []
    if spec.file_count:
        parts.append(f"共 {spec.file_count} 个文件")
    if spec.total_pages:
        parts.append(f"{spec.total_pages} 页")
    parts.append(date.today().isoformat())
    return " · ".join(parts)


def _draw_header(page: pymupdf.Page, spec: TocSpec, first: bool) -> float:
    w = page.rect.width
    if first:
        title = fit_text(spec.title or "目录", TITLE_SIZE, w - 2 * MARGIN, bold=True)
        write_text(page, MARGIN, 96, title, TITLE_SIZE, INK, bold=True)
        sub = spec.subtitle if spec.subtitle is not None else _auto_subtitle(spec)
        y_rule = 132.0
        if sub:
            write_text(page, MARGIN, 118, sub, 10, MUTED)
        else:
            y_rule = 114.0
        if spec.style == "simple":
            page.draw_line((MARGIN, y_rule), (MARGIN + 64, y_rule), color=ACCENT, width=1.6)
        elif spec.style == "formal":
            page.draw_line((MARGIN, y_rule), (w - MARGIN, y_rule), color=INK, width=0.6)
        if spec.style != "table" and (spec.title or "").strip() != "目录":
            write_text(page, MARGIN, y_rule + 26, "目录", 12, MUTED)
        return y_rule + 36.0
    write_text(page, MARGIN, 70, "目录（续）", 13, MUTED)
    if spec.style == "simple":
        page.draw_line((MARGIN, 80), (MARGIN + 40, 80), color=ACCENT, width=1.2)
    return 96.0


def _draw_table_header(page: pymupdf.Page, y: float) -> float:
    w = page.rect.width
    hdr = pymupdf.Rect(MARGIN, y - 2, w - MARGIN, y + 18)
    page.draw_rect(hdr, color=None, fill=(0.93, 0.95, 0.97))
    page.draw_line((MARGIN, y + 18), (w - MARGIN, y + 18), color=INK, width=0.6)
    write_text(page, MARGIN + 6, y + 12, "序号", 9.5, INK)
    write_text(page, MARGIN + 44, y + 12, "名称", 9.5, INK)
    write_text(page, w - MARGIN - 110, y + 12, "类型", 9.5, INK)
    write_text(page, w - MARGIN - 34, y + 12, "页码", 9.5, INK)
    return y + 26


def _draw_entry(page: pymupdf.Page, e: TocEntry, number: int, y: float, row_h: float, spec: TocSpec, links: bool = True) -> None:
    w = page.rect.width
    baseline = y + ENTRY_SIZE + 2
    x_num = MARGIN
    x_name = MARGIN + 30
    page_text = str(e.page + 1)
    pw = text_width(page_text, ENTRY_SIZE)
    x_page = w - MARGIN - pw
    if spec.style == "table":
        write_text(page, x_num + 6, baseline, str(number), ENTRY_SIZE, INK)
        name_w = (w - MARGIN - 110) - (x_name + 14) - 6
        write_text(page, x_name + 14, baseline, fit_text(e.title, ENTRY_SIZE, name_w), ENTRY_SIZE, INK)
        if e.kind_label:
            write_text(page, w - MARGIN - 110, baseline, e.kind_label, 9.5, MUTED)
        write_text(page, w - MARGIN - 34, baseline, page_text, ENTRY_SIZE, INK)
        page.draw_line((MARGIN, y + row_h - 4), (w - MARGIN, y + row_h - 4), color=(0.8, 0.82, 0.86), width=0.4)
        if spec.show_source and e.source:
            write_text(page, x_name + 14, baseline + 12, fit_text(e.source, SMALL_SIZE, name_w), SMALL_SIZE, MUTED)
    else:
        write_text(page, x_num, baseline, str(number), ENTRY_SIZE, MUTED)
        kind_w = 0.0
        if spec.show_kind and e.kind_label:
            kind_w = text_width(e.kind_label, SMALL_SIZE) + 10
        max_name_w = (x_page - 24) - x_name - kind_w - 6
        name = fit_text(e.title, ENTRY_SIZE, max_name_w)
        nw = write_text(page, x_name, baseline, name, ENTRY_SIZE, INK)
        x = x_name + nw + 6
        if kind_w:
            write_text(page, x, baseline, e.kind_label, SMALL_SIZE, MUTED)
            x += kind_w
        # dotted leader
        avail = (x_page - 8) - x
        dot_w = text_width(".", ENTRY_SIZE) * 1.5
        if avail > dot_w * 2:
            n = int(avail // dot_w)
            leader_x = x_page - 8 - n * dot_w
            for i in range(n):
                write_text(page, leader_x + i * dot_w, baseline, ".", ENTRY_SIZE, LEADER)
        write_text(page, x_page, baseline, page_text, ENTRY_SIZE, INK)
        if spec.show_source and e.source:
            write_text(page, x_name, baseline + 12, fit_text(e.source, SMALL_SIZE, x_page - x_name - 10), SMALL_SIZE, MUTED)
    if links:
        link_rect = pymupdf.Rect(MARGIN, y, w - MARGIN, y + row_h - 2)
        page.insert_link({"kind": pymupdf.LINK_GOTO, "from": link_rect, "page": e.page, "to": pymupdf.Point(0, 0), "zoom": 0})


def _draw_footer(page: pymupdf.Page, spec: TocSpec, n: int, total: int) -> None:
    w, h = page.rect.width, page.rect.height
    write_text(page, MARGIN, h - 40, "由 OrbPDF 生成 · 点击条目可跳转", 8, MUTED)
    if total > 1:
        write_right(page, w - MARGIN, h - 40, f"目录 {n} / {total}", 8, MUTED)


def build_divider_page(doc: pymupdf.Document, title: str, index: int, page_size: tuple[float, float], at: int = -1) -> pymupdf.Page:
    w, h = page_size
    page = doc.new_page(pno=at, width=w, height=h)
    size = 26.0
    t = fit_text(title, size, w - 2 * MARGIN, bold=True)
    write_centered(page, w / 2, h * 0.42, t, size, INK, bold=True)
    write_centered(page, w / 2, h * 0.42 + 26, f"第 {index} 部分", 11, MUTED)
    page.draw_line((w / 2 - 28, h * 0.42 + 40), (w / 2 + 28, h * 0.42 + 40), color=ACCENT, width=1.4)
    return page
