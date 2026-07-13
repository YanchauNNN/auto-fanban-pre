"""
PDF导出引擎 - Word/Excel导出PDF

职责：
1. Word文档导出PDF（优先Office COM）
2. Excel文档导出PDF
3. PDF页数计算

依赖：
- pywin32: Windows COM自动化（优先）
- libreoffice: 兜底方案

测试要点：
- test_export_docx_to_pdf: Word导出PDF
- test_export_xlsx_to_pdf: Excel导出PDF
- test_count_pdf_pages: PDF页数计算
- test_fallback_to_libreoffice: COM失败时降级
"""

from __future__ import annotations

import contextlib
import gc
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from ..config import get_config
from ..interfaces import ExportError, IPDFExporter
from .office_automation import get_office_automation_limiter

_RPC_CALL_REJECTED = -2147418111
_FILE_NOT_FOUND_HRESULT = -2147024894
_MK_E_UNAVAILABLE = -2147221021


def _hidden_subprocess_kwargs() -> dict[str, int]:
    if os.name != "nt":
        return {}
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"creationflags": creationflags} if creationflags else {}


class PDFExporter(IPDFExporter):
    """PDF导出器实现"""

    def __init__(self, preferred_engine: str | None = None):
        config = get_config()
        self.preferred = preferred_engine or config.pdf_engine.preferred
        self.fallback = config.pdf_engine.fallback
        self.timeout = config.timeouts.pdf_export_sec

    def _should_use_libreoffice_fallback(self) -> bool:
        return self.fallback == "libreoffice"

    def export_docx_to_pdf(self, docx_path: Path, pdf_path: Path) -> None:
        """Word文档导出PDF"""
        if not docx_path.exists():
            raise ExportError(f"Word文档不存在: {docx_path}")

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        # 尝试Office COM
        if self.preferred == "office_com":
            try:
                self._export_docx_via_com(docx_path, pdf_path)
                return
            except Exception as e:
                if self._should_use_libreoffice_fallback():
                    pass  # 降级到fallback
                else:
                    raise ExportError(f"Word导出PDF失败: {e}") from e

        # 尝试LibreOffice
        if self._should_use_libreoffice_fallback() or self.preferred == "libreoffice":
            self._export_via_libreoffice(docx_path, pdf_path)
        else:
            raise ExportError("无可用的PDF导出引擎")

    def export_xlsx_to_pdf(self, xlsx_path: Path, pdf_path: Path) -> None:
        """Excel文档导出PDF"""
        if not xlsx_path.exists():
            raise ExportError(f"Excel文档不存在: {xlsx_path}")

        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        # 尝试Office COM
        if self.preferred == "office_com":
            com_error: Exception | None = None
            try:
                self._export_xlsx_via_com_with_process_recycle(xlsx_path, pdf_path)
                return
            except Exception as exc:
                com_error = exc
            assert com_error is not None
            if self._should_use_libreoffice_fallback():
                try:
                    self._export_via_libreoffice(xlsx_path, pdf_path)
                    return
                except Exception as fallback_error:
                    raise ExportError(
                        "Excel export failed via Office COM, and LibreOffice fallback also failed. "
                        f"COM error: {com_error}; fallback error: {fallback_error}"
                    ) from fallback_error
            else:
                raise ExportError(f"Excel导出PDF失败: {com_error}") from com_error
        elif self._should_use_libreoffice_fallback() or self.preferred == "libreoffice":
            self._export_via_libreoffice(xlsx_path, pdf_path)
        else:
            raise ExportError("无可用的PDF导出引擎")

    def count_pdf_pages(self, pdf_path: Path) -> int:
        """计算PDF页数"""
        if not pdf_path.exists():
            raise ExportError(f"PDF文件不存在: {pdf_path}")

        # 尝试使用PyPDF2
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(pdf_path))
            return len(reader.pages)
        except ImportError:
            pass

        # 兜底：通过字符串匹配
        try:
            with open(pdf_path, "rb") as f:
                content = f.read()
            count = content.count(b"/Type /Page")
            # 减去可能的/Type /Pages
            count -= content.count(b"/Type /Pages")
            return max(1, count)
        except Exception:
            return 1

    @staticmethod
    def _prepare_word_for_headless_run(word: object) -> None:
        word_app = cast(Any, word)
        word_app.Visible = False
        word_app.DisplayAlerts = 0
        with contextlib.suppress(Exception):
            options = getattr(word_app, "Options", None)
            if options is not None:
                cast(Any, options).SaveNormalPrompt = False

    @staticmethod
    def _mark_word_document_saved(doc: object | None) -> None:
        if doc is None:
            return
        with contextlib.suppress(Exception):
            cast(Any, doc).Saved = True

    @staticmethod
    def _mark_word_normal_template_saved(word: object | None) -> None:
        if word is None:
            return
        with contextlib.suppress(Exception):
            template = getattr(cast(Any, word), "NormalTemplate", None)
            if template is not None:
                cast(Any, template).Saved = True

    @staticmethod
    def _prepare_excel_for_headless_run(excel: object) -> None:
        excel_app = cast(Any, excel)
        property_updates: list[tuple[str, object, bool]] = [
            ("Visible", False, True),
            ("DisplayAlerts", False, True),
            ("AskToUpdateLinks", False, False),
            ("EnableEvents", False, False),
            ("ScreenUpdating", False, False),
            ("DisplayStatusBar", False, False),
            ("UserControl", False, False),
            ("Interactive", False, False),
            ("AutomationSecurity", 3, False),
        ]
        for attr_name, attr_value, required in property_updates:
            try:
                PDFExporter._retry_excel_com_call(
                    lambda attr_name=attr_name, attr_value=attr_value: setattr(excel_app, attr_name, attr_value),
                    f"Excel.{attr_name}=set",
                    retries=12,
                )
            except Exception:
                if required:
                    raise

    @staticmethod
    def _clear_windows_zone_identifier(path: Path) -> None:
        ads_path = str(path) + ":Zone.Identifier"
        with contextlib.suppress(OSError, FileNotFoundError):
            os.remove(ads_path)

    @staticmethod
    def _sanitize_excel_label(label: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_")
        return normalized or "workbook"

    @staticmethod
    def _is_call_rejected(exc: Exception) -> bool:
        with contextlib.suppress(Exception):
            if getattr(exc, "hresult", None) == _RPC_CALL_REJECTED:
                return True
        message = str(exc).lower()
        return ("被呼叫方拒绝接收呼叫" in str(exc)) or ("call was rejected by callee" in message)

    @staticmethod
    def _is_missing_excel_server_registration(exc: Exception) -> bool:
        with contextlib.suppress(Exception):
            if getattr(exc, "hresult", None) == _FILE_NOT_FOUND_HRESULT:
                return True
        message = str(exc).lower()
        return ("系统找不到指定的文件" in str(exc)) or ("cannot find the file" in message)

    @staticmethod
    def _snapshot_process_ids_by_image(image_name: str) -> set[int]:
        if os.name != "nt":
            return set()
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                check=False,
                **_hidden_subprocess_kwargs(),
            )
        except Exception:
            return set()
        if completed.returncode != 0:
            return set()

        pids: set[int] = set()
        stdout = completed.stdout or ""
        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.upper().startswith("INFO:"):
                continue
            parts = [part.strip().strip('"') for part in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                pids.add(int(parts[1]))
            except ValueError:
                continue
        return pids

    @staticmethod
    def _snapshot_process_command_lines_by_image(image_name: str) -> dict[int, str]:
        if os.name != "nt":
            return {}
        script = (
            "$items = Get-CimInstance Win32_Process -Filter "
            f"\"Name='{image_name}'\" "
            "| Select-Object ProcessId,CommandLine; "
            "$items | ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
                **_hidden_subprocess_kwargs(),
            )
        except Exception:
            return {}
        stdout = completed.stdout or ""
        if completed.returncode != 0 or not stdout.strip():
            return {}

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return {}
        if isinstance(payload, dict):
            rows = [payload]
        elif isinstance(payload, list):
            rows = payload
        else:
            return {}

        result: dict[int, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                pid = int(row.get("ProcessId") or 0)
            except (TypeError, ValueError):
                continue
            if pid > 0:
                result[pid] = str(row.get("CommandLine") or "")
        return result

    @staticmethod
    def _is_excel_automation_command_line(command_line: str) -> bool:
        normalized = str(command_line or "").lower()
        return (
            "excel.exe" in normalized
            and (
                "/automation" in normalized
                or "-embedding" in normalized
                or "/embedding" in normalized
            )
        )

    @classmethod
    def _terminate_stale_excel_automation_processes(cls, *, keep_pids: set[int] | None = None) -> None:
        keep = keep_pids or set()
        command_lines = cls._snapshot_process_command_lines_by_image("EXCEL.EXE")
        stale_pids = {
            pid
            for pid, command_line in command_lines.items()
            if pid not in keep and cls._is_excel_automation_command_line(command_line)
        }
        cls._terminate_process_ids(stale_pids)

    @classmethod
    def _terminate_new_processes(cls, image_name: str, baseline_pids: set[int]) -> None:
        current_pids = cls._snapshot_process_ids_by_image(image_name)
        cls._terminate_process_ids(current_pids - baseline_pids)

    @staticmethod
    def _terminate_process_ids(pids: set[int]) -> None:
        for pid in sorted(pids):
            with contextlib.suppress(Exception):
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=8,
                    check=False,
                    **_hidden_subprocess_kwargs(),
                )

    @staticmethod
    def _is_excel_operation_unavailable(exc: Exception) -> bool:
        with contextlib.suppress(Exception):
            if getattr(exc, "hresult", None) == _MK_E_UNAVAILABLE:
                return True
        message = str(exc).lower()
        return ("操作无法使用" in str(exc)) or ("operation unavailable" in message)

    @classmethod
    def _is_recoverable_excel_bootstrap_error(cls, exc: Exception) -> bool:
        if (
            cls._is_missing_excel_server_registration(exc)
            or cls._is_call_rejected(exc)
            or cls._is_excel_operation_unavailable(exc)
        ):
            return True
        message = str(exc).lower()
        return (
            "excel.workbooks unavailable" in message
            or "excel com returned null" in message
            or "ready state unavailable" in message
            or "active object unavailable" in message
        )

    @staticmethod
    def _get_executable_path_from_command_text(command_text: str | None) -> Path | None:
        text = str(command_text or "").strip()
        if not text:
            return None
        if text.startswith('"'):
            parts = text.split('"')
            if len(parts) >= 2:
                candidate = parts[1].strip()
                return Path(candidate) if candidate else None
        executable = re.split(r"\s+", text, maxsplit=1)[0].strip()
        return Path(executable) if executable else None

    @classmethod
    def _iter_excel_executable_candidates(cls) -> list[Path]:
        candidates: list[Path] = []
        seen: set[str] = set()

        def add_candidate(path: Path | str | None) -> None:
            if path is None:
                return
            candidate = Path(path)
            if not candidate.exists() or not candidate.is_file():
                return
            normalized = str(candidate.resolve()).lower()
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(candidate)

        with contextlib.suppress(Exception):
            import winreg

            app_path_keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
            ]
            for root, subkey in app_path_keys:
                try:
                    with winreg.OpenKey(root, subkey) as key:
                        value, _ = winreg.QueryValueEx(key, "")
                except OSError:
                    continue
                add_candidate(cls._get_executable_path_from_command_text(str(value)))

            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application\CLSID") as key:
                    clsid, _ = winreg.QueryValueEx(key, "")
                clsid = str(clsid or "").strip()
                if clsid:
                    for subkey in (
                        fr"CLSID\{clsid}\LocalServer32",
                        fr"WOW6432Node\CLSID\{clsid}\LocalServer32",
                    ):
                        try:
                            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, fr"SOFTWARE\Classes\{subkey}") as key:
                                value, _ = winreg.QueryValueEx(key, "")
                            add_candidate(cls._get_executable_path_from_command_text(str(value)))
                        except OSError:
                            continue
                        try:
                            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, subkey) as key:
                                value, _ = winreg.QueryValueEx(key, "")
                            add_candidate(cls._get_executable_path_from_command_text(str(value)))
                        except OSError:
                            continue
            except OSError:
                pass

        office_roots = [
            Path(path)
            for path in {
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMW6432"),
                os.environ.get("PROGRAMFILES(X86)"),
            }
            if path
        ]
        office_versions = [f"Office{version}" for version in range(30, 11, -1)]
        for root in office_roots:
            microsoft_office = root / "Microsoft Office"
            for version in office_versions:
                add_candidate(microsoft_office / "root" / version / "EXCEL.EXE")
                add_candidate(microsoft_office / version / "EXCEL.EXE")

        return candidates

    @staticmethod
    def _launch_excel_candidate_for_automation(candidate: Path) -> subprocess.Popen[bytes]:
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return subprocess.Popen(
            [str(candidate), "/automation"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    @classmethod
    def _wait_for_excel_active_object(
        cls,
        win32com_module: Any,
        *,
        retries: int = 36,
        delay_sec: float = 0.5,
    ) -> object:
        last_exc: Exception | None = None
        for _ in range(retries):
            try:
                return win32com_module.client.GetActiveObject("Excel.Application")
            except Exception as exc:
                last_exc = exc
                time.sleep(delay_sec)
        raise RuntimeError(f"无法附着 Excel.Application 活动对象: {last_exc}") from last_exc

    @classmethod
    def _dispatch_excel_application(
        cls,
        win32com_module: Any,
        *,
        retries: int = 3,
        delay_sec: float = 0.8,
    ) -> object:
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                excel = win32com_module.client.DispatchEx("Excel.Application")
            except Exception as exc:
                last_exc = exc
                if (
                    not cls._is_recoverable_excel_bootstrap_error(exc)
                    or cls._is_missing_excel_server_registration(exc)
                    or attempt + 1 >= retries
                ):
                    raise
                time.sleep(delay_sec)
                continue

            cls._wait_for_excel_application_ready(excel)
            return excel

        raise RuntimeError(f"无法创建 Excel.Application: {last_exc}") from last_exc

    @staticmethod
    def _excel_app_matches_pid(excel: object, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            import win32process  # type: ignore[import]
        except ImportError:
            return False
        with contextlib.suppress(Exception):
            excel_app = cast(Any, excel)
            hwnd = int(excel_app.Hwnd)
            _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
            return int(process_id) == int(pid)
        return False

    @classmethod
    def _create_excel_application(cls, win32com_module: Any) -> tuple[object, bool]:
        try:
            excel = cls._dispatch_excel_application(win32com_module)
            return excel, True
        except Exception as dispatch_exc:
            if not cls._is_recoverable_excel_bootstrap_error(dispatch_exc):
                raise
            last_exc: Exception = dispatch_exc

        for candidate in cls._iter_excel_executable_candidates():
            process: subprocess.Popen[bytes] | None = None
            try:
                process = cls._launch_excel_candidate_for_automation(candidate)
                excel = cls._wait_for_excel_active_object(win32com_module)
                if not cls._excel_app_matches_pid(excel, int(process.pid)):
                    if process.poll() is None:
                        with contextlib.suppress(Exception):
                            process.terminate()
                            process.wait(timeout=5)
                    continue
                cls._wait_for_excel_application_ready(excel)
                return excel, True
            except Exception as exc:
                last_exc = exc
                if process is not None and process.poll() is None:
                    with contextlib.suppress(Exception):
                        process.terminate()
                        process.wait(timeout=5)
                continue

        raise RuntimeError(f"无法创建 Excel.Application: {last_exc}") from last_exc

    @classmethod
    def _retry_excel_com_call(
        cls,
        fn: Callable[[], Any],
        desc: str,
        *,
        retries: int = 10,
    ) -> Any:
        last_exc: Exception | None = None
        for _ in range(retries):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                time.sleep(0.8 if cls._is_call_rejected(exc) else 0.3)
        raise RuntimeError(f"Excel COM 调用失败 {desc}: {last_exc}") from last_exc

    @classmethod
    def _wait_for_excel_application_ready(
        cls,
        excel: object,
        *,
        retries: int = 18,
    ) -> object:
        excel_app = cast(Any, excel)
        last_exc: Exception | None = None
        for _ in range(retries):
            try:
                workbooks = excel_app.Workbooks
                if workbooks is None:
                    raise RuntimeError("Excel.Workbooks unavailable")
                ready = True
                with contextlib.suppress(Exception):
                    ready = bool(excel_app.Ready)
                if ready:
                    return workbooks
            except Exception as exc:
                last_exc = exc
                time.sleep(0.8 if cls._is_call_rejected(exc) else 0.3)
                continue
            time.sleep(0.3)
        if last_exc is not None:
            raise RuntimeError(f"Excel COM 就绪等待失败: {last_exc}") from last_exc
        raise RuntimeError("Excel COM 就绪等待失败: Excel.Workbooks unavailable")

    @classmethod
    def _prepare_excel_path_for_com(cls, xlsx_path: Path, *, label: str) -> tuple[Path, Path]:
        temp_dir = Path(tempfile.mkdtemp(prefix="fanban_excel_com_"))
        working_copy = temp_dir / f"{cls._sanitize_excel_label(label)}{xlsx_path.suffix.lower()}"
        shutil.copy2(xlsx_path, working_copy)
        cls._clear_windows_zone_identifier(working_copy)
        return working_copy, temp_dir

    @classmethod
    def _open_excel_workbook(cls, excel: object, workbook_path: Path, *, read_only: bool) -> object:
        workbooks = cls._wait_for_excel_application_ready(excel)
        return cls._retry_excel_com_call(
            lambda: cast(Any, workbooks).Open(str(workbook_path.absolute()), 0, read_only),
            f"Excel.Workbooks.Open({workbook_path.name})",
        )

    def _export_xlsx_via_com_with_process_recycle(self, xlsx_path: Path, pdf_path: Path) -> None:
        with get_office_automation_limiter().excel_session():
            self._terminate_stale_excel_automation_processes()
            baseline_excel_pids = self._snapshot_process_ids_by_image("EXCEL.EXE")
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    self._export_xlsx_via_com(xlsx_path, pdf_path, manage_limiter=False)
                    return
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt == 0:
                        self._terminate_new_processes("EXCEL.EXE", baseline_excel_pids)
                        time.sleep(0.8)
            assert last_exc is not None
            raise last_exc

    def _export_docx_via_com(self, docx_path: Path, pdf_path: Path) -> None:
        """通过Office COM导出Word到PDF"""
        pythoncom = None
        try:
            import pythoncom  # type: ignore[import]
            import win32com.client
        except ImportError as err:
            raise ExportError("pywin32未安装，无法使用Office COM") from err

        word = None
        doc = None
        with get_office_automation_limiter().word_session():
            try:
                pythoncom.CoInitialize()
                word = win32com.client.DispatchEx("Word.Application")
                self._prepare_word_for_headless_run(word)

                doc = word.Documents.Open(str(docx_path.absolute()))
                doc.ExportAsFixedFormat(str(pdf_path.absolute()), 17)  # 17 = PDF
            finally:
                if doc:
                    self._mark_word_document_saved(doc)
                    with contextlib.suppress(Exception):
                        doc.Close(False)
                doc = None
                if word:
                    self._mark_word_normal_template_saved(word)
                    with contextlib.suppress(Exception):
                        word.Quit()
                word = None
                gc.collect()
                if pythoncom is not None:
                    with contextlib.suppress(Exception):
                        pythoncom.CoUninitialize()

    def _export_xlsx_via_com(
        self,
        xlsx_path: Path,
        pdf_path: Path,
        *,
        manage_limiter: bool = True,
    ) -> None:
        """通过Office COM导出Excel到PDF"""
        pythoncom = None
        try:
            import pythoncom  # type: ignore[import]
            import win32com.client
        except ImportError as err:
            raise ExportError("pywin32未安装，无法使用Office COM") from err

        excel = None
        excel_owned = False
        wb = None
        temp_dir = None
        limiter_context = (
            get_office_automation_limiter().excel_session()
            if manage_limiter
            else contextlib.nullcontext()
        )
        with limiter_context:
            try:
                pythoncom.CoInitialize()
                excel, excel_owned = self._create_excel_application(win32com)
                self._prepare_excel_for_headless_run(excel)
                working_copy, temp_dir = self._prepare_excel_path_for_com(
                    xlsx_path,
                    label=pdf_path.stem or xlsx_path.stem,
                )

                wb = self._open_excel_workbook(excel, working_copy, read_only=True)
                self._retry_excel_com_call(
                    lambda: cast(Any, wb).ExportAsFixedFormat(0, str(pdf_path.absolute())),
                    "Workbook.ExportAsFixedFormat",
                )
            finally:
                if wb:
                    with contextlib.suppress(Exception):
                        cast(Any, wb).Close(False)
                wb = None
                if excel and excel_owned:
                    with contextlib.suppress(Exception):
                        cast(Any, excel).Quit()
                excel = None
                gc.collect()
                if pythoncom is not None:
                    with contextlib.suppress(Exception):
                        pythoncom.CoUninitialize()
                if temp_dir is not None:
                    shutil.rmtree(temp_dir, ignore_errors=True)

    def _export_via_libreoffice(self, input_path: Path, pdf_path: Path) -> None:
        """通过LibreOffice导出PDF"""
        cmd = [
            "soffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(pdf_path.parent),
            str(input_path),
        ]

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                timeout=self.timeout,
                check=True,
                **_hidden_subprocess_kwargs(),
            )
        except FileNotFoundError as e:
            raise ExportError("LibreOffice 未安装或 soffice 不在 PATH 中") from e
        except subprocess.TimeoutExpired as e:
            raise ExportError(f"LibreOffice导出超时: {input_path}") from e
        except subprocess.CalledProcessError as e:
            raise ExportError(f"LibreOffice导出失败: {e.stderr}") from e

        # LibreOffice输出文件名可能不同
        expected = pdf_path.parent / f"{input_path.stem}.pdf"
        if expected != pdf_path and expected.exists():
            expected.rename(pdf_path)
