"""JSON settings with defaults. Missing or corrupt file -> defaults."""
from __future__ import annotations

import json
import threading
from copy import deepcopy
from typing import Any

from .paths import settings_path

DEFAULTS: dict[str, Any] = {
    "theme": "dark",                # dark | light
    "egg_mode": False,              # Defect terminology
    "output_mode": "source",        # source | custom | ask
    "output_dir": "",
    "open_after": True,
    # conversion engines
    "prefer_office": True,
    "engine_order": ["msoffice", "wps", "libreoffice", "builtin"],
    "engine_timeout": 120,
    "fallback_on_error": True,
    # images
    "image_fit": "bleed",           # bleed | a4 | original
    "image_max_side": 0,            # px, 0 = keep
    "jpeg_quality": 90,
    # merge defaults
    "toc_enabled": True,
    "toc_style": "simple",          # simple | formal | table
    "toc_show_kind": True,
    "toc_show_source": False,
    "bookmarks": True,
    "dividers": False,
    "page_numbers": False,
    "page_size_mode": "keep",       # keep | a4
    # compress defaults
    "compress_preset": "standard",
    # window
    "window_geometry": None,
    "window_maximized": False,
    "recent_files": [],
    "sidebar_compact": False,
}


class Settings:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, Any] = deepcopy(DEFAULTS)
        self.load()

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        p = settings_path()
        try:
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    with self._lock:
                        for k, v in raw.items():
                            if k in DEFAULTS:
                                self._data[k] = v
        except Exception:
            # corrupt file -> keep defaults, overwrite on next save
            pass

    def save(self) -> None:
        p = settings_path()
        try:
            tmp = p.with_suffix(".json.tmp")
            with self._lock:
                payload = json.dumps(self._data, ensure_ascii=False, indent=2)
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            tmp.replace(p)
        except Exception:
            pass

    # -- access ------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return deepcopy(self._data.get(key, DEFAULTS.get(key, default)))

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with self._lock:
            self._data[key] = value
        if save:
            self.save()

    def update(self, **kv: Any) -> None:
        with self._lock:
            self._data.update(kv)
        self.save()

    def reset(self) -> None:
        with self._lock:
            self._data = deepcopy(DEFAULTS)
        self.save()

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data)


_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
