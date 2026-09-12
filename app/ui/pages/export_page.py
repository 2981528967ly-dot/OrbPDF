"""转换 — PDF out to images / text / Word, and extracting embedded images."""
from __future__ import annotations

from pathlib import Path

from .convert_page import FromPdfPage


class ExportPage(FromPdfPage):
    key = "export"
    title_text = "转换"
    hint_text = "把 PDF 变成图片、文本或 Word"

    def add_files(self, paths: list[Path]) -> None:
        super().add_files([Path(p) for p in paths])
