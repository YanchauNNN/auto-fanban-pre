from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from zipfile import BadZipFile, ZipFile

import httpx

from .archive_runtime_probe import (
    ArchiveRuntimeProbeError,
    probe_archive_runtime_package,
)
from .probe_report import ProbeReporter, ProbeSummary

_REQUIRED_DOCUMENTS = (
    "参数规范.yaml",
    "参数规范_运行期.yaml",
    "参数规范-3.yaml",
)
_REQUIRED_ASSETS = (
    "内部结构计算书.docx",
    "核岛厂房计算书.docx",
    "计算书模板文件.xlsx",
    "钢筋的公称直径、公称面积表.xlsx",
)
_REQUIRED_SKILLS = {
    "ansys-mapdl-18-2": Path("storage/ai/skills/ansys-mapdl-18-2/SKILL.md"),
    "building-structure-standards": Path(
        "storage/ai/skills/building-structure-standards/SKILL.md"
    ),
    "reinforcement-table-normalizer": Path(
        "storage/ai/skills/reinforcement-table-normalizer/SKILL.md"
    ),
    "recommend-rebar-from-smx": Path(
        "tools/ai/recommend-rebar-from-smx/SKILL.md"
    ),
}
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_PASSWORD_PATTERN = re.compile(
    r"(?i)(password(?:\s*[:=]\s*|\"\s*:\s*\"))[^\s,;\"}]+"
)


class _HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class CalculationBookProbeConfig:
    package_root: Path
    api_base_url: str
    output_dir: Path
    token: str = ""
    username: str = ""
    password: str = ""
    request_timeout_sec: float = 15.0
    task_timeout_sec: float = 3600.0
    run_full_smoke: bool = False
    archive: Path | None = None
    smoke_script: Path | None = None


