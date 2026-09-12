"""Conversion cache keyed by source identity (path, size, mtime) and options."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..paths import cache_dir
from .base import ConvertOptions


@dataclass
class CacheEntry:
    pdf_path: Path
    engine_id: str
    engine_name: str
    pages: int
    warnings: list[str]


def cache_key(src: Path, opts: ConvertOptions) -> str:
    try:
        st = src.stat()
        ident = f"{src.resolve()}|{st.st_size}|{int(st.st_mtime)}|{opts.cache_key_part()}"
    except OSError:
        ident = f"{src}|missing|{opts.cache_key_part()}"
    return hashlib.sha1(ident.encode("utf-8", "replace")).hexdigest()[:20]


class ConversionCache:
    def __init__(self) -> None:
        self.dir = cache_dir()

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self.dir / f"{key}.pdf", self.dir / f"{key}.json"

    def get(self, src: Path, opts: ConvertOptions) -> CacheEntry | None:
        pdf, meta = self._paths(cache_key(src, opts))
        if pdf.exists() and meta.exists():
            try:
                m = json.loads(meta.read_text("utf-8"))
                return CacheEntry(pdf, m.get("engine_id", ""), m.get("engine_name", ""), int(m.get("pages", 0)), list(m.get("warnings", [])))
            except Exception:
                return None
        return None

    def target_path(self, src: Path, opts: ConvertOptions) -> Path:
        return self._paths(cache_key(src, opts))[0]

    def put(self, src: Path, opts: ConvertOptions, engine_id: str, engine_name: str, pages: int, warnings: list[str]) -> None:
        _pdf, meta = self._paths(cache_key(src, opts))
        try:
            meta.write_text(json.dumps({"engine_id": engine_id, "engine_name": engine_name, "pages": pages, "warnings": warnings}, ensure_ascii=False), "utf-8")
        except OSError:
            pass

    def invalidate(self, src: Path, opts: ConvertOptions) -> None:
        for p in self._paths(cache_key(src, opts)):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    def clear(self) -> int:
        n = 0
        for p in self.dir.glob("*"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        return n

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.dir.glob("*") if p.is_file())
