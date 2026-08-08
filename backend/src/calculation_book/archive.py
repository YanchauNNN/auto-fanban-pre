from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import unicodedata
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Protocol

from .models import ReinforcementSource

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}
_FIGURE_NAME = re.compile(
    r"^(?P<prefix>[A-Za-z]+)(?P<number>\d+)(?P<suffix>[A-Za-z]?)"
    r"(?:-(?P<group>[12]))?-(?P<direction>[XYZ])$",
    re.IGNORECASE,
)
_SLAB_LAYER_FIGURE_NAME = re.compile(
    r"^(?P<elevation>[+-]?\d+(?:\.\d+)?)-"
    r"(?P<position>TOP|MIDDLE|BOTTOM)-(?P<direction>[XY])$",
    re.IGNORECASE,
)
_PARENTHETICAL_FIGURE_NAME = re.compile(
    r"^[^()]+\((?P<prefix>[A-Za-z]+)(?P<number>\d+)"
    r"(?P<suffix>[A-Za-z]?)(?:-(?P<group>[12]))?\)"
    r"-(?P<direction>[XYZ])$",
    re.IGNORECASE,
)
_SLAB_Z_FIGURE_NAME = re.compile(
    r"^(?P<elevation>[+-]?\d+(?:\.\d+)?)-Z$",
    re.IGNORECASE,
)


class InvalidCalculationArchive(ValueError):
    pass


class ArchiveFormat(StrEnum):
    ZIP = "zip"
    RAR = "rar"
    SEVEN_Z = "7z"


_ARCHIVE_FORMAT_BY_SUFFIX = {
    ".zip": ArchiveFormat.ZIP,
    ".rar": ArchiveFormat.RAR,
    ".7z": ArchiveFormat.SEVEN_Z,
}
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_RAR4_SIGNATURE = b"Rar!\x1a\x07\x00"
_RAR5_SIGNATURE = b"Rar!\x1a\x07\x01\x00"
_SEVEN_Z_SIGNATURE = b"7z\xbc\xaf'\x1c"


def detect_archive_format(archive_path: Path) -> ArchiveFormat:
    """Validate the filename suffix against the archive magic bytes."""
    suffix = archive_path.suffix.lower()
    suffix_format = _ARCHIVE_FORMAT_BY_SUFFIX.get(suffix)
    if suffix_format is None:
        raise InvalidCalculationArchive(f"不支持的压缩包后缀：{suffix or '无后缀'}")

    try:
        with archive_path.open("rb") as archive_file:
            header = archive_file.read(8)
    except OSError as exc:
        raise InvalidCalculationArchive("压缩包文件读取失败") from exc

    if header.startswith(_ZIP_SIGNATURES):
        signature_format = ArchiveFormat.ZIP
    elif header.startswith((_RAR4_SIGNATURE, _RAR5_SIGNATURE)):
        signature_format = ArchiveFormat.RAR
    elif header.startswith(_SEVEN_Z_SIGNATURE):
        signature_format = ArchiveFormat.SEVEN_Z
    else:
        raise InvalidCalculationArchive("无法识别压缩包签名")

    if suffix_format is not signature_format:
        raise InvalidCalculationArchive(
            "压缩包后缀与文件签名不一致："
            f"{suffix} / {signature_format.value}"
        )
    return signature_format


@dataclass(frozen=True)
class ArchiveLimits:
    max_files: int = 500
    max_total_bytes: int = 1024 * 1024 * 1024
    max_single_file_bytes: int = 50 * 1024 * 1024
    max_compression_ratio: float = 250.0


class ArchiveExtractorSettings(Protocol):
    executable: Path
    list_timeout_seconds: int
    extract_timeout_seconds: int
    max_list_output_bytes: int


@dataclass(frozen=True)
class _ArchiveMember:
    path: PurePosixPath
    size: int
    is_directory: bool


@dataclass(frozen=True)
class ReinforcementFigure:
    wall_id: str
    base_wall_id: str
    group_index: int | None
    direction: str
    path: Path
    sort_key: tuple[int, str, int, int, str]


