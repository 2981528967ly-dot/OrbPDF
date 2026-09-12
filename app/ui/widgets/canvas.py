"""The 生成 canvas: a ComfyUI-flavoured node graph.

Nodes float freely on an infinite dotted canvas. Wires run from each node's output socket to the next
node's input socket: [目录] → file → file → … → [导出]. The document order is *always* the chain
order, so a broken chain is impossible: rewiring or dropping a node onto a wire just reorders the list.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QLineF, QParallelAnimationGroup, QPointF, QPropertyAnimation, QRectF, QSequentialAnimationGroup,
                            QTimer, Qt, Signal, QObject, Property)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap,
                           QPolygonF, QImage, QTransform, QCursor)
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsObject, QGraphicsPixmapItem, QGraphicsProxyWidget, QGraphicsScene,
                               QGraphicsView, QLineEdit, QMenu, QStyleOptionGraphicsItem, QWidget, QApplication, QGraphicsRectItem)

from ...core.fileinfo import KIND_BLANK, KIND_DIVIDER, KIND_IMAGE, KIND_PDF, collect_files
from .. import assets, icons, theme
from ..strings import t
from .drop import mime_has_files, paths_from_mime
from .orb import draw_orb

NODE_W = 212.0
HEADER_H = 34.0
FILE_BODY_H = 178.0
SOCKET_R = 6.0
SOCKET_Y = HEADER_H + 14
GRID = 24.0

ORB_COLORS = {"blue": "#7FE3FF", "gold": "#FFD166", "green": "#6EF2A6", "purple": "#A78BFA", "white": "#E8EEF7"}


def _elide(text: str, font: QFont, width: float) -> str:
    return QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideMiddle, int(width))


def _rounded(rect: QRectF, r: float = 10.0) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(rect, r, r)
    return p


class Node(QGraphicsObject):
    """Base node: header (orb, title, order badge), body painted by subclasses, sockets on the edges."""

    def __init__(self, canvas: "Canvas", kind: str, item=None) -> None:
        super().__init__()
        self.canvas = canvas
        self.kind = kind          # start | file | end
        self.item = item
        self.hover = False
        self.order = 0
        self.body_h = FILE_BODY_H
        self.has_input = kind != "start"
        self.has_output = kind != "end"
        self._press_scene: QPointF | None = None
        self._moved = False
        self._hot: str | None = None      # hovered painted button
        self.setAcceptHoverEvents(True)
        flags = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        flags |= QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        self.setFlags(flags)
        self.setZValue(2)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    # -- geometry ------------------------------------------------------------
    @property
    def item_id(self) -> str | None:
        return self.item.id if self.item is not None else None

    def height(self) -> float:
        return HEADER_H + self.body_h

    def boundingRect(self) -> QRectF:
        return QRectF(-SOCKET_R - 8, -8, NODE_W + 2 * SOCKET_R + 16, self.height() + 18)

    def shape(self) -> QPainterPath:
        p = _rounded(QRectF(0, 0, NODE_W, self.height()))
        if self.has_input:
            p.addEllipse(self.input_pos(), SOCKET_R + 4, SOCKET_R + 4)
        if self.has_output:
            p.addEllipse(self.output_pos(), SOCKET_R + 4, SOCKET_R + 4)
        return p

    def input_pos(self) -> QPointF:
        return QPointF(0, SOCKET_Y)

    def output_pos(self) -> QPointF:
        return QPointF(NODE_W, SOCKET_Y)

    def scene_input(self) -> QPointF:
        return self.mapToScene(self.input_pos())

    def scene_output(self) -> QPointF:
        return self.mapToScene(self.output_pos())

    # -- painting ------------------------------------------------------------
    def header_color(self) -> str:
        return ORB_COLORS["white"]

    def title(self) -> str:
        return ""

    def paint(self, p: QPainter, _opt: QStyleOptionGraphicsItem, _w: QWidget | None = None) -> None:
        th = theme.current()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, 0, NODE_W, self.height())
        # soft shadow
        for i, a in ((6, 0.10), (3, 0.14)):
            sh = QColor(0, 0, 0, int(255 * a))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sh)
            p.drawRoundedRect(rect.adjusted(-i * 0.3, i * 0.7, i * 0.3, i), 12, 12)
        selected = self.isSelected()
        border = th.c("accent") if selected else (th.c("accent_hover") if self.hover else th.c("border2"))
        p.setPen(QPen(QColor(border), 1.6 if selected else 1.0))
        p.setBrush(QColor(th.c("surface2")))
        p.drawRoundedRect(rect, 10, 10)
        # header
        hc = QColor(self.header_color())
        hc.setAlphaF(0.22 if th.is_dark else 0.35)
        hp = QPainterPath()
        hp.addRoundedRect(QRectF(0, 0, NODE_W, HEADER_H + 10), 10, 10)
        hp.addRect(QRectF(0, HEADER_H - 2, NODE_W, 12))
        p.setPen(Qt.PenStyle.NoPen)
        p.save()
        p.setClipRect(QRectF(0, 0, NODE_W, HEADER_H))
        p.setBrush(hc)
        p.drawRoundedRect(rect, 10, 10)
        p.restore()
        p.setPen(QPen(QColor(th.c("border")), 1))
        p.drawLine(QPointF(0, HEADER_H), QPointF(NODE_W, HEADER_H))
        self.paint_header(p, th)
        self.paint_body(p, th, QRectF(0, HEADER_H, NODE_W, self.body_h))
        # sockets
        for pos, on in ((self.input_pos(), self.has_input), (self.output_pos(), self.has_output)):
            if not on:
                continue
            p.setPen(QPen(QColor(th.c("bg")), 2))
            p.setBrush(QColor(th.c("accent")))
            p.drawEllipse(pos, SOCKET_R, SOCKET_R)
        if selected:
            glow = QColor(th.c("accent"))
            glow.setAlphaF(0.16)
            p.setPen(QPen(glow, 6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 13, 13)

    def paint_header(self, p: QPainter, th) -> None:
        f = QFont(self.canvas.font())
        f.setBold(True)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor(th.c("text")))
        p.drawText(QRectF(14, 0, NODE_W - 48, HEADER_H), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, _elide(self.title(), f, NODE_W - 52))

    def paint_body(self, p: QPainter, th, body: QRectF) -> None:
        pass

    # -- interaction -----------------------------------------------------------
    def hoverEnterEvent(self, e) -> None:
        self.hover = True
        self.update()
        super().hoverEnterEvent(e)

    def hoverLeaveEvent(self, e) -> None:
        self.hover = False
        self._hot = None
        self.update()
        super().hoverLeaveEvent(e)

    def hit_button(self, pos: QPointF) -> str | None:
        return None

    def hoverMoveEvent(self, e) -> None:
        hot = self.hit_button(e.pos())
        if hot != self._hot:
            self._hot = hot
            self.setCursor(Qt.CursorShape.PointingHandCursor if hot else Qt.CursorShape.OpenHandCursor)
            self.update()
        super().hoverMoveEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            if self.has_output and (e.pos() - self.output_pos()).manhattanLength() <= SOCKET_R + 6:
                self.canvas.begin_wire_drag(self)
                e.accept()
                return
            btn = self.hit_button(e.pos())
            if btn:
                self.canvas.node_button(self, btn)
                e.accept()
                return
            self._press_scene = e.scenePos()
            self._moved = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.setZValue(10)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._press_scene is not None and (e.scenePos() - self._press_scene).manhattanLength() > 4:
            self._moved = True
            self.canvas.node_dragging(self, e.scenePos())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        super().mouseReleaseEvent(e)
        self.setZValue(2)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._press_scene is not None:
            if self._moved:
                self.canvas.node_dropped(self, e.scenePos())
            else:
                self.canvas.node_clicked(self)
        self._press_scene = None
        self._moved = False

    def mouseDoubleClickEvent(self, e) -> None:
        self.canvas.node_double_clicked(self)
        e.accept()

    def contextMenuEvent(self, e) -> None:
        self.canvas.node_menu(self, e.screenPos())
        e.accept()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.canvas.schedule_wires()
            if self.item is not None and self.canvas.model is not None:
                self.canvas.model.set_pos(self.item.id, self.pos().x(), self.pos().y())
        return super().itemChange(change, value)


class FileNode(Node):
    def __init__(self, canvas: "Canvas", item) -> None:
        super().__init__(canvas, "file", item)
        self._thumb: QPixmap | None = None
        self._thumb_src: bytes | None = None
        self.body_h = FILE_BODY_H

    def header_color(self) -> str:
        return ORB_COLORS.get(self.item.orb, "#7FE3FF")

    def title(self) -> str:
        return self.item.display_name

    def paint_header(self, p: QPainter, th) -> None:
        it = self.item
        status = "ready" if it.status == "ready" else ("busy" if it.status == "converting" else ("error" if it.status == "error" else "pending"))
        draw_orb(p, 10, (HEADER_H - 18) / 2, 18, it.orb, status, self.canvas.spin_angle, self.canvas.dpr())
        f = QFont(self.canvas.font())
        f.setBold(True)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor(th.c("text")))
        p.drawText(QRectF(34, 0, NODE_W - 34 - 30, HEADER_H), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, _elide(it.display_name, f, NODE_W - 70))
        badge = QRectF(NODE_W - 26, (HEADER_H - 18) / 2, 18, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(th.c("bg")))
        p.drawEllipse(badge)
        p.setPen(QColor(th.c("text2")))
        bf = QFont(self.canvas.font())
        bf.setPixelSize(10)
        bf.setBold(True)
        p.setFont(bf)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(self.order))

    def _thumb_rect(self) -> QRectF:
        return QRectF(14, HEADER_H + 10, NODE_W - 28, 112)

    def _buttons(self) -> dict[str, QRectF]:
        y = HEADER_H + self.body_h - 30
        return {"rotl": QRectF(14, y, 24, 24), "rotr": QRectF(42, y, 24, 24), "range": QRectF(70, y, 60, 24),
                "menu": QRectF(NODE_W - 66, y, 24, 24), "remove": QRectF(NODE_W - 38, y, 24, 24)}

    def hit_button(self, pos: QPointF) -> str | None:
        for key, r in self._buttons().items():
            if key == "range" and self.item.kind != KIND_PDF:
                continue
            if key in ("rotl", "rotr") and self.item.is_special:
                continue
            if r.contains(pos):
                return key
        return None

    def paint_body(self, p: QPainter, th, body: QRectF) -> None:
        it = self.item
        tr = self._thumb_rect()
        # thumbnail
        if it.thumb_png and it.thumb_png is not self._thumb_src:
            img = QImage.fromData(it.thumb_png)
            self._thumb = QPixmap.fromImage(img) if not img.isNull() else None
            self._thumb_src = it.thumb_png
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(th.c("bg")))
        p.drawRoundedRect(tr, 6, 6)
        if self._thumb is not None and it.thumb_png is not None:
            pm = self._thumb
            rot = it.rotation % 360
            w, h = pm.width(), pm.height()
            if rot % 180:
                w, h = h, w
            scale = min((tr.width() - 12) / w, (tr.height() - 12) / h)
            dw, dh = w * scale, h * scale
            p.save()
            p.translate(tr.center())
            p.rotate(rot)
            if rot % 180:
                dw, dh = dh, dw
            target = QRectF(-dw / 2, -dh / 2, dw, dh)
            p.drawPixmap(target, pm, QRectF(pm.rect()))
            p.setPen(QPen(QColor(th.c("border2")), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(target)
            p.restore()
        else:
            p.setPen(QColor(th.c("muted")))
            f = QFont(self.canvas.font())
            f.setPixelSize(11)
            p.setFont(f)
            txt = "空白页" if it.kind == KIND_BLANK else ("分隔页" if it.kind == KIND_DIVIDER else (t("status_converting") + "…" if it.status == "converting" else ("出错" if it.status == "error" else "…")))
            p.drawText(tr, Qt.AlignmentFlag.AlignCenter, txt)
        # status line
        small = QFont(self.canvas.font())
        small.setPixelSize(11)
        p.setFont(small)
        y = tr.bottom() + 6
        if it.status == "ready":
            col, txt = th.c("ok"), f"{it.kind_text} · {it.pages} 页" + (f" · 第 {it.page_range} 页" if it.page_range else "")
        elif it.status == "converting":
            col, txt = th.c("warn"), t("status_converting") + "…"
        elif it.status == "error":
            col, txt = th.c("danger"), ("需要密码，点右侧 …" if it.needs_password else "出错 · " + it.error)
        else:
            col, txt = th.c("muted"), "等待中"
        if it.rotation:
            txt += f" · 旋转 {it.rotation}°"
        if not it.in_toc and not it.is_special:
            txt += " · 不列入目录"
        p.setPen(QColor(col))
        p.drawText(QRectF(14, y, NODE_W - 28, 16), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, _elide(txt, small, NODE_W - 28))
        # painted buttons (visible on hover)
        if self.hover or self.isSelected():
            for key, r in self._buttons().items():
                if key == "range" and it.kind != KIND_PDF:
                    continue
                if key in ("rotl", "rotr") and it.is_special:
                    continue
                hot = self._hot == key
                p.setPen(QPen(QColor(th.c("accent_line") if hot else th.c("border2")), 1))
                p.setBrush(QColor(th.c("accent_dim")) if hot else QColor(th.c("surface3")))
                p.drawRoundedRect(r, 6, 6)
                color = th.c("accent") if hot else th.c("text2")
                if key == "range":
                    p.setPen(QColor(color))
                    p.drawText(r, Qt.AlignmentFlag.AlignCenter, "页面范围")
                else:
                    name = {"rotl": "rotate-left", "rotr": "rotate-right", "menu": "more", "remove": "close"}[key]
                    pm = icons.pixmap(name, color, 14, self.canvas.dpr())
                    p.drawPixmap(int(r.x() + 5), int(r.y() + 5), pm)


class StartNode(Node):
    def __init__(self, canvas: "Canvas") -> None:
        super().__init__(canvas, "start")
        self.body_h = 210.0
        self._preview: QPixmap | None = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def header_color(self) -> str:
        return ORB_COLORS["white"]

    def title(self) -> str:
        return "目录页" if self.canvas.toc_enabled else "起点（无目录）"

    def paint_header(self, p: QPainter, th) -> None:
        draw_orb(p, 10, (HEADER_H - 18) / 2, 18, "white", "ready", 0, self.canvas.dpr())
        f = QFont(self.canvas.font())
        f.setBold(True)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor(th.c("text")))
        p.drawText(QRectF(34, 0, NODE_W - 44, HEADER_H), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.title())

    def set_preview(self, pm: QPixmap | None) -> None:
        self._preview = pm
        self.update()

    def paint_body(self, p: QPainter, th, body: QRectF) -> None:
        # the widgets (title field + toggles) are proxies placed by the canvas; we paint the preview below them
        pr = QRectF(14, HEADER_H + 84, NODE_W - 28, self.body_h - 94)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(th.c("bg")))
        p.drawRoundedRect(pr, 6, 6)
        if self._preview is not None and self.canvas.toc_enabled:
            pm = self._preview
            scale = min((pr.width() - 10) / pm.width() * pm.devicePixelRatio(), (pr.height() - 10) / pm.height() * pm.devicePixelRatio())
            dw = pm.width() / pm.devicePixelRatio() * scale
            dh = pm.height() / pm.devicePixelRatio() * scale
            target = QRectF(pr.center().x() - dw / 2, pr.top() + 5, dw, dh)
            p.drawPixmap(target, pm, QRectF(pm.rect()))
        else:
            p.setPen(QColor(th.c("muted")))
            f = QFont(self.canvas.font())
            f.setPixelSize(11)
            p.setFont(f)
            p.drawText(pr, Qt.AlignmentFlag.AlignCenter, "不生成目录页" if not self.canvas.toc_enabled else "目录预览")


class EndNode(Node):
    def __init__(self, canvas: "Canvas") -> None:
        super().__init__(canvas, "end")
        self.body_h = 176.0

    def header_color(self) -> str:
        return "#6EF2A6"

    def title(self) -> str:
        return t("end_node")

    def paint_header(self, p: QPainter, th) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        ready = self.canvas.all_ready
        p.setBrush(QColor(th.c("accent")) if ready else QColor(th.c("muted")))
        tri = QPolygonF([QPointF(13, 10), QPointF(26, HEADER_H / 2), QPointF(13, HEADER_H - 10)])
        p.drawPolygon(tri)
        f = QFont(self.canvas.font())
        f.setBold(True)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor(th.c("text")))
        p.drawText(QRectF(34, 0, NODE_W - 44, HEADER_H), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.title())

    def paint_body(self, p: QPainter, th, body: QRectF) -> None:
        small = QFont(self.canvas.font())
        small.setPixelSize(11)
        p.setFont(small)
        ready = self.canvas.all_ready
        if not self.canvas.model.items:
            txt, col = "先把文件拖进来", th.c("muted")
        elif ready:
            txt, col = (f"共 {self.canvas.total_pages} 页 · {self.canvas.item_count} 个文件" if self.canvas.merge_mode else f"各自导出 {self.canvas.item_count} 个 PDF"), th.c("ok")
        else:
            txt, col = f"{self.canvas.busy_count} 个还在转换…", th.c("warn")
        p.setPen(QColor(col))
        p.drawText(QRectF(14, HEADER_H + self.body_h - 26, NODE_W - 28, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, _elide(txt, small, NODE_W - 28))


class Wire(QGraphicsObject):
    def __init__(self, canvas: "Canvas", gap: int) -> None:
        super().__init__()
        self.canvas = canvas
        self.gap = gap
        self.path = QPainterPath()
        self.mid = QPointF()
        self.hover = False
        self.highlight = False
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_endpoints(self, a: QPointF, b: QPointF) -> None:
        self.prepareGeometryChange()
        self.path = wire_path(a, b)
        self.mid = self.path.pointAtPercent(0.5)
        self.update()

    def boundingRect(self) -> QRectF:
        return self.path.boundingRect().adjusted(-18, -18, 18, 18)

    def shape(self) -> QPainterPath:
        st = QPainterPathStroker()
        st.setWidth(16)
        s = st.createStroke(self.path)
        s.addEllipse(self.mid, 12, 12)
        return s

    def paint(self, p: QPainter, _o, _w=None) -> None:
        th = theme.current()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.hover or self.highlight
        col = QColor(th.c("accent")) if active else QColor(th.c("accent"))
        if not active:
            col.setAlphaF(0.55)
        if self.highlight:
            glow = QColor(th.c("accent"))
            glow.setAlphaF(0.22)
            p.setPen(QPen(glow, 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(self.path)
        pen = QPen(col, 2.4 if active else 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self.path)
        if self.canvas.flowing:
            fp = QPen(QColor(th.c("accent_hover")), 2.6, Qt.PenStyle.CustomDashLine, Qt.PenCapStyle.RoundCap)
            fp.setDashPattern([1, 7])
            fp.setDashOffset(-self.canvas.flow_offset)
            p.setPen(fp)
            p.drawPath(self.path)
        r = 9.0 if active else 6.5
        p.setPen(QPen(col, 1.4))
        p.setBrush(QColor(th.c("accent_dim")) if active else QColor(th.c("bg")))
        p.drawEllipse(self.mid, r, r)
        p.setPen(QPen(col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        d = r * 0.5
        p.drawLine(QPointF(self.mid.x() - d, self.mid.y()), QPointF(self.mid.x() + d, self.mid.y()))
        p.drawLine(QPointF(self.mid.x(), self.mid.y() - d), QPointF(self.mid.x(), self.mid.y() + d))

    def hoverEnterEvent(self, e) -> None:
        self.hover = True
        self.setToolTip("在这里插入")
        self.update()
        super().hoverEnterEvent(e)

    def hoverLeaveEvent(self, e) -> None:
        self.hover = False
        self.update()
        super().hoverLeaveEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.canvas.insert_menu(self.gap, e.screenPos())
        e.accept()

    def contextMenuEvent(self, e) -> None:
        self.canvas.insert_menu(self.gap, e.screenPos())
        e.accept()


def wire_path(a: QPointF, b: QPointF) -> QPainterPath:
    path = QPainterPath(a)
    dx = b.x() - a.x()
    bend = max(60.0, abs(dx) * 0.5)
    if dx < 0:
        bend = max(90.0, abs(dx) * 0.6)
    c1 = QPointF(a.x() + bend, a.y())
    c2 = QPointF(b.x() - bend, b.y())
    path.cubicTo(c1, c2, b)
    return path


class Canvas(QGraphicsView):
    selection_changed = Signal(list)
    rename_requested = Signal(str, str)
    insert_files_requested = Signal(int)
    insert_folder_requested = Signal(int)
    insert_paste_requested = Signal(int)
    insert_special_requested = Signal(int, str)
    files_dropped = Signal(list, int)
    reorder_requested = Signal(str, int)
    remove_requested = Signal(list)
    range_requested = Signal(str)
    fit_requested = Signal(str, str)
    password_requested = Signal(str)
    reconvert_requested = Signal(str)
    rotate_requested = Signal(str, int)
    toc_toggled_requested = Signal(str, bool)
    duplicate_requested = Signal(str)
    open_source_requested = Signal(str)
    reveal_source_requested = Signal(str)
    export_requested = Signal()
    batch_rename_requested = Signal()
    start_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Canvas")
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(-4000, -4000, 8000, 8000)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.model = None
        self.file_nodes: list[FileNode] = []
        self.wires: list[Wire] = []
        self._wire_timer = QTimer(self)
        self._wire_timer.setSingleShot(True)
        self._wire_timer.timeout.connect(self.update_wires)
        self.start = StartNode(self)
        self.end = EndNode(self)
        self._scene.addItem(self.start)
        self._scene.addItem(self.end)
        self.start.setPos(0, 0)
        self.end.setPos(NODE_W + 120, 0)
        self.toc_enabled = True
        self.merge_mode = True
        self.total_pages = 0
        self.item_count = 0
        self.busy_count = 0
        self.all_ready = False
        self.spin_angle = 0.0
        self.flowing = False
        self.flow_offset = 0.0
        self._flow_timer = QTimer(self)
        self._flow_timer.setInterval(40)
        self._flow_timer.timeout.connect(self._tick)
        self._drag_gap: int | None = None
        self._wire_drag_from: Node | None = None
        self._temp_wire: QGraphicsItem | None = None
        self._editor: QGraphicsProxyWidget | None = None
        self._pan_last: QPointF | None = None
        self._anim: QParallelAnimationGroup | None = None
        self._placed_ids: set[str] = set()
        self._first_fit_done = False

    def dpr(self) -> float:
        return self.devicePixelRatioF()

    # -- model -----------------------------------------------------------------
    def set_model(self, model) -> None:
        self.model = model
        model.changed.connect(self.rebuild)
        model.item_changed.connect(self._on_item_changed)
        self.rebuild()

    def _tick(self) -> None:
        self.spin_angle = (self.spin_angle + 9) % 360
        self.flow_offset = (self.flow_offset + 1.2) % 1000
        for n in self.file_nodes:
            if n.item.status == "converting":
                n.update()
        for w in self.wires:
            w.update()

    def _on_item_changed(self, item_id: str) -> None:
        for n in self.file_nodes:
            if n.item_id == item_id:
                n.update()
        self.refresh_summary()

    def refresh_summary(self) -> None:
        if self.model is None:
            return
        items = self.model.items
        self.item_count = len([it for it in items if not it.is_special])
        self.busy_count = sum(1 for it in items if it.status in ("converting", "pending"))
        errors = sum(1 for it in items if it.status == "error")
        self.all_ready = bool(items) and self.busy_count == 0 and errors == 0
        self.flowing = self.busy_count > 0
        if self.flowing and not self._flow_timer.isActive():
            self._flow_timer.start()
        elif not self.flowing and self._flow_timer.isActive():
            self._flow_timer.stop()
            for w in self.wires:
                w.update()
        self.start.update()
        self.end.update()

    def set_state(self, toc_enabled: bool, merge_mode: bool, total_pages: int) -> None:
        self.toc_enabled = toc_enabled
        self.merge_mode = merge_mode
        self.total_pages = total_pages
        self.refresh_summary()

    def rebuild(self) -> None:
        if self.model is None:
            return
        self._close_editor()
        selected = {n.item_id for n in self.file_nodes if n.isSelected()}
        old = {n.item_id: n for n in self.file_nodes}
        for w in self.wires:
            self._scene.removeItem(w)
        self.wires = []
        new_nodes: list[FileNode] = []
        for i, it in enumerate(self.model.items):
            n = old.pop(it.id, None)
            if n is None:
                n = FileNode(self, it)
                self._scene.addItem(n)
                if it.pos is not None:
                    n.setPos(it.pos[0], it.pos[1])
                else:
                    n.setPos(self._auto_place(i))
                    self.model.set_pos(it.id, n.pos().x(), n.pos().y())
                    self._appear(n)
            n.item = it
            n.order = i + 1
            n.setSelected(it.id in selected)
            n.update()
            new_nodes.append(n)
        for n in old.values():
            self._scene.removeItem(n)
        added = [n for n in new_nodes if n.item_id not in old and n.item_id not in self._placed_ids]
        self._placed_ids = {n.item_id for n in new_nodes}
        self.file_nodes = new_nodes
        chain = [self.start] + self.file_nodes + [self.end]
        for k in range(len(chain) - 1):
            w = Wire(self, k)
            self._scene.addItem(w)
            self.wires.append(w)
        self._keep_end_right()
        self.refresh_summary()
        self.update_wires()
        self.selection_changed.emit([n.item_id for n in self.file_nodes if n.isSelected()])
        if added:
            if not self._first_fit_done:
                self._first_fit_done = True
                QTimer.singleShot(60, self.fit_all)
            else:
                last = added[-1]
                QTimer.singleShot(260, lambda: (self._reveal(last), self._reveal(self.end)))
        elif self.model.items:
            QTimer.singleShot(260, lambda: self._reveal(self.end))
        self.viewport().update()

    def _reveal(self, node: Node) -> None:
        try:
            self.ensureVisible(node, 60, 60)
        except Exception:
            pass

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self.model is None or not self.model.items:
            QTimer.singleShot(0, self._center_empty)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.model is None or not self.model.items:
            self._center_empty()

    def _center_empty(self) -> None:
        rect = self.start.sceneBoundingRect().united(self.end.sceneBoundingRect())
        self.resetTransform()
        self.centerOn(rect.center() + QPointF(0, -40))

    def _cols(self) -> int:
        """Columns of the default serpentine, from the viewport width at 100% zoom (deterministic)."""
        return max(2, int((max(700, self.viewport().width()) - 60) // (NODE_W + 70)))

    def _auto_place(self, index: int) -> QPointF:
        """Serpentine default placement, relative to the start node."""
        cols = self._cols()
        i = index + 1  # start node is column 0 of row 0
        row, col = divmod(i, cols)
        if row % 2 == 1:
            col = cols - 1 - col
        base = self.start.pos()
        return QPointF(base.x() + col * (NODE_W + 70), base.y() + row * (HEADER_H + FILE_BODY_H + 60))

    def _keep_end_right(self) -> None:
        """Move the end node after the last file node unless the user has dragged it."""
        if getattr(self.end, "_user_moved", False):
            return
        if self.file_nodes:
            idx = len(self.file_nodes)
            cols = self._cols()
            i = idx + 1
            row, col = divmod(i, cols)
            if row % 2 == 1:
                col = cols - 1 - col
            base = self.start.pos()
            target = QPointF(base.x() + col * (NODE_W + 70), base.y() + row * (HEADER_H + FILE_BODY_H + 60))
        else:
            target = self.start.pos() + QPointF(NODE_W + 120, 0)
        self._animate(self.end, target)

    def _appear(self, node: Node) -> None:
        node.setOpacity(0.0)
        anim = QPropertyAnimation(node, b"opacity", self)
        anim.setDuration(260)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _animate(self, node: Node, target: QPointF, duration: int = 220) -> None:
        if (node.pos() - target).manhattanLength() < 1:
            node.setPos(target)
            return
        anim = QPropertyAnimation(node, b"pos", self)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(node.pos())
        anim.setEndValue(target)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def tidy(self) -> None:
        """Snap every node into a neat serpentine."""
        self.end._user_moved = False
        for i, n in enumerate(self.file_nodes):
            target = self._auto_place(i)
            self._animate(n, target)
            self.model.set_pos(n.item.id, target.x(), target.y())
        self._keep_end_right()
        QTimer.singleShot(260, self.fit_all)

    def fit_all(self) -> None:
        items = [self.start, self.end] + self.file_nodes
        rect = QRectF()
        for n in items:
            rect = rect.united(n.sceneBoundingRect())
        rect = rect.adjusted(-60, -60, 60, 60)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        s = self.transform().m11()
        if s > 1.0:
            self.resetTransform()
            self.scale(1.0, 1.0)
            self.centerOn(rect.center())

    # -- wires ------------------------------------------------------------------
    def schedule_wires(self) -> None:
        if not hasattr(self, "_wire_timer"):
            return
        if not self._wire_timer.isActive():
            self._wire_timer.start(0)

    def update_wires(self) -> None:
        chain = [self.start] + self.file_nodes + [self.end]
        for k, w in enumerate(self.wires):
            if k + 1 < len(chain):
                w.set_endpoints(chain[k].scene_output(), chain[k + 1].scene_input())

    # -- background -------------------------------------------------------------
    def drawBackground(self, p: QPainter, rect: QRectF) -> None:
        th = theme.current()
        p.fillRect(rect, QColor(th.c("bg")))
        scale = self.transform().m11()
        step = GRID
        if scale < 0.6:
            step = GRID * 2
        dot = QColor(th.c("border2"))
        dot.setAlphaF(0.55)
        big = QColor(th.c("accent"))
        big.setAlphaF(0.18)
        left = math.floor(rect.left() / step) * step
        top = math.floor(rect.top() / step) * step
        x = left
        p.setPen(Qt.PenStyle.NoPen)
        while x < rect.right():
            y = top
            while y < rect.bottom():
                major = (round(x / step) % 5 == 0) and (round(y / step) % 5 == 0)
                p.setBrush(big if major else dot)
                r = 1.8 if major else 1.1
                p.drawEllipse(QPointF(x, y), r / max(scale, 0.5), r / max(scale, 0.5))
                y += step
            x += step

    def drawForeground(self, p: QPainter, rect: QRectF) -> None:
        if self.model is not None and not self.model.items:
            th = theme.current()
            p.resetTransform()
            vp = self.viewport().rect()
            cx, cy = vp.width() / 2, vp.height() / 2 + 40
            pm = assets.robot_head(96, self.dpr())
            ring = QColor(th.c("accent"))
            ring.setAlphaF(0.10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ring)
            p.drawEllipse(QPointF(cx, cy - 6), 70, 70)
            p.drawPixmap(int(cx - 48), int(cy - 54), pm)
            f = QFont(self.font())
            f.setPixelSize(15)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(th.c("text")))
            p.drawText(QRectF(cx - 240, cy + 56, 480, 24), Qt.AlignmentFlag.AlignCenter, "把文件拖进来")
            f2 = QFont(self.font())
            f2.setPixelSize(12)
            p.setFont(f2)
            p.setPen(QColor(th.c("muted")))
            p.drawText(QRectF(cx - 240, cy + 82, 480, 20), Qt.AlignmentFlag.AlignCenter, "PDF · Word · PPT · Excel · 图片 · 文本 都可以，会自动排好队")

    # -- navigation ---------------------------------------------------------------
    def wheelEvent(self, e) -> None:
        factor = 1.12 if e.angleDelta().y() > 0 else 1 / 1.12
        cur = self.transform().m11()
        new = max(0.35, min(2.2, cur * factor))
        if abs(new - cur) > 1e-4:
            self.scale(new / cur, new / cur)
        e.accept()

    def mousePressEvent(self, e) -> None:
        item = self.itemAt(e.position().toPoint())
        if item is None:
            if e.button() == Qt.MouseButton.LeftButton and (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
                super().mousePressEvent(e)
                return
            if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
                self._close_editor()
                self._pan_last = e.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                if e.button() == Qt.MouseButton.LeftButton:
                    self._scene.clearSelection()
                    self.selection_changed.emit([])
                e.accept()
                return
        if e.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._pan_last is not None:
            delta = e.position() - self._pan_last
            self._pan_last = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            e.accept()
            return
        if self._wire_drag_from is not None:
            self._update_temp_wire(self.mapToScene(e.position().toPoint()))
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if self._pan_last is not None:
            self._pan_last = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            e.accept()
            return
        if self._wire_drag_from is not None:
            self._finish_wire_drag(self.mapToScene(e.position().toPoint()), e.globalPosition().toPoint())
            e.accept()
            return
        super().mouseReleaseEvent(e)
        if self.dragMode() == QGraphicsView.DragMode.RubberBandDrag:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.selection_changed.emit([n.item_id for n in self.file_nodes if n.isSelected()])

    def contextMenuEvent(self, e) -> None:
        item = self.itemAt(e.pos())
        if item is None:
            m = QMenu(self)
            n = len(self.model.items) if self.model else 0
            m.addAction(icons.icon("add"), t("add_files")).triggered.connect(lambda: self.insert_files_requested.emit(n))
            m.addAction(icons.icon("folder"), t("add_folder")).triggered.connect(lambda: self.insert_folder_requested.emit(n))
            m.addAction(icons.icon("paste"), t("paste")).triggered.connect(lambda: self.insert_paste_requested.emit(n))
            m.addSeparator()
            m.addAction("空白页").triggered.connect(lambda: self.insert_special_requested.emit(n, KIND_BLANK))
            m.addAction("分隔页").triggered.connect(lambda: self.insert_special_requested.emit(n, KIND_DIVIDER))
            m.addSeparator()
            m.addAction("整理排列").triggered.connect(self.tidy)
            m.addAction("适应窗口").triggered.connect(self.fit_all)
            m.addAction("批量重命名…").triggered.connect(self.batch_rename_requested.emit)
            m.exec(e.globalPos())
            e.accept()
            return
        super().contextMenuEvent(e)

    def keyPressEvent(self, e) -> None:
        sel = [n.item_id for n in self.file_nodes if n.isSelected()]
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and sel:
            self.remove_requested.emit(sel)
            return
        if e.key() == Qt.Key.Key_F2 and len(sel) == 1:
            for n in self.file_nodes:
                if n.item_id == sel[0]:
                    self.begin_inline_rename(n)
            return
        if e.key() == Qt.Key.Key_A and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            for n in self.file_nodes:
                n.setSelected(True)
            self.selection_changed.emit([n.item_id for n in self.file_nodes])
            return
        if e.key() == Qt.Key.Key_Escape:
            self._close_editor()
            self._scene.clearSelection()
            self.selection_changed.emit([])
            return
        super().keyPressEvent(e)

    # -- node callbacks -----------------------------------------------------------------
    def node_clicked(self, node: Node) -> None:
        if node.kind == "start":
            self.start_clicked.emit()
        elif node.kind == "end":
            self.export_requested.emit()
        self.selection_changed.emit([n.item_id for n in self.file_nodes if n.isSelected()])

    def node_double_clicked(self, node: Node) -> None:
        if node.kind == "file":
            self.begin_inline_rename(node)

    def node_button(self, node: Node, key: str) -> None:
        it = node.item
        if key == "rotl":
            self.rotate_requested.emit(it.id, -90)
        elif key == "rotr":
            self.rotate_requested.emit(it.id, 90)
        elif key == "range":
            self.range_requested.emit(it.id)
        elif key == "remove":
            self.remove_requested.emit([it.id])
        elif key == "menu":
            self.node_menu(node, QCursor.pos())

    def node_dragging(self, node: Node, sp: QPointF) -> None:
        if node.kind == "end":
            node._user_moved = True
        if node.kind != "file":
            return
        gap = self._gap_near(sp, exclude=node)
        if gap != self._drag_gap:
            self._drag_gap = gap
            for w in self.wires:
                w.highlight = (w.gap == gap)
                w.update()

    def node_dropped(self, node: Node, sp: QPointF) -> None:
        gap = self._drag_gap
        self._drag_gap = None
        for w in self.wires:
            w.highlight = False
            w.update()
        if node.kind == "file" and gap is not None and node.item_id:
            self.reorder_requested.emit(node.item_id, gap)
        self.schedule_wires()

    def _gap_near(self, sp: QPointF, exclude: Node | None = None, radius: float = 34.0) -> int | None:
        """Gap whose wire midpoint is within radius (excluding the node's own two wires)."""
        idx = self.file_nodes.index(exclude) if exclude in self.file_nodes else None
        best, best_d = None, radius * radius
        for w in self.wires:
            if idx is not None and w.gap in (idx, idx + 1):
                continue
            d = (sp.x() - w.mid.x()) ** 2 + (sp.y() - w.mid.y()) ** 2
            if d < best_d:
                best, best_d = w.gap, d
        return best

    # -- wire dragging (output socket -> another node) --------------------------------------
    def begin_wire_drag(self, node: Node) -> None:
        self._wire_drag_from = node
        path_item = self._scene.addPath(QPainterPath(), QPen(QColor(theme.current().c("accent")), 2.2, Qt.PenStyle.DashLine))
        path_item.setZValue(30)
        self._temp_wire = path_item
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _update_temp_wire(self, sp: QPointF) -> None:
        if self._temp_wire is not None and self._wire_drag_from is not None:
            self._temp_wire.setPath(wire_path(self._wire_drag_from.scene_output(), sp))
            target = self._node_at(sp)
            for n in self.file_nodes + [self.end]:
                n.hover = (n is target and n is not self._wire_drag_from)
                n.update()

    def _node_at(self, sp: QPointF) -> Node | None:
        for it in self._scene.items(sp):
            if isinstance(it, Node):
                return it
        return None

    def _finish_wire_drag(self, sp: QPointF, global_pos) -> None:
        src = self._wire_drag_from
        self._wire_drag_from = None
        if self._temp_wire is not None:
            self._scene.removeItem(self._temp_wire)
            self._temp_wire = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        for n in self.file_nodes + [self.end]:
            n.hover = False
            n.update()
        if src is None:
            return
        target = self._node_at(sp)
        chain_ids = [n.item_id for n in self.file_nodes]
        src_idx = self.file_nodes.index(src) if src in self.file_nodes else -1   # -1 = start node
        if target is None or target is src:
            # dropped on empty space: offer to insert right after the source
            self.insert_menu(src_idx + 1, global_pos)
            return
        if target.kind == "end":
            if src.kind == "file":
                self.reorder_requested.emit(src.item_id, len(chain_ids))   # src becomes last
            return
        if target.kind == "start":
            return
        # "target follows src": move target right after src
        gap = src_idx + 1
        self.reorder_requested.emit(target.item_id, gap)

    # -- external drops ---------------------------------------------------------------------
    def dragEnterEvent(self, e) -> None:
        if mime_has_files(e.mimeData()):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e) -> None:
        if not mime_has_files(e.mimeData()):
            e.ignore()
            return
        sp = self.mapToScene(e.position().toPoint())
        gap = self._gap_near(sp, radius=48.0)
        for w in self.wires:
            w.highlight = (w.gap == gap)
            w.update()
        self._drag_gap = gap
        e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:
        for w in self.wires:
            w.highlight = False
            w.update()
        self._drag_gap = None
        super().dragLeaveEvent(e)

    def dropEvent(self, e) -> None:
        gap = self._drag_gap if self._drag_gap is not None else (len(self.model.items) if self.model else 0)
        for w in self.wires:
            w.highlight = False
            w.update()
        self._drag_gap = None
        paths = collect_files(paths_from_mime(e.mimeData()))
        if paths:
            self.files_dropped.emit(paths, gap)
        e.acceptProposedAction()

    # -- menus --------------------------------------------------------------------------------
    def insert_menu(self, gap: int, screen_pos) -> None:
        m = QMenu(self)
        m.addAction(icons.icon("add"), "插入文件…").triggered.connect(lambda: self.insert_files_requested.emit(gap))
        m.addAction(icons.icon("folder"), "插入文件夹…").triggered.connect(lambda: self.insert_folder_requested.emit(gap))
        m.addAction(icons.icon("paste"), "粘贴剪贴板").triggered.connect(lambda: self.insert_paste_requested.emit(gap))
        m.addSeparator()
        m.addAction("空白页").triggered.connect(lambda: self.insert_special_requested.emit(gap, KIND_BLANK))
        m.addAction("分隔页").triggered.connect(lambda: self.insert_special_requested.emit(gap, KIND_DIVIDER))
        m.exec(screen_pos)

    def node_menu(self, node: Node, screen_pos) -> None:
        if node.kind == "start":
            m = QMenu(self)
            m.addAction("在开头插入文件…").triggered.connect(lambda: self.insert_files_requested.emit(0))
            m.exec(screen_pos)
            return
        if node.kind == "end":
            m = QMenu(self)
            m.addAction("在末尾插入文件…").triggered.connect(lambda: self.insert_files_requested.emit(len(self.model.items)))
            m.exec(screen_pos)
            return
        it = node.item
        if not node.isSelected():
            self._scene.clearSelection()
            node.setSelected(True)
        ids = [n.item_id for n in self.file_nodes if n.isSelected()] or [it.id]
        m = QMenu(self)
        m.addAction(icons.icon("edit"), "重命名 (F2)").triggered.connect(lambda: self.begin_inline_rename(node))
        if not it.is_special:
            m.addAction(icons.icon("rotate-left"), "左转 90°").triggered.connect(lambda: self.rotate_requested.emit(it.id, -90))
            m.addAction(icons.icon("rotate-right"), "右转 90°").triggered.connect(lambda: self.rotate_requested.emit(it.id, 90))
        if it.kind == KIND_PDF:
            m.addAction(icons.icon("range"), "页面范围…").triggered.connect(lambda: self.range_requested.emit(it.id))
        if it.kind == KIND_IMAGE:
            sub = m.addMenu(icons.icon("image"), "图片页面")
            for key, text in (("bleed", "无白边（默认）"), ("a4", "适配 A4 留边"), ("original", "原始尺寸")):
                a = sub.addAction(text)
                a.setCheckable(True)
                a.setChecked((it.fit or "bleed") == key)
                a.triggered.connect(lambda _=False, k=key: self.fit_requested.emit(it.id, k))
        if it.needs_password:
            m.addAction(icons.icon("lock"), "输入密码…").triggered.connect(lambda: self.password_requested.emit(it.id))
        if it.status == "error" and not it.needs_password:
            m.addAction(icons.icon("refresh"), "重新转换").triggered.connect(lambda: self.reconvert_requested.emit(it.id))
        if not it.is_special:
            a = m.addAction("列入目录")
            a.setCheckable(True)
            a.setChecked(it.in_toc)
            a.triggered.connect(lambda on: self.toc_toggled_requested.emit(it.id, bool(on)))
        m.addSeparator()
        idx = self.model.index_of(it.id)
        n = len(self.model.items)
        a1 = m.addAction(icons.icon("left"), "前移")
        a1.setEnabled(idx > 0)
        a1.triggered.connect(lambda: self.reorder_requested.emit(it.id, idx - 1))
        a2 = m.addAction(icons.icon("right"), "后移")
        a2.setEnabled(idx < n - 1)
        a2.triggered.connect(lambda: self.reorder_requested.emit(it.id, idx + 2))
        m.addAction("移到开头").triggered.connect(lambda: self.reorder_requested.emit(it.id, 0))
        m.addAction("移到末尾").triggered.connect(lambda: self.reorder_requested.emit(it.id, n))
        m.addSeparator()
        m.addAction(icons.icon("add"), "在此之前插入…").triggered.connect(lambda: self.insert_files_requested.emit(idx))
        m.addAction(icons.icon("add"), "在此之后插入…").triggered.connect(lambda: self.insert_files_requested.emit(idx + 1))
        m.addAction(icons.icon("copy"), "复制一份").triggered.connect(lambda: self.duplicate_requested.emit(it.id))
        if it.path:
            m.addSeparator()
            m.addAction(icons.icon("open"), "打开源文件").triggered.connect(lambda: self.open_source_requested.emit(it.id))
            m.addAction(icons.icon("folder-open"), "打开所在文件夹").triggered.connect(lambda: self.reveal_source_requested.emit(it.id))
        m.addSeparator()
        rm = m.addAction(icons.icon("trash"), f"移除{'（' + str(len(ids)) + ' 项）' if len(ids) > 1 else ''}")
        rm.triggered.connect(lambda: self.remove_requested.emit(ids))
        m.exec(screen_pos)

    # -- inline rename -------------------------------------------------------------------------
    def begin_inline_rename(self, node: Node) -> None:
        self._close_editor()
        if node.item is None:
            return
        edit = QLineEdit(node.item.display_name)
        edit.setObjectName("Inline")
        edit.setFixedWidth(int(NODE_W - 44))
        proxy = self._scene.addWidget(edit)
        proxy.setPos(node.pos() + QPointF(30, 5))
        proxy.setZValue(40)
        self._editor = proxy
        item_id = node.item.id

        def commit() -> None:
            if self._editor is None:
                return
            text = edit.text()
            self._close_editor()
            self.rename_requested.emit(item_id, text)

        edit.returnPressed.connect(commit)
        edit.editingFinished.connect(commit)
        edit.selectAll()
        edit.setFocus()

    def _close_editor(self) -> None:
        if self._editor is not None:
            proxy = self._editor
            self._editor = None
            try:
                self._scene.removeItem(proxy)
                proxy.deleteLater()
            except Exception:
                pass

    # -- export animation: papers fly to the end node and stack --------------------------------
    def play_export_animation(self, on_done=None) -> None:
        nodes = [n for n in self.file_nodes if n._thumb is not None or True]
        if not nodes:
            if on_done:
                on_done()
            return
        target = self.end.mapToScene(QPointF(NODE_W / 2, HEADER_H + 70))
        group = QParallelAnimationGroup(self)
        ghosts: list[QGraphicsItem] = []
        for i, n in enumerate(nodes):
            pm = n._thumb if n._thumb is not None else assets.orb(n.item.orb, 48, self.dpr())
            ghost = QGraphicsPixmapItem(pm.scaledToHeight(90, Qt.TransformationMode.SmoothTransformation))
            ghost.setOffset(-ghost.pixmap().width() / 2, -ghost.pixmap().height() / 2)
            ghost.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            ghost.setZValue(50)
            ghost.setPos(n.mapToScene(QPointF(NODE_W / 2, HEADER_H + 66)))
            self._scene.addItem(ghost)
            ghosts.append(ghost)
            wrapper = _GhostAnimator(ghost)
            seq = QSequentialAnimationGroup(group)
            seq.addPause(90 * i)
            move = QPropertyAnimation(wrapper, b"pos", seq)
            move.setDuration(520)
            move.setEasingCurve(QEasingCurve.Type.InOutCubic)
            move.setStartValue(ghost.pos())
            move.setEndValue(target + QPointF(random.uniform(-6, 6), -i * 3))
            seq.addAnimation(move)
            rot = QPropertyAnimation(wrapper, b"rotation", seq)
            rot.setDuration(520)
            rot.setStartValue(0.0)
            rot.setEndValue(random.uniform(-8, 8))
            seq.addAnimation(rot)
            wrapper.setParent(seq)
            group.addAnimation(seq)

        def finish() -> None:
            fade = QParallelAnimationGroup(self)
            for g in ghosts:
                w = _GhostAnimator(g)
                a = QPropertyAnimation(w, b"opacity", fade)
                a.setDuration(360)
                a.setStartValue(1.0)
                a.setEndValue(0.0)
                w.setParent(fade)
                fade.addAnimation(a)

            def cleanup() -> None:
                for g in ghosts:
                    try:
                        self._scene.removeItem(g)
                    except Exception:
                        pass
                if on_done:
                    on_done()

            fade.finished.connect(cleanup)
            fade.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)

        group.finished.connect(finish)
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)


class _GhostAnimator(QObject):
    """QGraphicsPixmapItem is not a QObject; this adapter exposes pos/rotation/opacity as properties."""

    def __init__(self, item: QGraphicsItem) -> None:
        super().__init__()
        self._item = item

    def _get_pos(self) -> QPointF:
        return self._item.pos()

    def _set_pos(self, p: QPointF) -> None:
        self._item.setPos(p)

    def _get_rot(self) -> float:
        return self._item.rotation()

    def _set_rot(self, r: float) -> None:
        self._item.setRotation(r)

    def _get_op(self) -> float:
        return self._item.opacity()

    def _set_op(self, o: float) -> None:
        self._item.setOpacity(o)

    pos = Property(QPointF, _get_pos, _set_pos)
    rotation = Property(float, _get_rot, _set_rot)
    opacity = Property(float, _get_op, _set_op)
