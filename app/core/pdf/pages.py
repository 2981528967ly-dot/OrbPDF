"""Page-level editing and splitting."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from ..convert.base import ConvertError, ProgressFn, CancelFn, report, check_cancel
from ..naming import sanitize_filename, unique_path
from .info import contiguous_runs


@dataclass(frozen=True)
class PageRef:
    """A page in the editor: which source document, which page, extra rotation."""
    src_id: str
    page_no: int
    rotation: int = 0       # 0/90/180/270 added to the page's own rotation


def build_document(refs: list[PageRef], sources: dict[str, pymupdf.Document]) -> pymupdf.Document:
    """Materialise the editor state into a new document (rotations applied)."""
    out = pymupdf.open()
    i = 0
    while i < len(refs):
        # group consecutive pages from the same source with same rotation for speed
        j = i
        src_id = refs[i].src_id
        rot = refs[i].rotation
        run = [refs[i].page_no]
        while j + 1 < len(refs) and refs[j + 1].src_id == src_id and refs[j + 1].rotation == rot and refs[j + 1].page_no == refs[j].page_no + 1:
            j += 1
            run.append(refs[j].page_no)
        src = sources[src_id]
        out.insert_pdf(src, from_page=run[0], to_page=run[-1], links=True, annots=True)
        if rot:
            for k in range(len(run)):
                page = out[out.page_count - len(run) + k]
                page.set_rotation((page.rotation + rot) % 360)
        i = j + 1
    return out


def save_document(doc: pymupdf.Document, path: Path, *, overwrite_source: Path | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite_source and Path(overwrite_source).resolve() == path.resolve():
        # cannot save over an open source: save to temp then replace
        tmp = path.with_suffix(".orbpdf-tmp.pdf")
        doc.save(str(tmp), garbage=3, deflate=True)
        tmp.replace(path)
        return path
    target = unique_path(path) if _locked(path) else path
    doc.save(str(target), garbage=3, deflate=True)
    return target


def _locked(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with open(path, "ab"):
            return False
    except OSError:
        return True


def extract_pages(doc: pymupdf.Document, indices: list[int], out_path: Path) -> Path:
    if not indices:
        raise ConvertError("没有选中任何页面")
    out = pymupdf.open()
    try:
        for a, b in contiguous_runs(sorted(set(indices))):
            out.insert_pdf(doc, from_page=a, to_page=b)
        return save_document(out, out_path)
    finally:
        out.close()


def split_every(doc: pymupdf.Document, n: int, out_dir: Path, base: str, progress: ProgressFn = None, cancel: CancelFn = None) -> list[Path]:
    n = max(1, int(n))
    ranges = [list(range(i, min(i + n, doc.page_count))) for i in range(0, doc.page_count, n)]
    return split_ranges(doc, ranges, out_dir, base, progress, cancel)


def split_each(doc: pymupdf.Document, out_dir: Path, base: str, progress: ProgressFn = None, cancel: CancelFn = None) -> list[Path]:
    return split_every(doc, 1, out_dir, base, progress, cancel)


def split_ranges(doc: pymupdf.Document, ranges: list[list[int]], out_dir: Path, base: str, progress: ProgressFn = None,
                 cancel: CancelFn = None, names: list[str] | None = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    width = len(str(len(ranges)))
    for k, idxs in enumerate(ranges):
        check_cancel(cancel)
        if not idxs:
            continue
        report(progress, k / max(1, len(ranges)), f"拆分第 {k + 1}/{len(ranges)} 份")
        part = pymupdf.open()
        try:
            for a, b in contiguous_runs(sorted(idxs)):
                part.insert_pdf(doc, from_page=a, to_page=b)
            if names and k < len(names) and names[k]:
                name = sanitize_filename(names[k])
            else:
                first, last = idxs[0] + 1, idxs[-1] + 1
                span = f"{first}" if first == last else f"{first}-{last}"
                name = f"{base}_{str(k + 1).zfill(width)}_p{span}"
            target = unique_path(out_dir / f"{name}.pdf")
            part.save(str(target), garbage=3, deflate=True)
            outputs.append(target)
        finally:
            part.close()
    return outputs


def split_by_bookmarks(doc: pymupdf.Document, level: int, out_dir: Path, base: str, progress: ProgressFn = None, cancel: CancelFn = None) -> list[Path]:
    toc = [t for t in doc.get_toc(simple=True) if t[0] <= level]
    if not toc:
        raise ConvertError("这个 PDF 没有书签，无法按书签拆分")
    marks = sorted({max(0, t[2] - 1) for t in toc})
    if marks[0] != 0:
        marks.insert(0, 0)
    ranges = []
    names = []
    titles = {max(0, t[2] - 1): t[1] for t in toc}
    for i, start in enumerate(marks):
        end = marks[i + 1] if i + 1 < len(marks) else doc.page_count
        if end > start:
            ranges.append(list(range(start, end)))
            names.append(f"{str(i + 1).zfill(2)}_{titles.get(start, base)}")
    return split_ranges(doc, ranges, out_dir, base, progress, cancel, names)


def parse_split_ranges(spec: str, n_pages: int) -> list[list[int]]:
    """'1-2, 3-4, 5-' -> [[0,1],[2,3],[4..]]"""
    from .info import parse_page_range
    groups: list[list[int]] = []
    for part in [p for p in spec.replace("；", ";").replace("，", ",").split(",") if p.strip()]:
        idx = parse_page_range(part, n_pages)
        if idx:
            groups.append(idx)
    if not groups:
        raise ValueError("请输入拆分范围，例如 1-2, 3-4, 5-8")
    return groups


def insert_blank_page(doc: pymupdf.Document, at: int, width: float | None = None, height: float | None = None) -> None:
    if width is None or height is None:
        if doc.page_count:
            ref = doc[min(max(0, at - 1), doc.page_count - 1)].rect
            width, height = ref.width, ref.height
        else:
            width, height = 595.28, 841.89
    doc.new_page(pno=at, width=width, height=height)