@dataclass(frozen=True)
class SlabReinforcementFigure:
    elevation: str
    position: str | None
    direction: str
    path: Path
    sort_key: tuple[Decimal, int, int]


@dataclass(frozen=True)
class CalculationArchiveContents:
    root: Path
    reinforcement_figures: tuple[ReinforcementFigure, ...]
    slab_figures: tuple[SlabReinforcementFigure, ...]
    ignored_root_images: tuple[Path, ...]
    reinforcement_workbook: Path | None
    layout_image: Path
    model_image: Path
    extracted_files: tuple[Path, ...]

    @property
    def requires_manual_confirmation(self) -> bool:
        return any(
            figure.group_index is not None
            for figure in self.reinforcement_figures
        )


_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_SEVEN_Z_SAFE_FALSE_VALUES = {"", "-", "0", "false", "no"}
_SEVEN_Z_SAFE_TRUE_VALUES = {"+", "1", "true", "yes"}
_WINDOWS_FORBIDDEN_CHARACTERS = frozenset('*?"<>|')
_WINDOWS_DEVICE_DIGIT_TRANSLATION = str.maketrans({"¹": "1", "²": "2", "³": "3"})


def _normalized_member_path(raw_name: str, *, is_directory: bool) -> PurePosixPath:
    normalized = raw_name.replace("\\", "/")
    if is_directory:
        normalized = normalized.rstrip("/")
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
    ):
        raise InvalidCalculationArchive("压缩包包含不安全路径")

    raw_parts = normalized.split("/")
    if any(not part or part in {".", ".."} for part in raw_parts):
        raise InvalidCalculationArchive("压缩包包含不安全路径")
    for part in raw_parts:
        if any(ord(character) < 32 or ord(character) == 127 for character in part):
            raise InvalidCalculationArchive("压缩包包含不安全路径")
        if (
            ":" in part
            or any(character in _WINDOWS_FORBIDDEN_CHARACTERS for character in part)
            or part.endswith((".", " "))
        ):
            raise InvalidCalculationArchive("压缩包包含不安全路径")
        normalized_part = unicodedata.normalize("NFC", part)
        stem = normalized_part.split(".", 1)[0].upper().translate(
            _WINDOWS_DEVICE_DIGIT_TRANSLATION
        )
        if stem in _WINDOWS_RESERVED_NAMES:
            raise InvalidCalculationArchive("压缩包包含不安全路径")
    return PurePosixPath(*raw_parts)


def _member_key(member: PurePosixPath) -> str:
    return "/".join(
        unicodedata.normalize("NFC", part).casefold()
        for part in member.parts
    )


def _validate_member_topology(members: list[_ArchiveMember]) -> None:
    file_keys = {
        _member_key(member.path)
        for member in members
        if not member.is_directory
    }
    for member in members:
        key_parts = _member_key(member.path).split("/")
        for part_count in range(1, len(key_parts)):
            if "/".join(key_parts[:part_count]) in file_keys:
                raise InvalidCalculationArchive("压缩包存在文件与目录路径冲突")


def _is_reparse_point(file_stat: os.stat_result) -> bool:
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    attributes = int(getattr(file_stat, "st_file_attributes", 0))
    return bool(attributes & reparse_flag)


def _is_unsafe_file_stat(file_stat: os.stat_result) -> bool:
    return stat.S_ISLNK(file_stat.st_mode) or _is_reparse_point(file_stat)


def _prepare_destination(destination: Path) -> Path:
    if destination.exists() or destination.is_symlink():
        destination_stat = destination.lstat()
        if (
            _is_unsafe_file_stat(destination_stat)
            or not stat.S_ISDIR(destination_stat.st_mode)
        ):
            raise InvalidCalculationArchive("压缩包解压目标目录不安全")
        if any(destination.iterdir()):
            raise InvalidCalculationArchive("压缩包解压目标目录必须为空")
    return destination.resolve()


