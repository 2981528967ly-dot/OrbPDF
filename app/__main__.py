"""python -m app  /  PyInstaller entry."""
from __future__ import annotations

import multiprocessing
import sys


def _run() -> int:
    if getattr(sys, "frozen", False):
        # frozen: make ``import app...`` resolvable from the bundle root
        import os
        base = getattr(sys, "_MEIPASS", None)
        if base and base not in sys.path:
            sys.path.insert(0, base)
    from app.main import main
    return main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(_run())
