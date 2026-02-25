"""
模块5 集成回归测试（2016仿真图.dxf，真实切割+出图）

运行方式：
    cd backend
    python -m pytest ../tools/run_module5_integration_2016.py -v -s --tb=short

说明：
- 本测试会调用 tools/run_module5_test.py 执行完整流程（裁切 + PDF + DWG）
- 属于慢速集成测试，依赖本机 ODA 与运行环境
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DXF_PATH = PROJECT_ROOT / "test" / "dwg" / "_dxf_out" / "2016仿真图.dxf"
RUN_SCRIPT = PROJECT_ROOT / "tools" / "run_module5_test.py"

pytestmark = pytest.mark.skipif(not DXF_PATH.exists(), reason=f"测试DXF不存在: {DXF_PATH}")


class TestModule5Integration2016:
    def test_2016_pipeline_outputs_expected_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "out_2016"
            cmd = [
                sys.executable,
                str(RUN_SCRIPT),
                str(DXF_PATH),
                "-o",
                str(output_dir),
            ]
            env = os.environ.copy()
            env.setdefault("PYTHONUTF8", "1")
            env.setdefault("PYTHONIOENCODING", "utf-8")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(PROJECT_ROOT),
                timeout=900,
                env=env,
            )

            assert result.returncode == 0, (
                "模块5流程执行失败\n"
                f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
            )

            drawings_dir = output_dir / "drawings"
            split_dir = output_dir / "work" / "split"
            assert drawings_dir.exists(), f"drawings目录不存在: {drawings_dir}"
            assert split_dir.exists(), f"split目录不存在: {split_dir}"

            pdf_files = sorted(drawings_dir.glob("*.pdf"))
            dwg_files = sorted(drawings_dir.glob("*.dwg"))
            dxf_files = sorted(split_dir.glob("*.dxf"))

            # 当前2016样例稳定结果：存在同名覆盖，产物数量通常为14或15
            assert 14 <= len(dxf_files) <= 15, f"中间DXF数量异常: {len(dxf_files)}"
            assert 14 <= len(pdf_files) <= 15, f"PDF数量异常: {len(pdf_files)}"
            assert 14 <= len(dwg_files) <= 15, f"DWG数量异常: {len(dwg_files)}"

            key_pdf = drawings_dir / "JD1NHH11001B25C42SD(20161NH-JGS03-001).pdf"
            assert key_pdf.exists(), f"关键多页PDF不存在: {key_pdf.name}"

            from pypdf import PdfReader

            pages = len(PdfReader(str(key_pdf)).pages)
            assert pages == 4, f"001图纸PDF页数异常，预期4，实际{pages}"
