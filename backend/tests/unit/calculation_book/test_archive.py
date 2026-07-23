from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.calculation_book.archive import (
    ArchiveLimits,
    InvalidCalculationArchive,
    validate_and_extract_archive,
)


def _write_archive(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def _valid_entries() -> dict[str, bytes]:
    return {
        "RX1-X.png": b"x",
        "RX1-Y.png": b"y",
        "RX1-Z.png": b"z",
        "01/layout.png": b"layout",
        "02/model.png": b"model",
    }


def test_extracts_only_the_required_calculation_structure(tmp_path: Path) -> None:
    archive = _write_archive(tmp_path / "input.zip", _valid_entries())

    contents = validate_and_extract_archive(
        archive,
        tmp_path / "extracted",
        limits=ArchiveLimits(max_files=20, max_total_bytes=1024, max_single_file_bytes=128),
    )

    assert [figure.direction for figure in contents.reinforcement_figures] == ["X", "Y", "Z"]
    assert contents.layout_image.name == "layout.png"
    assert contents.model_image.name == "model.png"
    assert all(path.is_relative_to(contents.root) for path in contents.extracted_files)


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../outside.png",
        "/absolute.png",
        "C:/windows/system32/unsafe.png",
        "01/../../outside.png",
    ],
)
def test_rejects_path_traversal_and_absolute_members(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    entries = _valid_entries()
    entries[unsafe_name] = b"unsafe"
    archive = _write_archive(tmp_path / "unsafe.zip", entries)

    with pytest.raises(InvalidCalculationArchive, match="不安全"):
        validate_and_extract_archive(archive, tmp_path / "extracted")

    assert not (tmp_path / "outside.png").exists()


@pytest.mark.parametrize(
    ("removed_name", "message"),
    [
        ("RX1-X.png", "X"),
        ("RX1-Y.png", "Y"),
        ("RX1-Z.png", "Z"),
        ("01/layout.png", "01"),
        ("02/model.png", "02"),
    ],
)
def test_rejects_missing_required_images(
    tmp_path: Path,
    removed_name: str,
    message: str,
) -> None:
    entries = _valid_entries()
    entries.pop(removed_name)
    archive = _write_archive(tmp_path / "missing.zip", entries)

    with pytest.raises(InvalidCalculationArchive, match=message):
        validate_and_extract_archive(archive, tmp_path / "extracted")


def test_rejects_archive_limits_before_extraction(tmp_path: Path) -> None:
    archive = _write_archive(tmp_path / "large.zip", _valid_entries())

    with pytest.raises(InvalidCalculationArchive, match="单个文件"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            limits=ArchiveLimits(max_files=20, max_total_bytes=1024, max_single_file_bytes=2),
        )
