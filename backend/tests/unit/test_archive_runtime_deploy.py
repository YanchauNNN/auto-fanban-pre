from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

import src.deploy.archive_runtime as archive_runtime_mod
from src.config.mechanism_spec import (
    ArchiveRuntimeAssetConfig,
    ArchiveRuntimeFileConfig,
    ArchiveRuntimeMechanismConfig,
)
from src.deploy.archive_runtime import (
    ArchiveRuntimeError,
    archive_runtime_copy_plan,
    prepare_archive_runtime,
    render_archive_runtime_provenance,
    validate_archive_runtime_cache,
    validate_deployed_archive_runtime,
)
from src.deploy.terminal_package import (
    PACKAGE_MANIFEST,
    build_terminal_deploy_delta_package,
    write_package_manifest,
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


def _config(
    *,
    source_sha256: str | None = None,
    bootstrap_sha256: str | None = None,
    required_files: dict[str, bytes] | None = None,
    cache_dir: str = "build/runtime-cache/7-Zip",
) -> ArchiveRuntimeMechanismConfig:
    file_payloads = required_files if required_files is not None else FILES
    return ArchiveRuntimeMechanismConfig(
        version="26.02-test",
        architecture="x64",
        source=ArchiveRuntimeAssetConfig(
            filename="7z-test-x64.exe",
            url="https://example.invalid/7z-test-x64.exe",
            sha256=source_sha256 or _sha(SOURCE),
            size_bytes=len(SOURCE),
        ),
        bootstrap=ArchiveRuntimeAssetConfig(
            filename="7zr.exe",
            url="https://example.invalid/7zr.exe",
            sha256=bootstrap_sha256 or _sha(BOOTSTRAP),
            size_bytes=len(BOOTSTRAP),
        ),
        license_url="https://example.invalid/license.txt",
        cache_dir=cache_dir,
        destination_dir="bin/7-Zip",
        provenance_filename="PROVENANCE.txt",
        required_files=tuple(
            ArchiveRuntimeFileConfig(filename=name, sha256=_sha(payload))
            for name, payload in file_payloads.items()
        ),
        required_handlers=("7z", "zip", "Rar", "Rar5"),
        version_marker="7-Zip 26.02-test (x64)",
        download_timeout_sec=15,
        prepare_timeout_sec=20,
    )


def _downloader(url: str, destination: Path, timeout_sec: int, expected_size: int) -> None:
    assert timeout_sec == 15
    payload = BOOTSTRAP if url.endswith("7zr.exe") else SOURCE
    assert expected_size == len(payload)
    destination.write_bytes(payload)


def _runner_with_files(files: dict[str, bytes]):
    calls: list[tuple[list[str], dict[str, object]]] = []

    def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        output_arg = next(item for item in command if item.startswith("-o"))
        output_dir = Path(output_arg[2:])
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in files.items():
            (output_dir / name).write_bytes(payload)
        return subprocess.CompletedProcess(command, 0, stdout="Everything is Ok", stderr="")

    return _run, calls


def _write_valid_runtime(runtime_dir: Path, config: ArchiveRuntimeMechanismConfig) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in FILES.items():
        (runtime_dir / name).write_bytes(payload)
    (runtime_dir / config.provenance_filename).write_text(
        render_archive_runtime_provenance(config), encoding="utf-8"
    )


class _FakeResponse:
    def __init__(self, payload: bytes, *, final_url: str = "https://cdn.example/file") -> None:
        self._stream = io.BytesIO(payload)
        self._final_url = final_url

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._final_url


@pytest.mark.parametrize("payload", [SOURCE[:-1], SOURCE + b"too-long"])
def test_download_asset_rejects_inexact_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    monkeypatch.setattr(
        archive_runtime_mod,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(payload),
    )
    destination = tmp_path / "asset.exe"

    with pytest.raises(ArchiveRuntimeError, match="大小"):
        archive_runtime_mod._download_asset(
            "https://example.invalid/asset.exe",
            destination,
            15,
            len(SOURCE),
        )

    assert not destination.exists()


def test_download_asset_rejects_http_redirect_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        archive_runtime_mod,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(SOURCE, final_url="http://cdn.example/file"),
    )
    destination = tmp_path / "asset.exe"

    with pytest.raises(ArchiveRuntimeError, match="HTTPS"):
        archive_runtime_mod._download_asset(
            "https://example.invalid/asset.exe",
            destination,
            15,
            len(SOURCE),
        )

    assert not destination.exists()


def test_archive_runtime_config_rejects_windows_casefold_name_conflicts() -> None:
    payload = _config().model_dump()
    payload["required_files"] = [
        {"filename": "7z.exe", "sha256": "0" * 64},
        {"filename": "7Z.EXE", "sha256": "1" * 64},
    ]

    with pytest.raises(ValidationError, match="unique"):
        ArchiveRuntimeMechanismConfig(**payload)

    payload = _config().model_dump()
    payload["provenance_filename"] = "7Z.ExE"
    with pytest.raises(ValidationError, match="provenance"):
        ArchiveRuntimeMechanismConfig(**payload)


