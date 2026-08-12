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
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath


class InvalidArchive(ValueError):
    pass


class ArchiveFormat(StrEnum):
    ZIP = "zip"
    RAR = "rar"
    SEVEN_Z = "7z"


@dataclass(frozen=True)
class ArchiveLimits:
    max_files: int = 500
    max_total_bytes: int = 1024 * 1024 * 1024
    max_single_file_bytes: int = 50 * 1024 * 1024
    max_compression_ratio: float = 250.0


@dataclass(frozen=True)
class ArchiveExtractorSettings:
    executable: Path
    fallback_executables: tuple[Path, ...] = ()
    list_timeout_seconds: int = 120
    extract_timeout_seconds: int = 300
    max_list_output_bytes: int = 8_388_608


@dataclass(frozen=True)
class ExtractedArchive:
    root: Path
    files: tuple[Path, ...]
    archive_format: ArchiveFormat


@dataclass(frozen=True)
class _ArchiveMember:
    path: PurePosixPath
    size: int
    is_directory: bool


_FORMATS_BY_SUFFIX = {
    ".zip": ArchiveFormat.ZIP,
    ".rar": ArchiveFormat.RAR,
    ".7z": ArchiveFormat.SEVEN_Z,
}
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_RAR_SIGNATURES = (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")
_SEVEN_Z_SIGNATURE = b"7z\xbc\xaf'\x1c"
_WINDOWS_FORBIDDEN_CHARACTERS = frozenset('*?"<>|')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_DEVICE_DIGIT_TRANSLATION = str.maketrans({"¹": "1", "²": "2", "³": "3"})
_FALSE_VALUES = {"", "-", "0", "false", "no"}
_TRUE_VALUES = {"+", "1", "true", "yes"}
_MOJIBAKE_MARKERS = frozenset("╕╜╖╛╚╔║▒▓│┐└┴┬├┤╬")


def detect_archive_format(archive_path: Path) -> ArchiveFormat:
    suffix_format = _FORMATS_BY_SUFFIX.get(archive_path.suffix.casefold())
    if suffix_format is None:
        raise InvalidArchive(f"不支持的压缩包后缀：{archive_path.suffix or '无后缀'}")
    try:
        header = archive_path.read_bytes()[:8]
    except OSError as exc:
        raise InvalidArchive("压缩包文件读取失败") from exc
    if header.startswith(_ZIP_SIGNATURES):
        signature_format = ArchiveFormat.ZIP
    elif header.startswith(_RAR_SIGNATURES):
        signature_format = ArchiveFormat.RAR
    elif header.startswith(_SEVEN_Z_SIGNATURE):
        signature_format = ArchiveFormat.SEVEN_Z
    else:
        raise InvalidArchive("无法识别压缩包签名")
    if suffix_format is not signature_format:
        raise InvalidArchive(
            f"压缩包后缀与文件签名不一致：{archive_path.suffix} / {signature_format.value}"
        )
    return signature_format


def _normalized_member_path(raw_name: str, *, is_directory: bool) -> PurePosixPath:
    normalized = unicodedata.normalize("NFC", raw_name.replace("\\", "/"))
    if is_directory:
        normalized = normalized.rstrip("/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise InvalidArchive("压缩包包含不安全路径")
    parts = normalized.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise InvalidArchive("压缩包包含不安全路径")
    for part in parts:
        if any(ord(character) < 32 or ord(character) == 127 for character in part):
            raise InvalidArchive("压缩包包含不安全路径")
        if (
            ":" in part
            or any(character in _WINDOWS_FORBIDDEN_CHARACTERS for character in part)
            or part.endswith((".", " "))
        ):
            raise InvalidArchive("压缩包包含不安全路径")
        stem = part.split(".", 1)[0].upper().translate(_DEVICE_DIGIT_TRANSLATION)
        if stem in _WINDOWS_RESERVED_NAMES:
            raise InvalidArchive("压缩包包含不安全路径")
    return PurePosixPath(*parts)


def _member_key(path: PurePosixPath) -> str:
    return "/".join(part.rstrip(" .").casefold() for part in path.parts)


def _validate_member_topology(members: list[_ArchiveMember]) -> None:
    file_keys = {_member_key(member.path) for member in members if not member.is_directory}
    for member in members:
        key_parts = _member_key(member.path).split("/")
        for count in range(1, len(key_parts)):
            if "/".join(key_parts[:count]) in file_keys:
                raise InvalidArchive("压缩包存在文件与目录路径冲突")


def _is_reparse_point(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse_flag)


def _is_unsafe_stat(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(metadata)


def _prepare_destination(destination: Path) -> Path:
    if destination.exists() or destination.is_symlink():
        metadata = destination.lstat()
        if _is_unsafe_stat(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise InvalidArchive("压缩包解压目标目录不安全")
        if any(destination.iterdir()):
            raise InvalidArchive("压缩包解压目标目录必须为空")
    return destination.resolve()


def _verify_extracted_files(root: Path, members: list[_ArchiveMember]) -> list[Path]:
    resolved_root = root.resolve(strict=True)
    root_metadata = resolved_root.lstat()
    if _is_unsafe_stat(root_metadata) or not stat.S_ISDIR(root_metadata.st_mode):
        raise InvalidArchive("压缩包解压后校验失败")
    actual: dict[str, tuple[Path, int]] = {}
    pending = [resolved_root]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise InvalidArchive("压缩包解压后校验失败") from exc
        for entry in entries:
            path = Path(entry.path)
            metadata = entry.stat(follow_symlinks=False)
            if _is_unsafe_stat(metadata):
                raise InvalidArchive("压缩包解压后校验失败")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise InvalidArchive("压缩包解压后校验失败")
            relative = path.relative_to(resolved_root)
            normalized = _normalized_member_path(relative.as_posix(), is_directory=False)
            key = _member_key(normalized)
            if key in actual:
                raise InvalidArchive("压缩包解压后校验失败")
            actual[key] = (path.resolve(), metadata.st_size)
    expected_files = [member for member in members if not member.is_directory]
    expected = {_member_key(member.path): member for member in expected_files}
    if set(actual) != set(expected):
        raise InvalidArchive("压缩包解压后校验失败")
    for key, member in expected.items():
        if actual[key][1] != member.size:
            raise InvalidArchive("压缩包解压后校验失败")
    return [actual[_member_key(member.path)][0] for member in expected_files]


def _filename_quality(names: list[str], index: int) -> tuple[int, int, int]:
    text = "".join(names)
    suspicious = sum(character in _MOJIBAKE_MARKERS for character in text)
    replacements = text.count("�")
    cjk = sum("\u4e00" <= character <= "\u9fff" for character in text)
    return (replacements * 10_000 + suspicious * 100 - cjk, index, len(text))


def _open_zip_with_metadata_fallback(
    archive_path: Path,
    encodings: tuple[str, ...],
) -> zipfile.ZipFile:
    candidates: list[tuple[tuple[int, int, int], str]] = []
    errors: list[Exception] = []
    for index, encoding in enumerate(dict.fromkeys(encodings)):
        try:
            with zipfile.ZipFile(archive_path, metadata_encoding=encoding) as archive:
                names = [info.filename for info in archive.infolist()]
            candidates.append((_filename_quality(names, index), encoding))
        except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
            errors.append(exc)
    if not candidates:
        raise InvalidArchive("上传文件不是有效的 ZIP 压缩包") from (errors[-1] if errors else None)
    _, selected_encoding = min(candidates, key=lambda item: item[0])
    return zipfile.ZipFile(archive_path, metadata_encoding=selected_encoding)


def _safe_zip_member(info: zipfile.ZipInfo) -> _ArchiveMember:
    member = _normalized_member_path(info.filename, is_directory=info.is_dir())
    unix_mode = info.external_attr >> 16
    unix_type = stat.S_IFMT(unix_mode)
    if unix_type not in {0, stat.S_IFREG, stat.S_IFDIR} or bool(info.external_attr & 0x400):
        raise InvalidArchive("压缩包包含不安全文件类型")
    if info.flag_bits & 0x1:
        raise InvalidArchive("暂不支持加密压缩包")
    return _ArchiveMember(member, info.file_size, info.is_dir())


def _validate_limits(
    members: list[_ArchiveMember],
    limits: ArchiveLimits,
    *,
    compressed_sizes: list[int] | None = None,
) -> None:
    if len(members) > limits.max_files:
        raise InvalidArchive(f"压缩包条目数量超过限制 {limits.max_files}")
    total = 0
    seen: set[str] = set()
    for index, member in enumerate(members):
        key = _member_key(member.path)
        if key in seen:
            raise InvalidArchive("压缩包包含重复路径")
        seen.add(key)
        if member.is_directory:
            continue
        if member.size > limits.max_single_file_bytes:
            raise InvalidArchive("压缩包中单个文件超过限制")
        total += member.size
        if total > limits.max_total_bytes:
            raise InvalidArchive("压缩包解压后总大小超过限制")
        if compressed_sizes is not None and member.size > 0:
            if member.size / max(compressed_sizes[index], 1) > limits.max_compression_ratio:
                raise InvalidArchive("压缩包压缩比异常")
    if not any(not member.is_directory for member in members):
        raise InvalidArchive("压缩包中没有文件")
    _validate_member_topology(members)


def _publish_staging(staging: Path, destination: Path, relative_files: list[Path]) -> ExtractedArchive:
    if destination.exists():
        destination.rmdir()
    staging.replace(destination)
    return ExtractedArchive(
        root=destination,
        files=tuple(destination.joinpath(*relative.parts).resolve() for relative in relative_files),
        archive_format=ArchiveFormat.ZIP,
    )


def _extract_zip(
    archive_path: Path,
    destination: Path,
    limits: ArchiveLimits,
    encodings: tuple[str, ...],
) -> ExtractedArchive:
    resolved_destination = _prepare_destination(destination)
    staging: Path | None = None
    try:
        with _open_zip_with_metadata_fallback(archive_path, encodings) as archive:
            infos = archive.infolist()
            members = [_safe_zip_member(info) for info in infos]
            _validate_limits(
                members,
                limits,
                compressed_sizes=[info.compress_size for info in infos],
            )
            resolved_destination.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".archive-", dir=resolved_destination.parent))
            for info, member in zip(infos, members, strict=True):
                target = staging.joinpath(*member.path.parts)
                if member.is_directory:
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            files = _verify_extracted_files(staging, members)
            relatives = [path.relative_to(staging) for path in files]
            result = _publish_staging(staging, resolved_destination, relatives)
            staging = None
            return result
    except InvalidArchive:
        raise
    except (EOFError, NotImplementedError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise InvalidArchive("ZIP 压缩包解压失败") from exc
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def _parse_flag(value: str | None) -> bool:
    normalized = (value or "").strip().casefold()
    if normalized in _FALSE_VALUES:
        return False
    if normalized in _TRUE_VALUES:
        return True
    raise InvalidArchive("压缩包清单无法解析")


def _parse_size(value: str | None) -> int:
    try:
        parsed = int(value or "")
    except ValueError as exc:
        raise InvalidArchive("压缩包清单无法解析") from exc
    if parsed < 0:
        raise InvalidArchive("压缩包清单无法解析")
    return parsed


def _parse_listing(payload: bytes, limits: ArchiveLimits, archive_size: int) -> list[_ArchiveMember]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InvalidArchive("压缩包清单无法解析") from exc
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
        if key in current:
            raise InvalidArchive("压缩包清单无法解析")
        current[key] = value
    if current:
        records.append(current)
    for record in records:
        if _parse_flag(record.get("Encrypted")):
            raise InvalidArchive("暂不支持加密压缩包")
        if _parse_flag(record.get("Multivolume")) or _parse_flag(record.get("Split Before")) or _parse_flag(record.get("Split After")):
            raise InvalidArchive("暂不支持分卷压缩包")
    item_records = [
        record
        for record in records
        if "Path" in record
        and "Physical Size" not in record
        and any(field in record for field in ("Size", "Folder", "Attributes"))
    ]
    members: list[_ArchiveMember] = []
    for record in item_records:
        folder_value = record.get("Folder")
        is_directory = _parse_flag(folder_value) if folder_value is not None else record.get("Attributes", "")[:1].upper() == "D"
        for field in ("Symbolic Link", "Hard Link", "Alternate Stream", "Reparse"):
            if field in record and _parse_flag(record.get(field)):
                raise InvalidArchive("压缩包包含不安全文件类型")
        members.append(
            _ArchiveMember(
                _normalized_member_path(record["Path"], is_directory=is_directory),
                _parse_size(record.get("Size")),
                is_directory,
            )
        )
    _validate_limits(members, limits)
    total = sum(member.size for member in members if not member.is_directory)
    if total / max(archive_size, 1) > limits.max_compression_ratio:
        raise InvalidArchive("压缩包总压缩比异常")
    return members


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


def _limited_listing(command: list[str], *, timeout: int, max_bytes: int) -> subprocess.CompletedProcess[bytes]:
    stderr_limit = 16_384
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            shell=False,
        )
        deadline = time.monotonic() + timeout
        while True:
            if os.fstat(stdout_file.fileno()).st_size > max_bytes or os.fstat(stderr_file.fileno()).st_size > stderr_limit:
                _stop_process(process)
                raise InvalidArchive("压缩包清单输出超过限制")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise InvalidArchive("压缩包清单读取超时")
            try:
                returncode = process.wait(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        stdout_file.seek(0)
        stderr_file.seek(0)
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout_file.read(max_bytes + 1),
            stderr_file.read(501),
        )


def _validated_extractor(settings: ArchiveExtractorSettings | None) -> ArchiveExtractorSettings:
    if settings is None:
        raise InvalidArchive("RAR/7z 私有解包器不可用")
    if min(settings.list_timeout_seconds, settings.extract_timeout_seconds, settings.max_list_output_bytes) <= 0:
        raise InvalidArchive("RAR/7z 私有解包器安全参数无效")
    for executable in (settings.executable, *settings.fallback_executables):
        if not executable.is_absolute():
            raise InvalidArchive("RAR/7z 私有解包器必须使用绝对路径")
        try:
            if executable.is_file() and not _is_unsafe_stat(executable.lstat()):
                return replace(settings, executable=executable)
        except OSError:
            continue
    raise InvalidArchive("RAR/7z 私有解包器不存在或路径不安全")


def _extract_external(
    archive_path: Path,
    destination: Path,
    limits: ArchiveLimits,
    settings: ArchiveExtractorSettings | None,
    archive_format: ArchiveFormat,
) -> ExtractedArchive:
    active = _validated_extractor(settings)
    resolved_archive = archive_path.resolve(strict=True)
    if _is_unsafe_stat(resolved_archive.lstat()):
        raise InvalidArchive("外部压缩归档文件路径不安全")
    resolved_destination = _prepare_destination(destination)
    command_prefix = [str(active.executable.resolve())]
    listing = _limited_listing(
        command_prefix + ["l", "-slt", "-sccUTF-8", "-bd", str(resolved_archive)],
        timeout=active.list_timeout_seconds,
        max_bytes=active.max_list_output_bytes,
    )
    if listing.returncode != 0:
        raise InvalidArchive("压缩包读取失败或已损坏")
    members = _parse_listing(listing.stdout, limits, resolved_archive.stat().st_size)
    resolved_destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".archive-", dir=resolved_destination.parent))
    try:
        completed = subprocess.run(
            command_prefix + ["x", "-y", "-bd", "-bb0", "-sccUTF-8", f"-o{staging}", str(resolved_archive)],
            timeout=active.extract_timeout_seconds,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            shell=False,
        )
        if completed.returncode != 0:
            raise InvalidArchive("压缩包解压失败")
        files = _verify_extracted_files(staging, members)
        relatives = [path.relative_to(staging) for path in files]
        if resolved_destination.exists():
            resolved_destination.rmdir()
        staging.replace(resolved_destination)
        staging = None
        return ExtractedArchive(
            root=resolved_destination,
            files=tuple(resolved_destination.joinpath(*relative.parts).resolve() for relative in relatives),
            archive_format=archive_format,
        )
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def extract_archive(
    archive_path: Path,
    destination: Path,
    *,
    limits: ArchiveLimits | None = None,
    extractor: ArchiveExtractorSettings | None = None,
    zip_metadata_encodings: tuple[str, ...] = ("utf-8", "gbk"),
) -> ExtractedArchive:
    active_limits = limits or ArchiveLimits()
    archive_format = detect_archive_format(archive_path)
    if archive_format is ArchiveFormat.ZIP:
        return _extract_zip(archive_path, destination, active_limits, zip_metadata_encodings)
    return _extract_external(
        archive_path,
        destination,
        active_limits,
        extractor,
        archive_format,
    )
