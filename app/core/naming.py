"""Output naming helpers."""
from __future__ import annotations

import re
from pathlib import Path

_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def sanitize_filename(name: str, default: str = "文档") -> str:
    name = _BAD.sub(" ", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return name[:120] or default


def unique_path(path: Path) -> Path:
    """If path exists (or is locked), return path with _1, _2 ... appended."""
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 10000):
        cand = path.with_name(f"{stem}_{i}{suffix}")
        if not cand.exists():
            return cand
    return path


def is_writable_target(path: Path) -> bool:
    """True if we can create/overwrite this file (folder exists & writable, file not locked)."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            with open(path, "ab"):
                pass
        else:
            probe = path.parent / f".orbpdf-probe-{id(path)}"
            with open(probe, "wb"):
                pass
            probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def with_suffix_name(path: Path, suffix_text: str, ext: str = ".pdf") -> Path:
    path = Path(path)
    return path.with_name(f"{path.stem}{suffix_text}{ext}")


def default_merge_name(title: str | None, first_item_name: str | None) -> str:
    base = title.strip() if title and title.strip() else (first_item_name or "合并文档")
    return sanitize_filename(base)
