from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from ..config.mechanism_spec import (
    DEFAULT_MECHANISM_SPEC_PATH,
    ArchiveRuntimeAssetConfig,
    ArchiveRuntimeMechanismConfig,
    MechanismSpecLoader,
)

Downloader = Callable[[str, Path, int, int], None]
Runner = Callable[..., subprocess.CompletedProcess[str]]


class ArchiveRuntimeError(RuntimeError):
    """The private portable archive runtime could not be prepared or verified."""


@dataclass(frozen=True)
class ArchiveRuntimeCopyEntry:
    source: Path
    destination: Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_regular_file(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ArchiveRuntimeError(f"{label}不存在: {path}") from exc
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    if path.is_symlink() or attributes & reparse_flag or not stat.S_ISREG(metadata.st_mode):
        raise ArchiveRuntimeError(f"{label}必须是普通文件，不能是链接或重解析点: {path}")


def _is_reparse_point(path: Path, metadata: os.stat_result | None = None) -> bool:
    resolved_metadata = metadata or path.lstat()
    attributes = int(getattr(resolved_metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return path.is_symlink() or bool(attributes & reparse_flag)


def _windows_name_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).rstrip(" .").casefold()


def _verify_hash(path: Path, expected: str, *, label: str) -> None:
    _ensure_regular_file(path, label=label)
    actual = _sha256_file(path)
    if actual != expected:
        raise ArchiveRuntimeError(
            f"{label} SHA256 校验失败: {path.name}; expected={expected}; actual={actual}"
        )


def _resolve_repo_path(repo_root: Path, relative: str, *, label: str) -> Path:
    try:
        root = repo_root.resolve(strict=True)
    except OSError as exc:
        raise ArchiveRuntimeError(f"仓库根目录不存在或不可访问: {repo_root}") from exc
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ArchiveRuntimeError(f"{label}必须是仓库内相对路径: {relative}")
    candidate = root / relative_path
    current = root
    missing_tail = False
    for part in relative_path.parts:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            missing_tail = True
            continue
        except OSError as exc:
            raise ArchiveRuntimeError(f"无法检查 {label} 路径层级 {current}: {exc}") from exc
        if missing_tail:
            raise ArchiveRuntimeError(f"{label} 路径在检查期间发生变化: {current}")
        if _is_reparse_point(current, metadata):
            raise ArchiveRuntimeError(f"{label} 包含链接或重解析点: {current}")
        if current != candidate and not stat.S_ISDIR(metadata.st_mode):
            raise ArchiveRuntimeError(f"{label} 的父路径不是目录: {current}")
    try:
        resolved_candidate = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ArchiveRuntimeError(f"无法解析 {label}: {candidate}: {exc}") from exc
    try:
        resolved_candidate.relative_to(root)
    except ValueError as exc:
        raise ArchiveRuntimeError(f"{label}必须位于仓库内: {relative}") from exc
    return candidate


def _load_archive_runtime_config(repo_root: Path) -> ArchiveRuntimeMechanismConfig:
    spec = MechanismSpecLoader.load(repo_root / DEFAULT_MECHANISM_SPEC_PATH)
    config = spec.deployment_mechanism.archive_runtime
    if config is None:
        raise ArchiveRuntimeError(
            "参数规范-3.yaml 缺少 backend_mechanism.deployment_mechanism.archive_runtime"
        )
    return config


def render_archive_runtime_provenance(config: ArchiveRuntimeMechanismConfig) -> str:
    lines = [
        "7-Zip portable runtime provenance",
        f"version={config.version}",
        f"architecture={config.architecture}",
        f"version_marker={config.version_marker}",
        f"source_url={config.source.url}",
        f"source_sha256={config.source.sha256}",
        f"source_size_bytes={config.source.size_bytes}",
        f"bootstrap_url={config.bootstrap.url}",
        f"bootstrap_sha256={config.bootstrap.sha256}",
        f"bootstrap_size_bytes={config.bootstrap.size_bytes}",
        f"license_url={config.license_url}",
        f"probe_fixture_source={config.probe.fixture_source_relative_path}",
        f"probe_fixture_source_sha256={config.probe.fixture_source_sha256}",
        f"probe_fixture_decoded_sha256={config.probe.fixture_decoded_sha256}",
        f"probe_payload_filename={config.probe.payload_filename}",
        f"probe_payload_sha256={config.probe.payload_sha256}",
    ]
    lines.extend(
        f"required_file={item.filename} sha256={item.sha256}"
        for item in config.required_files
    )
    lines.extend(f"required_handler={handler}" for handler in config.required_handlers)
    return "\n".join(lines) + "\n"


def _cache_failure(message: str) -> ArchiveRuntimeError:
    return ArchiveRuntimeError(
        f"7-Zip 私有运行时缓存无效: {message}。"
        "请先运行 `python tools/prepare_archive_runtime.py`。"
    )


def _validate_runtime_directory(
    runtime_dir: Path,
    config: ArchiveRuntimeMechanismConfig,
    *,
    cache_message: bool,
) -> None:
    def fail(message: str) -> ArchiveRuntimeError:
        return _cache_failure(message) if cache_message else ArchiveRuntimeError(message)

    try:
        runtime_metadata = runtime_dir.lstat()
    except FileNotFoundError as exc:
        raise fail(f"目录不存在: {runtime_dir}") from exc
    except OSError as exc:
        raise fail(f"无法检查目录 {runtime_dir}: {exc}") from exc
    if _is_reparse_point(runtime_dir, runtime_metadata) or not stat.S_ISDIR(
        runtime_metadata.st_mode
    ):
        raise fail(f"目录不能是链接或重解析点: {runtime_dir}")
    expected_names = {item.filename for item in config.required_files}
    expected_names.add(config.provenance_filename)
    try:
        entries = list(os.scandir(runtime_dir))
    except OSError as exc:
        raise fail(f"无法读取目录 {runtime_dir}: {exc}") from exc
    actual_names = {entry.name for entry in entries}
    actual_name_keys = [_windows_name_key(entry.name) for entry in entries]
    if len(actual_name_keys) != len(set(actual_name_keys)):
        raise fail("目录内存在 Windows 大小写或尾随点空格名称冲突")
    missing = sorted(expected_names - actual_names)
    extra = sorted(actual_names - expected_names)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append("缺少 " + ", ".join(missing))
        if extra:
            details.append("存在额外文件 " + ", ".join(extra))
        raise fail("; ".join(details))
    for entry in entries:
        path = Path(entry.path)
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise fail(f"无法检查 {entry.name}: {exc}") from exc
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        if entry.is_symlink() or attributes & reparse_flag or not stat.S_ISREG(metadata.st_mode):
            raise fail(f"{entry.name} 不是普通文件")
        if path.name == config.provenance_filename:
            try:
                actual_provenance = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise fail(f"无法读取 {entry.name}: {exc}") from exc
            if actual_provenance != render_archive_runtime_provenance(config):
                raise fail(f"{entry.name} 内容与参数规范不一致")
    for required in config.required_files:
        path = runtime_dir / required.filename
        actual = _sha256_file(path)
        if actual != required.sha256:
            raise fail(
                f"{required.filename} SHA256 不匹配; "
                f"expected={required.sha256}; actual={actual}"
            )


def validate_archive_runtime_cache(
    repo_root: Path,
    config: ArchiveRuntimeMechanismConfig | None = None,
) -> Path:
    resolved_config = config or _load_archive_runtime_config(repo_root)
    cache_dir = _resolve_repo_path(
        repo_root,
        resolved_config.cache_dir,
        label="archive runtime cache_dir",
    )
    _validate_runtime_directory(cache_dir, resolved_config, cache_message=True)
    return cache_dir.resolve()


def validate_deployed_archive_runtime(
    package_root: Path,
    config: ArchiveRuntimeMechanismConfig,
) -> Path:
    runtime_dir = _resolve_repo_path(
        package_root,
        config.destination_dir,
        label="deployed archive runtime destination_dir",
    )
    _validate_runtime_directory(runtime_dir, config, cache_message=False)
    return runtime_dir.resolve()


def archive_runtime_copy_plan(
    repo_root: Path,
    config: ArchiveRuntimeMechanismConfig | None = None,
) -> list[ArchiveRuntimeCopyEntry]:
    resolved_config = config or _load_archive_runtime_config(repo_root)
    cache_dir = validate_archive_runtime_cache(repo_root, resolved_config)
    destination = Path(resolved_config.destination_dir)
    filenames = [item.filename for item in resolved_config.required_files]
    filenames.append(resolved_config.provenance_filename)
    return [
        ArchiveRuntimeCopyEntry(
            source=cache_dir / filename,
            destination=destination / filename,
        )
        for filename in filenames
    ]


def _download_asset(
    url: str,
    destination: Path,
    timeout_sec: int,
    expected_size: int,
) -> None:
    if urlsplit(url).scheme.casefold() != "https":
        raise ArchiveRuntimeError(f"7-Zip 官方资产 URL 必须使用 HTTPS: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(url, timeout=timeout_sec) as response, destination.open("wb") as output:
            final_url = str(response.geturl())
            if urlsplit(final_url).scheme.casefold() != "https":
                raise ArchiveRuntimeError(
                    f"7-Zip 官方资产重定向终点必须使用 HTTPS: {final_url}"
                )
            total = 0
            while True:
                remaining_with_probe = expected_size - total + 1
                chunk = response.read(min(1024 * 1024, max(1, remaining_with_probe)))
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_size:
                    raise ArchiveRuntimeError(
                        f"7-Zip 官方资产大小超过参数规范: expected={expected_size}; actual>{expected_size}"
                    )
                output.write(chunk)
            if total != expected_size:
                raise ArchiveRuntimeError(
                    f"7-Zip 官方资产大小与参数规范不一致: "
                    f"expected={expected_size}; actual={total}"
                )
    except ArchiveRuntimeError:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise ArchiveRuntimeError(f"下载 7-Zip 官方资产失败: {url}: {exc}") from exc


def _download_and_verify(
    asset: ArchiveRuntimeAssetConfig,
    destination: Path,
    *,
    timeout_sec: int,
    downloader: Downloader,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        downloader(asset.url, destination, timeout_sec, asset.size_bytes)
    except ArchiveRuntimeError:
        raise
    except Exception as exc:
        raise ArchiveRuntimeError(f"下载 7-Zip 官方资产失败: {asset.url}: {exc}") from exc
    _ensure_regular_file(destination, label=f"下载资产 {asset.filename}")
    actual_size = destination.stat().st_size
    if actual_size != asset.size_bytes:
        raise ArchiveRuntimeError(
            f"下载资产 {asset.filename} 大小校验失败: "
            f"expected={asset.size_bytes}; actual={actual_size}"
        )
    _verify_hash(destination, asset.sha256, label=f"下载资产 {asset.filename}")


def _extract_source(
    *,
    bootstrap: Path,
    source: Path,
    output_dir: Path,
    timeout_sec: int,
    runner: Runner,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(bootstrap.resolve()),
        "x",
        "-y",
        "-bd",
        f"-o{output_dir.resolve()}",
        str(source.resolve()),
    ]
    try:
        completed = runner(
            command,
            cwd=output_dir.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArchiveRuntimeError(f"7zr 解包官方 7-Zip SFX 失败: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise ArchiveRuntimeError(
            f"7zr 解包官方 7-Zip SFX 失败，exit={completed.returncode}: {detail}"
        )


def _publish_atomically(staged_runtime: Path, cache_dir: Path, temporary_root: Path) -> None:
    previous = temporary_root / "previous-cache"
    had_previous = cache_dir.exists()
    if had_previous:
        if not cache_dir.is_dir() or cache_dir.is_symlink():
            raise ArchiveRuntimeError(f"7-Zip 缓存目标不是普通目录: {cache_dir}")
        os.replace(cache_dir, previous)
    try:
        os.replace(staged_runtime, cache_dir)
    except Exception:
        if had_previous and previous.exists() and not cache_dir.exists():
            os.replace(previous, cache_dir)
        raise


def prepare_archive_runtime(
    *,
    repo_root: Path,
    config: ArchiveRuntimeMechanismConfig | None = None,
    downloader: Downloader = _download_asset,
    runner: Runner = subprocess.run,
) -> Path:
    resolved_config = config or _load_archive_runtime_config(repo_root)
    cache_dir = _resolve_repo_path(
        repo_root,
        resolved_config.cache_dir,
        label="archive runtime cache_dir",
    )
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".7zip-prepare-",
        dir=cache_dir.parent,
    ) as temporary_name:
        temporary_root = Path(temporary_name)
        downloads = temporary_root / "downloads"
        source = downloads / resolved_config.source.filename
        bootstrap = downloads / resolved_config.bootstrap.filename
        _download_and_verify(
            resolved_config.source,
            source,
            timeout_sec=resolved_config.download_timeout_sec,
            downloader=downloader,
        )
        _download_and_verify(
            resolved_config.bootstrap,
            bootstrap,
            timeout_sec=resolved_config.download_timeout_sec,
            downloader=downloader,
        )
        extracted = temporary_root / "extracted"
        _extract_source(
            bootstrap=bootstrap,
            source=source,
            output_dir=extracted,
            timeout_sec=resolved_config.prepare_timeout_sec,
            runner=runner,
        )
        staged_runtime = temporary_root / "runtime"
        staged_runtime.mkdir()
        for required in resolved_config.required_files:
            extracted_file = extracted / required.filename
            _verify_hash(
                extracted_file,
                required.sha256,
                label=f"解包文件 {required.filename}",
            )
            shutil.copy2(extracted_file, staged_runtime / required.filename)
        (staged_runtime / resolved_config.provenance_filename).write_text(
            render_archive_runtime_provenance(resolved_config),
            encoding="utf-8",
            newline="\n",
        )
        _validate_runtime_directory(
            staged_runtime,
            resolved_config,
            cache_message=False,
        )
        try:
            _publish_atomically(staged_runtime, cache_dir, temporary_root)
        except ArchiveRuntimeError:
            raise
        except OSError as exc:
            raise ArchiveRuntimeError(f"原子发布 7-Zip 运行时失败: {exc}") from exc
    return validate_archive_runtime_cache(repo_root, resolved_config)


__all__ = [
    "ArchiveRuntimeCopyEntry",
    "ArchiveRuntimeError",
    "archive_runtime_copy_plan",
    "prepare_archive_runtime",
    "render_archive_runtime_provenance",
    "validate_archive_runtime_cache",
    "validate_deployed_archive_runtime",
]
