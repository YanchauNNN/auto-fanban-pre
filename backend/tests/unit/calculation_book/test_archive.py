from __future__ import annotations

import os
import stat
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.calculation_book import archive as archive_module
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


def _write_external_archive(path: Path) -> Path:
    if path.suffix.lower() == ".rar":
        path.write_bytes(b"Rar!\x1a\x07\x01\x00payload")
    else:
        path.write_bytes(b"7z\xbc\xaf'\x1cpayload")
    return path


def _extractor_settings(
    tmp_path: Path,
    *,
    executable: Path | None = None,
    list_timeout_seconds: int = 17,
    extract_timeout_seconds: int = 29,
    max_list_output_bytes: int = 8_388_608,
) -> SimpleNamespace:
    active_executable = executable or (tmp_path / "private 7-Zip" / "7z.exe")
    if executable is None:
        active_executable.parent.mkdir(parents=True)
        active_executable.write_bytes(b"private-seven-zip")
    return SimpleNamespace(
        executable=active_executable,
        list_timeout_seconds=list_timeout_seconds,
        extract_timeout_seconds=extract_timeout_seconds,
        max_list_output_bytes=max_list_output_bytes,
    )


def _slt_listing(
    files: dict[str, bytes],
    *,
    directories: tuple[str, ...] = ("01", "02"),
    archive_fields: dict[str, str] | None = None,
    item_fields: dict[str, dict[str, str]] | None = None,
    omit_packed_size_for: set[str] | None = None,
) -> bytes:
    metadata = {
        "Path": "input archive.rar",
        "Type": "Rar5",
        "Physical Size": "1024",
        "Solid": "+",
        "Blocks": "1",
        "Encrypted": "-",
        "Multivolume": "-",
        "Volumes": "1",
    }
    metadata.update(archive_fields or {})
    records = ["\n".join(f"{key} = {value}" for key, value in metadata.items())]
    for directory in directories:
        records.append(
            "\n".join(
                (
                    f"Path = {directory}",
                    "Size = 0",
                    "Packed Size = 0",
                    "Attributes = D",
                    "Folder = +",
                    "Encrypted = -",
                )
            )
        )
    for name, payload in files.items():
        fields = {
            "Path": name,
            "Size": str(len(payload)),
            "Attributes": "A",
            "Folder": "-",
            "Encrypted": "-",
        }
        if name not in (omit_packed_size_for or set()):
            fields["Packed Size"] = str(max(len(payload), 1))
        fields.update((item_fields or {}).get(name, {}))
        records.append("\n".join(f"{key} = {value}" for key, value in fields.items()))
    return ("\n\n----------\n\n" + "\n\n".join(records) + "\n").encode("utf-8")


