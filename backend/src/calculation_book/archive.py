from __future__ import annotations

import locale
import re
import shutil
import stat
import subprocess
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath

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


@dataclass(frozen=True)
class ArchiveLimits:
    max_files: int = 500
    max_total_bytes: int = 1024 * 1024 * 1024
    max_single_file_bytes: int = 50 * 1024 * 1024
    max_compression_ratio: float = 250.0


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
    reinforcement_workbook: Path
    layout_image: Path
    model_image: Path
    extracted_files: tuple[Path, ...]

    @property
    def requires_manual_confirmation(self) -> bool:
        return any(
            figure.group_index is not None
            for figure in self.reinforcement_figures
        )


def _safe_member_path(info: zipfile.ZipInfo) -> PurePosixPath:
    raw_name = info.filename.replace("\\", "/")
    member = PurePosixPath(raw_name)
    if (
        not raw_name
        or raw_name.startswith("/")
        or re.match(r"^[A-Za-z]:/", raw_name)
        or ".." in member.parts
    ):
        raise InvalidCalculationArchive(f"ZIP 包含不安全路径：{info.filename}")
    unix_mode = info.external_attr >> 16
    if unix_mode and (stat.S_ISLNK(unix_mode) or stat.S_ISCHR(unix_mode) or stat.S_ISBLK(unix_mode)):
        raise InvalidCalculationArchive(f"ZIP 包含不安全文件类型：{info.filename}")
    return member


def _decode_tar_output(payload: bytes) -> str:
    encodings = (
        locale.getpreferredencoding(False),
        "gbk",
        "utf-8",
    )
    for encoding in dict.fromkeys(encodings):
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    raise InvalidCalculationArchive("RAR 文件名编码无法识别")


def _safe_rar_member_path(raw_name: str) -> PurePosixPath:
    normalized = raw_name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or ".." in member.parts
    ):
        raise InvalidCalculationArchive(f"RAR 包含不安全路径：{raw_name}")
    return member


