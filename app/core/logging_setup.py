"""Rotating file logging; also captures stdout/stderr when running windowed (no console)."""
from __future__ import annotations

import io
import logging
import logging.handlers
import os
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from .paths import appdata_dir, logs_dir, settings_path

LOG = logging.getLogger("orbpdf")


class _StreamToLogger(io.TextIOBase):
    def __init__(self, level: int) -> None:
        self.level = level
        self._buf = ""

    def write(self, s: str) -> int:  # type: ignore[override]
        if not s:
            return 0
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                LOG.log(self.level, line)
        return len(s)

    def flush(self) -> None:  # type: ignore[override]
        if self._buf.strip():
            LOG.log(self.level, self._buf)
        self._buf = ""


def setup_logging(debug: bool = False) -> Path:
    log_file = logs_dir() / "orbpdf.log"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if sys.stdout is not None and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)
    else:
        # windowed exe: print() would otherwise raise, redirect to the log
        sys.stdout = _StreamToLogger(logging.INFO)  # type: ignore[assignment]
        sys.stderr = _StreamToLogger(logging.ERROR)  # type: ignore[assignment]
    LOG.info("---- OrbPDF start ---- python %s frozen=%s", sys.version.split()[0], getattr(sys, "frozen", False))
    return log_file


def environment_report(extra: dict | None = None) -> str:
    lines = [
        f"time: {datetime.now().isoformat(timespec='seconds')}",
        f"os: {platform.platform()}",
        f"python: {sys.version}",
        f"frozen: {getattr(sys, 'frozen', False)}",
        f"exe: {sys.executable}",
        f"cwd: {os.getcwd()}",
        f"appdata: {appdata_dir()}",
    ]
    try:
        import pymupdf  # noqa: WPS433
        lines.append(f"pymupdf: {pymupdf.__doc__}")
    except Exception as e:  # pragma: no cover
        lines.append(f"pymupdf: unavailable ({e})")
    try:
        import PySide6  # noqa: WPS433
        lines.append(f"pyside6: {PySide6.__version__}")
    except Exception as e:  # pragma: no cover
        lines.append(f"pyside6: unavailable ({e})")
    for k, v in (extra or {}).items():
        lines.append(f"{k}: {v}")
    return "\n".join(lines)


def export_diagnostics(dest_zip: Path, extra: dict | None = None) -> Path:
    """Zip logs + settings + environment report so a friend can send it over."""
    dest_zip = Path(dest_zip)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("environment.txt", environment_report(extra))
        for p in logs_dir().glob("orbpdf.log*"):
            try:
                z.write(p, arcname=f"logs/{p.name}")
            except Exception:
                pass
        sp = settings_path()
        if sp.exists():
            z.write(sp, arcname="settings.json")
    return dest_zip
