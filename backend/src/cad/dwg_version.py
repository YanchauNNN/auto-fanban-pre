from __future__ import annotations

from pathlib import Path

DWG_HEADER_TO_ODA_VERSION: dict[str, str] = {
    "AC1009": "ACAD12",
    "AC1012": "ACAD13",
    "AC1014": "ACAD14",
    "AC1015": "ACAD2000",
    "AC1018": "ACAD2004",
    "AC1021": "ACAD2007",
    "AC1024": "ACAD2010",
    "AC1027": "ACAD2013",
    "AC1032": "ACAD2018",
}


def detect_dwg_version_code(dwg_path: str | Path) -> str:
    path = Path(dwg_path)
    with path.open("rb") as fh:
        header = fh.read(6)
    if len(header) < 6:
        raise ValueError(f"DWG header too short: {path}")
    version_code = header.decode("ascii", errors="strict").upper()
    if version_code not in DWG_HEADER_TO_ODA_VERSION:
        raise ValueError(f"unsupported DWG version header: {version_code}")
    return version_code


def detect_dwg_version_code_or_none(dwg_path: str | Path | None) -> str | None:
    if dwg_path is None:
        return None
    path = Path(dwg_path)
    if path.suffix.lower() != ".dwg" or not path.exists():
        return None
    return detect_dwg_version_code(path)


def oda_version_for_dwg_code(version_code: str) -> str:
    normalized = str(version_code or "").strip().upper()
    try:
        return DWG_HEADER_TO_ODA_VERSION[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported DWG version: {version_code}") from exc