def _mock_external_run(
    monkeypatch: pytest.MonkeyPatch,
    listing: bytes,
    extracted_files: dict[str, bytes] | None,
    *,
    list_result: subprocess.CompletedProcess[bytes] | None = None,
    extract_result: subprocess.CompletedProcess[bytes] | None = None,
) -> list[tuple[list[str], dict[str, Any]]]:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    class FakeListingProcess:
        def __init__(self, args: list[str], **kwargs: Any) -> None:
            calls.append((args, kwargs))
            result = list_result or subprocess.CompletedProcess(args, 0, listing, b"")
            kwargs["stdout"].write(result.stdout)
            kwargs["stdout"].flush()
            kwargs["stderr"].write(result.stderr)
            kwargs["stderr"].flush()
            self.returncode = result.returncode

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

        def terminate(self) -> None:
            calls.append((["<terminate-listing>"], {}))

        def kill(self) -> None:
            return None

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, kwargs))
        assert args[1] == "x"
        output_argument = next(argument for argument in args if argument.startswith("-o"))
        output_root = Path(output_argument[2:])
        for name, payload in (extracted_files or {}).items():
            target = output_root.joinpath(*name.replace("\\", "/").split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        return extract_result or subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr("src.calculation_book.archive.subprocess.Popen", FakeListingProcess)
    monkeypatch.setattr("src.calculation_book.archive.subprocess.run", fake_run)
    return calls


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


@pytest.mark.parametrize("suffix", [".rar", ".7z"])
def test_external_archive_uses_private_7zip_with_utf8_and_yaml_timeouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    archive = _write_external_archive(tmp_path / f"input archive{suffix}")
    settings = _extractor_settings(tmp_path)
    entries = _valid_entries()
    listing = _slt_listing(
        entries,
        omit_packed_size_for={"01/layout.png"},
    )
    calls = _mock_external_run(monkeypatch, listing, entries)

    contents = validate_and_extract_archive(
        archive,
        tmp_path / "destination with spaces",
        archive_extractor=settings,
    )

    assert contents.layout_image.read_bytes() == b"layout"
    assert contents.model_image.read_bytes() == b"model"
    assert len(calls) == 2
    list_args, list_kwargs = calls[0]
    assert list_args == [
        str(settings.executable.resolve()),
        "l",
        "-slt",
        "-sccUTF-8",
        "-bd",
        str(archive),
    ]
    assert list_kwargs["stdin"] is subprocess.DEVNULL
    assert list_kwargs["creationflags"] == int(
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    assert list_kwargs["shell"] is False
    assert list_kwargs["stdout"].closed
    assert list_kwargs["stderr"].closed
    assert "capture_output" not in list_kwargs
    extract_args, extract_kwargs = calls[1]
    assert extract_args == [
        str(settings.executable.resolve()),
        "x",
        "-y",
        "-bd",
        "-bb0",
        "-sccUTF-8",
        f"-o{tmp_path / 'destination with spaces'}",
        str(archive),
    ]
    assert extract_kwargs == {
        "check": False,
        "capture_output": True,
        "stdin": subprocess.DEVNULL,
        "timeout": 29,
        "creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        "shell": False,
    }


@pytest.mark.parametrize("relative_name", ["-input.rar", "@input.7z"])
def test_external_archive_resolves_switch_like_relative_paths_before_7zip_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_name: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    archive = _write_external_archive(Path(relative_name))
    resolved_archive = archive.resolve(strict=True)
    settings = _extractor_settings(tmp_path)
    entries = _valid_entries()
    calls = _mock_external_run(monkeypatch, _slt_listing(entries), entries)

    validate_and_extract_archive(
        archive,
        tmp_path / "extracted",
        archive_extractor=settings,
    )

    assert len(calls) == 2
    for args, _ in calls:
        assert args[-1] == str(resolved_archive)
        assert Path(args[-1]).is_absolute()
        assert not args[-1].startswith(("-", "@"))
        assert relative_name not in args


@pytest.mark.parametrize("unsafe_kind", ["symlink", "reparse"])
def test_external_archive_rejects_unsafe_archive_file_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    archive = _write_external_archive(tmp_path / "unsafe-input.rar")
    settings = _extractor_settings(tmp_path)
    archive_size = archive.stat().st_size
    if unsafe_kind == "symlink":
        real_lstat = Path.lstat
        archive_absolute = Path(os.path.abspath(archive))

        def mark_archive_as_symlink(path: Path) -> os.stat_result:
            file_stat = real_lstat(path)
            if Path(os.path.abspath(path)) != archive_absolute:
                return file_stat
            values = list(file_stat)
            values[0] = stat.S_IFLNK | 0o777
            return os.stat_result(values)

        monkeypatch.setattr(Path, "lstat", mark_archive_as_symlink)
    else:
        real_is_reparse_point = archive_module._is_reparse_point

        def mark_archive_as_reparse(file_stat: os.stat_result) -> bool:
            return (
                stat.S_ISREG(file_stat.st_mode)
                and file_stat.st_size == archive_size
            ) or real_is_reparse_point(file_stat)

        monkeypatch.setattr(
            "src.calculation_book.archive._is_reparse_point",
            mark_archive_as_reparse,
        )

    def fail_if_called(*args: object, **kwargs: object) -> None:
        pytest.fail("7-Zip must not run for an unsafe archive path")

    monkeypatch.setattr("src.calculation_book.archive.subprocess.run", fail_if_called)

    with pytest.raises(InvalidCalculationArchive, match="归档文件.*不安全"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )


def test_external_archive_rejects_directory_archive_path_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_directory = tmp_path / "directory.rar"
    archive_directory.mkdir()
    settings = _extractor_settings(tmp_path)

    def fail_if_called(*args: object, **kwargs: object) -> None:
        pytest.fail("7-Zip must not run for an archive directory")

    monkeypatch.setattr("src.calculation_book.archive.subprocess.run", fail_if_called)

    with pytest.raises(InvalidCalculationArchive, match="归档文件.*普通文件"):
        archive_module._extract_external_archive(
            archive_directory,
            tmp_path / "extracted",
            ArchiveLimits(),
            archive_format=ArchiveFormat.RAR,
            archive_extractor=settings,
        )


@pytest.mark.parametrize(
    ("executable", "message"),
    [
        (Path("bin/7-Zip/7z.exe"), "绝对路径"),
        (Path("C:/missing-private-7zip/7z.exe"), "不存在"),
    ],
)
def test_external_archive_rejects_non_absolute_or_missing_private_extractor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    executable: Path,
    message: str,
) -> None:
    archive = _write_external_archive(tmp_path / "input.rar")

    def fail_if_called(*args: object, **kwargs: object) -> None:
        pytest.fail("no executable discovery or subprocess call is allowed")

    monkeypatch.setattr("src.calculation_book.archive.subprocess.run", fail_if_called)
    monkeypatch.setattr("src.calculation_book.archive.shutil.which", fail_if_called)

    with pytest.raises(InvalidCalculationArchive, match=message):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=_extractor_settings(tmp_path, executable=executable),
        )


