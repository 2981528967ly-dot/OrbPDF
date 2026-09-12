"""File kinds, natural sorting, size formatting, folder expansion."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

KIND_PDF = "pdf"
KIND_WORD = "word"
KIND_PPT = "ppt"
KIND_EXCEL = "excel"
KIND_IMAGE = "image"
KIND_TEXT = "text"
# virtual kinds used by the merge chain
KIND_BLANK = "blank"
KIND_DIVIDER = "divider"

EXT_KINDS: dict[str, str] = {
    ".pdf": KIND_PDF,
    ".docx": KIND_WORD, ".doc": KIND_WORD, ".rtf": KIND_WORD, ".odt": KIND_WORD, ".wps": KIND_WORD, ".dotx": KIND_WORD,
    ".pptx": KIND_PPT, ".ppt": KIND_PPT, ".odp": KIND_PPT, ".dps": KIND_PPT, ".potx": KIND_PPT,
    ".xlsx": KIND_EXCEL, ".xls": KIND_EXCEL, ".xlsm": KIND_EXCEL, ".ods": KIND_EXCEL, ".csv": KIND_EXCEL, ".et": KIND_EXCEL,
    ".jpg": KIND_IMAGE, ".jpeg": KIND_IMAGE, ".png": KIND_IMAGE, ".bmp": KIND_IMAGE, ".gif": KIND_IMAGE,
    ".tif": KIND_IMAGE, ".tiff": KIND_IMAGE, ".webp": KIND_IMAGE, ".jfif": KIND_IMAGE,
    ".txt": KIND_TEXT, ".md": KIND_TEXT, ".markdown": KIND_TEXT, ".html": KIND_TEXT, ".htm": KIND_TEXT, ".log": KIND_TEXT,
}

# Legacy binary Office formats need a real Office/WPS; the built-in engines only read OOXML.
LEGACY_OFFICE_EXTS = {".doc", ".rtf", ".odt", ".wps", ".ppt", ".odp", ".dps", ".xls", ".ods", ".et"}

KIND_LABELS = {
    KIND_PDF: "PDF", KIND_WORD: "Word", KIND_PPT: "PPT", KIND_EXCEL: "Excel",
    KIND_IMAGE: "图片", KIND_TEXT: "文本", KIND_BLANK: "空白页", KIND_DIVIDER: "分隔页",
}

# orb colour per kind (asset key)
KIND_ORBS = {
    KIND_PDF: "blue", KIND_WORD: "gold", KIND_PPT: "gold", KIND_EXCEL: "gold",
    KIND_IMAGE: "green", KIND_TEXT: "purple", KIND_BLANK: "white", KIND_DIVIDER: "white",
}

SUPPORTED_EXTS = set(EXT_KINDS)


def kind_of(path: str | Path) -> str | None:
    return EXT_KINDS.get(Path(path).suffix.lower())


def is_supported(path: str | Path) -> bool:
    return kind_of(path) is not None


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind)


_NUM_RE = re.compile(r"(\d+)")


def natural_key(s: str | Path):
    name = str(s)
    return [int(t) if t.isdigit() else t.casefold() for t in _NUM_RE.split(name)]


def natural_sorted(paths: Iterable[Path]) -> list[Path]:
    return sorted(paths, key=lambda p: natural_key(p.name))


def human_size(n: int | float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def collect_files(paths: Iterable[str | Path], recursive: bool = True, kinds: set[str] | None = None) -> list[Path]:
    """Expand folders, keep supported files, natural-sort within each folder, preserve given order."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        key = str(p).lower()
        if key in seen:
            return
        k = kind_of(p)
        if k is None or (kinds and k not in kinds):
            return
        seen.add(key)
        out.append(p)

    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            try:
                entries = natural_sorted([e for e in p.iterdir()])
            except OSError:
                continue
            for e in entries:
                if e.is_dir():
                    if recursive:
                        for sub in collect_files([e], recursive=True, kinds=kinds):
                            add(sub)
                elif e.is_file():
                    add(e)
        elif p.is_file():
            add(p)
    return out


def file_size(path: str | Path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0
