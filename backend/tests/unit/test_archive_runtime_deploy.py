from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from src.config.mechanism_spec import (
    ArchiveRuntimeAssetConfig,
    ArchiveRuntimeFileConfig,
    ArchiveRuntimeMechanismConfig,
    ArchiveRuntimeProbeConfig,
    DeploymentMechanismConfig,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


SOURCE = b"official-sfx"
BOOTSTRAP = b"official-bootstrap"
FILES = {
    "7z.exe": b"portable-7z-exe",
    "7z.dll": b"portable-7z-dll",
    "License.txt": b"7-zip-license",
}


def _config() -> ArchiveRuntimeMechanismConfig:
    return ArchiveRuntimeMechanismConfig(
        version="26.02-test",
        architecture="x64",
        source=ArchiveRuntimeAssetConfig(
            filename="7z-test-x64.exe",
            url="https://example.invalid/7z-test-x64.exe",
            sha256=_sha(SOURCE),
            size_bytes=len(SOURCE),
        ),
        bootstrap=ArchiveRuntimeAssetConfig(
            filename="7zr.exe",
            url="https://example.invalid/7zr.exe",
            sha256=_sha(BOOTSTRAP),
            size_bytes=len(BOOTSTRAP),
        ),
        license_url="https://example.invalid/license.txt",
        cache_dir="build/runtime-cache/7-Zip",
        destination_dir="bin/7-Zip",
        provenance_filename="PROVENANCE.txt",
        required_files=tuple(
            ArchiveRuntimeFileConfig(filename=name, sha256=_sha(payload))
            for name, payload in FILES.items()
        ),
        required_handlers=("7z", "zip", "Rar", "Rar5"),
        version_marker="7-Zip 26.02-test (x64)",
        download_timeout_sec=15,
        prepare_timeout_sec=20,
        probe=ArchiveRuntimeProbeConfig(
            timeout_sec=5,
            max_output_bytes=131_072,
            fixture_source_relative_path="fixtures/archive-runtime-smoke-rar5.rar.b64",
            fixture_encoding="base64",
            fixture_source_sha256=_sha(b"fixture-source"),
            fixture_source_size_bytes=len(b"fixture-source"),
            fixture_decoded_sha256=_sha(b"fixture-decoded"),
            fixture_decoded_size_bytes=len(b"fixture-decoded"),
            payload_source_relative_path="fixtures/archive-runtime-smoke.txt",
            payload_filename="archive-runtime-smoke.txt",
            payload_sha256=_sha(b"payload"),
            payload_size_bytes=len(b"payload"),
        ),
    )


def _downloader(url: str, destination: Path, timeout_sec: int, expected_size: int) -> None:
    assert timeout_sec == 15
    payload = BOOTSTRAP if url.endswith("7zr.exe") else SOURCE
    assert expected_size == len(payload)
    destination.write_bytes(payload)


def _runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
    output_arg = next(item for item in command if item.startswith("-o"))
    output_dir = Path(output_arg[2:])
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in FILES.items():
        (output_dir / name).write_bytes(payload)
    return subprocess.CompletedProcess(command, 0, stdout="Everything is Ok", stderr="")


def test_prepare_and_copy_private_archive_runtime(tmp_path: Path) -> None:
    from src.deploy.archive_runtime import archive_runtime_copy_plan, prepare_archive_runtime

    config = _config()
    cache_dir = prepare_archive_runtime(
        repo_root=tmp_path,
        config=config,
        downloader=_downloader,
        runner=_runner,
    )

    assert {path.name for path in cache_dir.iterdir()} == {
        "7z.exe",
        "7z.dll",
        "License.txt",
        "PROVENANCE.txt",
    }
    assert [entry.destination.as_posix() for entry in archive_runtime_copy_plan(tmp_path, config)] == [
        "bin/7-Zip/7z.exe",
        "bin/7-Zip/7z.dll",
        "bin/7-Zip/License.txt",
        "bin/7-Zip/PROVENANCE.txt",
    ]


def test_archive_runtime_copy_plan_fails_closed_when_cache_is_missing(tmp_path: Path) -> None:
    from src.deploy.archive_runtime import ArchiveRuntimeError, archive_runtime_copy_plan

    with pytest.raises(ArchiveRuntimeError, match="prepare_archive_runtime.py"):
        archive_runtime_copy_plan(tmp_path, _config())


def test_terminal_package_copy_plan_includes_private_archive_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.deploy.terminal_package as terminal_package
    from src.deploy.archive_runtime import prepare_archive_runtime

    config = _config()
    prepare_archive_runtime(
        repo_root=tmp_path,
        config=config,
        downloader=_downloader,
        runner=_runner,
    )
    monkeypatch.setattr(
        terminal_package,
        "_deployment_mechanism",
        lambda _root=None: DeploymentMechanismConfig(archive_runtime=config),
    )

    destinations = {entry.destination.as_posix() for entry in terminal_package.gather_copy_plan(tmp_path)}

    assert "bin/7-Zip/7z.exe" in destinations
    assert "bin/7-Zip/7z.dll" in destinations
    assert "bin/7-Zip/License.txt" in destinations
    assert "bin/7-Zip/PROVENANCE.txt" in destinations
