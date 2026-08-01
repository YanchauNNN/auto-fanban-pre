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
        "计算书模板文件.xlsx": b"xlsx",
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
    assert contents.reinforcement_workbook.name == "计算书模板文件.xlsx"
    assert all(path.is_relative_to(contents.root) for path in contents.extracted_files)


def test_accepts_one_shared_wrapper_directory(tmp_path: Path) -> None:
    entries = {
        f"6层11.45~15.95m 结果云图/{name}": content
        for name, content in _valid_entries().items()
    }
    archive = _write_archive(tmp_path / "wrapped.zip", entries)

    contents = validate_and_extract_archive(archive, tmp_path / "extracted")

    assert contents.root.name == "6层11.45~15.95m 结果云图"
    assert contents.reinforcement_workbook.parent == contents.root
    assert contents.layout_image.parent.name == "01"
    assert contents.model_image.parent.name == "02"


def test_extracts_five_slab_figures_without_treating_them_as_ignored(
    tmp_path: Path,
) -> None:
    entries = _valid_entries()
    for name in (
        "11.2-top-x.JPEG",
        "11.2-top-y.JPEG",
        "11.2-BOTTOM-x.JPEG",
        "11.2-BOTTOM-y.JPEG",
        "11.2-Z.JPEG",
    ):
        entries[name] = name.encode()
    archive = _write_archive(tmp_path / "slab-five.zip", entries)

    contents = validate_and_extract_archive(archive, tmp_path / "extracted")

    assert [
        (figure.elevation, figure.position, figure.direction)
        for figure in contents.slab_figures
    ] == [
        ("11.2", "TOP", "X"),
        ("11.2", "TOP", "Y"),
        ("11.2", "BOTTOM", "X"),
        ("11.2", "BOTTOM", "Y"),
        ("11.2", None, "Z"),
    ]
    assert not {
        figure.path.name for figure in contents.slab_figures
    }.intersection(path.name for path in contents.ignored_root_images)


def test_extracts_mixed_case_middle_as_seven_slab_figures(
    tmp_path: Path,
) -> None:
    entries = _valid_entries()
    for name in (
        "11.20-top-x.JPEG",
        "11.20-top-y.JPEG",
        "11.20-Middle-x.JPEG",
        "11.20-mIDDLE-y.JPEG",
        "11.20-bottom-x.JPEG",
        "11.20-bottom-y.JPEG",
        "11.20-z.JPEG",
    ):
        entries[name] = name.encode()
    archive = _write_archive(tmp_path / "slab-seven.zip", entries)

    contents = validate_and_extract_archive(archive, tmp_path / "extracted")

    assert len(contents.slab_figures) == 7
    assert {figure.elevation for figure in contents.slab_figures} == {"11.2"}
    assert {
        (figure.position, figure.direction)
        for figure in contents.slab_figures
    } == {
        ("TOP", "X"),
        ("TOP", "Y"),
        ("MIDDLE", "X"),
        ("MIDDLE", "Y"),
        ("BOTTOM", "X"),
        ("BOTTOM", "Y"),
        (None, "Z"),
    }


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
        ("计算书模板文件.xlsx", "配筋表"),
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


def test_alpha_suffix_wall_is_independent_and_normalized_to_uppercase(
    tmp_path: Path,
) -> None:
    entries = _valid_entries()
    for direction in ("X", "Y", "Z"):
        entries[f"S7157a-{direction}.JPEG"] = direction.encode()
    archive = _write_archive(tmp_path / "alpha.zip", entries)

    contents = validate_and_extract_archive(archive, tmp_path / "extracted")

    alpha_figures = [
        figure
        for figure in contents.reinforcement_figures
        if figure.wall_id == "S7157A"
    ]
    assert [figure.direction for figure in alpha_figures] == ["X", "Y", "Z"]
    assert all(figure.group_index is None for figure in alpha_figures)


def test_uses_parenthetical_wall_id_in_prefixed_figure_names(
    tmp_path: Path,
) -> None:
    entries = _valid_entries()
    for direction in ("X", "Y", "Z"):
        entries[f"Ndtj2(N5056C)-{direction}.JPEG"] = direction.encode()
    archive = _write_archive(tmp_path / "parenthetical-wall.zip", entries)

    contents = validate_and_extract_archive(archive, tmp_path / "extracted")

    figures = [
        figure
        for figure in contents.reinforcement_figures
        if figure.wall_id == "N5056C"
    ]
    assert [figure.direction for figure in figures] == ["X", "Y", "Z"]
    assert not {
        figure.path.name for figure in figures
    }.intersection(path.name for path in contents.ignored_root_images)


def test_minus_one_and_minus_two_are_separate_groups_for_completion_review(
    tmp_path: Path,
) -> None:
    entries = _valid_entries()
    for direction in ("X", "Y", "Z"):
        entries[f"S7157-1-{direction}.JPEG"] = f"1{direction}".encode()
        entries[f"S7157-2-{direction}.JPEG"] = f"2{direction}".encode()
    archive = _write_archive(tmp_path / "groups.zip", entries)

    contents = validate_and_extract_archive(archive, tmp_path / "extracted")

    grouped = [
        figure
        for figure in contents.reinforcement_figures
        if figure.base_wall_id == "S7157"
    ]
    assert {figure.wall_id for figure in grouped} == {"S7157-1", "S7157-2"}
    assert {figure.group_index for figure in grouped} == {1, 2}
    assert contents.requires_manual_confirmation


def test_rejects_incomplete_minus_group(tmp_path: Path) -> None:
    entries = _valid_entries()
    entries["S7157-1-X.JPEG"] = b"x"
    entries["S7157-1-Y.JPEG"] = b"y"
    archive = _write_archive(tmp_path / "incomplete-group.zip", entries)

    with pytest.raises(InvalidCalculationArchive, match="S7157-1.*Z"):
        validate_and_extract_archive(archive, tmp_path / "extracted")


def test_rejects_multiple_root_reinforcement_workbooks(tmp_path: Path) -> None:
    entries = _valid_entries()
    entries["另一个配筋表.xlsx"] = b"xlsx"
    archive = _write_archive(tmp_path / "multiple-workbooks.zip", entries)

    with pytest.raises(InvalidCalculationArchive, match="只能包含一个"):
        validate_and_extract_archive(archive, tmp_path / "extracted")


@pytest.mark.parametrize("folder", ["01", "02"])
def test_rejects_multiple_images_in_layout_or_model_folder(
    tmp_path: Path,
    folder: str,
) -> None:
    entries = _valid_entries()
    entries[f"{folder}/second.png"] = b"second"
    archive = _write_archive(tmp_path / f"multiple-{folder}.zip", entries)

    with pytest.raises(InvalidCalculationArchive, match=f"{folder}.*只能包含一张"):
        validate_and_extract_archive(archive, tmp_path / "extracted")