def _verify_extracted_files(
    extraction_root: Path,
    expected_members: list[_ArchiveMember],
) -> list[Path]:
    resolved_root = extraction_root.resolve()
    root_stat = resolved_root.lstat()
    if _is_unsafe_file_stat(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise InvalidCalculationArchive("压缩包解压后校验失败")

    actual_by_key: dict[str, tuple[Path, int]] = {}
    pending_directories = [resolved_root]
    while pending_directories:
        current = pending_directories.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise InvalidCalculationArchive("压缩包解压后校验失败") from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise InvalidCalculationArchive("压缩包解压后校验失败") from exc
            if _is_unsafe_file_stat(entry_stat):
                raise InvalidCalculationArchive("压缩包解压后校验失败")
            if stat.S_ISDIR(entry_stat.st_mode):
                pending_directories.append(path)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                raise InvalidCalculationArchive("压缩包解压后校验失败")
            relative = path.relative_to(resolved_root)
            member = _normalized_member_path(relative.as_posix(), is_directory=False)
            key = _member_key(member)
            if key in actual_by_key:
                raise InvalidCalculationArchive("压缩包解压后校验失败")
            actual_by_key[key] = (path.resolve(), entry_stat.st_size)

    expected_files = [member for member in expected_members if not member.is_directory]
    expected_by_key = {_member_key(member.path): member for member in expected_files}
    if set(actual_by_key) != set(expected_by_key):
        raise InvalidCalculationArchive("压缩包解压后校验失败")
    for key, expected in expected_by_key.items():
        if actual_by_key[key][1] != expected.size:
            raise InvalidCalculationArchive("压缩包解压后校验失败")
    return [actual_by_key[_member_key(member.path)][0] for member in expected_files]


def _safe_zip_member(info: zipfile.ZipInfo) -> _ArchiveMember:
    member = _normalized_member_path(info.filename, is_directory=info.is_dir())
    unix_mode = info.external_attr >> 16
    unix_type = stat.S_IFMT(unix_mode)
    unsafe_unix_type = unix_type not in {0, stat.S_IFREG, stat.S_IFDIR}
    has_reparse_attribute = bool(info.external_attr & 0x400)
    if unsafe_unix_type or has_reparse_attribute:
        raise InvalidCalculationArchive("压缩包包含不安全文件类型")
    if info.flag_bits & 0x1:
        raise InvalidCalculationArchive("暂不支持加密压缩包")
    return _ArchiveMember(
        path=member,
        size=info.file_size,
        is_directory=info.is_dir(),
    )


def _extract_zip(
    archive_path: Path,
    destination: Path,
    limits: ArchiveLimits,
) -> tuple[Path, list[Path]]:
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InvalidCalculationArchive("上传文件不是有效的压缩包") from exc

    staging_root: Path | None = None
    try:
        with archive:
            infos = archive.infolist()
            if not infos:
                raise InvalidCalculationArchive("压缩包中没有文件")
            if len(infos) > limits.max_files:
                raise InvalidCalculationArchive(
                    f"压缩包条目数量超过限制 {limits.max_files}"
                )

            total_bytes = 0
            seen: set[str] = set()
            safe_members: list[tuple[zipfile.ZipInfo, _ArchiveMember]] = []
            for info in infos:
                member = _safe_zip_member(info)
                key = _member_key(member.path)
                if key in seen:
                    raise InvalidCalculationArchive("压缩包包含重复路径")
                seen.add(key)
                if not member.is_directory:
                    if member.size > limits.max_single_file_bytes:
                        raise InvalidCalculationArchive("压缩包中单个文件超过限制")
                    total_bytes += member.size
                    if total_bytes > limits.max_total_bytes:
                        raise InvalidCalculationArchive("压缩包解压后总大小超过限制")
                    if member.size > 0:
                        compressed = max(info.compress_size, 1)
                        if member.size / compressed > limits.max_compression_ratio:
                            raise InvalidCalculationArchive("压缩包压缩比异常")
                safe_members.append((info, member))

            members = [member for _, member in safe_members]
            if not any(not member.is_directory for member in members):
                raise InvalidCalculationArchive("压缩包中没有文件")
            _validate_member_topology(members)
            resolved_root = _prepare_destination(destination)
            resolved_root.parent.mkdir(parents=True, exist_ok=True)
            staging_root = Path(
                tempfile.mkdtemp(
                    prefix=".calculation-archive-",
                    dir=resolved_root.parent,
                )
            )
            for info, member in safe_members:
                target = staging_root.joinpath(*member.path.parts)
                if member.is_directory:
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            staged_extracted = _verify_extracted_files(staging_root, members)
            relative_extracted = [
                path.relative_to(staging_root)
                for path in staged_extracted
            ]
            if resolved_root.exists():
                resolved_root.rmdir()
            staging_root.replace(resolved_root)
            staging_root = None
            extracted = [
                resolved_root.joinpath(*relative.parts).resolve()
                for relative in relative_extracted
            ]
            return resolved_root, extracted
    except InvalidCalculationArchive:
        raise
    except (
        EOFError,
        NotImplementedError,
        OSError,
        RuntimeError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        raise InvalidCalculationArchive("ZIP 压缩包解压失败") from exc
    finally:
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)


def _parse_slt_records(payload: bytes) -> list[dict[str, str]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidCalculationArchive("压缩包清单无法解析") from exc

    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip("\r")
        if not line.strip() or set(line.strip()) <= {"-"}:
            if current:
                records.append(current)
                current = {}
            continue
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        key = key.strip()
        if not key or key in current:
            raise InvalidCalculationArchive("压缩包清单无法解析")
        current[key] = value
    if current:
        records.append(current)
    if not records:
        raise InvalidCalculationArchive("压缩包清单无法解析")
    return records


def _parse_slt_flag(value: str | None) -> bool:
    normalized = (value or "").strip().casefold()
    if normalized in _SEVEN_Z_SAFE_FALSE_VALUES:
        return False
    if normalized in _SEVEN_Z_SAFE_TRUE_VALUES:
        return True
    raise InvalidCalculationArchive("压缩包清单无法解析")


def _parse_nonnegative_size(value: str | None) -> int:
    try:
        parsed = int(value or "")
    except ValueError as exc:
        raise InvalidCalculationArchive("压缩包清单无法解析") from exc
    if parsed < 0:
        raise InvalidCalculationArchive("压缩包清单无法解析")
    return parsed


def _record_is_directory(record: dict[str, str]) -> bool:
    folder = record.get("Folder")
    if folder is not None:
        return _parse_slt_flag(folder)
    attributes = record.get("Attributes", "").strip()
    return attributes[:1].upper() == "D"


def _record_has_unsafe_type(record: dict[str, str]) -> bool:
    for field in ("Symbolic Link", "Hard Link"):
        value = record.get(field)
        if value is not None and value.strip().casefold() not in _SEVEN_Z_SAFE_FALSE_VALUES:
            return True
    for field in ("Alternate Stream", "Reparse"):
        if _parse_slt_flag(record.get(field)):
            return True
    item_type = record.get("Type", "").strip().casefold()
    if item_type and item_type not in {"file", "directory"}:
        return True
    attributes = record.get("Attributes", "").strip().casefold()
    return bool(re.search(r"(?:^|[\s_])[lbcps][rwx-]{9}(?:$|\s)", attributes))


def _validate_archive_metadata(records: list[dict[str, str]]) -> None:
    for record in records:
        if _parse_slt_flag(record.get("Encrypted")):
            raise InvalidCalculationArchive("暂不支持加密压缩包")
        if _parse_slt_flag(record.get("Multivolume")):
            raise InvalidCalculationArchive("暂不支持分卷压缩包")
        if _parse_slt_flag(record.get("Split Before")):
            raise InvalidCalculationArchive("暂不支持分卷压缩包")
        if _parse_slt_flag(record.get("Split After")):
            raise InvalidCalculationArchive("暂不支持分卷压缩包")
        volume_index = record.get("Volume Index")
        if volume_index is not None and volume_index.strip():
            raise InvalidCalculationArchive("暂不支持分卷压缩包")
        volumes = record.get("Volumes")
        if volumes is not None and _parse_nonnegative_size(volumes) != 1:
            raise InvalidCalculationArchive("暂不支持分卷压缩包")


def _members_from_slt_listing(
    payload: bytes,
    archive_path: Path,
    limits: ArchiveLimits,
) -> list[_ArchiveMember]:
    records = _parse_slt_records(payload)
    _validate_archive_metadata(records)
    item_records = [
        record
        for record in records
        if "Path" in record
        and "Physical Size" not in record
        and any(field in record for field in ("Size", "Folder", "Attributes"))
    ]
    if not item_records:
        raise InvalidCalculationArchive("压缩包中没有文件")
    if len(item_records) > limits.max_files:
        raise InvalidCalculationArchive(
            f"压缩包条目数量超过限制 {limits.max_files}"
        )

    total_bytes = 0
    seen: set[str] = set()
    members: list[_ArchiveMember] = []
    for record in item_records:
        is_directory = _record_is_directory(record)
        if _record_has_unsafe_type(record):
            raise InvalidCalculationArchive("压缩包包含不安全文件类型")
        member = _normalized_member_path(record["Path"], is_directory=is_directory)
        key = _member_key(member)
        if key in seen:
            raise InvalidCalculationArchive("压缩包包含重复路径")
        seen.add(key)
        size = _parse_nonnegative_size(record.get("Size"))
        if "Packed Size" in record:
            _parse_nonnegative_size(record["Packed Size"])
        if not is_directory:
            if size > limits.max_single_file_bytes:
                raise InvalidCalculationArchive("压缩包中单个文件超过限制")
            total_bytes += size
            if total_bytes > limits.max_total_bytes:
                raise InvalidCalculationArchive("压缩包解压后总大小超过限制")
        members.append(_ArchiveMember(member, size, is_directory))

    if not any(not member.is_directory for member in members):
        raise InvalidCalculationArchive("压缩包中没有文件")
    _validate_member_topology(members)
    archive_size = max(archive_path.stat().st_size, 1)
    if total_bytes / archive_size > limits.max_compression_ratio:
        raise InvalidCalculationArchive("压缩包总压缩比异常")
    return members


def _private_extractor(
    settings: ArchiveExtractorSettings | None,
) -> tuple[Path, int, int, int]:
    if settings is None:
        raise InvalidCalculationArchive("RAR/7z 私有解包器不可用")
    executable = Path(settings.executable)
    if not executable.is_absolute():
        raise InvalidCalculationArchive("RAR/7z 私有解包器必须使用绝对路径")
    if not executable.exists() or not executable.is_file():
        raise InvalidCalculationArchive("RAR/7z 私有解包器不存在")
    executable_stat = executable.lstat()
    if _is_unsafe_file_stat(executable_stat):
        raise InvalidCalculationArchive("RAR/7z 私有解包器路径不安全")
    list_timeout = settings.list_timeout_seconds
    extract_timeout = settings.extract_timeout_seconds
    max_list_output_bytes = settings.max_list_output_bytes
    if (
        not isinstance(list_timeout, int)
        or isinstance(list_timeout, bool)
        or list_timeout <= 0
        or not isinstance(extract_timeout, int)
        or isinstance(extract_timeout, bool)
        or extract_timeout <= 0
        or not isinstance(max_list_output_bytes, int)
        or isinstance(max_list_output_bytes, bool)
        or max_list_output_bytes <= 0
    ):
        raise InvalidCalculationArchive("RAR/7z 私有解包器安全参数无效")
    return (
        executable.resolve(),
        list_timeout,
        extract_timeout,
        max_list_output_bytes,
    )


def _seven_zip_failure_message(stderr: bytes, *, operation: str) -> str:
    detail = stderr[:500].decode("utf-8", errors="replace").casefold()
    if any(
        marker in detail
        for marker in ("can not open the file as archive", "unexpected end", "not archive")
    ):
        return "压缩包已损坏或格式无效"
    if "wrong password" in detail or "encrypted" in detail:
        return "暂不支持加密压缩包"
    return f"压缩包{operation}失败"


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    with suppress(OSError):
        process.terminate()
    try:
        process.wait(timeout=1)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    with suppress(OSError):
        process.kill()
    with suppress(OSError, subprocess.TimeoutExpired):
        process.wait(timeout=1)


def _run_limited_7zip_listing(
    command: list[str],
    *,
    timeout_seconds: int,
    max_output_bytes: int,
    creationflags: int,
) -> subprocess.CompletedProcess[bytes]:
    stderr_limit = 16_384
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=creationflags,
            shell=False,
        )
        deadline = time.monotonic() + timeout_seconds
        while True:
            stdout_size = os.fstat(stdout_file.fileno()).st_size
            stderr_size = os.fstat(stderr_file.fileno()).st_size
            if stdout_size > max_output_bytes:
                _stop_process(process)
                raise InvalidCalculationArchive("压缩包清单输出超过限制")
            if stderr_size > stderr_limit:
                _stop_process(process)
                raise InvalidCalculationArchive("压缩包清单错误输出超过安全限制")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            try:
                returncode = process.wait(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue

        stdout_size = os.fstat(stdout_file.fileno()).st_size
        stderr_size = os.fstat(stderr_file.fileno()).st_size
        if stdout_size > max_output_bytes:
            _stop_process(process)
            raise InvalidCalculationArchive("压缩包清单输出超过限制")
        if stderr_size > stderr_limit:
            raise InvalidCalculationArchive("压缩包清单错误输出超过安全限制")
        stdout_file.seek(0)
        stderr_file.seek(0)
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout_file.read(max_output_bytes + 1),
            stderr_file.read(501),
        )


def _extract_external_archive(
    archive_path: Path,
    destination: Path,
    limits: ArchiveLimits,
    *,
    archive_format: ArchiveFormat,
    archive_extractor: ArchiveExtractorSettings | None,
) -> tuple[Path, list[Path]]:
    if archive_format not in {ArchiveFormat.RAR, ArchiveFormat.SEVEN_Z}:
        raise InvalidCalculationArchive("压缩包格式不支持外部解压")
    try:
        resolved_archive = archive_path.resolve(strict=True)
        source_stat = Path(os.path.abspath(archive_path)).lstat()
        resolved_stat = resolved_archive.lstat()
    except OSError as exc:
        raise InvalidCalculationArchive("外部压缩归档文件读取失败") from exc
    if _is_unsafe_file_stat(source_stat) or _is_unsafe_file_stat(resolved_stat):
        raise InvalidCalculationArchive("外部压缩归档文件路径不安全")
    if not stat.S_ISREG(source_stat.st_mode) or not stat.S_ISREG(resolved_stat.st_mode):
        raise InvalidCalculationArchive("外部压缩归档文件必须是普通文件")
    (
        executable,
        list_timeout,
        extract_timeout,
        max_list_output_bytes,
    ) = _private_extractor(archive_extractor)
    resolved_root = _prepare_destination(destination)
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        listing = _run_limited_7zip_listing(
            [
                str(executable),
                "l",
                "-slt",
                "-sccUTF-8",
                "-bd",
                str(resolved_archive),
            ],
            timeout_seconds=list_timeout,
            max_output_bytes=max_list_output_bytes,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise InvalidCalculationArchive("压缩包清单读取超时") from exc
    except OSError as exc:
        raise InvalidCalculationArchive("压缩包清单读取失败") from exc
    if listing.returncode != 0:
        raise InvalidCalculationArchive(
            _seven_zip_failure_message(listing.stderr, operation="读取")
        )
    members = _members_from_slt_listing(listing.stdout, resolved_archive, limits)

    resolved_root.mkdir(parents=True, exist_ok=True)
    try:
        extracted_result = subprocess.run(
            [
                str(executable),
                "x",
                "-y",
                "-bd",
                "-bb0",
                "-sccUTF-8",
                f"-o{resolved_root}",
                str(resolved_archive),
            ],
            timeout=extract_timeout,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise InvalidCalculationArchive("压缩包解压超时") from exc
    except OSError as exc:
        raise InvalidCalculationArchive("压缩包解压失败") from exc
    if extracted_result.returncode != 0:
        raise InvalidCalculationArchive(
            _seven_zip_failure_message(extracted_result.stderr, operation="解压")
        )
    extracted = _verify_extracted_files(resolved_root, members)
    return resolved_root, extracted


def _single_image(folder: Path, label: str) -> Path:
    images = sorted(
        path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise InvalidCalculationArchive(f"压缩包的 {label} 目录中没有支持的图片")
    if len(images) > 1:
        raise InvalidCalculationArchive(f"压缩包的 {label} 目录只能包含一张支持的图片")
    return images[0]


def _normalize_elevation(value: str) -> tuple[str, Decimal]:
    decimal_value = Decimal(value)
    normalized = format(decimal_value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if normalized in {"-0", "+0"}:
        normalized = "0"
    return normalized, decimal_value


def _validate_slab_figure_groups(
    slab_figures: list[SlabReinforcementFigure],
) -> None:
    required_keys = ("TOP-X", "TOP-Y", "BOTTOM-X", "BOTTOM-Y", "Z")
    groups: dict[str, set[str]] = {}
    for figure in slab_figures:
        key = (
            "Z"
            if figure.position is None
            else f"{figure.position}-{figure.direction}"
        )
        keys = groups.setdefault(figure.elevation, set())
        if key in keys:
            raise InvalidCalculationArchive(
                f"楼板标高 {figure.elevation} 存在重复图片：{key}"
            )
        keys.add(key)

    for elevation, keys in groups.items():
        missing = [key for key in required_keys if key not in keys]
        if missing:
            raise InvalidCalculationArchive(
                f"楼板标高 {elevation} 缺少 {'/'.join(missing)} 应力图片"
            )
        has_middle_x = "MIDDLE-X" in keys
        has_middle_y = "MIDDLE-Y" in keys
        if has_middle_x != has_middle_y:
            raise InvalidCalculationArchive(
                f"楼板标高 {elevation} 的 MIDDLE-X/Y 图片必须成对出现"
            )


def _content_root(
    extraction_root: Path,
    extracted: list[Path],
) -> Path:
    relative_parts = [
        path.relative_to(extraction_root).parts
        for path in extracted
    ]
    first_parts = {
        parts[0]
        for parts in relative_parts
        if parts
    }
    if (
        len(first_parts) == 1
        and relative_parts
        and all(len(parts) >= 2 for parts in relative_parts)
    ):
        candidate = extraction_root / next(iter(first_parts))
        if candidate.is_dir():
            return candidate.resolve()
    return extraction_root


def validate_and_extract_archive(
    archive_path: Path,
    destination: Path,
    *,
    reinforcement_source: ReinforcementSource | str = ReinforcementSource.PROVIDED,
    limits: ArchiveLimits | None = None,
    archive_extractor: ArchiveExtractorSettings | None = None,
) -> CalculationArchiveContents:
    active_reinforcement_source = ReinforcementSource(reinforcement_source)
    active_limits = limits or ArchiveLimits()
    archive_format = detect_archive_format(archive_path)
    if archive_format is ArchiveFormat.ZIP:
        resolved_root, extracted = _extract_zip(
            archive_path,
            destination,
            active_limits,
        )
    else:
        resolved_root, extracted = _extract_external_archive(
            archive_path,
            destination,
            active_limits,
            archive_format=archive_format,
            archive_extractor=archive_extractor,
        )

    content_root = _content_root(resolved_root, extracted)
    figures: list[ReinforcementFigure] = []
    slab_figures: list[SlabReinforcementFigure] = []
    ignored_root_images: list[Path] = []
    direction_order = {"X": 0, "Y": 1, "Z": 2}
    slab_position_order = {"TOP": 0, "MIDDLE": 1, "BOTTOM": 2}
    for path in extracted:
        if path.parent != content_root or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        slab_layer_match = _SLAB_LAYER_FIGURE_NAME.fullmatch(path.stem)
        if slab_layer_match is not None:
            position = slab_layer_match.group("position").upper()
            direction = slab_layer_match.group("direction").upper()
            elevation, elevation_value = _normalize_elevation(
                slab_layer_match.group("elevation")
            )
            slab_figures.append(
                SlabReinforcementFigure(
                    elevation=elevation,
                    position=position,
                    direction=direction,
                    path=path,
                    sort_key=(
                        elevation_value,
                        slab_position_order[position],
                        direction_order[direction],
                    ),
                )
            )
            continue
        slab_z_match = _SLAB_Z_FIGURE_NAME.fullmatch(path.stem)
        if slab_z_match is not None:
            elevation, elevation_value = _normalize_elevation(
                slab_z_match.group("elevation")
            )
            slab_figures.append(
                SlabReinforcementFigure(
                    elevation=elevation,
                    position=None,
                    direction="Z",
                    path=path,
                    sort_key=(elevation_value, 3, 0),
                )
            )
            continue
        match = _PARENTHETICAL_FIGURE_NAME.fullmatch(path.stem)
        if match is None:
            match = _FIGURE_NAME.fullmatch(path.stem)
        if match is None:
            ignored_root_images.append(path)
            continue
        direction = match.group("direction").upper()
        number = int(match.group("number"))
        prefix = match.group("prefix").upper()
        suffix = match.group("suffix").upper()
        group_text = match.group("group")
        group_index = int(group_text) if group_text is not None else None
        base_wall_id = f"{prefix}{number}{suffix}"
        wall_id = (
            f"{base_wall_id}-{group_index}"
            if group_index is not None
            else base_wall_id
        )
        figures.append(
            ReinforcementFigure(
                wall_id=wall_id,
                base_wall_id=base_wall_id,
                group_index=group_index,
                direction=direction,
                path=path,
                sort_key=(
                    number,
                    suffix,
                    group_index or 0,
                    direction_order[direction],
                    prefix,
                ),
            )
        )
    figures.sort(key=lambda item: item.sort_key)
    slab_figures.sort(key=lambda item: item.sort_key)
    _validate_slab_figure_groups(slab_figures)
    figure_groups: dict[str, set[str]] = {}
    for figure in figures:
        directions = figure_groups.setdefault(figure.wall_id, set())
        if figure.direction in directions:
            raise InvalidCalculationArchive(
                f"压缩包根目录的 {figure.wall_id} 存在重复 {figure.direction} 方向配筋图片"
            )
        directions.add(figure.direction)
    if not figure_groups:
        raise InvalidCalculationArchive("压缩包根目录没有可识别的墙体 X/Y/Z 配筋图片")
    for wall_id, directions in figure_groups.items():
        missing_directions = [
            direction for direction in ("X", "Y", "Z") if direction not in directions
        ]
        if missing_directions:
            raise InvalidCalculationArchive(
                f"压缩包根目录的 {wall_id} 缺少 "
                f"{'/'.join(missing_directions)} 方向配筋图片"
            )

    root_xlsx_files = sorted(
        path
        for path in extracted
        if (
            path.parent == content_root
            and path.suffix.lower() == ".xlsx"
        )
    )
    if active_reinforcement_source is ReinforcementSource.AI_SUGGESTED:
        archive_xlsx_files = [
            path for path in extracted if path.suffix.lower() == ".xlsx"
        ]
        if archive_xlsx_files:
            raise InvalidCalculationArchive(
                "无实配钢筋模式不得包含 Excel 配筋表"
            )
        reinforcement_workbook = None
    else:
        reinforcement_workbooks = [
            path for path in root_xlsx_files if not path.name.startswith("~$")
        ]
        if not reinforcement_workbooks:
            raise InvalidCalculationArchive("压缩包根目录缺少墙体配筋表")
        if len(reinforcement_workbooks) > 1:
            raise InvalidCalculationArchive("压缩包根目录只能包含一个墙体配筋表")
        reinforcement_workbook = reinforcement_workbooks[0]

    folder_01 = content_root / "01"
    folder_02 = content_root / "02"
    if not folder_01.is_dir():
        raise InvalidCalculationArchive("压缩包根目录缺少 01 目录")
    if not folder_02.is_dir():
        raise InvalidCalculationArchive("压缩包根目录缺少 02 目录")

    return CalculationArchiveContents(
        root=content_root,
        reinforcement_figures=tuple(figures),
        slab_figures=tuple(slab_figures),
        ignored_root_images=tuple(sorted(ignored_root_images)),
        reinforcement_workbook=reinforcement_workbook,
        layout_image=_single_image(folder_01, "01"),
        model_image=_single_image(folder_02, "02"),
        extracted_files=tuple(extracted),
    )
