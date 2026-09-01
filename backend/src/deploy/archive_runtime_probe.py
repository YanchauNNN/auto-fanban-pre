from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import threading
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZIP_STORED, ZipFile

from ..config.mechanism_spec import (
    DEFAULT_MECHANISM_SPEC_PATH,
    ArchiveRuntimeMechanismConfig,
    MechanismSpecLoader,
)
from .archive_runtime import ArchiveRuntimeError, validate_deployed_archive_runtime


class ArchiveRuntimeProbeError(RuntimeError):
    """Stable, path-neutral failure raised by the private archive runtime probe."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BoundedCommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[..., BoundedCommandResult]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse(path: Path, metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return path.is_symlink() or bool(attributes & reparse_flag)


def _resolve_verified_asset(
    module_dir: Path,
    relative_path: str,
    *,
    expected_size: int,
    expected_sha256: str,
) -> tuple[Path, bytes]:
    try:
        root = module_dir.resolve(strict=True)
    except OSError as exc:
        raise ArchiveRuntimeProbeError(
            "fixture_validation_failed",
            "probe fixture directory is unavailable",
        ) from exc
    candidate = root / Path(relative_path)
    current = root
    for part in Path(relative_path).parts:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ArchiveRuntimeProbeError(
                "fixture_validation_failed",
                "probe fixture asset is unavailable",
            ) from exc
        if _is_reparse(current, metadata):
            raise ArchiveRuntimeProbeError(
                "fixture_validation_failed",
                "probe fixture asset must not use links or reparse points",
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        metadata = candidate.lstat()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ArchiveRuntimeProbeError(
            "fixture_validation_failed",
            "probe fixture asset escaped its managed directory",
        ) from exc
    if _is_reparse(candidate, metadata) or not stat.S_ISREG(metadata.st_mode):
        raise ArchiveRuntimeProbeError(
            "fixture_validation_failed",
            "probe fixture asset must be a regular file",
        )
    if metadata.st_size != expected_size:
        raise ArchiveRuntimeProbeError(
            "fixture_validation_failed",
            "probe fixture asset integrity verification failed",
        )
    try:
        with candidate.open("rb") as handle:
            opened_metadata = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened_metadata.st_mode)
                or opened_metadata.st_size != expected_size
            ):
                raise ArchiveRuntimeProbeError(
                    "fixture_validation_failed",
                    "probe fixture asset integrity verification failed",
                )
            payload = handle.read(expected_size + 1)
    except OSError as exc:
        raise ArchiveRuntimeProbeError(
            "fixture_validation_failed",
            "probe fixture asset could not be read",
        ) from exc
    if len(payload) != expected_size or _sha256_bytes(payload) != expected_sha256:
        raise ArchiveRuntimeProbeError(
            "fixture_validation_failed",
            "probe fixture asset integrity verification failed",
        )
    return resolved, payload


def run_bounded_command(
    command: Sequence[str],
    *,
    timeout_sec: int,
    max_output_bytes: int,
) -> BoundedCommandResult:
    if not command or not Path(command[0]).is_absolute():
        raise ArchiveRuntimeProbeError(
            "command_invalid",
            "archive runtime command executable must be absolute",
        )

    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = int(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    try:
        process = subprocess.Popen(list(command), **popen_kwargs)
    except OSError as exc:
        raise ArchiveRuntimeProbeError(
            "command_start_failed",
            "private archive runtime command could not start",
        ) from exc

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    output_size = 0
    output_lock = threading.Lock()
    output_exceeded = threading.Event()

    def drain(stream: Any, chunks: list[bytes]) -> None:
        nonlocal output_size
        if stream is None:
            return
        while True:
            block = stream.read(64 * 1024)
            if not block:
                break
            if isinstance(block, str):
                block = block.encode("utf-8", errors="replace")
            with output_lock:
                remaining = max_output_bytes - output_size
                if remaining > 0:
                    accepted = block[:remaining]
                    chunks.append(accepted)
                    output_size += len(accepted)
                if len(block) > max(remaining, 0):
                    output_exceeded.set()
            if output_exceeded.is_set():
                with suppress(OSError):
                    process.kill()
                break

    threads = [
        threading.Thread(target=drain, args=(process.stdout, stdout_chunks), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr_chunks), daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        returncode = process.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired as exc:
        with suppress(OSError):
            process.kill()
        with suppress(OSError, subprocess.TimeoutExpired):
            process.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=1)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        raise ArchiveRuntimeProbeError(
            "command_timeout",
            "private archive runtime command timed out",
        ) from exc
    for thread in threads:
        thread.join(timeout=1)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    if output_exceeded.is_set():
        raise ArchiveRuntimeProbeError(
            "command_output_limit",
            "private archive runtime command exceeded its output limit",
        )
    stdout = b"".join(stdout_chunks).decode("utf-8-sig", errors="replace")
    stderr = b"".join(stderr_chunks).decode("utf-8-sig", errors="replace")
    return BoundedCommandResult(returncode, stdout, stderr)


def _invoke(
    executable: Path,
    arguments: Sequence[str],
    *,
    config: ArchiveRuntimeMechanismConfig,
    command_runner: CommandRunner,
) -> BoundedCommandResult:
    command = (str(executable.resolve()), *(str(argument) for argument in arguments))
    result = command_runner(
        command,
        timeout_sec=config.probe.timeout_sec,
        max_output_bytes=config.probe.max_output_bytes,
    )
    if result.returncode != 0:
        raise ArchiveRuntimeProbeError(
            "command_failed",
            "private archive runtime command returned a non-zero exit code",
        )
    return result


def _validate_info_output(
    output: str,
    config: ArchiveRuntimeMechanismConfig,
) -> None:
    if config.version_marker not in output:
        raise ArchiveRuntimeProbeError(
            "version_mismatch",
            "private archive runtime version verification failed",
        )
    tokens: set[str] = set()
    in_formats = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped == "Formats:":
            in_formats = True
            continue
        if in_formats and stripped.endswith(":"):
            break
        if in_formats:
            tokens.update(stripped.split())
    missing = [handler for handler in config.required_handlers if handler not in tokens]
    if missing:
        raise ArchiveRuntimeProbeError(
            "required_handlers_missing",
            "private archive runtime is missing required handlers: " + ", ".join(missing),
        )


def _parse_listed_payloads(output: str) -> list[tuple[str, int]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in (*output.splitlines(), ""):
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        current[key.strip()] = value.strip()
    payloads: list[tuple[str, int]] = []
    for record in records:
        if "Path" not in record or "Size" not in record or "Type" in record:
            continue
        try:
            payloads.append((record["Path"], int(record["Size"])))
        except ValueError as exc:
            raise ArchiveRuntimeProbeError(
                "list_validation_failed",
                "archive runtime list output contained an invalid size",
            ) from exc
    return payloads


def _validate_list_output(output: str, config: ArchiveRuntimeMechanismConfig) -> None:
    payloads = _parse_listed_payloads(output)
    expected = [(config.probe.payload_filename, config.probe.payload_size_bytes)]
    if payloads != expected:
        raise ArchiveRuntimeProbeError(
            "list_validation_failed",
            "archive runtime list output did not contain the exact probe payload",
        )


def _validate_extracted_payload(
    output_dir: Path,
    config: ArchiveRuntimeMechanismConfig,
) -> None:
    try:
        entries = list(output_dir.rglob("*"))
    except OSError as exc:
        raise ArchiveRuntimeProbeError(
            "payload_validation_failed",
            "probe payload output could not be inspected",
        ) from exc
    if len(entries) != 1:
        raise ArchiveRuntimeProbeError(
            "payload_validation_failed",
            "probe extraction did not produce exactly one payload",
        )
    payload = entries[0]
    try:
        metadata = payload.lstat()
    except OSError as exc:
        raise ArchiveRuntimeProbeError(
            "payload_validation_failed",
            "probe payload output could not be inspected",
        ) from exc
    if (
        payload.relative_to(output_dir).as_posix() != config.probe.payload_filename
        or _is_reparse(payload, metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size != config.probe.payload_size_bytes
        or _sha256_file(payload) != config.probe.payload_sha256
    ):
        raise ArchiveRuntimeProbeError(
            "payload_validation_failed",
            "probe extraction payload integrity verification failed",
        )


def _probe_archive(
    archive: Path,
    output_dir: Path,
    *,
    executable: Path,
    config: ArchiveRuntimeMechanismConfig,
    command_runner: CommandRunner,
) -> dict[str, bool | str]:
    listed = _invoke(
        executable,
        ("l", "-slt", "-sccUTF-8", "-bd", str(archive.resolve())),
        config=config,
        command_runner=command_runner,
    )
    _validate_list_output(listed.stdout, config)
    _invoke(
        executable,
        (
            "x",
            "-y",
            "-bd",
            "-bb0",
            "-sccUTF-8",
            str(archive.resolve()),
            "-o" + str(output_dir.resolve()),
        ),
        config=config,
        command_runner=command_runner,
    )
    _validate_extracted_payload(output_dir, config)
    return {"status": "pass", "listed": True, "extracted": True}


def run_archive_runtime_probe(
    package_root: Path,
    config: ArchiveRuntimeMechanismConfig,
    *,
    fixture_module_dir: Path | None = None,
    command_runner: CommandRunner = run_bounded_command,
) -> dict[str, Any]:
    try:
        runtime_dir = validate_deployed_archive_runtime(package_root, config)
    except ArchiveRuntimeError as exc:
        raise ArchiveRuntimeProbeError(
            "runtime_integrity_failed",
            "private archive runtime integrity verification failed",
        ) from exc
    executable = (runtime_dir / "7z.exe").resolve()
    if not executable.is_absolute():
        raise ArchiveRuntimeProbeError(
            "runtime_integrity_failed",
            "private archive runtime executable was not resolved absolutely",
        )

    module_dir = (fixture_module_dir or Path(__file__).resolve().parent).resolve()
    _, encoded_fixture = _resolve_verified_asset(
        module_dir,
        config.probe.fixture_source_relative_path,
        expected_size=config.probe.fixture_source_size_bytes,
        expected_sha256=config.probe.fixture_source_sha256,
    )
    _, payload = _resolve_verified_asset(
        module_dir,
        config.probe.payload_source_relative_path,
        expected_size=config.probe.payload_size_bytes,
        expected_sha256=config.probe.payload_sha256,
    )
    try:
        compact_fixture = b"".join(encoded_fixture.split())
        decoded_fixture = base64.b64decode(compact_fixture, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ArchiveRuntimeProbeError(
            "fixture_validation_failed",
            "probe fixture Base64 decoding failed",
        ) from exc
    if (
        len(decoded_fixture) != config.probe.fixture_decoded_size_bytes
        or _sha256_bytes(decoded_fixture) != config.probe.fixture_decoded_sha256
    ):
        raise ArchiveRuntimeProbeError(
            "fixture_validation_failed",
            "decoded probe fixture integrity verification failed",
        )

    info = _invoke(
        executable,
        ("i", "-sccUTF-8", "-bd"),
        config=config,
        command_runner=command_runner,
    )
    _validate_info_output(info.stdout, config)

    with tempfile.TemporaryDirectory(prefix="fanban-archive-runtime-probe-") as temp_text:
        temp_root = Path(temp_text).resolve()
        payload_path = temp_root / config.probe.payload_filename
        payload_path.write_bytes(payload)
        zip_path = (temp_root / "probe.zip").resolve()
        with ZipFile(zip_path, "w", compression=ZIP_STORED) as archive:
            archive.writestr(config.probe.payload_filename, payload)
        seven_path = (temp_root / "probe.7z").resolve()
        _invoke(
            executable,
            (
                "a",
                "-t7z",
                "-mx=0",
                "-bd",
                "-bb0",
                "-sccUTF-8",
                str(seven_path),
                str(payload_path.resolve()),
            ),
            config=config,
            command_runner=command_runner,
        )
        rar_path = (temp_root / "probe.rar").resolve()
        rar_path.write_bytes(decoded_fixture)

        formats: dict[str, dict[str, bool | str]] = {}
        for label, archive_path in (
            ("zip", zip_path),
            ("7z", seven_path),
            ("rar5", rar_path),
        ):
            output_dir = (temp_root / f"extract-{label}").resolve()
            output_dir.mkdir()
            formats[label] = _probe_archive(
                archive_path,
                output_dir,
                executable=executable,
                config=config,
                command_runner=command_runner,
            )

    return {
        "status": "pass",
        "ok": True,
        "executable": str(executable),
        "version_marker": config.version_marker,
        "required_handlers": list(config.required_handlers),
        "formats": formats,
    }


def probe_archive_runtime_package(package_root: Path) -> dict[str, Any]:
    spec_path = package_root.resolve() / DEFAULT_MECHANISM_SPEC_PATH
    try:
        mechanism = MechanismSpecLoader.load(spec_path)
    except Exception as exc:
        raise ArchiveRuntimeProbeError(
            "mechanism_config_invalid",
            "archive runtime mechanism configuration could not be loaded",
        ) from exc
    config = mechanism.deployment_mechanism.archive_runtime
    if config is None:
        raise ArchiveRuntimeProbeError(
            "mechanism_config_missing",
            "archive runtime mechanism configuration is missing",
        )
    return run_archive_runtime_probe(package_root.resolve(), config)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe the packaged private 7-Zip runtime")
    parser.add_argument("--package-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = probe_archive_runtime_package(args.package_root)
    except ArchiveRuntimeProbeError as exc:
        result = {
            "status": "fail",
            "ok": False,
            "code": exc.code,
            "error": str(exc),
        }
        exit_code = 2
    except Exception:
        result = {
            "status": "fail",
            "ok": False,
            "code": "internal_error",
            "error": "archive runtime probe failed unexpectedly",
        }
        exit_code = 3
    else:
        exit_code = 0
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
