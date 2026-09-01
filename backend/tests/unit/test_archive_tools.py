from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from src.archive_tools import (
    ArchiveFormat,
    ArchiveLimits,
    InvalidArchive,
    detect_archive_format,
    extract_archive,
)
from tests.archive_test_helpers import build_legacy_gbk_zip


def test_real_gbk_zip_extracts_readable_chinese_pdf_names(tmp_path: Path) -> None:
    archive_path = tmp_path / "legacy-gbk.zip"
    archive_path.write_bytes(
        build_legacy_gbk_zip(
            (f"附图{index} 钢衬里筒壁{index}.pdf", b"%PDF-1.4\n")
            for index in range(1, 11)
        )
    )
    result = extract_archive(
        archive_path,
        tmp_path / "extracted",
        limits=ArchiveLimits(max_files=50),
        zip_metadata_encodings=("utf-8", "gbk"),
    )

    pdf_names = sorted(path.name for path in result.files if path.suffix.lower() == ".pdf")

    assert result.archive_format is ArchiveFormat.ZIP
    assert len(pdf_names) == 10
    assert any(name.startswith("附图1") and "钢衬里筒壁" in name for name in pdf_names)
    assert not any("╕" in name or "╜" in name for name in pdf_names)


def test_rejects_archive_suffix_and_signature_mismatch(tmp_path: Path) -> None:
    archive_path = tmp_path / "fake.rar"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("one.pdf", b"not important")

    with pytest.raises(InvalidArchive, match="后缀与文件签名不一致"):
        detect_archive_format(archive_path)


def test_rejects_parent_path_member_without_writing_outside_destination(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.pdf", b"unsafe")

    destination = tmp_path / "extracted"
    with pytest.raises(InvalidArchive, match="不安全路径"):
        extract_archive(archive_path, destination)

    assert not (tmp_path / "outside.pdf").exists()


def test_rejects_zip_bomb_by_compression_ratio(tmp_path: Path) -> None:
    archive_path = tmp_path / "bomb.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("large.pdf", b"0" * 100_000, compress_type=8)

    with pytest.raises(InvalidArchive, match="压缩比异常"):
        extract_archive(
            archive_path,
            tmp_path / "extracted",
            limits=ArchiveLimits(max_compression_ratio=2.0),
        )
