from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest

import src.deploy.terminal_package as terminal_package


def _load_build_terminal_deploy_module():
    script_path = Path(__file__).resolve().parents[3] / "tools" / "build_terminal_deploy.py"
    spec = importlib.util.spec_from_file_location("build_terminal_deploy", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_sample_package(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    package_root = tmp_path / "fanban-terminal-deploy"
    files = {
        "documents/参数规范.yaml": "项目: 计算书\n".encode(),
        "documents_bin/计算书模板文件.xlsx": b"sample-workbook",
        "scripts/start_backend.ps1": b"Write-Host ready\n",
    }
    for relative_path, content in files.items():
        path = package_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (package_root / "storage" / "jobs").mkdir(parents=True)
    terminal_package.write_package_manifest(package_root, package_kind="full")
    return package_root, files


def test_publish_terminal_deploy_zip_preserves_unicode_paths_and_outer_directory(
    tmp_path: Path,
) -> None:
    package_root, files = _write_sample_package(tmp_path)
    archive_path = tmp_path / "AI测试终端部署包.zip"

    result = terminal_package.publish_terminal_deploy_zip(
        package_root=package_root,
        archive_path=archive_path,
    )

    expected_prefix = f"{package_root.name}/"
    with ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert f"{expected_prefix}storage/jobs/" in archive.namelist()
        for relative_path, content in files.items():
            archive_name = f"{expected_prefix}{relative_path}"
            info = archive.getinfo(archive_name)
            assert archive.read(info) == content
            if any(ord(character) > 127 for character in archive_name):
                assert info.flag_bits & 0x800

    expected_digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert result.archive_path == archive_path
    assert result.sha256_path == archive_path.with_name(f"{archive_path.name}.sha256")
    assert result.sha256 == expected_digest
    assert result.sha256_path.read_text(encoding="utf-8") == (
        f"{expected_digest}  {archive_path.name}\n"
    )


def test_publish_terminal_deploy_zip_keeps_previous_archive_when_manifest_is_stale(
    tmp_path: Path,
) -> None:
    package_root, _ = _write_sample_package(tmp_path)
    archive_path = tmp_path / "AI测试终端部署包.zip"
    checksum_path = archive_path.with_name(f"{archive_path.name}.sha256")
    archive_path.write_bytes(b"previous-archive")
    checksum_path.write_text("previous-checksum\n", encoding="utf-8")
    (package_root / "documents" / "参数规范.yaml").write_text(
        "项目: manifest 生成后被修改\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="manifest"):
        terminal_package.publish_terminal_deploy_zip(
            package_root=package_root,
            archive_path=archive_path,
        )

    assert archive_path.read_bytes() == b"previous-archive"
    assert checksum_path.read_text(encoding="utf-8") == "previous-checksum\n"


def test_build_cli_places_formal_zip_next_to_the_full_deploy_directory(tmp_path: Path) -> None:
    module = _load_build_terminal_deploy_module()
    output_root = tmp_path / "custom-build" / "fanban-terminal-deploy"

    archive_path = module._resolve_archive_output(output_root, None)

    assert archive_path == output_root.parent / "AI测试终端部署包.zip"


def test_publish_terminal_deploy_zip_restores_both_previous_files_when_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root, _ = _write_sample_package(tmp_path)
    archive_path = tmp_path / "AI测试终端部署包.zip"
    checksum_path = archive_path.with_name(f"{archive_path.name}.sha256")
    archive_path.write_bytes(b"previous-archive")
    checksum_path.write_text("previous-checksum\n", encoding="utf-8")
    real_replace = terminal_package.os.replace
    failed_once = False

    def fail_first_checksum_publish(source: Path, destination: Path) -> None:
        nonlocal failed_once
        if Path(destination) == checksum_path and not failed_once:
            failed_once = True
            raise OSError("simulated checksum publish failure")
        real_replace(source, destination)

    monkeypatch.setattr(terminal_package.os, "replace", fail_first_checksum_publish)

    with pytest.raises(OSError, match="simulated checksum publish failure"):
        terminal_package.publish_terminal_deploy_zip(
            package_root=package_root,
            archive_path=archive_path,
        )

    assert archive_path.read_bytes() == b"previous-archive"
    assert checksum_path.read_text(encoding="utf-8") == "previous-checksum\n"