def test_external_archive_rejects_list_timeout_without_running_extract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_external_archive(tmp_path / "input.7z")
    settings = _extractor_settings(tmp_path)
    calls: list[list[str]] = []

    class HangingListingProcess:
        def __init__(self, args: list[str], **kwargs: Any) -> None:
            calls.append(args)

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd="7z", timeout=timeout)

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

    monotonic_values = iter((0.0, 18.0))
    monkeypatch.setattr(
        "src.calculation_book.archive.subprocess.Popen",
        HangingListingProcess,
    )
    monkeypatch.setattr(
        "src.calculation_book.archive.time.monotonic",
        lambda: next(monotonic_values),
    )

    with pytest.raises(InvalidCalculationArchive, match="清单读取超时"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 1


@pytest.mark.parametrize(
    ("stderr", "message"),
    [
        (b"ERROR: Can not open the file as archive", "损坏|格式无效"),
        (b"ERROR: Data Error\nprivate/member/secret.png", "读取失败"),
    ],
)
def test_external_archive_rejects_7zip_list_errors_without_leaking_member_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stderr: bytes,
    message: str,
) -> None:
    archive = _write_external_archive(tmp_path / "input.rar")
    settings = _extractor_settings(tmp_path)
    result = subprocess.CompletedProcess(["7z"], 2, b"", stderr + b"X" * 2_000)
    calls = _mock_external_run(
        monkeypatch,
        b"",
        None,
        list_result=result,
    )

    with pytest.raises(InvalidCalculationArchive, match=message) as exc_info:
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert "secret.png" not in str(exc_info.value)
    assert len(str(exc_info.value)) < 600
    assert len(calls) == 1


