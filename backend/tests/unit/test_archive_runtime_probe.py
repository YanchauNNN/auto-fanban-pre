from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import src.deploy.archive_runtime_probe as probe_mod
from src.config.mechanism_spec import (
    ArchiveRuntimeAssetConfig,
    ArchiveRuntimeFileConfig,
    ArchiveRuntimeMechanismConfig,
    ArchiveRuntimeProbeConfig,
)
from src.deploy.archive_runtime import render_archive_runtime_provenance
from src.deploy.archive_runtime_probe import (
    ArchiveRuntimeProbeError,
    BoundedCommandResult,
    run_archive_runtime_probe,
)

PAYLOAD = b"fanban archive runtime smoke payload v1\n"
RAR5 = base64.b64decode(
    "UmFyIRoHAQAzkrXlCgEFBgAFAQGAgAD3WFxjNQIDC6gABKgAIAuotTmAAAAZ"
    "YXJjaGl2ZS1ydW50aW1lLXNtb2tlLnR4dAoDAnaBI2gpJ90BZmFuYmFuIGFy"
    "Y2hpdmUgcnVudGltZSBzbW9rZSBwYXlsb2FkIHYxCh13VlEDBQQA",
    validate=True,
)
RUNTIME_FILES = {
    "7z.exe": b"private-7z",
    "7z.dll": b"private-7z-dll",
    "License.txt": b"7-Zip license",
}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _probe_config(tmp_path: Path) -> ArchiveRuntimeMechanismConfig:
    fixture_root = tmp_path / "backend" / "src" / "deploy" / "fixtures"
    fixture_root.mkdir(parents=True)
    encoded = base64.b64encode(RAR5) + b"\n"
    (fixture_root / "archive-runtime-smoke-rar5.rar.b64").write_bytes(encoded)
    (fixture_root / "archive-runtime-smoke.txt").write_bytes(PAYLOAD)
    probe = ArchiveRuntimeProbeConfig(
        timeout_sec=5,
        max_output_bytes=131_072,
        fixture_source_relative_path="fixtures/archive-runtime-smoke-rar5.rar.b64",
        fixture_encoding="base64",
        fixture_source_sha256=_sha(encoded),
        fixture_source_size_bytes=len(encoded),
        fixture_decoded_sha256=_sha(RAR5),
        fixture_decoded_size_bytes=len(RAR5),
        payload_source_relative_path="fixtures/archive-runtime-smoke.txt",
        payload_filename="archive-runtime-smoke.txt",
        payload_sha256=_sha(PAYLOAD),
        payload_size_bytes=len(PAYLOAD),
    )
    return ArchiveRuntimeMechanismConfig(
        version="26.02-test",
        architecture="x64",
        source=ArchiveRuntimeAssetConfig(
            filename="7z-test.exe",
            url="https://example.invalid/7z-test.exe",
            sha256=_sha(b"source"),
            size_bytes=6,
        ),
        bootstrap=ArchiveRuntimeAssetConfig(
            filename="7zr.exe",
            url="https://example.invalid/7zr.exe",
            sha256=_sha(b"bootstrap"),
            size_bytes=9,
        ),
        license_url="https://example.invalid/license.txt",
        cache_dir="build/runtime-cache/7-Zip",
        destination_dir="bin/7-Zip",
        provenance_filename="PROVENANCE.txt",
        required_files=tuple(
            ArchiveRuntimeFileConfig(filename=name, sha256=_sha(payload))
            for name, payload in RUNTIME_FILES.items()
        ),
        required_handlers=("7z", "zip", "Rar", "Rar5"),
        version_marker="7-Zip 26.02-test (x64)",
        download_timeout_sec=15,
        prepare_timeout_sec=20,
        probe=probe,
    )


def _write_package(package_root: Path, config: ArchiveRuntimeMechanismConfig) -> None:
    runtime = package_root / config.destination_dir
    runtime.mkdir(parents=True)
    for name, payload in RUNTIME_FILES.items():
        (runtime / name).write_bytes(payload)
    (runtime / config.provenance_filename).write_text(
        render_archive_runtime_provenance(config),
        encoding="utf-8",
    )


