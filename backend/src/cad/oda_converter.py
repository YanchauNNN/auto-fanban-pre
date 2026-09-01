"""ODA File Converter wrapper with an AutoCAD-native DWG fallback."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Protocol

from ..config import get_config
from ..interfaces import ConversionError, IODAConverter
from .dwg_version import oda_version_for_dwg_code

logger = logging.getLogger(__name__)


class _DwgToDxfFallback(Protocol):
    def dwg_to_dxf(self, dwg_path: Path, output_dir: Path) -> Path: ...


def _hidden_subprocess_kwargs() -> dict[str, int]:
    if os.name != "nt":
        return {}
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"creationflags": creationflags} if creationflags else {}


class ODAConverter(IODAConverter):
    """Run ODA conversions and preserve the converter's real diagnostics."""

    def __init__(
        self,
        exe_path: str | None = None,
        timeout: int | None = None,
        *,
        native_fallback: _DwgToDxfFallback | None = None,
        native_fallback_enabled: bool | None = None,
    ) -> None:
        config = get_config()
        self.exe_path = Path(exe_path or config.oda.exe_path)
        self.timeout = timeout or config.timeouts.oda_convert_sec
        self.work_dir = Path(config.oda.work_dir) if config.oda.work_dir else None
        self._config = config
        self._native_fallback = native_fallback
        self._native_fallback_enabled = (
            bool(config.oda.native_dxf_fallback_enabled)
            if native_fallback_enabled is None
            else bool(native_fallback_enabled)
        )

    def _ensure_exe(self) -> None:
        if not self.exe_path or not self.exe_path.exists() or not self.exe_path.is_file():
            raise ConversionError(f"ODA可执行文件不存在或未配置: {self.exe_path}")
        if self.work_dir:
            self.work_dir.mkdir(parents=True, exist_ok=True)

    def dwg_to_dxf(self, dwg_path: Path, output_dir: Path) -> Path:
        """Convert DWG to DXF, falling back to AutoCAD/.NET when configured."""
        if not dwg_path.exists():
            raise ConversionError(f"DWG文件不存在: {dwg_path}")

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{dwg_path.stem}.dxf"
        oda_error: ConversionError | None = None

        try:
            self._ensure_exe()
            cmd = [
                str(self.exe_path),
                str(dwg_path.parent),
                str(output_dir),
                "ACAD2018",
                "DXF",
                "0",
                "1",
                f"*.{dwg_path.suffix[1:]}",
            ]
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=True,
                cwd=str(self.work_dir) if self.work_dir else None,
                **_hidden_subprocess_kwargs(),
            )
            try:
                return self._resolve_output(output_dir, dwg_path.stem, ".dxf")
            except ConversionError:
                diagnostic = self._read_error_artifact(output_dir, dwg_path.stem)
                detail = diagnostic or f"未生成 {output_path}"
                oda_error = ConversionError(f"ODA转换失败: {detail}")
        except subprocess.TimeoutExpired:
            oda_error = ConversionError(f"ODA转换超时: {dwg_path}")
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or exc.stdout or ""
            oda_error = ConversionError(f"ODA转换失败: {detail}")
        except ConversionError as exc:
            oda_error = exc

        if not self._native_fallback_enabled:
            raise oda_error

        logger.warning(
            "ODA DWG->DXF failed; using AutoCAD/.NET fallback: source=%s error=%s",
            dwg_path,
            oda_error,
        )
        try:
            return self._get_native_fallback().dwg_to_dxf(dwg_path, output_dir)
        except Exception as fallback_error:
            raise ConversionError(
                f"{oda_error}; AutoCAD原生转换失败: {fallback_error}",
            ) from fallback_error

    def dxf_to_dwg(
        self,
        dxf_path: Path,
        output_dir: Path,
        target_version_code: str | None = None,
    ) -> Path:
        """Convert DXF to DWG using ODA."""
        if not dxf_path.exists():
            raise ConversionError(f"DXF文件不存在: {dxf_path}")

        self._ensure_complete_ascii_dxf(dxf_path)
        self._ensure_exe()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_version = (
            oda_version_for_dwg_code(target_version_code)
            if target_version_code
            else "ACAD2018"
        )
        cmd = [
            str(self.exe_path),
            str(dxf_path.parent),
            str(output_dir),
            output_version,
            "DWG",
            "0",
            "1",
            "*.dxf",
        ]

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=True,
                cwd=str(self.work_dir) if self.work_dir else None,
                **_hidden_subprocess_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise ConversionError(f"ODA转换超时: {dxf_path}") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or exc.stdout or ""
            raise ConversionError(f"ODA转换失败: {detail}") from exc

        return self._resolve_output(output_dir, dxf_path.stem, ".dwg")

    @staticmethod
    def _ensure_complete_ascii_dxf(dxf_path: Path) -> None:
        """Reject interrupted ASCII DXF writes before ODA creates a bad DWG."""
        with dxf_path.open("rb") as stream:
            header = stream.read(22)
            if header.startswith(b"AutoCAD Binary DXF"):
                return
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 8192))
            tail = stream.read()

        lines = [
            line.strip()
            for line in tail.decode("ascii", errors="ignore").splitlines()
            if line.strip()
        ]
        if len(lines) < 2 or lines[-2:] != ["0", "EOF"]:
            raise ConversionError(f"DXF文件不完整，末尾缺少 0/EOF 标记: {dxf_path}")

    @staticmethod
    def _resolve_output(output_dir: Path, stem: str, suffix: str) -> Path:
        expected = output_dir / f"{stem}{suffix}"
        if expected.exists():
            return expected
        for candidate in output_dir.glob(f"{stem}.*"):
            if candidate.suffix.lower() == suffix:
                return candidate
        raise ConversionError(f"转换后文件不存在: {expected}")

    @staticmethod
    def _read_error_artifact(output_dir: Path, stem: str) -> str:
        candidates = [
            output_dir / f"{stem}.dxf.err",
            output_dir / f"{stem}.err",
        ]
        candidates.extend(
            candidate
            for candidate in output_dir.glob(f"{stem}.*")
            if candidate.suffix.lower() == ".err"
        )
        seen: set[Path] = set()
        for candidate in candidates:
            if candidate in seen or not candidate.is_file():
                continue
            seen.add(candidate)
            try:
                content = candidate.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).strip()
            except OSError:
                continue
            if content:
                return content[:4000]
        return ""

    def _get_native_fallback(self) -> _DwgToDxfFallback:
        if self._native_fallback is None:
            from .native_dxf_converter import AutoCadDwgToDxfConverter

            self._native_fallback = AutoCadDwgToDxfConverter(config=self._config)
        return self._native_fallback
