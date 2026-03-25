from __future__ import annotations

from pathlib import Path

import pytest

from src.cad.dwg_version import (
    detect_dwg_version_code,
    oda_version_for_dwg_code,
)


def test_detect_dwg_version_code_reads_magic_header(tmp_path: Path) -> None:
    dwg_path = tmp_path / "sample.dwg"
    dwg_path.write_bytes(b"AC1027rest-of-file")

    assert detect_dwg_version_code(dwg_path) == "AC1027"


def test_oda_version_for_dwg_code_maps_supported_versions() -> None:
    assert oda_version_for_dwg_code("AC1015") == "ACAD2000"
    assert oda_version_for_dwg_code("AC1018") == "ACAD2004"
    assert oda_version_for_dwg_code("AC1027") == "ACAD2013"
    assert oda_version_for_dwg_code("AC1032") == "ACAD2018"


def test_oda_version_for_dwg_code_rejects_unsupported_versions() -> None:
    with pytest.raises(ValueError, match="unsupported DWG version"):
        oda_version_for_dwg_code("AC9999")
