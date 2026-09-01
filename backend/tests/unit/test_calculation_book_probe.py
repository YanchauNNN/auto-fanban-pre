from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import httpx

from src.deploy.calculation_book_probe import (
    CalculationBookProbeConfig,
    SmokeRunResult,
    run_calculation_book_probe,
)

_SKILL_PATHS = {
    "ansys-mapdl-18-2": Path("storage/ai/skills/ansys-mapdl-18-2/SKILL.md"),
    "building-structure-standards": Path(
        "storage/ai/skills/building-structure-standards/SKILL.md"
    ),
    "reinforcement-table-normalizer": Path(
        "tools/ai/reinforcement-table-normalizer/SKILL.md"
    ),
    "recommend-rebar-from-smx": Path(
        "tools/ai/recommend-rebar-from-smx/SKILL.md"
    ),
}


def _make_package(root: Path) -> None:
    (root / "documents").mkdir(parents=True)
    for name in ("参数规范.yaml", "参数规范_运行期.yaml", "参数规范-3.yaml"):
        (root / "documents" / name).write_text("schema_version: '1.0'\n", "utf-8")
    template_root = root / "documents_bin" / "calculation_book"
    template_root.mkdir(parents=True)
    for name in (
        "内部结构计算书.docx",
        "核岛厂房计算书.docx",
        "计算书模板文件.xlsx",
        "钢筋的公称直径、公称面积表.xlsx",
    ):
        (template_root / name).write_bytes(b"probe-asset")
    tesseract_root = template_root / "Tesseract-OCR"
    (tesseract_root / "tessdata").mkdir(parents=True)
    (tesseract_root / "tesseract.exe").write_bytes(b"probe-executable")
    (tesseract_root / "tessdata" / "eng.traineddata").write_bytes(b"probe-data")
    for skill_id, relative_path in _SKILL_PATHS.items():
        skill_path = root / relative_path
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text(f"# {skill_id}\n", "utf-8")


def _healthy_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/system/health":
        return httpx.Response(
            200,
            json={
                "ready": True,
                "storage_writable": True,
                "worker_alive": True,
                "worker_count": 1,
            },
        )
    if request.url.path == "/api/meta/form-schema":
        return httpx.Response(
            200,
            json={
                "job_types": ["calculation_book"],
                "runtime_options": {"calculation_book": {}},
            },
        )
    raise AssertionError(request.url.path)


def _config(tmp_path: Path, **overrides: object) -> CalculationBookProbeConfig:
    package_root = tmp_path / "package"
    _make_package(package_root)
    values: dict[str, object] = {
        "package_root": package_root,
        "api_base_url": "http://probe.local",
        "output_dir": tmp_path / "probe-result",
        "token": "probe-token",
        "request_timeout_sec": 3.0,
    }
    values.update(overrides)
    return CalculationBookProbeConfig(**values)


def _archive_probe(_package_root: Path) -> dict[str, object]:
    return {
        "status": "pass",
        "ok": True,
        "formats": {
            "zip": {"status": "pass"},
            "7z": {"status": "pass"},
            "rar5": {"status": "pass"},
        },
    }


def test_environment_probe_passes_required_assets_skills_runtime_and_api(
    tmp_path: Path,
) -> None:
    result = run_calculation_book_probe(
        _config(tmp_path),
        transport=httpx.MockTransport(_healthy_transport),
        archive_probe=_archive_probe,
    )

    assert result.status == "PASS"
    summary = json.loads(result.summary_path.read_text("utf-8"))
    assert summary["checks"]["business_assets"] == "PASS"
    assert summary["checks"]["ai_skills"] == "PASS"
    assert summary["checks"]["archive_runtime"] == "PASS"
    assert summary["checks"]["system_health"] == "PASS"
    assert summary["checks"]["calculation_schema"] == "PASS"
    assert summary["checks"]["full_smoke"] == "SKIPPED"


