from __future__ import annotations

import subprocess
from pathlib import Path

from src.cad.oda_converter import ODAConverter


def test_dxf_to_dwg_uses_requested_target_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exe_path = tmp_path / "ODAFileConverter.exe"
    exe_path.write_text("stub", encoding="utf-8")
    dxf_path = tmp_path / "sample.dxf"
    dxf_path.write_text("0\nEOF\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "sample.dwg").write_text("dwg", encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    converter = ODAConverter(exe_path=str(exe_path), timeout=1)
    result = converter.dxf_to_dwg(
        dxf_path,
        output_dir,
        target_version_code="AC1027",
    )

    assert result == output_dir / "sample.dwg"
    assert captured["cmd"][3] == "ACAD2013"
