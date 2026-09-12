"""Last-resort converter: let MuPDF open the Office file itself (text only, no images)."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from ...fileinfo import KIND_WORD, KIND_PPT, KIND_EXCEL
from ..base import ConvertError, ConvertOptions, Engine, EngineInfo, ProgressFn, CancelFn, report


class MuPdfNativeEngine(Engine):
    id = "builtin-native"
    name = "MuPDF 原生解析"
    kinds = frozenset({KIND_WORD, KIND_PPT, KIND_EXCEL})
    fidelity = "basic"

    def probe(self) -> EngineInfo:
        return EngineInfo(self.id, self.name, True, "仅文字", set(self.kinds), self.fidelity)

    def supports(self, src: Path) -> bool:
        return src.suffix.lower() in (".docx", ".pptx", ".xlsx", ".hwpx")

    def convert(self, src: Path, dst: Path, opts: ConvertOptions, progress: ProgressFn = None, cancel: CancelFn = None) -> list[str]:
        report(progress, 0.2, "MuPDF 解析文档")
        try:
            doc = pymupdf.open(str(src))
            try:
                data = doc.convert_to_pdf()
            finally:
                doc.close()
            pdf = pymupdf.open("pdf", data)
            try:
                pdf.save(str(dst), garbage=2, deflate=True)
            finally:
                pdf.close()
        except Exception as e:
            raise ConvertError(f"MuPDF 无法解析该文档：{e}") from e
        return ["已用 MuPDF 原生解析（仅保留文字，图片与表格边框丢失）"]
