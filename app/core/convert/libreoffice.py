"""LibreOffice headless conversion (optional engine, only if soffice.exe is installed)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..fileinfo import KIND_WORD, KIND_PPT, KIND_EXCEL
from ..paths import session_dir
from .base import ConvertError, ConvertOptions, Engine, EngineInfo, EngineUnavailable, ProgressFn, CancelFn, report


def find_soffice() -> Path | None:
    candidates = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "LibreOffice" / "program" / "soffice.exe")
    exe = shutil.which("soffice")
    if exe:
        candidates.append(Path(exe))
    for c in candidates:
        if c.exists():
            return c
    return None


class LibreOfficeEngine(Engine):
    id = "libreoffice"
    name = "LibreOffice"
    kinds = frozenset({KIND_WORD, KIND_PPT, KIND_EXCEL})
    fidelity = "high"
    verified = False

    def __init__(self) -> None:
        self._exe: Path | None = None
        self._probed = False

    def probe(self, force: bool = False) -> EngineInfo:
        if not self._probed or force:
            self._exe = find_soffice()
            self._probed = True
        ok = self._exe is not None
        return EngineInfo(self.id, self.name, ok, str(self._exe) if ok else "未找到 soffice.exe", set(self.kinds) if ok else set(), self.fidelity, self.verified)

    def supports(self, src: Path) -> bool:
        return self.probe().available and super().supports(src)

    def convert(self, src: Path, dst: Path, opts: ConvertOptions, progress: ProgressFn = None, cancel: CancelFn = None) -> list[str]:
        exe = self._exe or find_soffice()
        if not exe:
            raise EngineUnavailable("LibreOffice 未安装")
        outdir = Path(tempfile.mkdtemp(prefix="lo-", dir=str(session_dir())))
        profile = session_dir() / "lo-profile"
        profile.mkdir(exist_ok=True)
        cmd = [str(exe), "--headless", "--norestore", "--nolockcheck", f"-env:UserInstallation={profile.as_uri()}",
               "--convert-to", "pdf", "--outdir", str(outdir), str(src)]
        report(progress, 0.2, "LibreOffice 转换中")
        try:
            subprocess.run(cmd, capture_output=True, timeout=max(30, opts.timeout), creationflags=0x08000000)
        except subprocess.TimeoutExpired as e:
            raise ConvertError(f"LibreOffice 超过 {opts.timeout} 秒未完成") from e
        except Exception as e:
            raise ConvertError(f"LibreOffice 启动失败：{e}") from e
        produced = outdir / (src.stem + ".pdf")
        if not produced.exists():
            pdfs = list(outdir.glob("*.pdf"))
            if not pdfs:
                raise ConvertError("LibreOffice 没有生成 PDF")
            produced = pdfs[0]
        shutil.move(str(produced), str(dst))
        shutil.rmtree(outdir, ignore_errors=True)
        return []
