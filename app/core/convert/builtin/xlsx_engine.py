"""Built-in Excel (.xlsx / .csv) engine: openpyxl -> HTML tables -> Story.

Each worksheet starts on a new page; sheets wider than the page are split into column groups.
Keeps: values (formatted roughly by number format), bold/italic, colours, fills, alignment, merged cells,
column widths, borders. Skips: charts, images, conditional formatting.
"""
from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

from ...fileinfo import KIND_EXCEL
from ..base import ConvertError, ConvertOptions, Engine, EngineInfo, ProgressFn, CancelFn, report, check_cancel
from .story_utils import esc, html_sections_to_pdf, A4_PORTRAIT, A4_LANDSCAPE, css_color
from .text import read_text

_MARGIN = 36.0
_CHAR_PT = 5.6   # approx width of one Excel "character unit" in points


class XlsxEngine(Engine):
    id = "builtin-xlsx"
    name = "内置 Excel 引擎"
    kinds = frozenset({KIND_EXCEL})
    fidelity = "basic"

    def probe(self) -> EngineInfo:
        return EngineInfo(self.id, self.name, True, "xlsx / csv 表格排版", set(self.kinds), self.fidelity)

    def supports(self, src: Path) -> bool:
        return src.suffix.lower() in (".xlsx", ".xlsm", ".csv")

    def convert(self, src: Path, dst: Path, opts: ConvertOptions, progress: ProgressFn = None, cancel: CancelFn = None) -> list[str]:
        warnings: list[str] = []
        if src.suffix.lower() == ".csv":
            sheets = [_csv_sheet(src)]
        else:
            sheets, warnings = _xlsx_sheets(src, cancel)
        if not sheets:
            raise ConvertError("工作簿里没有可打印的内容")
        sections = []
        for name, grid, widths, merges in sheets:
            check_cancel(cancel)
            sections.extend(_sheet_sections(name, grid, widths, merges))
        report(progress, 0.5, "排版表格")
        css = "table{border-collapse:collapse} td{border:0.5pt solid #999;padding:2pt 4pt;font-size:9pt;vertical-align:top} h3{font-size:12pt;margin:0 0 6pt 0}"
        html_sections_to_pdf([(h, size, css) for h, size in sections], dst, margins=(_MARGIN,) * 4, progress=progress, cancel=cancel)
        return warnings


def _fmt_value(v, number_format: str) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (_dt.datetime, _dt.date)):
        if isinstance(v, _dt.datetime) and (v.hour or v.minute or v.second):
            return v.strftime("%Y-%m-%d %H:%M")
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float):
        nf = number_format or ""
        if "%" in nf:
            dec = nf.count("0", nf.find(".") + 1) if "." in nf else 0
            return f"{v * 100:.{dec}f}%"
        if "." in nf:
            dec = len(nf.split(".")[1].split(";")[0].rstrip("%_)]"))
            dec = min(max(dec, 0), 8)
            return f"{v:,.{dec}f}" if "," in nf else f"{v:.{dec}f}"
        if v.is_integer():
            return f"{int(v)}"
        return f"{v:g}"
    return str(v)


def _xlsx_sheets(src: Path, cancel: CancelFn):
    try:
        import openpyxl  # noqa: WPS433
        from openpyxl.utils import get_column_letter  # noqa: WPS433
    except Exception as e:  # pragma: no cover
        raise ConvertError(f"缺少 openpyxl：{e}") from e
    try:
        wb = openpyxl.load_workbook(str(src), data_only=True, read_only=False)
    except Exception as e:
        raise ConvertError(f"无法打开工作簿：{e}") from e
    warnings: list[str] = []
    sheets = []
    for ws in wb.worksheets:
        check_cancel(cancel)
        if getattr(ws, "sheet_state", "visible") != "visible":
            continue
        max_r, max_c = _used_range(ws)
        if max_r == 0 or max_c == 0:
            continue
        if getattr(ws, "_charts", None) or getattr(ws, "_images", None):
            warnings.append(f"工作表「{ws.title}」中的图表/图片未包含")
        widths = []
        for c in range(1, max_c + 1):
            letter = get_column_letter(c)
            dim = ws.column_dimensions.get(letter) if hasattr(ws.column_dimensions, "get") else None
            w = None
            try:
                w = dim.width if dim is not None and dim.width else None
            except Exception:
                w = None
            widths.append((w or 8.43) * _CHAR_PT + 6)
        merges = {}
        skip = set()
        try:
            for rng in ws.merged_cells.ranges:
                r0, c0, r1, c1 = rng.min_row, rng.min_col, rng.max_row, rng.max_col
                merges[(r0, c0)] = (r1 - r0 + 1, c1 - c0 + 1)
                for r in range(r0, r1 + 1):
                    for c in range(c0, c1 + 1):
                        if (r, c) != (r0, c0):
                            skip.add((r, c))
        except Exception:
            pass
        grid = []
        for r in range(1, max_r + 1):
            row = []
            for c in range(1, max_c + 1):
                if (r, c) in skip:
                    row.append(None)
                    continue
                cell = ws.cell(row=r, column=c)
                row.append(_cell_info(cell, merges.get((r, c))))
            grid.append(row)
        sheets.append((ws.title, grid, widths, merges))
    return sheets, warnings


