"""Microsoft Office / WPS Office automation through COM (Windows only).

The same class drives both suites; only the ProgIDs differ. Instances are created lazily on the
calling thread, reused for a batch, and quit in ``end_batch``. A watchdog kills the process if a
single conversion exceeds the timeout, after which the registry falls back to the next engine.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from ..fileinfo import KIND_WORD, KIND_PPT, KIND_EXCEL, kind_of
from ..paths import new_temp_file
from .base import ConvertError, ConvertOptions, Engine, EngineInfo, EngineUnavailable, ProgressFn, CancelFn, report

LOG = logging.getLogger("orbpdf.com")

_WD_PDF = 17
_PP_PDF = 32
_XL_PDF = 0

MS_PROGIDS = {KIND_WORD: "Word.Application", KIND_PPT: "PowerPoint.Application", KIND_EXCEL: "Excel.Application"}
WPS_PROGIDS = {KIND_WORD: "KWPS.Application", KIND_PPT: "KWPP.Application", KIND_EXCEL: "KET.Application"}
_PROCESS_NAMES = {
    "Word.Application": "WINWORD.EXE", "PowerPoint.Application": "POWERPNT.EXE", "Excel.Application": "EXCEL.EXE",
    "KWPS.Application": "wps.exe", "KWPP.Application": "wpp.exe", "KET.Application": "et.exe",
}
_LABELS = {KIND_WORD: "Word", KIND_PPT: "PowerPoint", KIND_EXCEL: "Excel"}
_WPS_LABELS = {KIND_WORD: "WPS 文字", KIND_PPT: "WPS 演示", KIND_EXCEL: "WPS 表格"}


def _progid_registered(progid: str) -> tuple[bool, str]:
    if os.name != "nt":
        return False, ""
    try:
        import winreg  # noqa: WPS433
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid) as k:
            ver = ""
            try:
                with winreg.OpenKey(k, "CurVer") as cv:
                    cur, _ = winreg.QueryValueEx(cv, "")
                    ver = str(cur).rsplit(".", 1)[-1]
            except OSError:
                pass
            return True, ver
    except OSError:
        return False, ""


def _pids(image: str) -> set[int]:
    """PIDs of running processes whose exe name matches (Toolhelp snapshot; no console encoding issues)."""
    if os.name != "nt" or not image:
        return set()
    try:
        import ctypes  # noqa: WPS433
        from ctypes import wintypes  # noqa: WPS433

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
            ]

        k32 = ctypes.windll.kernel32
        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
        if snap == -1 or snap == 0xFFFFFFFFFFFFFFFF:
            return set()
        pids: set[int] = set()
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                if entry.szExeFile.lower() == image.lower():
                    pids.add(int(entry.th32ProcessID))
                ok = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        return pids
    except Exception:
        return set()


def _kill(pid: int) -> None:
    try:
        import ctypes  # noqa: WPS433
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x0001, False, int(pid))  # PROCESS_TERMINATE
        if h:
            try:
                k32.TerminateProcess(h, 1)
            finally:
                k32.CloseHandle(h)
    except Exception:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, creationflags=0x08000000, timeout=10)
        except Exception:
            pass


class OfficeComEngine(Engine):
    kinds = frozenset({KIND_WORD, KIND_PPT, KIND_EXCEL})
    fidelity = "high"

    def __init__(self, engine_id: str, name: str, progids: dict[str, str], labels: dict[str, str], verified: bool = True) -> None:
        self.id = engine_id
        self.name = name
        self.progids = progids
        self.labels = labels
        self.verified = verified
        self._apps: dict[tuple[int, str], tuple[object, int | None]] = {}
        self._lock = threading.RLock()
        self._probe_cache: EngineInfo | None = None

    # -- detection -------------------------------------------------------
    def probe(self, force: bool = False) -> EngineInfo:
        if self._probe_cache is not None and not force:
            return self._probe_cache
        available_kinds: set[str] = set()
        details = []
        for kind, progid in self.progids.items():
            ok, ver = _progid_registered(progid)
            if ok:
                available_kinds.add(kind)
                details.append(f"{self.labels[kind]}{(' ' + ver) if ver else ''}")
        info = EngineInfo(self.id, self.name, bool(available_kinds), " · ".join(details) if details else "未安装",
                          available_kinds, self.fidelity, self.verified)
        self._probe_cache = info
        return info

    def supports(self, src: Path) -> bool:
        k = kind_of(src)
        return k in self.probe().kinds

    # -- lifecycle -------------------------------------------------------
    def end_batch(self) -> None:
        with self._lock:
            apps = list(self._apps.items())
            self._apps.clear()
        for (_tid, progid), (app, pid) in apps:
            try:
                app.Quit()
            except Exception:
                pass
            time.sleep(0.2)
            if pid is not None and pid in _pids(_PROCESS_NAMES.get(progid, "")):
                _kill(pid)

    def _get_app(self, progid: str):
        key = (threading.get_ident(), progid)
        with self._lock:
            if key in self._apps:
                return self._apps[key]
        import pythoncom  # noqa: WPS433
        import win32com.client  # noqa: WPS433
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
        image = _PROCESS_NAMES.get(progid, "")
        before = _pids(image) if image else set()
        try:
            app = win32com.client.DispatchEx(progid)
        except Exception as e:
            raise EngineUnavailable(f"无法启动 {progid}：{e}") from e
        after = _pids(image) if image else set()
        new = list(after - before)
        pid = new[0] if len(new) == 1 else None
        try:
            if progid.startswith(("Word", "KWPS")):
                app.Visible = False
                app.DisplayAlerts = 0
                try:
                    app.AutomationSecurity = 3   # disable macros
                except Exception:
                    pass
            elif progid.startswith(("Excel", "KET")):
                app.Visible = False
                app.DisplayAlerts = False
                try:
                    app.AutomationSecurity = 3
                except Exception:
                    pass
            elif progid.startswith(("PowerPoint", "KWPP")):
                try:
                    app.DisplayAlerts = 1  # ppAlertsNone
                except Exception:
                    pass
        except Exception:
            pass
        with self._lock:
            self._apps[key] = (app, pid)
        return app, pid

    def _drop_app(self, progid: str) -> None:
        key = (threading.get_ident(), progid)
        with self._lock:
            entry = self._apps.pop(key, None)
        if entry:
            app, pid = entry
            try:
                app.Quit()
            except Exception:
                pass
            if pid is not None:
                _kill(pid)

    # -- staging -----------------------------------------------------------
    @staticmethod
    def _stage(src: Path) -> Path:
        """Plain stream copy into the session temp dir. Drops the Zone.Identifier stream (so Office does not
        open the file in Protected View, which stalls automation) and sidesteps long or unusual paths."""
        tmp = new_temp_file(Path(src).suffix.lower() or ".bin", "src")
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            shutil.copyfileobj(fi, fo, 1024 * 1024)
        return tmp

    # -- conversion ------------------------------------------------------
    def convert(self, src: Path, dst: Path, opts: ConvertOptions, progress: ProgressFn = None, cancel: CancelFn = None) -> list[str]:
        kind = kind_of(src)
        if kind not in self.progids:
            raise EngineUnavailable("类型不支持")
        progid = self.progids[kind]
        if not _progid_registered(progid)[0]:
            raise EngineUnavailable(f"{self.labels[kind]} 未安装")
        report(progress, 0.05, f"启动 {self.labels[kind]}")
        app, pid = self._get_app(progid)
        temp_copy: Path | None = None
        try:
            temp_copy = self._stage(Path(src))
            src_use = temp_copy
        except OSError:
            src_use = Path(src)
        dst_tmp = Path(str(dst) + ".part.pdf")
        dst_tmp.unlink(missing_ok=True)
        timed_out = threading.Event()

        def watchdog():
            timed_out.set()
            LOG.warning("COM timeout, killing %s pid=%s", progid, pid)
            if pid is not None:
                _kill(pid)
            self._drop_app(progid)

        timer = threading.Timer(max(10, opts.timeout), watchdog)
        timer.daemon = True
        timer.start()
        try:
            report(progress, 0.2, f"{self.labels[kind]} 导出 PDF")
            if kind == KIND_WORD:
                self._word(app, src_use, dst_tmp)
            elif kind == KIND_PPT:
                self._ppt(app, src_use, dst_tmp)
            else:
                self._excel(app, src_use, dst_tmp)
        except Exception as e:
            if timed_out.is_set():
                raise ConvertError(f"{self.labels[kind]} 超过 {opts.timeout} 秒未响应，已强制结束") from e
            LOG.warning("COM conversion failed via %s: %s", progid, e)
            self._drop_app(progid)
            raise ConvertError(f"{self.labels[kind]} 导出失败：{_short(e)}") from e
        finally:
            timer.cancel()
            if temp_copy:
                try:
                    temp_copy.unlink(missing_ok=True)
                except OSError:
                    pass
        if not dst_tmp.exists() or dst_tmp.stat().st_size == 0:
            raise ConvertError(f"{self.labels[kind]} 没有生成 PDF")
        dst_tmp.replace(dst)
        report(progress, 0.95, "完成")
        return []

    # -- PDF -> Word (Word 2013+ / WPS can open PDFs) ---------------------
    def pdf_to_docx(self, src: Path, dst: Path, timeout: int = 600, progress: ProgressFn = None) -> None:
        progid = self.progids.get(KIND_WORD)
        if not progid or not _progid_registered(progid)[0]:
            raise EngineUnavailable("需要本机安装 Microsoft Word 或 WPS 文字")
        report(progress, 0.05, "启动 Word")
        app, pid = self._get_app(progid)
        try:
            app.Options.ConfirmConversions = False
        except Exception:
            pass
        staged = self._stage(Path(src))
        dst_tmp = Path(str(dst) + ".part.docx")
        dst_tmp.unlink(missing_ok=True)
        timed_out = threading.Event()

        def watchdog():
            timed_out.set()
            LOG.warning("PDF->Word timeout, killing %s pid=%s", progid, pid)
            if pid is not None:
                _kill(pid)
            self._drop_app(progid)

        timer = threading.Timer(max(60, timeout), watchdog)
        timer.daemon = True
        timer.start()
        dismisser = _PromptDismisser(pid, time.time() + max(60, timeout))
        try:
            # Word must be *visible* for its PDF prompt to be dismissable; park the window off-screen.
            try:
                app.Visible = True
                app.WindowState = 0
                app.Left = -4000
                app.Top = -4000
            except Exception:
                pass
            dismisser.start()
            report(progress, 0.15, "Word 正在识别 PDF 版面，大文件可能要几分钟…")
            # FileName, ConfirmConversions=False, ReadOnly=False, AddToRecentFiles=False
            doc = app.Documents.Open(str(staged), False, False, False)
            dismisser.stop_flag.set()
            try:
                report(progress, 0.7, "另存为 Word 文档")
                doc.SaveAs2(str(dst_tmp), 16)   # wdFormatXMLDocument
            finally:
                try:
                    doc.Close(False)
                except Exception:
                    pass
                try:
                    app.Visible = False
                except Exception:
                    pass
        except Exception as e:
            dismisser.stop_flag.set()
            if timed_out.is_set():
                raise ConvertError(f"Word 超过 {timeout // 60} 分钟未完成，已强制结束") from e
            self._drop_app(progid)
            raise ConvertError(f"Word 转换失败：{_short(e)}") from e
        finally:
            timer.cancel()
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass
        if not dst_tmp.exists() or dst_tmp.stat().st_size == 0:
            raise ConvertError("Word 没有生成文档")
        dst_tmp.replace(dst)
        report(progress, 0.95, "完成")

    # -- per application -------------------------------------------------
    @staticmethod
    def _word(app, src: Path, dst: Path) -> None:
        doc = app.Documents.Open(str(src), False, True, False)  # ConfirmConversions, ReadOnly, AddToRecentFiles
        try:
            try:
                doc.ExportAsFixedFormat(str(dst), _WD_PDF, False, 0, 0, 0, 0, 0, True, True, 1)
            except Exception:
                try:
                    doc.ExportAsFixedFormat(str(dst), _WD_PDF)
                except Exception:
                    doc.SaveAs2(str(dst), _WD_PDF)
        finally:
            try:
                doc.Close(False)
            except Exception:
                pass

    @staticmethod
    def _ppt(app, src: Path, dst: Path) -> None:
        pres = app.Presentations.Open(str(src), True, False, False)  # ReadOnly, Untitled, WithWindow
        try:
            try:
                pres.SaveAs(str(dst), _PP_PDF)
            except Exception:
                pres.ExportAsFixedFormat(str(dst), 2)
        finally:
            try:
                pres.Close()
            except Exception:
                pass

    @staticmethod
    def _excel(app, src: Path, dst: Path) -> None:
        wb = app.Workbooks.Open(str(src), 0, True)  # UpdateLinks, ReadOnly
        try:
            wb.ExportAsFixedFormat(_XL_PDF, str(dst))
        finally:
            try:
                wb.Close(False)
            except Exception:
                pass


# -- Word's PDF prompt ----------------------------------------------------------------------------
# Word 2013+ shows "Word will now convert your PDF…" (an NUIDialog) even under automation with
# DisplayAlerts=0. With the app hidden the dialog is never painted and Open() blocks forever.
# Workaround: keep Word visible but parked off-screen, watch for the dialog and press Enter once.

def _word_dialogs(pid: int) -> list[int]:
    if os.name != "nt" or not pid:
        return []
    try:
        import ctypes  # noqa: WPS433
        from ctypes import wintypes  # noqa: WPS433
        u32 = ctypes.windll.user32
        proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        found: list[int] = []

        def cb(h, _):
            owner = wintypes.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(owner))
            if owner.value == pid and u32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(64)
                u32.GetClassNameW(h, buf, 64)
                if buf.value in ("NUIDialog", "#32770"):
                    found.append(int(h))
            return True

        u32.EnumWindows(proc(cb), 0)
        return found
    except Exception:
        return []


def _press_enter(hwnd: int, pid: int) -> bool:
    """Bring the dialog forward (off-screen) and send Enter. Only presses when a window of ``pid`` is in front."""
    try:
        import ctypes  # noqa: WPS433
        from ctypes import wintypes  # noqa: WPS433
        u32 = ctypes.windll.user32
        u32.SetWindowPos(hwnd, 0, -4000, -4000, 0, 0, 0x0001 | 0x0004 | 0x0010)  # NOSIZE | NOZORDER | NOACTIVATE
        u32.ShowWindow(hwnd, 5)
        u32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        fg = u32.GetForegroundWindow()
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(fg, ctypes.byref(owner))
        if owner.value != pid:
            u32.PostMessageW(hwnd, 0x0100, 0x0D, 0)
            u32.PostMessageW(hwnd, 0x0101, 0x0D, 0)
            return False
        u32.keybd_event(0x0D, 0, 0, 0)
        u32.keybd_event(0x0D, 0, 2, 0)
        return True
    except Exception:
        return False


class _PromptDismisser(threading.Thread):
    """Polls for Word's modal prompt and presses Enter exactly once (a later dialog is Word's own progress box)."""

    def __init__(self, pid: int | None, deadline: float) -> None:
        super().__init__(daemon=True)
        self.pid = pid
        self.deadline = deadline
        self.stop_flag = threading.Event()
        self.dismissed = False

    def run(self) -> None:
        attempts = 0
        while not self.stop_flag.is_set() and time.time() < self.deadline and not self.dismissed and attempts < 8:
            if self.pid:
                for h in _word_dialogs(self.pid):
                    attempts += 1
                    if _press_enter(h, self.pid):
                        self.dismissed = True
                        LOG.info("dismissed Word PDF prompt")
                        break
                    time.sleep(0.6)
            self.stop_flag.wait(0.3)


def _short(e: Exception) -> str:
    s = str(e)
    if len(s) > 160:
        s = s[:160] + "…"
    return s.replace("\n", " ")


def make_ms_office() -> OfficeComEngine:
    return OfficeComEngine("msoffice", "Microsoft Office", MS_PROGIDS, _LABELS, verified=True)


def make_wps() -> OfficeComEngine:
    return OfficeComEngine("wps", "WPS Office", WPS_PROGIDS, _WPS_LABELS, verified=False)