def test_external_archive_rejects_unparseable_7zip_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_external_archive(tmp_path / "input.7z")
    settings = _extractor_settings(tmp_path)
    calls = _mock_external_run(monkeypatch, b"arbitrary banner only", None)

    with pytest.raises(InvalidCalculationArchive, match="清单.*无法解析"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 1


def test_external_archive_rejects_oversized_listing_before_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_external_archive(tmp_path / "oversized-listing.7z")
    settings = _extractor_settings(tmp_path, max_list_output_bytes=32)
    entries = _valid_entries()
    calls = _mock_external_run(monkeypatch, _slt_listing(entries), None)

    with pytest.raises(InvalidCalculationArchive, match="清单输出超过限制"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 2
    assert calls[1][0] == ["<terminate-listing>"]


def test_external_archive_rejects_extract_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_external_archive(tmp_path / "input.rar")
    settings = _extractor_settings(tmp_path)
    listing = _slt_listing(_valid_entries())
    calls = _mock_external_run(monkeypatch, listing, None)

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired(cmd="7z", timeout=29)

    monkeypatch.setattr("src.calculation_book.archive.subprocess.run", fake_run)

    with pytest.raises(InvalidCalculationArchive, match="解压超时"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 2


def test_external_archive_rejects_extract_error_without_leaking_member_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_external_archive(tmp_path / "input.7z")
    settings = _extractor_settings(tmp_path)
    listing = _slt_listing(_valid_entries())
    extract_result = subprocess.CompletedProcess(
        ["7z"],
        2,
        b"",
        b"ERROR: Data Error\nprivate/member/secret.png" + b"X" * 2_000,
    )
    calls = _mock_external_run(
        monkeypatch,
        listing,
        None,
        extract_result=extract_result,
    )

    with pytest.raises(InvalidCalculationArchive, match="解压失败") as exc_info:
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert "secret.png" not in str(exc_info.value)
    assert len(str(exc_info.value)) < 600
    assert len(calls) == 2


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
        "//server/share/unsafe.png",
        "bad\x01name.png",
        "image.png:secret",
        "CON",
        "folder/aux.txt",
        "folder/LPT1.png",
        "trailing-dot./image.png",
        "trailing-space /image.png",
        "bad*name.png",
        "bad?name.png",
        'bad"name.png',
        "bad<name.png",
        "bad>name.png",
        "bad|name.png",
        "COM¹.txt",
        "folder/LPT¹.png",
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


def test_zip_rejects_case_insensitive_duplicate_targets(tmp_path: Path) -> None:
    entries = _valid_entries()
    entries["A.png"] = b"first"
    entries["a.PNG"] = b"second"
    archive = _write_archive(tmp_path / "duplicate-case.zip", entries)

    with pytest.raises(InvalidCalculationArchive, match="重复路径"):
        validate_and_extract_archive(archive, tmp_path / "extracted")


def test_zip_counts_directories_toward_entry_limit(tmp_path: Path) -> None:
    entries = _valid_entries()
    entries["extra-directory/"] = b""
    archive = _write_archive(tmp_path / "directory-limit.zip", entries)

    with pytest.raises(InvalidCalculationArchive, match="条目数量.*6"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            limits=ArchiveLimits(max_files=6),
        )


def test_zip_rejects_symbolic_link_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, payload in _valid_entries().items():
            archive.writestr(name, payload)
        link = zipfile.ZipInfo("unsafe-link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, b"RX1-X.png")

    with pytest.raises(InvalidCalculationArchive, match="不安全文件类型"):
        validate_and_extract_archive(archive_path, tmp_path / "extracted")


@pytest.mark.parametrize("file_first", [True, False])
def test_zip_rejects_file_directory_prefix_conflicts_before_writing(
    tmp_path: Path,
    file_first: bool,
) -> None:
    entries = _valid_entries()
    conflicting = [
        ("conflict", b"file"),
        ("conflict/child.png", b"child"),
    ]
    if not file_first:
        conflicting.reverse()
    entries.update(conflicting)
    archive = _write_archive(tmp_path / "prefix-conflict.zip", entries)
    destination = tmp_path / "extracted"

    with pytest.raises(InvalidCalculationArchive, match="文件与目录路径冲突"):
        validate_and_extract_archive(archive, destination)

    assert not destination.exists() or not any(destination.iterdir())


@pytest.mark.parametrize(
    "failure",
    [
        zipfile.BadZipFile("Bad CRC-32 for file"),
        OSError("simulated ZIP read/write failure"),
    ],
)
def test_zip_wraps_crc_and_os_errors_without_leaving_partial_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    archive = _write_archive(tmp_path / "broken-read.zip", _valid_entries())
    destination = tmp_path / "extracted"

    def fail_copy(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr("src.calculation_book.archive.shutil.copyfileobj", fail_copy)

    with pytest.raises(InvalidCalculationArchive, match="ZIP.*解压失败"):
        validate_and_extract_archive(archive, destination)

    assert not destination.exists() or not any(destination.iterdir())


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "../outside.png",
        "/absolute.png",
        "C:/windows/system32/unsafe.png",
        "\\\\server\\share\\unsafe.png",
        "bad\x01name.png",
        "image.png:secret",
        "CON",
        "folder/aux.txt",
        "folder/LPT1.png",
        "trailing-dot./image.png",
        "trailing-space /image.png",
        "bad*name.png",
        "bad?name.png",
        'bad"name.png',
        "bad<name.png",
        "bad>name.png",
        "bad|name.png",
        "COM¹.txt",
        "folder/LPT¹.png",
    ],
)
def test_external_archive_rejects_unsafe_member_paths_before_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_name: str,
) -> None:
    archive = _write_external_archive(tmp_path / "unsafe.rar")
    settings = _extractor_settings(tmp_path)
    listing = _slt_listing({unsafe_name: b"unsafe"}, directories=())
    calls = _mock_external_run(monkeypatch, listing, None)

    with pytest.raises(InvalidCalculationArchive, match="不安全路径"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 1
    assert not (tmp_path / "outside.png").exists()


def test_external_archive_rejects_case_insensitive_duplicate_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_external_archive(tmp_path / "duplicate.7z")
    settings = _extractor_settings(tmp_path)
    listing = _slt_listing({"A.png": b"a", "a.PNG": b"b"}, directories=())
    calls = _mock_external_run(monkeypatch, listing, None)

    with pytest.raises(InvalidCalculationArchive, match="重复路径"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 1


@pytest.mark.parametrize("file_first", [True, False])
def test_external_archive_rejects_file_directory_prefix_conflicts_before_extract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_first: bool,
) -> None:
    archive = _write_external_archive(tmp_path / "prefix-conflict.rar")
    settings = _extractor_settings(tmp_path)
    conflicting = [
        ("conflict", b"file"),
        ("conflict/child.png", b"child"),
    ]
    if not file_first:
        conflicting.reverse()
    listing = _slt_listing(dict(conflicting), directories=())
    calls = _mock_external_run(monkeypatch, listing, None)

    with pytest.raises(InvalidCalculationArchive, match="文件与目录路径冲突"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 1


@pytest.mark.parametrize(
    "unsafe_fields",
    [
        {"Symbolic Link": "target.png"},
        {"Hard Link": "target.png"},
        {"Alternate Stream": "+"},
        {"Reparse": "+"},
        {"Attributes": "_ lrwxrwxrwx"},
        {"Type": "Character Device"},
    ],
)
def test_external_archive_rejects_links_streams_reparse_and_special_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_fields: dict[str, str],
) -> None:
    archive = _write_external_archive(tmp_path / "unsafe-type.rar")
    settings = _extractor_settings(tmp_path)
    name = "unsafe.png"
    listing = _slt_listing(
        {name: b"unsafe"},
        directories=(),
        item_fields={name: unsafe_fields},
    )
    calls = _mock_external_run(monkeypatch, listing, None)

    with pytest.raises(InvalidCalculationArchive, match="不安全文件类型"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 1


@pytest.mark.parametrize(
    ("archive_fields", "item_fields", "message"),
    [
        ({"Encrypted": "+"}, {}, "加密"),
        ({}, {"Encrypted": "+"}, "加密"),
        ({"Volumes": "2"}, {}, "分卷"),
        ({"Multivolume": "+"}, {}, "分卷"),
        ({}, {"Volume Index": "1"}, "分卷"),
    ],
)
def test_external_archive_rejects_encryption_and_multivolume_archives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    archive_fields: dict[str, str],
    item_fields: dict[str, str],
    message: str,
) -> None:
    archive = _write_external_archive(tmp_path / "unsupported.7z")
    settings = _extractor_settings(tmp_path)
    name = "file.png"
    listing = _slt_listing(
        {name: b"x"},
        directories=(),
        archive_fields=archive_fields,
        item_fields={name: item_fields},
    )
    calls = _mock_external_run(monkeypatch, listing, None)

    with pytest.raises(InvalidCalculationArchive, match=message):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 1


@pytest.mark.parametrize(
    ("files", "directories", "limits", "message"),
    [
        ({}, (), ArchiveLimits(), "没有文件"),
        ({"a": b"x"}, ("d",), ArchiveLimits(max_files=1), "条目数量"),
        ({"a": b"xx"}, (), ArchiveLimits(max_single_file_bytes=1), "单个文件"),
        (
            {"a": b"xx", "b": b"yy"},
            (),
            ArchiveLimits(max_total_bytes=3),
            "总大小",
        ),
        ({"a": b"x" * 20}, (), ArchiveLimits(max_compression_ratio=1.0), "压缩比"),
    ],
)
def test_external_archive_enforces_entry_size_and_ratio_limits_before_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, bytes],
    directories: tuple[str, ...],
    limits: ArchiveLimits,
    message: str,
) -> None:
    archive = _write_external_archive(tmp_path / "limited.rar")
    settings = _extractor_settings(tmp_path)
    listing = _slt_listing(files, directories=directories)
    calls = _mock_external_run(monkeypatch, listing, None)

    with pytest.raises(InvalidCalculationArchive, match=message):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
            limits=limits,
        )

    assert len(calls) == 1


