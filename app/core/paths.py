"""Where OrbPDF keeps things at runtime.

Rules:
* the directory containing the exe is never written to;
* settings/logs live under %APPDATA%\\OrbPDF;
* caches live under %TEMP%\\OrbPDF\\session-<pid> and are removed on exit.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

APP_NAME = "OrbPDF"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Directory that contains the ``assets`` folder (PyInstaller temp dir when frozen)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "app"
    return Path(__file__).resolve().parents[1]


def asset_path(*parts: str) -> Path:
    return app_root().joinpath("assets", *parts)


def exe_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def appdata_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = appdata_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_path() -> Path:
    return appdata_dir() / "settings.json"


def temp_base() -> Path:
    p = Path(tempfile.gettempdir()) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


_SESSION_DIR: Path | None = None


def session_dir() -> Path:
    """Per-process scratch directory (conversion cache, intermediate PDFs)."""
    global _SESSION_DIR
    if _SESSION_DIR is None:
        _SESSION_DIR = temp_base() / f"session-{os.getpid()}"
        _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return _SESSION_DIR


def cache_dir() -> Path:
    p = session_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_temp_file(suffix: str = ".pdf", prefix: str = "tmp") -> Path:
    d = session_dir() / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{prefix}-{int(time.time() * 1000)}-{os.urandom(3).hex()}{suffix}"


def cleanup_session(remove_stale_days: float = 1.0) -> None:
    """Remove this session's temp dir and any stale session dirs left by crashed runs."""
    try:
        if _SESSION_DIR and _SESSION_DIR.exists():
            shutil.rmtree(_SESSION_DIR, ignore_errors=True)
    except Exception:
        pass
    try:
        now = time.time()
        for child in temp_base().iterdir():
            if child.is_dir() and child.name.startswith("session-"):
                try:
                    if now - child.stat().st_mtime > remove_stale_days * 86400:
                        shutil.rmtree(child, ignore_errors=True)
                except Exception:
                    pass
    except Exception:
        pass


def long_path(p: Path | str) -> str:
    """Return a Windows long-path safe string for APIs that choke on >260 chars."""
    s = str(Path(p).resolve())
    if os.name == "nt" and len(s) > 240 and not s.startswith("\\\\?\\"):
        if s.startswith("\\\\"):
            return "\\\\?\\UNC\\" + s[2:]
        return "\\\\?\\" + s
    return s
