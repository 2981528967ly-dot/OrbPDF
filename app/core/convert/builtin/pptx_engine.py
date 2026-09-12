"""Built-in PowerPoint (.pptx) engine: python-pptx -> one PDF page per slide, drawn with PyMuPDF.

Keeps: slide size, solid backgrounds, pictures, text boxes (size/bold/italic/colour/alignment/bullets,
auto-shrunk to fit), basic auto-shapes (rect / rounded rect / oval with fill & outline), tables, groups.
Skips: animations, SmartArt, charts (placeholder box), media, gradients.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

from ...fileinfo import KIND_PPT
from ..base import ConvertError, ConvertOptions, Engine, EngineInfo, ProgressFn, CancelFn, report, check_cancel
from .story_utils import esc, pt, css_color

# python-pptx enum ints (avoid importing enums at module import time)
_SHAPE_PICTURE = 13
_SHAPE_GROUP = 6
_SHAPE_TABLE = 19
_SHAPE_CHART = 3
_SHAPE_MEDIA = 16
_SHAPE_PLACEHOLDER = 14
_FILL_SOLID = 1

_PH_TITLE = {1, 3, 15}       # TITLE, CENTER_TITLE, VERTICAL_TITLE
_PH_SUBTITLE = {4}
_PH_BODY = {2, 7, 16}        # BODY, OBJECT, VERTICAL_BODY


class PptxEngine(Engine):
    id = "builtin-pptx"
    name = "内置 PPT 引擎"
    kinds = frozenset({KIND_PPT})
    fidelity = "basic"

    def probe(self) -> EngineInfo:
        return EngineInfo(self.id, self.name, True, "pptx 逐页绘制", set(self.kinds), self.fidelity)

    def supports(self, src: Path) -> bool:
        return src.suffix.lower() in (".pptx", ".potx")

    def convert(self, src: Path, dst: Path, opts: ConvertOptions, progress: ProgressFn = None, cancel: CancelFn = None) -> list[str]:
        try:
            from pptx import Presentation  # noqa: WPS433
        except Exception as e:  # pragma: no cover
            raise ConvertError(f"缺少 python-pptx：{e}") from e
        try:
            prs = Presentation(str(src))
        except Exception as e:
            raise ConvertError(f"无法解析 pptx：{e}") from e
        W, H = pt(prs.slide_width, 960), pt(prs.slide_height, 540)
        doc = pymupdf.open()
        r = _Renderer(doc, W, H)
        slides = list(prs.slides)
        n = max(1, len(slides))
        try:
            for i, slide in enumerate(slides):
                check_cancel(cancel)
                report(progress, i / n, f"绘制幻灯片 {i + 1}/{n}")
                r.render_slide(slide, i + 1)
            if not slides:
                doc.new_page(width=W, height=H)
            doc.save(str(dst), garbage=3, deflate=True)
        finally:
            doc.close()
        return sorted(set(r.warnings))


class _Renderer:
    def __init__(self, doc: pymupdf.Document, W: float, H: float) -> None:
        self.doc = doc
        self.W, self.H = W, H
        self.warnings: list[str] = []
        self.page: pymupdf.Page | None = None
        self.slide_no = 0

    # -- slide ------------------------------------------------------------
    def render_slide(self, slide, number: int) -> None:
        self.slide_no = number
        self.page = self.doc.new_page(width=self.W, height=self.H)
        bg = self._background_color(slide)
        if bg:
            self.page.draw_rect(self.page.rect, color=None, fill=bg, overlay=False)
        try:
            hidden = slide._element.get("show") == "0"
        except Exception:
            hidden = False
        if hidden:
            self.page.insert_text((20, 30), "(隐藏幻灯片)", fontsize=10, color=(0.5, 0.5, 0.5), fontname="china-s")
        for shape in slide.shapes:
            self._shape(shape, _Xform())

    def _background_color(self, slide):
        for owner in (slide, getattr(slide, "slide_layout", None), getattr(getattr(slide, "slide_layout", None), "slide_master", None)):
            if owner is None:
                continue
            try:
                fill = owner.background.fill
                if fill.type == _FILL_SOLID:
                    c = _rgb(fill.fore_color.rgb)
                    if c:
                        return c
                    return None
            except Exception:
                continue
        return None

    # -- shapes ------------------------------------------------------------
    def _shape(self, shape, xf: "_Xform") -> None:
        try:
            if shape._element.get("hidden") == "1":
                return
        except Exception:
            pass
        try:
            st = int(shape.shape_type) if shape.shape_type is not None else 0
        except Exception:
            st = 0
        rect = xf.rect(shape)
        if st == _SHAPE_GROUP:
            self._group(shape, xf)
            return
        if st == _SHAPE_PICTURE or (st == _SHAPE_PLACEHOLDER and hasattr(shape, "image")):
            self._picture(shape, rect)
            return
        if getattr(shape, "has_table", False) and shape.has_table:
            self._table(shape, rect)
            return
        if getattr(shape, "has_chart", False) and shape.has_chart:
            self._placeholder_box(rect, "[图表]")
            self.warnings.append("图表已用占位框代替")
            return
        if st == _SHAPE_MEDIA:
            self._placeholder_box(rect, "[媒体]")
            return
        try:
            if shape._element.tag.endswith("graphicFrame") and "diagram" in shape._element.xml[:4000]:
                self._placeholder_box(rect, "[SmartArt]")
                self.warnings.append("SmartArt 已用占位框代替")
                return
        except Exception:
            pass
        self._autoshape(shape, rect)
        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            self._text(shape, rect)

    def _group(self, group, xf: "_Xform") -> None:
        child_xf = xf.child(group)
        for sub in group.shapes:
            self._shape(sub, child_xf)

    def _picture(self, shape, rect: pymupdf.Rect) -> None:
        try:
            blob = shape.image.blob
        except Exception:
            self._placeholder_box(rect, "[图片]")
            return
        try:
            self.page.insert_image(rect, stream=blob, keep_proportion=False)
        except Exception:
            try:
                self.page.insert_image(rect, stream=blob, keep_proportion=True)
            except Exception:
                self._placeholder_box(rect, "[图片]")
                self.warnings.append("部分图片格式无法嵌入")

    def _autoshape(self, shape, rect: pymupdf.Rect) -> None:
        fill = None
        line = None
        width = 0.0
        try:
            if shape.fill.type == _FILL_SOLID:
                fill = _rgb(shape.fill.fore_color.rgb)
        except Exception:
            fill = None
        try:
            if shape.line.fill.type == _FILL_SOLID:
                line = _rgb(shape.line.color.rgb)
                width = max(0.5, pt(shape.line.width, 12700))
        except Exception:
            line = None
        if fill is None and line is None:
            return
        kind = None
        try:
            kind = int(shape.auto_shape_type) if getattr(shape, "auto_shape_type", None) is not None else None
        except Exception:
            kind = None
        sh = self.page.new_shape()
        if kind == 9:      # OVAL
            sh.draw_oval(rect)
        elif kind == 5:    # ROUNDED_RECTANGLE
            sh.draw_rect(rect)  # PyMuPDF has no rounded rect; plain rect is close enough
        else:
            sh.draw_rect(rect)
        sh.finish(color=line, fill=fill, width=width if line else 0)
        sh.commit()

    def _placeholder_box(self, rect: pymupdf.Rect, label: str) -> None:
        sh = self.page.new_shape()
        sh.draw_rect(rect)
        sh.finish(color=(0.6, 0.6, 0.65), fill=(0.94, 0.95, 0.97), width=0.75, dashes="[3 3] 0")
        sh.commit()
        try:
            self.page.insert_textbox(rect, label, fontsize=12, color=(0.45, 0.45, 0.5), align=1, fontname="china-s")
        except Exception:
            pass

    # -- text --------------------------------------------------------------
    def _placeholder_type(self, shape) -> int | None:
        try:
            if shape.is_placeholder:
                return int(shape.placeholder_format.type)
        except Exception:
            return None
        return None

    def _text(self, shape, rect: pymupdf.Rect) -> None:
        tf = shape.text_frame
        ph = self._placeholder_type(shape)
        if ph in _PH_TITLE:
            base_size, bullets, default_bold = 32.0, False, True
        elif ph in _PH_SUBTITLE:
            base_size, bullets, default_bold = 20.0, False, False
        elif ph in _PH_BODY:
            base_size, bullets, default_bold = 20.0, True, False
        else:
            base_size, bullets, default_bold = 16.0, False, False
        paras = []
        for p in tf.paragraphs:
            level = int(getattr(p, "level", 0) or 0)
            size = base_size * (1.0 if level == 0 else max(0.6, 1.0 - 0.12 * level))
            runs_html = []
            for r in p.runs:
                t = esc(r.text).replace("\n", "<br>")
                if not t:
                    continue
                st = []
                f = r.font
                try:
                    if f.size:
                        st.append(f"font-size:{float(f.size.pt):.1f}pt")
                    b = f.bold if f.bold is not None else default_bold
                    if b:
                        st.append("font-weight:bold")
                    if f.italic:
                        st.append("font-style:italic")
                    if f.underline:
                        st.append("text-decoration:underline")
                    c = None
                    try:
                        c = css_color(f.color.rgb) if f.color and f.color.type is not None else None
                    except Exception:
                        c = None
                    if c:
                        st.append(f"color:{c}")
                except Exception:
                    pass
                runs_html.append(f'<span style="{";".join(st)}">{t}</span>' if st else t)
            if not runs_html and not p.text:
                runs_html = ["&nbsp;"]
            inner = "".join(runs_html)
            if bullets and p.text.strip() and not _bullet_off(p):
                inner = "•&nbsp;" + inner
            align = "left"
            try:
                al = int(p.alignment) if p.alignment is not None else None
                align = {2: "center", 3: "right", 4: "justify"}.get(al, "left")
            except Exception:
                pass
            if ph in _PH_TITLE and align == "left":
                try:
                    if p.alignment is None:
                        align = "left"
                except Exception:
                    pass
            paras.append(f'<p style="font-size:{size:.1f}pt;margin:0 0 {size*0.35:.1f}pt {level*18}pt;text-align:{align};line-height:1.2">{inner}</p>')
        if not any(p.text.strip() for p in tf.paragraphs):
            return
        html = "".join(paras)
        color = None
        # default text colour: dark on light background
        css = "body{font-family:sans-serif;color:#1a1a1a}"
        box = rect + (4, 3, -4, -3)
        if box.is_empty or box.width < 4 or box.height < 4:
            return
        # vertical anchor: middle for titles
        try:
            anchor = tf.vertical_anchor  # MSO_ANCHOR: TOP=1, MIDDLE=3, BOTTOM=4
            anchor = int(anchor) if anchor is not None else None
        except Exception:
            anchor = None
        if anchor is None and ph in _PH_TITLE:
            anchor = 3
        try:
            if anchor in (3, 4):
                # measure first, then offset the box
                spare, _scale = self.page.insert_htmlbox(box, html, css=css, scale_low=0, archive=None, overlay=True)
                # insert_htmlbox already drew; if spare is large, redraw centred by undoing is not possible -> draw first pass into a throwaway page
                if spare and spare > 4:
                    # remove the text we just drew by re-rendering on a scratch page next time; simplest: clear and redraw
                    self._redraw_anchored(box, html, css, spare, anchor)
            else:
                self.page.insert_htmlbox(box, html, css=css, scale_low=0)
        except Exception as e:  # pragma: no cover
            try:
                self.page.insert_textbox(box, tf.text, fontsize=base_size * 0.8, fontname="china-s")
            except Exception:
                pass
            self.warnings.append("部分文本框以简化方式绘制")

    def _redraw_anchored(self, box: pymupdf.Rect, html: str, css: str, spare: float, anchor: int) -> None:
        """We drew top-aligned already; PyMuPDF cannot undo, so we cover it and draw again lower.
        Covering is only safe on plain backgrounds; so instead we measure on a scratch page first."""
        # Undo strategy: the last drawn content is in the page's contents; simplest robust approach is to
        # measure on a scratch document, then delete the last content stream object.
        try:
            self.page.clean_contents()
            xrefs = self.page.get_contents()
            if xrefs:
                # remove the last content stream (the htmlbox we just inserted)
                self.doc.update_stream(xrefs[-1], b"")
        except Exception:
            return
        dy = spare if anchor == 4 else spare / 2.0
        shifted = pymupdf.Rect(box.x0, box.y0 + dy, box.x1, box.y1)
        try:
            self.page.insert_htmlbox(shifted, html, css=css, scale_low=0)
        except Exception:
            pass

    # -- tables ------------------------------------------------------------
    def _table(self, shape, rect: pymupdf.Rect) -> None:
        tbl = shape.table
        cols = [pt(c.width, 0) for c in tbl.columns]
        rows = [pt(r.height, 0) for r in tbl.rows]
        total_w = sum(cols) or rect.width
        total_h = sum(rows) or rect.height
        sx = rect.width / total_w if total_w else 1
        sy = rect.height / total_h if total_h else 1
        y = rect.y0
        for ri, row in enumerate(tbl.rows):
            x = rect.x0
            rh = (rows[ri] or rect.height / max(1, len(rows))) * sy
            for ci, cell in enumerate(row.cells):
                cw = (cols[ci] or rect.width / max(1, len(cols))) * sx
                cell_rect = pymupdf.Rect(x, y, x + cw, y + rh)
                fill = None
                try:
                    if cell.fill.type == _FILL_SOLID:
                        fill = _rgb(cell.fill.fore_color.rgb)
                except Exception:
                    fill = None
                sh = self.page.new_shape()
                sh.draw_rect(cell_rect)
                sh.finish(color=(0.45, 0.45, 0.5), fill=fill, width=0.6)
                sh.commit()
                text = cell.text if not getattr(cell, "is_spanned", False) else ""
                if text.strip():
                    bold = ri == 0
                    html = f'<p style="font-size:11pt;margin:0;{"font-weight:bold" if bold else ""}">{esc(text).replace(chr(10), "<br>")}</p>'
                    try:
                        self.page.insert_htmlbox(cell_rect + (3, 2, -3, -2), html, css="body{font-family:sans-serif;color:#1a1a1a}", scale_low=0)
                    except Exception:
                        pass
                x += cw
            y += rh


class _Xform:
    """Maps shape coordinates (EMU) into page points, handling group child coordinate spaces."""

    def __init__(self, scale_x: float = 1.0, scale_y: float = 1.0, off_x: float = 0.0, off_y: float = 0.0) -> None:
        self.sx, self.sy, self.ox, self.oy = scale_x, scale_y, off_x, off_y

    def rect(self, shape) -> pymupdf.Rect:
        left = float(shape.left or 0)
        top = float(shape.top or 0)
        w = float(shape.width or 0)
        h = float(shape.height or 0)
        x0 = pt(self.ox + left * self.sx)
        y0 = pt(self.oy + top * self.sy)
        return pymupdf.Rect(x0, y0, x0 + pt(w * self.sx), y0 + pt(h * self.sy))

    def child(self, group) -> "_Xform":
        try:
            xfrm = group._element.grpSpPr.xfrm
            ch_off = xfrm.chOff
            ch_ext = xfrm.chExt
            off = xfrm.off
            ext = xfrm.ext
            if ch_ext is None or ext is None or not ch_ext.cx or not ch_ext.cy:
                return self
            sx = (ext.cx / ch_ext.cx) * self.sx
            sy = (ext.cy / ch_ext.cy) * self.sy
            ox = self.ox + off.x * self.sx - ch_off.x * sx
            oy = self.oy + off.y * self.sy - ch_off.y * sy
            return _Xform(sx, sy, ox, oy)
        except Exception:
            return self


def _rgb(rgb) -> tuple[float, float, float] | None:
    c = css_color(rgb)
    if not c:
        return None
    return (int(c[1:3], 16) / 255.0, int(c[3:5], 16) / 255.0, int(c[5:7], 16) / 255.0)


def _bullet_off(p) -> bool:
    try:
        pPr = p._p.pPr
        if pPr is not None and pPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}buNone") is not None:
            return True
    except Exception:
        pass
    return False
