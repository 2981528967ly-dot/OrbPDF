"""Encrypt / decrypt."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from ..convert.base import ConvertError
from ..naming import unique_path
from .info import open_pdf


def encrypt_pdf(src: Path, dst: Path, *, user_password: str = "", owner_password: str = "",
                allow_print: bool = True, allow_copy: bool = True, allow_modify: bool = False,
                current_password: str | None = None) -> Path:
    if not user_password and not owner_password:
        raise ConvertError("请至少设置一个密码")
    perm = pymupdf.PDF_PERM_ACCESSIBILITY
    if allow_print:
        perm |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    if allow_copy:
        perm |= pymupdf.PDF_PERM_COPY
    if allow_modify:
        perm |= pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ANNOTATE | pymupdf.PDF_PERM_FORM | pymupdf.PDF_PERM_ASSEMBLE
    doc = open_pdf(src, current_password)
    try:
        target = unique_path(dst) if dst.exists() and dst.resolve() != src.resolve() else dst
        doc.save(str(target) if target.resolve() != src.resolve() else str(target) + ".part.pdf",
                 encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw=owner_password or user_password,
                 user_pw=user_password, permissions=perm, garbage=3, deflate=True)
    finally:
        doc.close()
    if target.resolve() == src.resolve():
        Path(str(target) + ".part.pdf").replace(target)
    return target


def decrypt_pdf(src: Path, dst: Path, password: str) -> Path:
    # NOTE: never read ``doc.needs_pass`` after authenticating - PyMuPDF then writes undecryptable streams.
    doc = open_pdf(src, password)
    try:
        target = unique_path(dst) if dst.exists() and dst.resolve() != src.resolve() else dst
        out = str(target) if target.resolve() != src.resolve() else str(target) + ".part.pdf"
        doc.save(out, encryption=pymupdf.PDF_ENCRYPT_NONE, garbage=3, deflate=True)
    finally:
        doc.close()
    if target.resolve() == src.resolve():
        Path(str(target) + ".part.pdf").replace(target)
    return target


def is_encrypted(path: Path) -> bool:
    try:
        doc = pymupdf.open(str(path))
        try:
            return bool(doc.needs_pass)
        finally:
            doc.close()
    except Exception:
        return False
