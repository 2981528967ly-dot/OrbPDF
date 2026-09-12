"""One-shot build: regenerate icon/splash, run PyInstaller, report the exe size.

Usage (from the project root, inside the venv):
    python build/build.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
WORK = ROOT / "build" / "work"


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from build.make_assets import make_icon, make_splash
    make_icon()
    make_splash()
    shutil.rmtree(WORK, ignore_errors=True)
    exe = DIST / "OrbPDF.exe"
    if exe.exists():
        try:
            exe.unlink()
        except OSError:
            print("dist/OrbPDF.exe is in use; close it first")
            return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST), "--workpath", str(WORK),
           str(ROOT / "build" / "orbpdf.spec")]
    t0 = time.time()
    print(" ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        return rc
    if exe.exists():
        print(f"built {exe} ({exe.stat().st_size / 1e6:.1f} MB) in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