def test_archive_runtime_config_rejects_parent_traversal() -> None:
    payload = _config().model_dump()
    payload["cache_dir"] = "../outside"

    with pytest.raises(ValidationError, match="package-relative"):
        ArchiveRuntimeMechanismConfig(**payload)


@pytest.mark.parametrize(
    ("bad_field", "expected"),
    [("source", "7z-test-x64.exe"), ("bootstrap", "7zr.exe")],
)
def test_prepare_archive_runtime_rejects_download_hash_mismatch(
    tmp_path: Path,
    bad_field: str,
    expected: str,
) -> None:
    kwargs = {f"{bad_field}_sha256": "0" * 64}
    config = _config(**kwargs)
    runner, _ = _runner_with_files(FILES)

    with pytest.raises(ArchiveRuntimeError, match=expected):
        prepare_archive_runtime(
            repo_root=tmp_path,
            config=config,
            downloader=_downloader,
            runner=runner,
        )

    assert not (tmp_path / config.cache_dir).exists()


def test_prepare_archive_runtime_rejects_missing_required_file(tmp_path: Path) -> None:
    config = _config()
    runner, _ = _runner_with_files({"7z.exe": FILES["7z.exe"], "7z.dll": FILES["7z.dll"]})

    with pytest.raises(ArchiveRuntimeError, match="License.txt"):
        prepare_archive_runtime(
            repo_root=tmp_path,
            config=config,
            downloader=_downloader,
            runner=runner,
        )


def test_prepare_archive_runtime_rejects_extracted_file_hash_mismatch(tmp_path: Path) -> None:
    config = _config()
    extracted = dict(FILES)
    extracted["7z.dll"] = b"tampered"
    runner, _ = _runner_with_files(extracted)

    with pytest.raises(ArchiveRuntimeError, match="7z.dll"):
        prepare_archive_runtime(
            repo_root=tmp_path,
            config=config,
            downloader=_downloader,
            runner=runner,
        )