def _used_range(ws) -> tuple[int, int]:
    max_r = min(ws.max_row or 0, 5000)
    max_c = min(ws.max_column or 0, 200)
    # trim trailing empty rows/cols
    while max_r > 0 and all(ws.cell(row=max_r, column=c).value in (None, "") for c in range(1, max_c + 1)):
        max_r -= 1
    while max_c > 0 and all(ws.cell(row=r, column=max_c).value in (None, "") for r in range(1, max_r + 1)):
        max_c -= 1
    return max_r, max_c


def _cell_info(cell, span):
    text = _fmt_value(cell.value, cell.number_format or "")
    st = []
    try:
        f = cell.font
        if f.bold:
            st.append("font-weight:bold")
        if f.italic:
            st.append("font-style:italic")
        if f.color is not None and f.color.type == "rgb" and f.color.rgb and isinstance(f.color.rgb, str) and len(f.color.rgb) == 8:
            c = "#" + f.color.rgb[2:]
            if c.lower() != "#000000":
                st.append(f"color:{c}")
        if f.size and float(f.size) != 11:
            st.append(f"font-size:{float(f.size) * 0.82:.1f}pt")
    except Exception:
        pass
    try:
        fill = cell.fill
        if fill is not None and fill.fill_type == "solid" and fill.fgColor is not None and fill.fgColor.type == "rgb":
            rgb = fill.fgColor.rgb
            if isinstance(rgb, str) and len(rgb) == 8 and rgb[2:].lower() not in ("ffffff", "000000"):
                st.append(f"background:#{rgb[2:]}")
    except Exception:
        pass
    try:
        al = cell.alignment
        if al is not None and al.horizontal in ("center", "right"):
            st.append(f"text-align:{al.horizontal}")
        elif isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
            st.append("text-align:right")
    except Exception:
        pass
    return text, ";".join(st), span


def _csv_sheet(src: Path):
    text = read_text(src)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except Exception:
        dialect = csv.excel
    rows = list(csv.reader(text.splitlines(), dialect))
    max_c = max((len(r) for r in rows), default=0)
    grid = [[(v, "", None) for v in r] + [("", "", None)] * (max_c - len(r)) for r in rows]
    widths = []
    for c in range(max_c):
        longest = max((len(r[c][0]) for r in grid if c < len(r)), default=8)
        widths.append(min(220.0, max(40.0, longest * 5.0 + 10)))
    return src.stem, grid, widths, {}


def _sheet_sections(name: str, grid, widths, merges):
    """Split columns into groups that fit a page; choose landscape for wide sheets."""
    total = sum(widths)
    portrait_w = A4_PORTRAIT[0] - 2 * _MARGIN
    landscape_w = A4_LANDSCAPE[0] - 2 * _MARGIN
    size = A4_PORTRAIT if total <= portrait_w else A4_LANDSCAPE
    avail = portrait_w if size == A4_PORTRAIT else landscape_w
    groups: list[tuple[int, int]] = []
    start = 0
    acc = 0.0
    for i, w in enumerate(widths):
        w = min(w, avail)
        if acc + w > avail and i > start:
            groups.append((start, i))
            start, acc = i, 0.0
        acc += w
    groups.append((start, len(widths)))
    sections = []
    for gi, (c0, c1) in enumerate(groups):
        title = esc(name) if len(groups) == 1 else f"{esc(name)}（第 {gi + 1}/{len(groups)} 列组）"
        rows_html = []
        for r, row in enumerate(grid):
            cells = []
            for c in range(c0, c1):
                info = row[c] if c < len(row) else ("", "", None)
                if info is None:
                    continue
                text, style, span = info
                attrs = ""
                if span:
                    rs, cs = span
                    cs = min(cs, c1 - c)
                    if rs > 1:
                        attrs += f' rowspan="{rs}"'
                    if cs > 1:
                        attrs += f' colspan="{cs}"'
                wstyle = f"width:{min(widths[c], avail):.1f}pt"
                st = f' style="{wstyle};{style}"' if style else f' style="{wstyle}"'
                cells.append(f"<td{attrs}{st}>{esc(text).replace(chr(10), '<br>') or '&nbsp;'}</td>")
            rows_html.append("<tr>" + "".join(cells) + "</tr>")
        html = f"<h3>{title}</h3><table>{''.join(rows_html)}</table>"
        sections.append((html, size))
    return sections