class Fake7ZipRunner:
    def __init__(self, *, info_output: str | None = None, extracted: bytes = PAYLOAD) -> None:
        self.info_output = info_output or (
            "7-Zip 26.02-test (x64)\nFormats:\n"
            " 0 C  7z  7z\n 0 C  zip zip\n 0 F  Rar rar\n 0 F  Rar5 rar\n"
        )
        self.extracted = extracted
        self.calls: list[tuple[tuple[str, ...], int, int]] = []

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        timeout_sec: int,
        max_output_bytes: int,
    ) -> BoundedCommandResult:
        self.calls.append((command, timeout_sec, max_output_bytes))
        verb = command[1]
        if verb == "i":
            return BoundedCommandResult(0, self.info_output, "")
        if verb == "a":
            archive_path = next(Path(arg) for arg in command if arg.lower().endswith(".7z"))
            archive_path.write_bytes(b"synthetic-7z")
            return BoundedCommandResult(0, "Everything is Ok", "")
        if verb == "l":
            return BoundedCommandResult(
                0,
                "Path = archive-runtime-smoke.txt\nSize = 40\nEncrypted = -\n",
                "",
            )
        if verb == "x":
            output_arg = next(arg for arg in command if arg.startswith("-o"))
            output = Path(output_arg[2:])
            output.mkdir(parents=True, exist_ok=True)
            (output / "archive-runtime-smoke.txt").write_bytes(self.extracted)
            return BoundedCommandResult(0, "Everything is Ok", "")
        raise AssertionError(f"unexpected verb: {verb}")


def test_probe_validates_version_handlers_and_three_format_list_extract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _probe_config(tmp_path)
    package_root = tmp_path / "package"
    _write_package(package_root, config)
    runner = Fake7ZipRunner()
    monkeypatch.setenv("PATH", "")

    result = run_archive_runtime_probe(
        package_root,
        config,
        fixture_module_dir=tmp_path / "backend" / "src" / "deploy",
        command_runner=runner,
    )

    expected_exe = (package_root / "bin" / "7-Zip" / "7z.exe").resolve()
    assert result["status"] == "pass"
    assert result["version_marker"] == "7-Zip 26.02-test (x64)"
    assert result["required_handlers"] == ["7z", "zip", "Rar", "Rar5"]
    assert result["executable"] == str(expected_exe)
    assert result["formats"] == {
        "zip": {"status": "pass", "listed": True, "extracted": True},
        "7z": {"status": "pass", "listed": True, "extracted": True},
        "rar5": {"status": "pass", "listed": True, "extracted": True},
    }
    assert [call[0][1] for call in runner.calls] == ["i", "a", "l", "x", "l", "x", "l", "x"]
    assert all(Path(call[0][0]).is_absolute() for call in runner.calls)
    assert all(call[1:] == (5, 131_072) for call in runner.calls)


def test_probe_config_is_frozen_forbids_extra_and_rejects_path_escape(
    tmp_path: Path,
) -> None:
    probe = _probe_config(tmp_path).probe
    with pytest.raises(ValidationError, match="frozen"):
        probe.timeout_sec = 1
    payload = probe.model_dump()
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ArchiveRuntimeProbeConfig(**payload)
    payload.pop("unexpected")
    payload["fixture_source_relative_path"] = "../fixture.rar.b64"
    with pytest.raises(ValidationError, match="module-relative"):
        ArchiveRuntimeProbeConfig(**payload)


def test_probe_fixture_hash_assets_are_forced_to_lf_on_windows_checkout() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    attributes = (repo_root / ".gitattributes").read_text(encoding="utf-8")
    assert (
        "backend/src/deploy/fixtures/archive-runtime-smoke-rar5.rar.b64 text eol=lf"
        in attributes
    )
    assert (
        "backend/src/deploy/fixtures/archive-runtime-smoke.txt text eol=lf"
        in attributes
    )


@pytest.mark.parametrize(
    ("info_output", "code"),
    [
        ("7-Zip wrong version\n 0 C 7z\n 0 C zip\n 0 F Rar\n 0 F Rar5", "version_mismatch"),
        ("7-Zip 26.02-test (x64)\n 0 C 7z\n 0 C zip\n 0 F Rar", "required_handlers_missing"),
    ],
)
def test_probe_fails_closed_for_version_or_handler_mismatch(
    tmp_path: Path,
    info_output: str,
    code: str,
) -> None:
    config = _probe_config(tmp_path)
    package_root = tmp_path / "package"
    _write_package(package_root, config)

    with pytest.raises(ArchiveRuntimeProbeError) as caught:
        run_archive_runtime_probe(
            package_root,
            config,
            fixture_module_dir=tmp_path / "backend" / "src" / "deploy",
            command_runner=Fake7ZipRunner(info_output=info_output),
        )

    assert caught.value.code == code
    assert str(tmp_path) not in str(caught.value)


