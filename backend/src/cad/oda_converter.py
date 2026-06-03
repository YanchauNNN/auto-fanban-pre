"""
ODA 转换器 - DWG↔DXF 转换

职责：
- 调用 ODA File Converter 执行格式转换
- 处理超时和错误
- 清理临时文件

依赖：
- ODA File Converter 可执行文件（路径由运行期配置指定）

测试要点：
- test_dwg_to_dxf_success: 正常转换
- test_dwg_to_dxf_timeout: 超时处理
- test_dwg_to_dxf_file_not_found: 文件不存在
- test_dxf_to_dwg_success: 反向转换
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import get_config
from ..interfaces import ConversionError, IODAConverter
from .dwg_version import oda_version_for_dwg_code


class ODAConverter(IODAConverter):
    """ODA File Converter 封装"""

    def __init__(self, exe_path: str | None = None, timeout: int | None = None):
        config = get_config()
        self.exe_path = Path(exe_path or config.oda.exe_path)
        self.timeout = timeout or config.timeouts.oda_convert_sec
        self.work_dir = Path(config.oda.work_dir) if config.oda.work_dir else None

    def _ensure_exe(self) -> None:
        if not self.exe_path or not self.exe_path.exists() or not self.exe_path.is_file():
            raise ConversionError(f"ODA可执行文件不存在或未配置: {self.exe_path}")
        if self.work_dir:
            self.work_dir.mkdir(parents=True, exist_ok=True)

    def dwg_to_dxf(self, dwg_path: Path, output_dir: Path) -> Path:
        """DWG 转 DXF"""
        if not dwg_path.exists():
            raise ConversionError(f"DWG文件不存在: {dwg_path}")

        self._ensure_exe()

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{dwg_path.stem}.dxf"

        cmd = [
            str(self.exe_path),
            str(dwg_path.parent),
            str(output_dir),
            "ACAD2018",
            "DXF",
            "0",  # Recursive
            "1",  # Audit
            f"*.{dwg_path.suffix[1:]}",  # Filter
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
            )
        except subprocess.TimeoutExpired as e:
            raise ConversionError(f"ODA转换超时: {dwg_path}") from e
        except subprocess.CalledProcessError as e:
            detail = e.stderr or e.stdout or ""
            raise ConversionError(f"ODA转换失败: {detail}") from e

        output_path = self._resolve_output(output_dir, dwg_path.stem, ".dxf")

        return output_path

    def dxf_to_dwg(
        self,
        dxf_path: Path,
        output_dir: Path,
        target_version_code: str | None = None,
    ) -> Path:
        """DXF 转 DWG"""
        if not dxf_path.exists():
            raise ConversionError(f"DXF文件不存在: {dxf_path}")

        self._ensure_exe()

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{dxf_path.stem}.dwg"

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
            )
        except subprocess.TimeoutExpired as e:
            raise ConversionError(f"ODA转换超时: {dxf_path}") from e
        except subprocess.CalledProcessError as e:
            detail = e.stderr or e.stdout or ""
            raise ConversionError(f"ODA转换失败: {detail}") from e

        output_path = self._resolve_output(output_dir, dxf_path.stem, ".dwg")

        return output_path

    @staticmethod
    def _resolve_output(output_dir: Path, stem: str, suffix: str) -> Path:
        expected = output_dir / f"{stem}{suffix}"
        if expected.exists():
            return expected
        for candidate in output_dir.glob(f"{stem}.*"):
            if candidate.suffix.lower() == suffix:
                return candidate
        raise ConversionError(f"转换后文件不存在: {expected}")
