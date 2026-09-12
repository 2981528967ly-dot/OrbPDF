"""Engine interface shared by all converters."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

ProgressFn = Optional[Callable[[float, str], None]]
CancelFn = Optional[Callable[[], bool]]


class ConvertError(Exception):
    """Conversion failed in a way the user should hear about."""


class EngineUnavailable(ConvertError):
    """The engine cannot run on this machine (not installed, wrong kind)."""


class ConvertCancelled(ConvertError):
    pass


class NeedsPassword(ConvertError):
    """PDF is encrypted; ask the user for a password and retry."""


@dataclass
class ConvertOptions:
    image_fit: str = "bleed"        # bleed | a4 | original
    image_max_side: int = 0         # px; 0 = keep original pixels
    jpeg_quality: int = 90
    timeout: int = 120              # seconds, per file, for external engines
    password: str | None = None

    def cache_key_part(self) -> str:
        return f"{self.image_fit}|{self.image_max_side}|{self.jpeg_quality}"


@dataclass
class ConvertResult:
    pdf_path: Path
    engine_id: str
    engine_name: str
    pages: int = 0
    warnings: list[str] = field(default_factory=list)
    duration: float = 0.0
    from_cache: bool = False


@dataclass
class EngineInfo:
    id: str
    name: str
    available: bool
    detail: str = ""            # e.g. "Word 16.0 · PowerPoint 16.0"
    kinds: set[str] = field(default_factory=set)
    fidelity: str = "high"      # high | basic
    verified: bool = True       # False = implemented from spec, not tested on this machine


def report(progress: ProgressFn, fraction: float, message: str = "") -> None:
    if progress is not None:
        try:
            progress(max(0.0, min(1.0, fraction)), message)
        except Exception:
            pass


def check_cancel(cancel: CancelFn) -> None:
    if cancel is not None and cancel():
        raise ConvertCancelled("已取消")


class Engine:
    id: str = "base"
    name: str = "引擎"
    kinds: frozenset[str] = frozenset()
    fidelity: str = "high"
    verified: bool = True

    def probe(self) -> EngineInfo:
        return EngineInfo(self.id, self.name, False, kinds=set(self.kinds), fidelity=self.fidelity, verified=self.verified)

    def supports(self, src: Path) -> bool:
        from ..fileinfo import kind_of
        return kind_of(src) in self.kinds

    def begin_batch(self) -> None:
        """Called once before a series of conversions (COM engines keep their app alive)."""

    def end_batch(self) -> None:
        """Called after a batch; release external resources."""

    def convert(self, src: Path, dst: Path, opts: ConvertOptions, progress: ProgressFn = None, cancel: CancelFn = None) -> list[str]:
        """Convert ``src`` to PDF at ``dst``. Return warnings. Raise ConvertError on failure."""
        raise NotImplementedError
