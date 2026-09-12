"""Exercise every conversion engine on the sample files and render first pages for eyeballing."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402

from app.core.convert.base import ConvertOptions  # noqa: E402
from app.core.convert.registry import registry  # noqa: E402
from tests.make_samples import make_all  # noqa: E402

OUT = ROOT / "tests" / "out"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    files = make_all()
    reg = registry()
    print("engines:")
    for eid, info in reg.probe_all(force=True).items():
        print(f"  {eid:12s} available={info.available!s:5s} kinds={sorted(info.kinds)} {info.detail}")
    forced = sys.argv[1] if len(sys.argv) > 1 else None
    failures = 0
    with reg.batch():
        for key, src in files.items():
            for engine in ([forced] if forced else [None, "builtin"]):
                if engine == "builtin" and src.suffix.lower() in (".jpg", ".png", ".md", ".txt", ".pdf"):
                    continue
                dst = OUT / f"{src.stem}.{engine or 'auto'}.pdf"
                t0 = time.time()
                try:
                    res = reg.convert(src, dst, ConvertOptions(), use_cache=False, forced_engine=engine,
                                      progress=lambda f, m: None)
                    doc = pymupdf.open(str(res.pdf_path))
                    sizes = [(round(p.rect.width), round(p.rect.height)) for p in doc]
                    imgs = sum(len(p.get_images()) for p in doc)
                    pix = doc[0].get_pixmap(dpi=40)
                    pix.save(str(OUT / f"{src.stem}.{engine or 'auto'}.png"))
                    print(f"OK   {key:8s} via {res.engine_name:16s} pages={res.pages} sizes={sizes[:3]} images={imgs} "
                          f"{time.time() - t0:.1f}s warn={res.warnings}")
                    doc.close()
                except Exception as e:  # noqa: BLE001
                    failures += 1
                    print(f"FAIL {key:8s} engine={engine}: {type(e).__name__}: {e}")
    print("failures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
