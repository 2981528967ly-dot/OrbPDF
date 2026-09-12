"""Bitmap assets: the Defect head cut-out and the five orbs."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

from ..core.paths import asset_path

# eye centres / radii as fractions of the head image width & height (measured on robot_head.png)
BIG_EYE = (0.485, 0.655, 0.182)
SMALL_EYE = (0.644, 0.332, 0.067)

ORB_KEYS = ("blue", "gold", "green", "purple", "white")
ORB_NAMES = {"blue": "晶蓝", "gold": "金黄", "green": "青绿", "purple": "紫黑", "white": "珍珠白"}


@lru_cache(maxsize=8)
def _head_image() -> QImage:
    p = asset_path("robot_head.png")
    img = QImage(str(p))
    return img


@lru_cache(maxsize=32)
def robot_head(size: int, dpr: float = 1.0) -> QPixmap:
    img = _head_image()
    if img.isNull():
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.fill(Qt.GlobalColor.transparent)
        pm.setDevicePixelRatio(dpr)
        return pm
    px = int(size * dpr)
    scaled = img.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    pm = QPixmap.fromImage(scaled)
    pm.setDevicePixelRatio(dpr)
    return pm


@lru_cache(maxsize=64)
def orb(key: str, size: int, dpr: float = 1.0) -> QPixmap:
    if key not in ORB_KEYS:
        key = "blue"
    img = QImage(str(asset_path("orbs", f"orb_{key}.png")))
    px = int(size * dpr)
    if img.isNull():
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
    else:
        pm = QPixmap.fromImage(img.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    pm.setDevicePixelRatio(dpr)
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(robot_head(s))
    return ic


def eye_center(size: int) -> QPointF:
    """Centre of the big eye for a head drawn at ``size`` px (square)."""
    img = _head_image()
    if img.isNull():
        return QPointF(size / 2, size / 2)
    w, h = img.width(), img.height()
    scale = size / max(w, h)
    dw, dh = w * scale, h * scale
    ox, oy = (size - dw) / 2, (size - dh) / 2
    return QPointF(ox + BIG_EYE[0] * dw, oy + BIG_EYE[1] * dh)


def eye_radius(size: int) -> float:
    img = _head_image()
    if img.isNull():
        return size * 0.18
    w, h = img.width(), img.height()
    return BIG_EYE[2] * (w * size / max(w, h))


def small_eye(size: int) -> tuple[QPointF, float]:
    img = _head_image()
    if img.isNull():
        return QPointF(size * 0.64, size * 0.33), size * 0.06
    w, h = img.width(), img.height()
    scale = size / max(w, h)
    dw, dh = w * scale, h * scale
    ox, oy = (size - dw) / 2, (size - dh) / 2
    return QPointF(ox + SMALL_EYE[0] * dw, oy + SMALL_EYE[1] * dh), SMALL_EYE[2] * dw