def test_probe_fails_closed_for_extracted_payload_mismatch(tmp_path: Path) -> None:
    config = _probe_config(tmp_path)
    package_root = tmp_path / "package"
    _write_package(package_root, config)

    with pytest.raises(ArchiveRuntimeProbeError) as caught:
        run_archive_runtime_probe(
            package_root,
            config,
            fixture_module_dir=tmp_path / "backend" / "src" / "deploy",
            command_runner=Fake7ZipRunner(extracted=b"wrong"),
        )

    assert caught.value.code == "payload_validation_failed"
    assert str(tmp_path) not in str(caught.value)


def test_probe_rejects_fixture_source_hash_mismatch(tmp_path: Path) -> None:
    config = _probe_config(tmp_path)
    package_root = tmp_path / "package"
    _write_package(package_root, config)
    source = tmp_path / "backend" / "src" / "deploy" / config.probe.fixture_source_relative_path
    source.write_bytes(b"tampered")

    with pytest.raises(ArchiveRuntimeProbeError) as caught:
        run_archive_runtime_probe(
            package_root,
            config,
            fixture_module_dir=tmp_path / "backend" / "src" / "deploy",
            command_runner=Fake7ZipRunner(),
        )

    assert caught.value.code == "fixture_validation_failed"


def test_probe_rejects_oversized_fixture_before_opening_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _probe_config(tmp_path)
    package_root = tmp_path / "package"
    _write_package(package_root, config)
    source = (
        tmp_path
        / "backend"
        / "src"
        / "deploy"
        / config.probe.fixture_source_relative_path
    )
    source.write_bytes(b"x" * (config.probe.fixture_source_size_bytes + 1))
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):
        if path == source:
            raise AssertionError("oversized fixture must be rejected before opening")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    with pytest.raises(ArchiveRuntimeProbeError) as caught:
        run_archive_runtime_probe(
            package_root,
            config,
            fixture_module_dir=tmp_path / "backend" / "src" / "deploy",
            command_runner=Fake7ZipRunner(),
        )

    assert caught.value.code == "fixture_validation_failed"


def test_bounded_command_timeout_and_output_limit_are_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        returncode = None
        stdout = None
        stderr = None

        def wait(self, timeout: int) -> int:
            raise probe_mod.subprocess.TimeoutExpired(["private-7z"], timeout)

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(probe_mod.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())

    with pytest.raises(ArchiveRuntimeProbeError) as caught:
        probe_mod.run_bounded_command(
            (str((tmp_path / "7z.exe").resolve()), "i"),
            timeout_sec=1,
            max_output_bytes=16,
        )

    assert caught.value.code == "command_timeout"
    assert str(tmp_path) not in str(caught.value)

    class OutputProcess:
        returncode = 0
        stdout = io.BytesIO(b"x" * 17)
        stderr = io.BytesIO()

        def wait(self, timeout: int) -> int:
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    monkeypatch.setattr(probe_mod.subprocess, "Popen", lambda *_args, **_kwargs: OutputProcess())
    with pytest.raises(ArchiveRuntimeProbeError) as output_caught:
        probe_mod.run_bounded_command(
            (str((tmp_path / "7z.exe").resolve()), "i"),
            timeout_sec=1,
            max_output_bytes=16,
        )
    assert output_caught.value.code == "command_output_limit"


def test_json_cli_success_and_failure_have_stable_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        probe_mod,
        "probe_archive_runtime_package",
        lambda _root: {"status": "pass", "formats": {}},
    )
    assert probe_mod.main(["--package-root", str(tmp_path)]) == 0
    success = json.loads(capsys.readouterr().out)
    assert success["status"] == "pass"

    def _fail(_root: Path) -> dict[str, object]:
        raise ArchiveRuntimeProbeError("version_mismatch", "version verification failed")

    monkeypatch.setattr(probe_mod, "probe_archive_runtime_package", _fail)
    assert probe_mod.main(["--package-root", str(tmp_path)]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure == {
        "status": "fail",
        "ok": False,
        "code": "version_mismatch",
        "error": "version verification failed",
    }
