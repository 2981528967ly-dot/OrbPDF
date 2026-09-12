"""End-to-end: convert mixed sources, merge with TOC + dividers + page numbers, verify links & bookmarks."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402

from app.core.convert.registry import registry  # noqa: E402
from app.core.fileinfo import KIND_BLANK, KIND_DIVIDER, kind_of  # noqa: E402
from app.core.pdf.compress import CompressSettings, compress_pdf  # noqa: E402
from app.core.pdf.info import parse_page_range  # noqa: E402
from app.core.pdf.merge import MergeOptions, MergeSource, merge  # noqa: E402
from app.core.pdf.numbering import stamp_page_numbers  # noqa: E402
from app.core.pdf.pages import PageRef, build_document, split_every  # noqa: E402
from app.core.pdf.security import decrypt_pdf, encrypt_pdf  # noqa: E402
from app.core.pdf.watermark import WatermarkSpec, apply_watermark  # noqa: E402
from tests.make_samples import make_all  # noqa: E402

OUT = ROOT / "tests" / "out"


def main() -> int:
    import shutil
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(exist_ok=True)
    files = make_all()
    reg = registry()
    order = [
        ("高铁票 北京→上海", files["jpg"], None),
        ("酒店住宿 3 晚", files["docx"], None),
        ("出租车 ×4", files["jpg_exif"], None),
        ("餐饮电子发票", files["pdf"], "1-3"),
    ]
    sources: list[MergeSource] = []
    with reg.batch():
        for name, path, rng in order:
            res = reg.convert(path, forced_engine="builtin" if kind_of(path) != "pdf" else None)
            idx = parse_page_range(rng, res.pages) if rng else None
            sources.append(MergeSource(name, kind_of(path), res.pdf_path, idx, source_name=path.name))
    sources.insert(2, MergeSource("附录：空白页", KIND_BLANK))
    sources.append(MergeSource("说明部分", KIND_DIVIDER))
    for style in ("simple", "formal", "table"):
        opts = MergeOptions(toc_title="2026年8月 出差报销凭证", toc_style=style, dividers=(style == "table"),
                            page_numbers=True, toc_show_source=(style == "table"))
        res = merge(sources, opts, OUT / f"merged_{style}.pdf")
        doc = pymupdf.open(str(res.path))
        links = doc[0].get_links()
        toc = doc.get_toc()
        print(f"{style:7s} pages={res.pages} size={res.size_bytes} entries={res.entries} links={[(l['page']) for l in links]} toc={[(t[0], t[1], t[2]) for t in toc][:8]} warn={res.warnings}")
        assert len(links) == len(res.entries), "one link per entry"
        for (name, start), link in zip(res.entries, links):
            assert link["page"] == start, f"link target mismatch {name}: {link['page']} != {start}"
        doc[0].get_pixmap(dpi=60).save(str(OUT / f"merged_{style}_toc.png"))
        doc.close()
    # pages module
    src = pymupdf.open(str(OUT / "merged_simple.pdf"))
    refs = [PageRef("a", i, 90 if i == 1 else 0) for i in range(src.page_count) if i != 2]
    edited = build_document(refs, {"a": src})
    assert edited.page_count == src.page_count - 1 and edited[1].rotation == 90
    edited.save(str(OUT / "edited.pdf"))
    parts = split_every(src, 3, OUT / "split", "merged")
    print("split parts:", [p.name for p in parts])
    src.close()
    # compress
    r = compress_pdf(OUT / "merged_simple.pdf", OUT / "merged_simple_压缩.pdf", CompressSettings.preset("standard"))
    print(f"compress {r.before} -> {r.after} ({r.ratio:.0%}) kept={r.kept_original}")
    # watermark + numbering + encryption
    d = pymupdf.open(str(OUT / "merged_simple.pdf"))
    apply_watermark(d, WatermarkSpec(text="OrbPDF 内部资料", tile=True))
    stamp_page_numbers(d, "第 {n} 页 / 共 {N} 页", "bottom-right")
    d.save(str(OUT / "watermarked.pdf"))
    d[1].get_pixmap(dpi=50).save(str(OUT / "watermarked_p2.png"))
    d.close()
    enc = encrypt_pdf(OUT / "watermarked.pdf", OUT / "encrypted.pdf", user_password="1234")
    assert pymupdf.open(str(enc)).needs_pass
    dec = decrypt_pdf(enc, OUT / "decrypted.pdf", "1234")
    assert not pymupdf.open(str(dec)).needs_pass
    print("security OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
