from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.calculation_book.archive import (
    ArchiveFormat,
    ArchiveLimits,
    InvalidCalculationArchive,
    detect_archive_format,
    validate_and_extract_archive,
)
from src.calculation_book.models import ReinforcementSource


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


@pytest.mark.parametrize(
    ("suffix", "signature", "expected"),
    [
        (".zip", b"PK\x03\x04payload", ArchiveFormat.ZIP),
        (".rar", b"Rar!\x1a\x07\x00payload", ArchiveFormat.RAR),
        (".rar", b"Rar!\x1a\x07\x01\x00payload", ArchiveFormat.RAR),
        (".7z", b"7z\xbc\xaf'\x1cpayload", ArchiveFormat.SEVEN_Z),
        (".ZIP", b"PK\x03\x04payload", ArchiveFormat.ZIP),
        (".RAR", b"Rar!\x1a\x07\x01\x00payload", ArchiveFormat.RAR),
        (".7Z", b"7z\xbc\xaf'\x1cpayload", ArchiveFormat.SEVEN_Z),
        (".ZIP", b"PK\x05\x06", ArchiveFormat.ZIP),
        (".ZIP", b"PK\x07\x08", ArchiveFormat.ZIP),
    ],
)
def test_detects_archive_format_from_suffix_and_magic_bytes(
    tmp_path: Path,
    suffix: str,
    signature: bytes,
    expected: ArchiveFormat,
) -> None:
    archive = tmp_path / f"input{suffix}"
    archive.write_bytes(signature)

    assert detect_archive_format(archive) is expected


def test_rejects_unknown_archive_magic_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "input.zip"
    archive.write_bytes(b"not-an-archive")

    with pytest.raises(InvalidCalculationArchive, match="无法识别.*签名"):
        detect_archive_format(archive)


def test_rejects_archive_suffix_and_magic_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "input.zip"
    archive.write_bytes(b"Rar!\x1a\x07\x01\x00")

    with pytest.raises(InvalidCalculationArchive, match="后缀.*签名.*不一致"):
        detect_archive_format(archive)


@pytest.mark.parametrize("payload", [b"", b"P", b"PK\x03"])
def test_rejects_empty_or_short_archive_signatures(
    tmp_path: Path,
    payload: bytes,
) -> None:
    archive = tmp_path / "input.zip"
    archive.write_bytes(payload)

    with pytest.raises(InvalidCalculationArchive, match="无法识别.*签名"):
        detect_archive_format(archive)


def test_validation_rejects_zip_content_renamed_as_rar_before_extraction(
    tmp_path: Path,
) -> None:
    archive = _write_archive(tmp_path / "renamed.rar", _valid_entries())

    with pytest.raises(InvalidCalculationArchive, match="后缀.*签名.*不一致"):
        validate_and_extract_archive(archive, tmp_path / "extracted")


def test_validation_rejects_unknown_rar_signature_without_calling_tar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "unknown.rar"
    archive.write_bytes(b"not-a-rar")

    def fail_if_tar_is_called(*args: object, **kwargs: object) -> None:
        pytest.fail("tar must not be called before archive signature validation")

    monkeypatch.setattr(
        "src.calculation_book.archive.subprocess.run",
        fail_if_tar_is_called,
    )

    with pytest.raises(InvalidCalculationArchive, match="无法识别.*签名"):
        validate_and_extract_archive(archive, tmp_path / "extracted")


