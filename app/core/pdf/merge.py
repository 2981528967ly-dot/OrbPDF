"""Assemble the final PDF: TOC page(s) + sources in order, bookmarks, dividers, page numbers."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from ..convert.base import ConvertCancelled, ConvertError, ProgressFn, CancelFn, report
from ..fileinfo import KIND_BLANK, KIND_DIVIDER, kind_label
from ..naming import unique_path
from .info import contiguous_runs, open_pdf
from .numbering import stamp_page_numbers
from .toc import TocEntry, TocSpec, build_divider_page, insert_toc_pages, toc_page_count

LOG = logging.getLogger("orbpdf.merge")
A4 = (595.28, 841.89)


@dataclass
class MergeSource:
    display_name: str
    kind: str                                  # fileinfo kind (pdf/word/... or blank/divider)
    pdf_path: Path | None = None               # converted PDF (None for blank/divider)
    page_indices: list[int] | None = None      # None = all pages
    password: str | None = None
    source_name: str = ""
    in_toc: bool = True
    rotation: int = 0                          # extra rotation applied to every page of this source


@dataclass
class MergeOptions:
    toc_enabled: bool = True
    toc_title: str = "合并文档"
    toc_style: str = "simple"
    toc_show_kind: bool = False
    toc_show_source: bool = False
    toc_footer: bool = True
    bookmarks: bool = True
    nested_bookmarks: bool = True
    dividers: bool = False
    page_size: str = "keep"          # keep | a4
    page_numbers: bool = False
    pn_format: str = "{n} / {N}"
    pn_position: str = "bottom-center"
    pn_skip_toc: bool = True
    metadata_title: str | None = None


@dataclass
class MergeResult:
    path: Path
    pages: int
    size_bytes: int
    entries: list[tuple[str, int]] = field(default_factory=list)   # (name, 0-based start page)
    warnings: list[str] = field(default_factory=list)


def _page_size_of(doc: pymupdf.Document, idx: int) -> tuple[float, float]:
    try:
        r = doc[idx].rect
        return (r.width, r.height)
    except Exception:
        return A4


def plan_pages(sources: list[MergeSource], opts: MergeOptions, docs: dict[int, pymupdf.Document]) -> tuple[list[TocEntry], int, list[int]]:
    """Return (toc entries, toc page count, per-source page counts). Page numbers already include TOC pages."""
    counts: list[int] = []
    for i, s in enumerate(sources):
        if s.kind in (KIND_BLANK, KIND_DIVIDER):
            counts.append(1)
        else:
            d = docs[i]
            counts.append(len(s.page_indices) if s.page_indices else d.page_count)
    listed = [s for s in sources if s.in_toc and s.kind != KIND_BLANK]
    first_size = A4
    for i, s in enumerate(sources):
        if i in docs and docs[i].page_count:
            first_size = _page_size_of(docs[i], (s.page_indices or [0])[0])
            break
    spec = _spec(opts, len(listed), 0)
    n_toc = toc_page_count(len(listed), spec, first_size) if opts.toc_enabled else 0
    entries: list[TocEntry] = []
    page = n_toc
    for i, s in enumerate(sources):
        divider = opts.dividers and s.in_toc and s.kind not in (KIND_BLANK, KIND_DIVIDER)
        start = page
        if divider:
            page += 1
        if s.in_toc and s.kind != KIND_BLANK:
            entries.append(TocEntry(s.display_name, start, kind_label(s.kind) if s.kind != KIND_DIVIDER else "", s.source_name, counts[i] + (1 if divider else 0)))
        page += counts[i]
    return entries, n_toc, counts


def _spec(opts: MergeOptions, file_count: int, total_pages: int) -> TocSpec:
    return TocSpec(title=opts.toc_title or "合并文档", style=opts.toc_style, show_kind=opts.toc_show_kind,
                   show_source=opts.toc_show_source, footer=opts.toc_footer, total_pages=total_pages, file_count=file_count)


def merge(sources: list[MergeSource], opts: MergeOptions, out_path: Path, *, progress: ProgressFn = None,
          cancel: CancelFn = None) -> MergeResult:
    if not sources:
        raise ConvertError("队列是空的")
    docs: dict[int, pymupdf.Document] = {}
    warnings: list[str] = []
    out = pymupdf.open()
    try:
        # 1. open everything
        for i, s in enumerate(sources):
            if cancel and cancel():
                raise ConvertCancelled("已取消")
            if s.kind in (KIND_BLANK, KIND_DIVIDER):
                continue
            if not s.pdf_path or not Path(s.pdf_path).exists():
                raise ConvertError(f"「{s.display_name}」还没有转换完成")
            docs[i] = open_pdf(s.pdf_path, s.password)
            if s.page_indices:
                bad = [p for p in s.page_indices if p < 0 or p >= docs[i].page_count]
                if bad:
                    raise ConvertError(f"「{s.display_name}」的页面范围超出了 {docs[i].page_count} 页")
        entries, n_toc, counts = plan_pages(sources, opts, docs)
        total_pages = n_toc + sum(counts)
        first_size = A4
        for i, s in enumerate(sources):
            if i in docs and docs[i].page_count:
                first_size = _page_size_of(docs[i], (s.page_indices or [0])[0])
                break
        if opts.page_size == "a4":
            first_size = A4 if first_size[0] <= first_size[1] else (A4[1], A4[0])

        # 2. bodies (TOC pages are inserted at the front afterwards, so that links can be validated)
        outline: list[list] = []
        part_no = 0
        n = len(sources)
        prev_size = first_size
        result_entries: list[tuple[str, int]] = []
        for i, s in enumerate(sources):
            if cancel and cancel():
                raise ConvertCancelled("已取消")
            report(progress, 0.1 + 0.8 * i / max(1, n), f"合并 {s.display_name}")
            start = out.page_count + n_toc   # final page index once the TOC is in front
            if s.kind == KIND_BLANK:
                out.new_page(width=prev_size[0], height=prev_size[1])
                continue
            if s.kind == KIND_DIVIDER:
                part_no += 1
                build_divider_page(out, s.display_name, part_no, prev_size)
                if s.in_toc:
                    outline.append([1, s.display_name, start + 1])
                    result_entries.append((s.display_name, start))
                continue
            if opts.dividers and s.in_toc:
                part_no += 1
                build_divider_page(out, s.display_name, part_no, prev_size if opts.page_size != "a4" else first_size)
            d = docs[i]
            indices = s.page_indices or list(range(d.page_count))
            if opts.page_size == "a4":
                for p in indices:
                    src_rect = d[p].rect
                    landscape = src_rect.width > src_rect.height
                    pw, ph = (A4[1], A4[0]) if landscape else A4
                    if s.rotation % 180:
                        pw, ph = ph, pw
                    page = out.new_page(width=pw, height=ph)
                    try:
                        page.show_pdf_page(page.rect, d, p, rotate=s.rotation)
                    except Exception as e:  # noqa: BLE001
                        warnings.append(f"「{s.display_name}」第 {p + 1} 页无法缩放：{e}")
            else:
                for a, b in contiguous_runs(indices):
                    first_new = out.page_count
                    out.insert_pdf(d, from_page=a, to_page=b, links=True, annots=True)
                    if s.rotation:
                        for k, p in enumerate(range(a, b + 1)):
                            try:
                                out[first_new + k].set_rotation((d[p].rotation + s.rotation) % 360)
                            except Exception:
                                pass
            if indices:
                prev_size = _page_size_of(d, indices[-1]) if opts.page_size != "a4" else first_size
            if s.in_toc:
                outline.append([1, s.display_name, start + 1])
                result_entries.append((s.display_name, start))
                if opts.nested_bookmarks:
                    try:
                        sub = d.get_toc(simple=True)
                    except Exception:
                        sub = []
                    pos = {p: k for k, p in enumerate(indices)}
                    offset = start + (1 if (opts.dividers and s.in_toc) else 0)
                    for lvl, title, pg in sub[:200]:
                        if not title or not title.strip():
                            continue
                        if (pg - 1) in pos and lvl <= 2:
                            outline.append([min(3, lvl + 1), title.strip()[:120], offset + pos[pg - 1] + 1])

        # 3. TOC pages at the front
        if opts.toc_enabled:
            report(progress, 0.9, "绘制目录页")
            listed = [s for s in sources if s.in_toc and s.kind != KIND_BLANK]
            spec = _spec(opts, len(listed), total_pages)
            drawn = insert_toc_pages(out, entries, spec, first_size)
            if drawn != n_toc:
                warnings.append("目录页数与预计不一致")

        # 4. bookmarks, numbering, metadata
        if opts.bookmarks and outline:
            try:
                out.set_toc(_sanitize_outline(outline))
            except Exception as e:  # noqa: BLE001
                warnings.append(f"书签写入失败：{e}")
        if opts.page_numbers:
            report(progress, 0.92, "添加页码")
            first = n_toc if opts.pn_skip_toc else 0
            stamp_page_numbers(out, opts.pn_format, opts.pn_position, start_index=first, first_number=1)
        title = opts.metadata_title or (opts.toc_title if opts.toc_enabled else "") or sources[0].display_name
        try:
            out.set_metadata({"title": title, "producer": "OrbPDF", "creator": "OrbPDF", "author": ""})
        except Exception:
            pass
        report(progress, 0.95, "保存")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        target = unique_path(out_path) if _is_locked(out_path) else out_path
        try:
            out.save(str(target), garbage=3, deflate=True)
        except Exception:
            target = unique_path(out_path)
            out.save(str(target), garbage=3, deflate=True)
        size = target.stat().st_size
        return MergeResult(target, out.page_count, size, result_entries, warnings)
    finally:
        for d in docs.values():
            try:
                d.close()
            except Exception:
                pass
        out.close()


def _sanitize_outline(outline: list[list]) -> list[list]:
    """PyMuPDF requires levels to increase by at most one step."""
    fixed: list[list] = []
    prev = 0
    for lvl, title, page in outline:
        lvl = int(lvl)
        if lvl > prev + 1:
            lvl = prev + 1
        fixed.append([lvl, title, int(page)])
        prev = lvl
    return fixed


def _is_locked(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with open(path, "ab"):
            return False
    except OSError:
        return True
