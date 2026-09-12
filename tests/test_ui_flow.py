"""Offscreen end-to-end UI flow for the three workspaces: 生成 (canvas), 修改 (editor + steps), 转换.

Run:  .venv/Scripts/python tests/test_ui_flow.py
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import pymupdf  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.settings import settings  # noqa: E402
from app.core.tasks.runner import runner  # noqa: E402
from app.ui import theme  # noqa: E402
from tests.make_samples import make_all  # noqa: E402

OUT = ROOT / "tests" / "out_ui"


def pump(seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.02)


def wait_until(cond, timeout: float, what: str) -> None:
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting for {what}")


def wait_idle(page, timeout: float = 120) -> None:
    wait_until(lambda: not runner().busy and getattr(page, "_task_id", None) is None and getattr(page, "_pending_export", None) is None,
               timeout, "task")


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    files = make_all()
    app = QApplication([])
    theme.set_theme("dark")
    app.setStyleSheet(theme.build_qss(theme.current()))
    from app.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1240, 800)
    win.show()
    pump(0.3)
    failures: list[str] = []

    # ---- 生成: canvas + merge ------------------------------------------------------
    make = win.pages["make"]
    make.add_files([files["jpg"], files["docx"], files["jpg_exif"], files["pdf"]])
    make.model.add_special("divider", None, "附录")
    make.title_edit.setText("UI 流程测试")
    make._set_dir(OUT)
    make.filename_edit.setText("合并结果")
    make._filename_touched = True
    make.open_after.setChecked(False)
    wait_until(lambda: make.model.count_status("converting") == 0 and make.model.count_status("pending") == 0, 180, "pre-conversion")
    errs = [it for it in make.model.items if it.status == "error"]
    if errs:
        failures.append("pre-conversion errors: " + "; ".join(f"{it.display_name}: {it.error}" for it in errs))
    ids = [it.id for it in make.model.items]
    # interactions through the canvas API
    canvas = make.canvas
    make.model.rename(ids[0], "高铁票")
    make.model.set_range(ids[3], "1-2")
    make.model.rotate(ids[2], 90)
    canvas.reorder_requested.emit(ids[0], 2)           # wire drop / rewire path
    pump(0.4)
    order = [it.display_name for it in make.model.items]
    print("order after reorder:", order)
    if order[1] != "高铁票":
        failures.append(f"reorder failed: {order}")
    canvas.tidy()
    pump(0.4)
    node = canvas.file_nodes[0]
    # simulate dragging node 0 onto the wire before the last file node (gap = len-1)
    gap_target = len(make.model.items) - 1
    wire = canvas.wires[gap_target]
    canvas.node_dragging(node, wire.mid)
    canvas.node_dropped(node, wire.mid)
    pump(0.3)
    print("order after drag-onto-wire:", [it.display_name for it in make.model.items])
    if len(canvas.wires) != len(make.model.items) + 1:
        failures.append("wire count mismatch")
    make.export()
    wait_idle(make, 120)
    pump(1.6)   # let the paper-stack animation finish
    merged = OUT / "合并结果.pdf"
    if not merged.exists():
        failures.append("merge export missing")
    else:
        d = pymupdf.open(str(merged))
        links = d[0].get_links()
        toc = d.get_toc()
        rot_pages = [p.rotation for p in d]
        print(f"merge: pages={d.page_count} links={len(links)} toc={len(toc)} rotations={rot_pages}")
        if d.page_count < 6 or len(links) < 4 or 90 not in rot_pages:
            failures.append(f"merge output unexpected: pages={d.page_count} links={len(links)} rot={rot_pages}")
        d.close()
    if canvas.start._preview is None:
        failures.append("toc preview not rendered on start node")
    # each mode
    make.mode.set_value("each", emit=True)
    pump(0.2)
    make.export()
    wait_idle(make, 120)
    each = [p for p in OUT.glob("*.pdf") if p.name != "合并结果.pdf"]
    print("each-mode outputs:", [p.name for p in each])
    if len(each) < 4:
        failures.append("each-mode outputs missing")
    make.mode.set_value("merge", emit=True)

    # ---- 修改: pages + steps ---------------------------------------------------------
    edit = win.pages["edit"]
    edit.open_pdf(merged)
    pump(0.6)
    d0 = edit.current
    n0 = len(d0.refs)
    edit.grid.item(1).setSelected(True)
    edit.delete_selected()
    edit.grid.item(0).setSelected(True)
    edit.rotate(90)
    edit.undo()
    edit.redo()
    pump(0.3)
    edit._render_preview()
    if edit.preview.pixmap().isNull():
        failures.append("edit preview not rendered")
    edit.st_wm.switch.setChecked(True)
    edit.wm_text.setText("测试水印")
    edit.st_pn.switch.setChecked(True)
    edit.st_compress.switch.setChecked(True)
    edit.st_enc.switch.setChecked(True)
    edit.enc_user.setText("1234")
    pump(0.4)
    edit._render_preview()
    target = OUT / "修改结果.pdf"
    edit._save_to(target, overwrite=False)
    wait_idle(edit, 180)
    if not target.exists():
        failures.append("edit save missing")
    else:
        dd = pymupdf.open(str(target))
        ok_pw = dd.needs_pass
        if ok_pw:
            dd.authenticate("1234")
        print(f"edit save: pages={dd.page_count} (from {n0}) encrypted={ok_pw} rot0={dd[0].rotation}")
        if dd.page_count != n0 - 1 or not ok_pw or dd[0].rotation != 90:
            failures.append("edit save content unexpected")
        dd.close()
    edit.split("every", 2)
    wait_idle(edit, 60)
    parts = list((merged.parent / "合并结果_拆分").glob("*.pdf"))
    print("split parts:", len(parts))
    if not parts:
        failures.append("split missing")
    # second doc + apply to all
    edit.open_pdf(files["pdf"])
    pump(0.3)
    if len(edit.docs) != 2 or edit.apply_all.isHidden():
        failures.append("multi-doc tabs missing")

    # ---- 转换 -------------------------------------------------------------------------
    exp = win.pages["export"]
    exp.add_files([merged])
    exp.set_mode("png")
    exp.dpi.setValue(50)
    exp.output.rb_custom.setChecked(True)
    exp.output.dir_edit.setText(str(OUT))
    exp.output.open_after.setChecked(False)
    exp.run()
    wait_idle(exp, 120)
    pngs = list((OUT / "合并结果").glob("*.png")) if (OUT / "合并结果").exists() else []
    print("pdf->png:", len(pngs))
    if not pngs:
        failures.append("pdf->images missing")

    # ---- theme / egg / settings / screenshots ---------------------------------------------
    win.show_page("make", animate=False)
    pump(0.3)
    win.grab().save(str(OUT / "make.png"))
    win.apply_theme("light")
    pump(0.3)
    win.grab().save(str(OUT / "make_light.png"))
    win.apply_theme("dark")
    from app.ui.strings import strings
    strings().set_egg(True)
    pump(0.2)
    strings().set_egg(False)
    win.show_page("edit", animate=False)
    pump(0.3)
    win.grab().save(str(OUT / "edit.png"))
    win.show_page("settings", animate=False)
    pump(0.3)
    win.close()
    pump(0.3)
    print("FAILURES:", failures if failures else "none")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