def test_validation_fails_closed_for_7z_before_calling_tar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "input.7z"
    archive.write_bytes(b"7z\xbc\xaf'\x1cpayload")

    def fail_if_tar_is_called(*args: object, **kwargs: object) -> None:
        pytest.fail("7z must not be routed through the legacy RAR tar path")

    monkeypatch.setattr(
        "src.calculation_book.archive.subprocess.run",
        fail_if_tar_is_called,
    )

    with pytest.raises(InvalidCalculationArchive, match="私有解包器.*(?:尚未接入|不可用)"):
        validate_and_extract_archive(archive, tmp_path / "extracted")


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
    "reinforcement_source",
    [ReinforcementSource.PROVIDED, ReinforcementSource.AI_SUGGESTED],
)
def test_rejects_incomplete_five_figure_slab_group_for_each_source(
    tmp_path: Path,
    reinforcement_source: ReinforcementSource,
) -> None:
    entries = _valid_entries()
    if reinforcement_source is ReinforcementSource.AI_SUGGESTED:
        entries.pop("计算书模板文件.xlsx")
    for name in (
        "11.2-TOP-X.png",
        "11.2-TOP-Y.png",
        "11.2-BOTTOM-X.png",
        "11.2-BOTTOM-Y.png",
    ):
        entries[name] = name.encode()
    archive = _write_archive(tmp_path / "incomplete-slab.zip", entries)

    with pytest.raises(InvalidCalculationArchive, match="11.2.*Z"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            reinforcement_source=reinforcement_source,
        )


def test_rejects_unpaired_middle_slab_figure(tmp_path: Path) -> None:
    entries = _valid_entries()
    for name in (
        "11.2-TOP-X.png",
        "11.2-TOP-Y.png",
        "11.2-MIDDLE-X.png",
        "11.2-BOTTOM-X.png",
        "11.2-BOTTOM-Y.png",
        "11.2-Z.png",
    ):
        entries[name] = name.encode()
    archive = _write_archive(tmp_path / "unpaired-middle-slab.zip", entries)

    with pytest.raises(InvalidCalculationArchive, match="MIDDLE-X/Y.*成对"):
        validate_and_extract_archive(archive, tmp_path / "extracted")


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


@pytest.mark.parametrize(
    "reinforcement_source",
    [ReinforcementSource.PROVIDED, ReinforcementSource.AI_SUGGESTED],
)
def test_rejects_duplicate_wall_direction_across_image_extensions(
    tmp_path: Path,
    reinforcement_source: ReinforcementSource,
) -> None:
    entries = _valid_entries()
    if reinforcement_source is ReinforcementSource.AI_SUGGESTED:
        entries.pop("计算书模板文件.xlsx")
    entries["RX1-X.jpg"] = b"duplicate-x"
    archive = _write_archive(tmp_path / "duplicate-direction.zip", entries)

    with pytest.raises(InvalidCalculationArchive, match="RX1.*重复.*X"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            reinforcement_source=reinforcement_source,
        )


@pytest.mark.parametrize(
    "reinforcement_source",
    [ReinforcementSource.AI_SUGGESTED, "ai_suggested"],
)
def test_ai_suggested_accepts_archive_without_reinforcement_workbook(
    tmp_path: Path,
    reinforcement_source: ReinforcementSource | str,
) -> None:
    entries = _valid_entries()
    entries.pop("计算书模板文件.xlsx")
    archive = _write_archive(tmp_path / "ai-suggested.zip", entries)

    contents = validate_and_extract_archive(
        archive,
        tmp_path / "extracted",
        reinforcement_source=reinforcement_source,
    )

    assert contents.reinforcement_workbook is None


def test_rejects_unknown_reinforcement_source(tmp_path: Path) -> None:
    archive = _write_archive(tmp_path / "unknown-source.zip", _valid_entries())

    with pytest.raises(ValueError, match="unsupported.*ReinforcementSource"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            reinforcement_source="unsupported",
        )


def test_ai_suggested_rejects_any_root_reinforcement_workbook(
    tmp_path: Path,
) -> None:
    archive = _write_archive(tmp_path / "ai-with-workbook.zip", _valid_entries())

    with pytest.raises(
        InvalidCalculationArchive,
        match="无实配钢筋模式不得包含.*(?:Excel|配筋表)",
    ):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            reinforcement_source=ReinforcementSource.AI_SUGGESTED,
        )


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