@pytest.mark.parametrize("mutation", ["extra", "missing", "wrong-size"])
def test_external_archive_postcheck_requires_exact_declared_file_set_and_sizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    archive = _write_external_archive(tmp_path / "postcheck.7z")
    settings = _extractor_settings(tmp_path)
    declared = _valid_entries()
    extracted = dict(declared)
    if mutation == "extra":
        extracted["unexpected.txt"] = b"extra"
    elif mutation == "missing":
        extracted.pop("RX1-Z.png")
    else:
        extracted["RX1-Y.png"] = b"wrong-size"
    calls = _mock_external_run(monkeypatch, _slt_listing(declared), extracted)

    with pytest.raises(InvalidCalculationArchive, match="解压后校验失败"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 2


def test_external_archive_postcheck_rejects_reparse_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_external_archive(tmp_path / "postcheck-reparse.rar")
    settings = _extractor_settings(tmp_path)
    entries = _valid_entries()
    calls = _mock_external_run(monkeypatch, _slt_listing(entries), entries)
    real_is_reparse_point = archive_module._is_reparse_point

    def mark_layout_as_reparse(file_stat: os.stat_result) -> bool:
        return (
            stat.S_ISREG(file_stat.st_mode)
            and file_stat.st_size == len(entries["01/layout.png"])
        ) or real_is_reparse_point(file_stat)

    monkeypatch.setattr(
        "src.calculation_book.archive._is_reparse_point",
        mark_layout_as_reparse,
    )

    with pytest.raises(InvalidCalculationArchive, match="解压后校验失败"):
        validate_and_extract_archive(
            archive,
            tmp_path / "extracted",
            archive_extractor=settings,
        )

    assert len(calls) == 2


def test_external_archive_rejects_non_empty_destination_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _write_external_archive(tmp_path / "input.rar")
    settings = _extractor_settings(tmp_path)
    destination = tmp_path / "not-empty"
    destination.mkdir()
    (destination / "existing.txt").write_text("keep", encoding="utf-8")

    def fail_if_called(*args: object, **kwargs: object) -> None:
        pytest.fail("subprocess must not run for a non-empty destination")

    monkeypatch.setattr("src.calculation_book.archive.subprocess.run", fail_if_called)

    with pytest.raises(InvalidCalculationArchive, match="目标目录.*为空"):
        validate_and_extract_archive(
            archive,
            destination,
            archive_extractor=settings,
        )


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