def test_environment_probe_fails_when_required_skill_is_missing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (config.package_root / _SKILL_PATHS["recommend-rebar-from-smx"]).unlink()

    result = run_calculation_book_probe(
        config,
        transport=httpx.MockTransport(_healthy_transport),
        archive_probe=_archive_probe,
    )

    assert result.status == "FAIL"
    assert "skill_missing" in result.events_path.read_text("utf-8")


def test_environment_probe_fails_when_worker_is_not_alive(tmp_path: Path) -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/system/health":
            return httpx.Response(
                200,
                json={
                    "ready": False,
                    "storage_writable": True,
                    "worker_alive": False,
                    "worker_count": 0,
                },
            )
        return _healthy_transport(request)

    result = run_calculation_book_probe(
        _config(tmp_path),
        transport=httpx.MockTransport(transport),
        archive_probe=_archive_probe,
    )

    assert result.status == "FAIL"
    assert "worker_not_alive" in result.events_path.read_text("utf-8")


def _write_full_smoke_artifacts(output_dir: Path, *, terminal: bool = True) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    word_path = output_dir / "probe.docx"
    with ZipFile(word_path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
    log_path = output_dir / "probe.log"
    events = [
        {"event": "task_started", "sequence": 1},
        {"event": "task_completed" if terminal else "stage_completed", "sequence": 2},
    ]
    log_path.write_text("\n".join(json.dumps(item) for item in events) + "\n", "utf-8")
    return {
        "task_id": "probe-task-1",
        "word_path": str(word_path),
        "log_path": str(log_path),
        "model": "internal-model",
        "skill_version": "1.0.0",
        "skill_sha256": "a" * 64,
    }


def test_full_smoke_validates_docx_and_terminal_diagnostic_event(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        run_full_smoke=True,
        archive=tmp_path / "business.rar",
    )
    config.archive.write_bytes(b"rar-smoke")

    def smoke_runner(_config: CalculationBookProbeConfig) -> SmokeRunResult:
        payload = _write_full_smoke_artifacts(config.output_dir / "downloaded-artifacts")
        return SmokeRunResult(returncode=0, stdout=json.dumps(payload), stderr="")

    result = run_calculation_book_probe(
        config,
        transport=httpx.MockTransport(_healthy_transport),
        archive_probe=_archive_probe,
        smoke_runner=smoke_runner,
    )

    assert result.status == "PASS"
    assert '"full_smoke":"PASS"' in result.summary_path.read_text("utf-8").replace(" ", "")


def test_full_smoke_fails_when_diagnostic_log_has_no_terminal_event(
    tmp_path: Path,
) -> None:
    config = _config(
        tmp_path,
        run_full_smoke=True,
        archive=tmp_path / "business.rar",
    )
    config.archive.write_bytes(b"rar-smoke")

    def smoke_runner(_config: CalculationBookProbeConfig) -> SmokeRunResult:
        payload = _write_full_smoke_artifacts(
            config.output_dir / "downloaded-artifacts",
            terminal=False,
        )
        return SmokeRunResult(returncode=0, stdout=json.dumps(payload), stderr="")

    result = run_calculation_book_probe(
        config,
        transport=httpx.MockTransport(_healthy_transport),
        archive_probe=_archive_probe,
        smoke_runner=smoke_runner,
    )

    assert result.status == "FAIL"
    assert "task_completed_missing" in result.events_path.read_text("utf-8")


def test_full_smoke_failure_keeps_redacted_child_logs(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        run_full_smoke=True,
        archive=tmp_path / "business.rar",
    )
    config.archive.write_bytes(b"rar-smoke")

    def smoke_runner(_config: CalculationBookProbeConfig) -> SmokeRunResult:
        return SmokeRunResult(
            returncode=1,
            stdout="task=probe-task-9",
            stderr="Authorization: Bearer should-not-leak",
        )

    result = run_calculation_book_probe(
        config,
        transport=httpx.MockTransport(_healthy_transport),
        archive_probe=_archive_probe,
        smoke_runner=smoke_runner,
    )

    assert result.status == "FAIL"
    stderr_log = config.output_dir / "child-process" / "calculation-smoke.stderr.log"
    assert stderr_log.exists()
    assert "should-not-leak" not in stderr_log.read_text("utf-8")
