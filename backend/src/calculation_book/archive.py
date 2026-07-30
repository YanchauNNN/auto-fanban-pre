from __future__ import annotations

import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}
_FIGURE_NAME = re.compile(
    r"^(?P<prefix>[A-Za-z]+)(?P<number>\d+)(?P<suffix>[A-Za-z]?)"
    r"(?:-(?P<group>[12]))?-(?P<direction>[XYZ])$",
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
class CalculationArchiveContents:
    root: Path
    reinforcement_figures: tuple[ReinforcementFigure, ...]
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


def _first_image(folder: Path, label: str) -> Path:
    images = sorted(
        path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise InvalidCalculationArchive(f"ZIP 的 {label} 目录中没有支持的图片")
    return images[0]


def validate_and_extract_archive(
    archive_path: Path,
    destination: Path,
    *,
    limits: ArchiveLimits | None = None,
) -> CalculationArchiveContents:
    active_limits = limits or ArchiveLimits()
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InvalidCalculationArchive("上传文件不是有效的 ZIP") from exc

    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if not infos:
            raise InvalidCalculationArchive("ZIP 中没有文件")
        if len(infos) > active_limits.max_files:
            raise InvalidCalculationArchive(f"ZIP 文件数量超过限制 {active_limits.max_files}")

        total_bytes = 0
        safe_members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        for info in infos:
            member = _safe_member_path(info)
            if info.file_size > active_limits.max_single_file_bytes:
                raise InvalidCalculationArchive(
                    f"ZIP 中单个文件超过限制：{info.filename}"
                )
            total_bytes += info.file_size
            if total_bytes > active_limits.max_total_bytes:
                raise InvalidCalculationArchive("ZIP 解压后总大小超过限制")
            if info.file_size > 0:
                compressed = max(info.compress_size, 1)
                if info.file_size / compressed > active_limits.max_compression_ratio:
                    raise InvalidCalculationArchive(f"ZIP 压缩比异常：{info.filename}")
            safe_members.append((info, member))

        destination.mkdir(parents=True, exist_ok=True)
        resolved_root = destination.resolve()
        extracted: list[Path] = []
        for info, member in safe_members:
            target = destination.joinpath(*member.parts)
            resolved_target = target.resolve()
            if not resolved_target.is_relative_to(resolved_root):
                raise InvalidCalculationArchive(f"ZIP 包含不安全路径：{info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(resolved_target)

    figures: list[ReinforcementFigure] = []
    ignored_root_images: list[Path] = []
    direction_order = {"X": 0, "Y": 1, "Z": 2}
    for path in extracted:
        if path.parent != resolved_root or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
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
            path.parent == resolved_root
            and path.suffix.lower() == ".xlsx"
            and not path.name.startswith("~$")
        )
    )
    if not reinforcement_workbooks:
        raise InvalidCalculationArchive("ZIP 根目录缺少墙体配筋表")
    if len(reinforcement_workbooks) > 1:
        raise InvalidCalculationArchive("ZIP 根目录只能包含一个墙体配筋表")

    folder_01 = resolved_root / "01"
    folder_02 = resolved_root / "02"
    if not folder_01.is_dir():
        raise InvalidCalculationArchive("ZIP 根目录缺少 01 目录")
    if not folder_02.is_dir():
        raise InvalidCalculationArchive("ZIP 根目录缺少 02 目录")

    return CalculationArchiveContents(
        root=resolved_root,
        reinforcement_figures=tuple(figures),
        ignored_root_images=tuple(sorted(ignored_root_images)),
        reinforcement_workbook=reinforcement_workbooks[0],
        layout_image=_first_image(folder_01, "01"),
        model_image=_first_image(folder_02, "02"),
        extracted_files=tuple(extracted),
    )
