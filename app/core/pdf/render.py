"""Thumbnails and page previews (returns raw RGB samples; the UI wraps them into QImage)."""
from __future__ import annotations

from dataclasses import dataclass

import pymupdf


@dataclass
class RgbImage:
    width: int
    height: int
    stride: int
    samples: bytes


def render_page(doc: pymupdf.Document, pno: int, max_side: int = 200, rotation: int = 0) -> RgbImage:
    page = doc[pno]
    r = page.rect
    scale = max_side / max(r.width, r.height) if max(r.width, r.height) else 1.0
    mat = pymupdf.Matrix(scale, scale).prerotate(rotation % 360)
    pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=pymupdf.csRGB)
    return RgbImage(pix.width, pix.height, pix.stride, bytes(pix.samples))


def render_page_png(doc: pymupdf.Document, pno: int, max_side: int = 200) -> bytes:
    page = doc[pno]
    r = page.rect
    scale = max_side / max(r.width, r.height) if max(r.width, r.height) else 1.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, colorspace=pymupdf.csRGB)
    return pix.tobytes("png")