def test_prepare_archive_runtime_atomically_publishes_whitelist_and_provenance(
    tmp_path: Path,
) -> None:
    config = _config()
    cache = tmp_path / config.cache_dir
    cache.mkdir(parents=True)
    (cache / "old.txt").write_text("old", encoding="utf-8")
    runner, calls = _runner_with_files({**FILES, "Lang.dll": b"must-not-be-published"})

    result = prepare_archive_runtime(
        repo_root=tmp_path,
        config=config,
        downloader=_downloader,
        runner=runner,
    )

    assert result == cache.resolve()
    assert {path.name for path in cache.iterdir()} == {*FILES, "PROVENANCE.txt"}
    assert (cache / "PROVENANCE.txt").read_text(encoding="utf-8") == (
        render_archive_runtime_provenance(config)
    )
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert Path(command[0]).name == "7zr.exe"
    assert command[1:4] == ["x", "-y", "-bd"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 20
    assert not any(path.name.startswith(".7zip-prepare-") for path in cache.parent.iterdir())


def test_prepare_archive_runtime_preserves_existing_cache_on_failed_prepare(tmp_path: Path) -> None:
    config = _config()
    cache = tmp_path / config.cache_dir
    cache.mkdir(parents=True)
    (cache / "sentinel.txt").write_text("keep", encoding="utf-8")
    runner, _ = _runner_with_files({"7z.exe": b"wrong"})

    with pytest.raises(ArchiveRuntimeError):
        prepare_archive_runtime(
            repo_root=tmp_path,
            config=config,
            downloader=_downloader,
            runner=runner,
        )

    assert (cache / "sentinel.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("mutation", ["missing", "extra", "tampered"])
def test_validate_archive_runtime_cache_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    config = _config()
    cache = tmp_path / config.cache_dir
    cache.mkdir(parents=True)
    for name, payload in FILES.items():
        (cache / name).write_bytes(payload)
    (cache / "PROVENANCE.txt").write_text(
        render_archive_runtime_provenance(config), encoding="utf-8"
    )
    if mutation == "missing":
        (cache / "7z.dll").unlink()
    elif mutation == "extra":
        (cache / "7zr.exe").write_bytes(BOOTSTRAP)
    else:
        (cache / "7z.exe").write_bytes(b"tampered")

    with pytest.raises(ArchiveRuntimeError, match="prepare_archive_runtime.py"):
        validate_archive_runtime_cache(tmp_path, config)


def test_validate_archive_runtime_cache_rejects_symlink_escape(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    outside = tmp_path / "outside"
    config = _config(cache_dir="runtime-link")
    _write_valid_runtime(outside, config)
    repo_root.mkdir()
    link = repo_root / "runtime-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(ArchiveRuntimeError, match="重解析|链接|仓库"):
        validate_archive_runtime_cache(repo_root, config)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_prepare_archive_runtime_rejects_junction_parent_escape(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    junction_parent = repo_root / "build" / "runtime-cache"
    outside_parent = tmp_path / "outside-cache"
    outside_parent.mkdir(parents=True)
    junction_parent.parent.mkdir(parents=True)
    created = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction_parent), str(outside_parent)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"junction creation unavailable: {created.stderr or created.stdout}")
    config = _config()
    downloads: list[str] = []

    def unexpected_downloader(
        url: str,
        _destination: Path,
        _timeout_sec: int,
        _expected_size: int,
    ) -> None:
        downloads.append(url)

    runner, _ = _runner_with_files(FILES)
    try:
        with pytest.raises(ArchiveRuntimeError, match="重解析|链接|仓库"):
            prepare_archive_runtime(
                repo_root=repo_root,
                config=config,
                downloader=unexpected_downloader,
                runner=runner,
            )
        assert downloads == []
        assert not (outside_parent / "7-Zip").exists()
    finally:
        if junction_parent.exists():
            os.rmdir(junction_parent)


def test_validate_archive_runtime_cache_rejects_casefold_duplicate_entries(
    tmp_path: Path,
) -> None:
    config = _config()
    runtime_dir = tmp_path / config.cache_dir
    _write_valid_runtime(runtime_dir, config)
    alias = runtime_dir / "7Z.EXE"
    alias.write_bytes(b"case-conflict")
    if len(list(runtime_dir.iterdir())) == 4:
        pytest.skip("filesystem is case-insensitive")

    with pytest.raises(ArchiveRuntimeError, match="名称冲突"):
        validate_archive_runtime_cache(tmp_path, config)


def test_validate_deployed_archive_runtime_rechecks_exact_package_files(tmp_path: Path) -> None:
    config = _config()
    deployed = tmp_path / config.destination_dir
    _write_valid_runtime(deployed, config)

    assert validate_deployed_archive_runtime(tmp_path, config) == deployed.resolve()

    (deployed / "7z.dll").write_bytes(b"tampered-after-copy")
    with pytest.raises(ArchiveRuntimeError, match="7z.dll"):
        validate_deployed_archive_runtime(tmp_path, config)


def test_archive_runtime_copy_plan_contains_only_four_verified_files(tmp_path: Path) -> None:
    config = _config()
    runner, _ = _runner_with_files(FILES)
    prepare_archive_runtime(
        repo_root=tmp_path,
        config=config,
        downloader=_downloader,
        runner=runner,
    )

    plan = archive_runtime_copy_plan(tmp_path, config)

    assert [(entry.source.name, entry.destination.as_posix()) for entry in plan] == [
        ("7z.exe", "bin/7-Zip/7z.exe"),
        ("7z.dll", "bin/7-Zip/7z.dll"),
        ("License.txt", "bin/7-Zip/License.txt"),
        ("PROVENANCE.txt", "bin/7-Zip/PROVENANCE.txt"),
    ]


def test_archive_runtime_files_are_recorded_in_full_and_delta_manifests(tmp_path: Path) -> None:
    config = _config()
    runner, _ = _runner_with_files(FILES)
    prepare_archive_runtime(
        repo_root=tmp_path,
        config=config,
        downloader=_downloader,
        runner=runner,
    )
    full = tmp_path / "full"
    for entry in archive_runtime_copy_plan(tmp_path, config):
        target = full / entry.destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(entry.source.read_bytes())
    manifest = write_package_manifest(full, package_kind="full")
    entries = {item["path"]: item["sha256"] for item in manifest["files"]}
    assert entries["bin/7-Zip/7z.exe"] == _sha(FILES["7z.exe"])
    assert entries["bin/7-Zip/7z.dll"] == _sha(FILES["7z.dll"])
    assert "7z2602-x64.exe" not in "\n".join(entries)
    assert "7zr.exe" not in "\n".join(entries)

    baseline = tmp_path / "baseline"
    baseline.mkdir()
    for source in full.rglob("*"):
        if source.is_file():
            target = baseline / source.relative_to(full)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    (full / "bin" / "7-Zip" / "7z.dll").write_bytes(b"changed")
    (full / "bin" / "7-Zip" / "License.txt").unlink()
    (full / "bin" / "7-Zip" / "new.txt").write_text("new", encoding="utf-8")
    write_package_manifest(full, package_kind="full")
    delta = tmp_path / "delta"

    build_terminal_deploy_delta_package(
        baseline_root=baseline,
        target_root=full,
        delta_root=delta,
        baseline_label="baseline",
        target_label="full",
    )

    delta_payload = json.loads(
        (delta / "_delta" / "delta-manifest.json").read_text(encoding="utf-8")
    )
    assert "bin/7-Zip/new.txt" in delta_payload["added_files"]
    assert "bin/7-Zip/7z.dll" in delta_payload["modified_files"]
    assert "bin/7-Zip/License.txt" in delta_payload["deleted_files"]
    delta_manifest = json.loads((delta / PACKAGE_MANIFEST).read_text(encoding="utf-8"))
    assert any(item["path"] == "bin/7-Zip/7z.dll" for item in delta_manifest["files"])
