from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.cad.oda_converter import ODAConverter
from src.interfaces import ConversionError


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


def test_dxf_to_dwg_rejects_truncated_ascii_dxf_before_converter_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exe_path = tmp_path / "ODAFileConverter.exe"
    exe_path.write_text("stub", encoding="utf-8")
    dxf_path = tmp_path / "truncated.dxf"
    dxf_path.write_text("0\nSECTION\n2\nENTITIES\n0\nTEXT\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    converter_called = False

    def _fake_run(cmd, **kwargs):
        nonlocal converter_called
        converter_called = True
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    converter = ODAConverter(exe_path=str(exe_path), timeout=1)
    with pytest.raises(ConversionError, match="DXF.*EOF"):
        converter.dxf_to_dwg(dxf_path, output_dir)

    assert converter_called is False
    assert not output_dir.exists()


def test_dwg_to_dxf_subprocess_uses_safe_output_decoding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exe_path = tmp_path / "ODAFileConverter.exe"
    exe_path.write_text("stub", encoding="utf-8")
    dwg_path = tmp_path / "sample.dwg"
    dwg_path.write_text("dwg", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "sample.dxf").write_text("0\nEOF\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    converter = ODAConverter(exe_path=str(exe_path), timeout=1)
    result = converter.dwg_to_dxf(dwg_path, output_dir)

    assert result == output_dir / "sample.dxf"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_dwg_to_dxf_hides_converter_subprocess_window_on_windows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exe_path = tmp_path / "ODAFileConverter.exe"
    exe_path.write_text("stub", encoding="utf-8")
    dwg_path = tmp_path / "sample.dwg"
    dwg_path.write_text("dwg", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "sample.dxf").write_text("0\nEOF\n", encoding="utf-8")
    monkeypatch.setattr("src.cad.oda_converter.os.name", "nt")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    converter = ODAConverter(exe_path=str(exe_path), timeout=1)
    result = converter.dwg_to_dxf(dwg_path, output_dir)

    assert result == output_dir / "sample.dxf"
    assert captured["creationflags"] == 0x08000000


def test_dwg_to_dxf_reports_oda_error_file_when_output_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exe_path = tmp_path / "ODAFileConverter.exe"
    exe_path.write_text("stub", encoding="utf-8")
    dwg_path = tmp_path / "sample.dwg"
    dwg_path.write_text("dwg", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)

    def _fake_run(cmd, **kwargs):
        (output_dir / "sample.dxf.err").write_text(
            'OdError thrown during readFile of drawing "sample.dwg":\n'
            "  XData size exceeded: <object> (2C)",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    converter = ODAConverter(
        exe_path=str(exe_path),
        timeout=1,
        native_fallback_enabled=False,
    )

    with pytest.raises(ConversionError, match="XData size exceeded"):
        converter.dwg_to_dxf(dwg_path, output_dir)


def test_dwg_to_dxf_uses_native_fallback_after_oda_read_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exe_path = tmp_path / "ODAFileConverter.exe"
    exe_path.write_text("stub", encoding="utf-8")
    dwg_path = tmp_path / "sample.dwg"
    dwg_path.write_text("dwg", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)

    def _fake_run(cmd, **kwargs):
        (output_dir / "sample.dxf.err").write_text(
            "XData size exceeded",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    class _NativeFallback:
        def __init__(self) -> None:
            self.calls: list[tuple[Path, Path]] = []

        def dwg_to_dxf(self, source: Path, target_dir: Path) -> Path:
            self.calls.append((source, target_dir))
            output = target_dir / f"{source.stem}.dxf"
            output.write_text("0\nEOF\n", encoding="utf-8")
            return output

    monkeypatch.setattr(subprocess, "run", _fake_run)
    native_fallback = _NativeFallback()
    converter = ODAConverter(
        exe_path=str(exe_path),
        timeout=1,
        native_fallback=native_fallback,
        native_fallback_enabled=True,
    )

    result = converter.dwg_to_dxf(dwg_path, output_dir)

    assert result == output_dir / "sample.dxf"
    assert native_fallback.calls == [(dwg_path, output_dir)]