@dataclass(frozen=True)
class SmokeRunResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class CalculationBookProbeFailure(RuntimeError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


ArchiveProbe = Callable[[Path], dict[str, object]]
SmokeRunner = Callable[[CalculationBookProbeConfig], SmokeRunResult]


def _redact_text(value: str) -> str:
    redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    return _PASSWORD_PATTERN.sub(r"\1[REDACTED]", redacted)


def _write_child_log(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_redact_text(value), encoding="utf-8", newline="\n")


def _check_assets(package_root: Path, reporter: ProbeReporter) -> None:
    missing: list[str] = []
    for filename in _REQUIRED_DOCUMENTS:
        candidate = package_root / "documents" / filename
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            missing.append(str(candidate.relative_to(package_root)))
    asset_root = package_root / "documents_bin" / "calculation_book"
    for filename in _REQUIRED_ASSETS:
        candidate = asset_root / filename
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            missing.append(str(candidate.relative_to(package_root)))
    tesseract = asset_root / "Tesseract-OCR" / "tesseract.exe"
    traineddata = asset_root / "Tesseract-OCR" / "tessdata"
    if not tesseract.is_file() or tesseract.stat().st_size <= 0:
        missing.append(str(tesseract.relative_to(package_root)))
    if not traineddata.is_dir() or not any(traineddata.glob("*.traineddata")):
        missing.append(str(traineddata.relative_to(package_root) / "*.traineddata"))
    if missing:
        reporter.event(
            "business_assets",
            "FAIL",
            error_code="business_asset_missing",
            message="required calculation-book assets are missing",
            context={"missing": missing},
        )
        return
    reporter.event(
        "business_assets",
        "PASS",
        context={"asset_count": len(_REQUIRED_DOCUMENTS) + len(_REQUIRED_ASSETS) + 2},
    )


def _check_skills(package_root: Path, reporter: ProbeReporter) -> None:
    missing = [
        skill_id
        for skill_id, relative_path in _REQUIRED_SKILLS.items()
        if not (package_root / relative_path).is_file()
    ]
    if missing:
        reporter.event(
            "ai_skills",
            "FAIL",
            error_code="skill_missing",
            message="required calculation-book AI skills are missing",
            context={"missing_skill_ids": missing},
        )
        return
    reporter.event(
        "ai_skills",
        "PASS",
        context={"skill_ids": list(_REQUIRED_SKILLS)},
    )


def _check_archive_runtime(
    package_root: Path,
    reporter: ProbeReporter,
    archive_probe: ArchiveProbe,
) -> None:
    try:
        result = archive_probe(package_root)
        if str(result.get("status", "")).casefold() != "pass":
            raise CalculationBookProbeFailure(
                "private archive runtime probe did not pass",
                error_code="archive_runtime_failed",
            )
        reporter.event("archive_runtime", "PASS", context={"result": result})
    except ArchiveRuntimeProbeError as exc:
        reporter.event(
            "archive_runtime",
            "FAIL",
            error_code=exc.code,
            message=str(exc),
        )
    except CalculationBookProbeFailure as exc:
        reporter.event(
            "archive_runtime",
            "FAIL",
            error_code=exc.error_code,
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - probe must always emit a summary
        reporter.event(
            "archive_runtime",
            "FAIL",
            error_code="archive_runtime_exception",
            message=str(exc),
            context={"exception_type": type(exc).__name__},
        )


def _response_json(response: Any, *, operation: str) -> Mapping[str, Any]:
    if int(response.status_code) < 200 or int(response.status_code) >= 300:
        raise CalculationBookProbeFailure(
            f"{operation} returned HTTP {response.status_code}",
            error_code="http_request_failed",
        )
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise CalculationBookProbeFailure(
            f"{operation} returned invalid JSON",
            error_code="invalid_json_response",
        ) from exc
    if not isinstance(payload, Mapping):
        raise CalculationBookProbeFailure(
            f"{operation} response must be an object",
            error_code="response_contract_invalid",
        )
    return payload


def _check_health(client: _HttpClient, reporter: ProbeReporter) -> None:
    try:
        payload = _response_json(client.get("/api/system/health"), operation="system health")
        issues: list[str] = []
        if payload.get("ready") is not True:
            issues.append("api_not_ready")
        if payload.get("storage_writable") is not True:
            issues.append("storage_not_writable")
        if payload.get("worker_alive") is not True:
            issues.append("worker_not_alive")
        worker_count = payload.get("worker_count")
        if not isinstance(worker_count, int) or worker_count <= 0:
            issues.append("worker_count_invalid")
        if issues:
            raise CalculationBookProbeFailure(
                "system health requirements failed: " + ", ".join(issues),
                error_code=issues[0],
            )
        reporter.event(
            "system_health",
            "PASS",
            context={"worker_count": worker_count},
        )
    except CalculationBookProbeFailure as exc:
        reporter.event(
            "system_health",
            "FAIL",
            error_code=exc.error_code,
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - probe must always emit a summary
        reporter.event(
            "system_health",
            "FAIL",
            error_code="health_request_exception",
            message=str(exc),
            context={"exception_type": type(exc).__name__},
        )


def _check_schema(client: _HttpClient, reporter: ProbeReporter) -> None:
    try:
        payload = _response_json(
            client.get("/api/meta/form-schema"),
            operation="calculation-book form schema",
        )
        job_types = payload.get("job_types")
        runtime_options = payload.get("runtime_options")
        calculation_options = (
            runtime_options.get("calculation_book")
            if isinstance(runtime_options, Mapping)
            else None
        )
        if not isinstance(job_types, list) or "calculation_book" not in job_types:
            raise CalculationBookProbeFailure(
                "form schema does not expose calculation_book job type",
                error_code="calculation_schema_missing",
            )
        if not isinstance(calculation_options, Mapping):
            raise CalculationBookProbeFailure(
                "form schema does not expose calculation-book runtime options",
                error_code="calculation_runtime_options_missing",
            )
        reporter.event("calculation_schema", "PASS")
    except CalculationBookProbeFailure as exc:
        reporter.event(
            "calculation_schema",
            "FAIL",
            error_code=exc.error_code,
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - probe must always emit a summary
        reporter.event(
            "calculation_schema",
            "FAIL",
            error_code="schema_request_exception",
            message=str(exc),
            context={"exception_type": type(exc).__name__},
        )


def _resolve_smoke_script(config: CalculationBookProbeConfig) -> Path:
    candidates = (
        config.smoke_script,
        config.package_root / "scripts" / "smoke_calculation_book_ai_suggestion.py",
        config.package_root / "tools" / "smoke_calculation_book_ai_suggestion.py",
    )
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise CalculationBookProbeFailure(
        "formal calculation-book smoke script is missing",
        error_code="smoke_script_missing",
    )


def _default_smoke_runner(config: CalculationBookProbeConfig) -> SmokeRunResult:
    if config.archive is None or not config.archive.is_file():
        raise CalculationBookProbeFailure(
            "full smoke requires a readable business archive",
            error_code="smoke_archive_missing",
        )
    script = _resolve_smoke_script(config)
    command = [
        sys.executable,
        str(script),
        "--api-base-url",
        config.api_base_url,
        "--archive",
        str(config.archive.resolve()),
        "--output-dir",
        str((config.output_dir / "downloaded-artifacts").resolve()),
        "--include-slab-stress",
        "--timeout-seconds",
        str(config.task_timeout_sec),
        "--request-timeout-seconds",
        str(config.request_timeout_sec),
    ]
    environment = os.environ.copy()
    if config.token:
        environment["FANBAN_SMOKE_TOKEN"] = config.token
    if config.username:
        environment["FANBAN_SMOKE_USERNAME"] = config.username
    if config.password:
        environment["FANBAN_SMOKE_PASSWORD"] = config.password
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=max(1.0, config.task_timeout_sec + config.request_timeout_sec),
        )
    except subprocess.TimeoutExpired as exc:
        return SmokeRunResult(
            returncode=-1,
            stdout=str(exc.stdout or ""),
            stderr=str(exc.stderr or ""),
            timed_out=True,
        )
    return SmokeRunResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _last_json_object(value: str) -> Mapping[str, Any]:
    decoder = json.JSONDecoder()
    last_payload: Mapping[str, Any] | None = None
    for index, character in enumerate(value):
        if character != "{":
            continue
        try:
            candidate, _end = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, Mapping):
            last_payload = candidate
    if last_payload is None:
        raise CalculationBookProbeFailure(
            "formal smoke did not return a JSON result",
            error_code="smoke_result_invalid",
        )
    return last_payload


def _validate_full_smoke(payload: Mapping[str, Any]) -> dict[str, Any]:
    word_path = Path(str(payload.get("word_path", "")))
    log_path = Path(str(payload.get("log_path", "")))
    if not word_path.is_file():
        raise CalculationBookProbeFailure(
            "formal smoke did not produce a Word document",
            error_code="word_artifact_missing",
        )
    try:
        with ZipFile(word_path) as document:
            if document.testzip() is not None:
                raise BadZipFile("document contains a damaged member")
    except (BadZipFile, OSError) as exc:
        raise CalculationBookProbeFailure(
            "formal smoke produced an invalid Word document",
            error_code="word_artifact_invalid",
        ) from exc
    try:
        records = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalculationBookProbeFailure(
            "formal smoke diagnostic log could not be read",
            error_code="diagnostic_log_invalid",
        ) from exc
    if not records or records[-1].get("event") != "task_completed":
        raise CalculationBookProbeFailure(
            "formal smoke diagnostic log has no durable terminal event",
            error_code="task_completed_missing",
        )
    return {
        "task_id": payload.get("task_id"),
        "word_path": word_path,
        "log_path": log_path,
        "model": payload.get("model"),
        "skill_version": payload.get("skill_version"),
        "skill_sha256": payload.get("skill_sha256"),
    }


def _run_full_smoke(
    config: CalculationBookProbeConfig,
    reporter: ProbeReporter,
    smoke_runner: SmokeRunner,
) -> None:
    child_root = config.output_dir / "child-process"
    try:
        result = smoke_runner(config)
        _write_child_log(child_root / "calculation-smoke.stdout.log", result.stdout)
        _write_child_log(child_root / "calculation-smoke.stderr.log", result.stderr)
        if result.timed_out:
            raise CalculationBookProbeFailure(
                "formal calculation-book smoke timed out",
                error_code="smoke_timeout",
            )
        if result.returncode != 0:
            raise CalculationBookProbeFailure(
                "formal calculation-book smoke returned a non-zero exit code",
                error_code="smoke_process_failed",
            )
        payload = _last_json_object(result.stdout)
        context = _validate_full_smoke(payload)
        reporter.event("full_smoke", "PASS", context=context)
    except CalculationBookProbeFailure as exc:
        reporter.event(
            "full_smoke",
            "FAIL",
            error_code=exc.error_code,
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - probe must always emit a summary
        reporter.event(
            "full_smoke",
            "FAIL",
            error_code="smoke_exception",
            message=str(exc),
            context={"exception_type": type(exc).__name__},
        )


def run_calculation_book_probe(
    config: CalculationBookProbeConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    client: _HttpClient | None = None,
    archive_probe: ArchiveProbe = probe_archive_runtime_package,
    smoke_runner: SmokeRunner = _default_smoke_runner,
) -> ProbeSummary:
    required_checks = [
        "business_assets",
        "ai_skills",
        "archive_runtime",
        "system_health",
        "calculation_schema",
    ]
    if config.run_full_smoke:
        required_checks.append("full_smoke")
    reporter = ProbeReporter(
        config.output_dir,
        session_id=f"calculation-book-{uuid.uuid4().hex[:12]}",
        probe_name="calculation-book",
        required_checks=required_checks,
    )
    owned_client: httpx.Client | None = None
    if client is None:
        owned_client = httpx.Client(
            base_url=config.api_base_url.rstrip("/"),
            timeout=config.request_timeout_sec,
            transport=transport,
        )
        client = owned_client
    try:
        package_root = config.package_root.resolve()
        _check_assets(package_root, reporter)
        _check_skills(package_root, reporter)
        _check_archive_runtime(package_root, reporter, archive_probe)
        _check_health(client, reporter)
        _check_schema(client, reporter)
        if config.run_full_smoke:
            _run_full_smoke(config, reporter, smoke_runner)
        else:
            reporter.event(
                "full_smoke",
                "SKIPPED",
                message="full calculation-book smoke was not requested",
            )
        return reporter.finish()
    finally:
        if owned_client is not None:
            owned_client.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe calculation-book deployment health.")
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--request-timeout-sec", type=float, default=15.0)
    parser.add_argument("--task-timeout-sec", type=float, default=3600.0)
    parser.add_argument("--run-full-smoke", action="store_true")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--smoke-script", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_calculation_book_probe(
        CalculationBookProbeConfig(
            package_root=args.package_root,
            api_base_url=args.api_base_url,
            output_dir=args.output_dir,
            token=os.getenv("FANBAN_PROBE_TOKEN", ""),
            username=os.getenv("FANBAN_PROBE_USERNAME", ""),
            password=os.getenv("FANBAN_PROBE_PASSWORD", ""),
            request_timeout_sec=args.request_timeout_sec,
            task_timeout_sec=args.task_timeout_sec,
            run_full_smoke=args.run_full_smoke,
            archive=args.archive,
            smoke_script=args.smoke_script,
        )
    )
    print(result.summary_path)
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
