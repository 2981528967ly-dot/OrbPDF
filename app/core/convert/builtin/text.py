"""txt / markdown / html -> PDF through the Story layout engine."""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from ...fileinfo import KIND_TEXT
from ..base import ConvertError, ConvertOptions, Engine, EngineInfo, ProgressFn, CancelFn, report
from .story_utils import esc, html_to_pdf

_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "utf-16", "big5", "latin-1")


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


class TextEngine(Engine):
    id = "builtin-text"
    name = "内置文本引擎"
    kinds = frozenset({KIND_TEXT})
    fidelity = "high"

    def probe(self) -> EngineInfo:
        return EngineInfo(self.id, self.name, True, "txt / md / html", set(self.kinds), self.fidelity)

    def convert(self, src: Path, dst: Path, opts: ConvertOptions, progress: ProgressFn = None, cancel: CancelFn = None) -> list[str]:
        ext = src.suffix.lower()
        warnings: list[str] = []
        archive = None
        try:
            text = read_text(src)
        except Exception as e:
            raise ConvertError(f"无法读取文本：{e}") from e
        report(progress, 0.2, "解析文本")
        if ext in (".md", ".markdown"):
            body, css = _markdown_html(text)
            archive = _dir_archive(src)
        elif ext in (".html", ".htm"):
            body, css = _clean_html(text)
            archive = _dir_archive(src)
            warnings.append("网页中的外链资源未包含")
        else:
            body, css = _plain_html(text)
        html_to_pdf(body, dst, css=css, archive=archive, progress=progress, cancel=cancel)
        return warnings


def _dir_archive(src: Path):
    try:
        return pymupdf.Archive(str(src.parent))
    except Exception:
        return None


def _plain_html(text: str) -> tuple[str, str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    for line in lines:
        s = esc(line.replace("\t", "    "))
        s = re.sub(r"  +", lambda m: "&nbsp;" * len(m.group(0)), s)
        out.append(f"<p>{s or '&nbsp;'}</p>")
    css = "body{font-family:monospace;font-size:10pt;line-height:1.45} p{margin:0}"
    return "\n".join(out), css


def _markdown_html(text: str) -> tuple[str, str]:
    try:
        import markdown  # noqa: WPS433
        body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "toc"], output_format="html")
    except Exception:
        body, _ = _plain_html(text)
    css = ("body{font-family:sans-serif;font-size:11pt} code{background:#f1f3f6;padding:0 2pt} "
           "pre{background:#f4f6f8;padding:6pt;border:1px solid #dde;} table td,table th{border:1px solid #999;padding:3pt 6pt} "
           "th{background:#eef2f6;font-weight:bold} img{max-width:100%}")
    return body, css


_STRIP = [
    (re.compile(r"<script\b.*?</script>", re.S | re.I), ""),
    (re.compile(r"<link\b[^>]*>", re.I), ""),
    (re.compile(r"<iframe\b.*?</iframe>", re.S | re.I), ""),
    (re.compile(r"<!--.*?-->", re.S), ""),
]


def _clean_html(text: str) -> tuple[str, str]:
    body = text
    for rx, rep in _STRIP:
        body = rx.sub(rep, body)
    m = re.search(r"<body[^>]*>(.*)</body>", body, re.S | re.I)
    if m:
        body = m.group(1)
    styles = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I))
    css = "body{font-family:sans-serif;font-size:11pt} img{max-width:100%} " + styles
    return body, css