def _extract_zip(
    archive_path: Path,
    destination: Path,
    limits: ArchiveLimits,
) -> tuple[Path, list[Path]]:
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InvalidCalculationArchive("上传文件不是有效的 ZIP") from exc

    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if not infos:
            raise InvalidCalculationArchive("ZIP 中没有文件")
        if len(infos) > limits.max_files:
            raise InvalidCalculationArchive(
                f"ZIP 文件数量超过限制 {limits.max_files}"
            )

        total_bytes = 0
        safe_members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        for info in infos:
            member = _safe_member_path(info)
            if info.file_size > limits.max_single_file_bytes:
                raise InvalidCalculationArchive(
                    f"ZIP 中单个文件超过限制：{info.filename}"
                )
            total_bytes += info.file_size
            if total_bytes > limits.max_total_bytes:
                raise InvalidCalculationArchive("ZIP 解压后总大小超过限制")
            if info.file_size > 0:
                compressed = max(info.compress_size, 1)
                if info.file_size / compressed > limits.max_compression_ratio:
                    raise InvalidCalculationArchive(
                        f"ZIP 压缩比异常：{info.filename}"
                    )
            safe_members.append((info, member))

        destination.mkdir(parents=True, exist_ok=True)
        resolved_root = destination.resolve()
        extracted: list[Path] = []
        for info, member in safe_members:
            target = destination.joinpath(*member.parts)
            resolved_target = target.resolve()
            if not resolved_target.is_relative_to(resolved_root):
                raise InvalidCalculationArchive(
                    f"ZIP 包含不安全路径：{info.filename}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(resolved_target)
    return resolved_root, extracted


def _extract_rar(
    archive_path: Path,
    destination: Path,
    limits: ArchiveLimits,
) -> tuple[Path, list[Path]]:
    tar_executable = shutil.which("tar.exe") or shutil.which("tar")
    if tar_executable is None:
        raise InvalidCalculationArchive(
            "当前运行环境缺少 RAR 解压支持（未找到 tar.exe）"
        )
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        listing = subprocess.run(
            [tar_executable, "-tvf", str(archive_path)],
            check=False,
            capture_output=True,
            timeout=120,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidCalculationArchive("RAR 文件读取失败") from exc
    if listing.returncode != 0:
        detail = _decode_tar_output(listing.stderr).strip()
        raise InvalidCalculationArchive(
            f"上传文件不是有效的 RAR{f'：{detail}' if detail else ''}"
        )

    safe_members: list[tuple[PurePosixPath, int]] = []
    seen: set[PurePosixPath] = set()
    total_bytes = 0
    for raw_line in _decode_tar_output(listing.stdout).splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split(maxsplit=8)
        if len(parts) != 9 or len(parts[0]) < 1:
            raise InvalidCalculationArchive("RAR 文件清单格式无法识别")
        mode = parts[0]
        raw_name = parts[8]
        if mode.startswith("d") or raw_name.endswith(("/", "\\")):
            continue
        if not mode.startswith("-"):
            raise InvalidCalculationArchive(
                f"RAR 包含不安全文件类型：{raw_name}"
            )
        try:
            file_size = int(parts[4])
        except ValueError as exc:
            raise InvalidCalculationArchive(
                f"RAR 文件大小无法识别：{raw_name}"
            ) from exc
        member = _safe_rar_member_path(raw_name)
        if member in seen:
            raise InvalidCalculationArchive(f"RAR 包含重复路径：{raw_name}")
        seen.add(member)
        if file_size > limits.max_single_file_bytes:
            raise InvalidCalculationArchive(
                f"RAR 中单个文件超过限制：{raw_name}"
            )
        total_bytes += file_size
        if total_bytes > limits.max_total_bytes:
            raise InvalidCalculationArchive("RAR 解压后总大小超过限制")
        safe_members.append((member, file_size))

    if not safe_members:
        raise InvalidCalculationArchive("RAR 中没有文件")
    if len(safe_members) > limits.max_files:
        raise InvalidCalculationArchive(
            f"RAR 文件数量超过限制 {limits.max_files}"
        )
    archive_size = max(archive_path.stat().st_size, 1)
    if total_bytes / archive_size > limits.max_compression_ratio:
        raise InvalidCalculationArchive("RAR 总压缩比异常")

    destination.mkdir(parents=True, exist_ok=True)
    resolved_root = destination.resolve()
    try:
        extracted_result = subprocess.run(
            [
                tar_executable,
                "-xf",
                str(archive_path),
                "-C",
                str(destination),
                "--no-same-owner",
                "--no-same-permissions",
            ],
            check=False,
            capture_output=True,
            timeout=300,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidCalculationArchive("RAR 解压失败") from exc
    if extracted_result.returncode != 0:
        detail = _decode_tar_output(extracted_result.stderr).strip()
        raise InvalidCalculationArchive(
            f"RAR 解压失败{f'：{detail}' if detail else ''}"
        )

    extracted: list[Path] = []
    for member, expected_size in safe_members:
        target = destination.joinpath(*member.parts)
        resolved_target = target.resolve()
        if not resolved_target.is_relative_to(resolved_root):
            raise InvalidCalculationArchive(
                f"RAR 包含不安全路径：{member.as_posix()}"
            )
        if not target.is_file() or target.is_symlink():
            raise InvalidCalculationArchive(
                f"RAR 文件未安全解压：{member.as_posix()}"
            )
        if target.stat().st_size != expected_size:
            raise InvalidCalculationArchive(
                f"RAR 文件大小校验失败：{member.as_posix()}"
            )
        extracted.append(resolved_target)
    return resolved_root, extracted


def _single_image(folder: Path, label: str) -> Path:
    images = sorted(
        path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise InvalidCalculationArchive(f"ZIP 的 {label} 目录中没有支持的图片")
    if len(images) > 1:
        raise InvalidCalculationArchive(f"ZIP 的 {label} 目录只能包含一张支持的图片")
    return images[0]


def _normalize_elevation(value: str) -> tuple[str, Decimal]:
    decimal_value = Decimal(value)
    normalized = format(decimal_value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if normalized in {"-0", "+0"}:
        normalized = "0"
    return normalized, decimal_value


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
    limits: ArchiveLimits | None = None,
) -> CalculationArchiveContents:
    active_limits = limits or ArchiveLimits()
    if zipfile.is_zipfile(archive_path):
        resolved_root, extracted = _extract_zip(
            archive_path,
            destination,
            active_limits,
        )
    else:
        resolved_root, extracted = _extract_rar(
            archive_path,
            destination,
            active_limits,
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
    figure_groups: dict[str, set[str]] = {}
    for figure in figures:
        figure_groups.setdefault(figure.wall_id, set()).add(figure.direction)
    if not figure_groups:
        raise InvalidCalculationArchive("ZIP 根目录没有可识别的墙体 X/Y/Z 配筋图片")
    for wall_id, directions in figure_groups.items():
        missing_directions = [
            direction for direction in ("X", "Y", "Z") if direction not in directions
        ]
        if missing_directions:
            raise InvalidCalculationArchive(
                f"ZIP 根目录的 {wall_id} 缺少 "
                f"{'/'.join(missing_directions)} 方向配筋图片"
            )

    reinforcement_workbooks = sorted(
        path
        for path in extracted
        if (
            path.parent == content_root
            and path.suffix.lower() == ".xlsx"
            and not path.name.startswith("~$")
        )
    )
    if not reinforcement_workbooks:
        raise InvalidCalculationArchive("ZIP 根目录缺少墙体配筋表")
    if len(reinforcement_workbooks) > 1:
        raise InvalidCalculationArchive("ZIP 根目录只能包含一个墙体配筋表")

    folder_01 = content_root / "01"
    folder_02 = content_root / "02"
    if not folder_01.is_dir():
        raise InvalidCalculationArchive("ZIP 根目录缺少 01 目录")
    if not folder_02.is_dir():
        raise InvalidCalculationArchive("ZIP 根目录缺少 02 目录")

    return CalculationArchiveContents(
        root=content_root,
        reinforcement_figures=tuple(figures),
        slab_figures=tuple(slab_figures),
        ignored_root_images=tuple(sorted(ignored_root_images)),
        reinforcement_workbook=reinforcement_workbooks[0],
        layout_image=_single_image(folder_01, "01"),
        model_image=_single_image(folder_02, "02"),
        extracted_files=tuple(extracted),
    )
