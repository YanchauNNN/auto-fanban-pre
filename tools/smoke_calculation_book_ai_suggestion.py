from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

APPROVED_ARCHIVE_SHA256 = (
    "B3593CBEB654D8FF3D9350D4C93FBD4311D83F87138B0123CD7816D6BACDE466"
)
EXPECTED_WALL_GROUPS = 59
EXPECTED_WALL_DIRECTION_IMAGES = 177
EXPECTED_SLAB_IMAGES = 5
EXPECTED_RECOMMENDATION_DIRECTIONS = 182
EXPECTED_ARCHIVE_IMAGES = 184
FATAL_AI_WARNING_REASONS = {
    "AI_BASE_FAILURE_LIMIT": (
        "the internal model or response protocol remained unavailable after retries"
    ),
    "OCR_RECOGNITION_FAILED": "an SMX value could not be recognized",
}


class SmokeFailure(RuntimeError):
    """Expected non-zero smoke-test outcome with a safe diagnostic."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the approved no-rebar-table archive through the formal "
            "calculation-book API and independent Worker."
        )
    )
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--reinforcement-source",
        choices=("ai_suggested",),
        default="ai_suggested",
    )
    parser.add_argument("--include-slab-stress", action="store_true")
    parser.add_argument(
        "--token",
        help="Existing bearer token; may also use FANBAN_SMOKE_TOKEN.",
    )
    parser.add_argument(
        "--username",
        help="Account ID; may also use FANBAN_SMOKE_USERNAME.",
    )
    parser.add_argument(
        "--password",
        help="Password; may also use FANBAN_SMOKE_PASSWORD.",
    )
    parser.add_argument(
        "--params-json",
        type=Path,
        help="Optional JSON object overriding the approved smoke metadata.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=600.0)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SmokeFailure(f"cannot read archive: {path}") from exc
    return digest.hexdigest().upper()


def _default_params() -> dict[str, object]:
    return {
        "template_type": "internal_structure",
        "project_no": "SMOKE",
        "project_name": "计算书 AI 配筋建议正式烟测",
        "internal_code": "SMOKE-CALC-01",
        "version": "A",
        "subproject_code": "RX",
        "subproject_name": "内部结构",
        "design_phase": "施工图设计",
        "document_name": "11.450m~15.950m配筋计算书",
        "workshop_length": 72.5,
        "workshop_width": 48.0,
        "raft_slab_top_elevation": 11.45,
        "roof_top_elevation": 15.95,
        "factory_extreme_min_temperature": -18.0,
        "factory_extreme_max_temperature": 39.0,
        "site_soil_temperature": 15.0,
    }


def _load_params(path: Path | None) -> dict[str, object]:
    params = _default_params()
    if path is None:
        return params
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure(f"cannot read params JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure("params JSON must contain one object")
    params.update(payload)
    return params


def _response_json(response: httpx.Response, *, operation: str) -> dict[str, Any]:
    if response.is_error:
        detail = response.text.strip().replace("\r", " ").replace("\n", " ")
        raise SmokeFailure(
            f"{operation} failed with HTTP {response.status_code}: "
            f"{detail[:1000]}"
        )
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise SmokeFailure(f"{operation} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{operation} returned a non-object JSON payload")
    return payload


def _resolve_token(client: httpx.Client, args: argparse.Namespace) -> str:
    token = str(args.token or os.getenv("FANBAN_SMOKE_TOKEN") or "").strip()
    username = str(
        args.username or os.getenv("FANBAN_SMOKE_USERNAME") or ""
    ).strip()
    password = str(
        args.password or os.getenv("FANBAN_SMOKE_PASSWORD") or ""
    )
    if token:
        if username or password:
            raise SmokeFailure("use either a bearer token or username/password")
        return token
    if not username or not password:
        raise SmokeFailure(
            "authentication requires --token or both --username and --password"
        )
    payload = _response_json(
        client.post(
            "/api/auth/login",
            json={"account_id": username, "password": password},
        ),
        operation="login",
    )
    resolved = payload.get("token")
    if not isinstance(resolved, str) or not resolved.strip():
        raise SmokeFailure("login response did not contain a bearer token")
    return resolved.strip()


def _preflight(
    client: httpx.Client,
    *,
    archive: Path,
    reinforcement_source: str,
    include_slab_stress: bool,
) -> dict[str, Any]:
    media_type = (
        "application/vnd.rar"
        if archive.suffix.lower() == ".rar"
        else "application/zip"
    )
    try:
        with archive.open("rb") as stream:
            response = client.post(
                "/api/jobs/calculation-books/preflight",
                data={
                    "reinforcement_source": reinforcement_source,
                    "include_slab_stress": str(include_slab_stress).lower(),
                },
                files={"archive": (archive.name, stream, media_type)},
            )
    except OSError as exc:
        raise SmokeFailure(f"cannot upload archive: {archive}") from exc
    return _response_json(response, operation="preflight")


def _validate_preflight(payload: dict[str, Any]) -> dict[str, int]:
    expected = {
        "image_wall_group_count": EXPECTED_WALL_GROUPS,
        "wall_direction_figure_count": EXPECTED_WALL_DIRECTION_IMAGES,
        "slab_figure_count": EXPECTED_SLAB_IMAGES,
    }
    if payload.get("reinforcement_source") != "ai_suggested":
        raise SmokeFailure("preflight did not retain ai_suggested mode")
    if payload.get("requires_ai_recommendation") is not True:
        raise SmokeFailure("preflight did not activate AI rebar recommendation")
    if payload.get("reinforcement_workbook") is not None:
        raise SmokeFailure("approved AI archive unexpectedly contains an Excel table")
    for field, expected_value in expected.items():
        if payload.get(field) != expected_value:
            raise SmokeFailure(
                f"preflight conservation failed: {field}="
                f"{payload.get(field)!r}, expected {expected_value}"
            )
    ignored = payload.get("ignored_root_images")
    if ignored not in (None, []):
        raise SmokeFailure(f"preflight found ignored root images: {ignored!r}")
    recommendation_directions = (
        EXPECTED_WALL_DIRECTION_IMAGES + EXPECTED_SLAB_IMAGES
    )
    archive_images = recommendation_directions + 2
    if recommendation_directions != EXPECTED_RECOMMENDATION_DIRECTIONS:
        raise SmokeFailure("internal expected direction counts are inconsistent")
    if archive_images != EXPECTED_ARCHIVE_IMAGES:
        raise SmokeFailure("internal expected archive image counts are inconsistent")
    return {
        "excel_files": 0,
        "wall_groups": EXPECTED_WALL_GROUPS,
        "wall_direction_images": EXPECTED_WALL_DIRECTION_IMAGES,
        "slab_images": EXPECTED_SLAB_IMAGES,
        "recommendation_directions": recommendation_directions,
        "archive_images_including_01_02": archive_images,
    }


def _create_job(
    client: httpx.Client,
    *,
    params: dict[str, object],
) -> str:
    payload = _response_json(
        client.post(
            "/api/jobs/calculation-books",
            data={
                "params_json": json.dumps(params, ensure_ascii=False),
            },
        ),
        operation="create calculation-book job",
    )
    jobs = payload.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != 1:
        raise SmokeFailure("create response did not contain exactly one job")
    job_id = jobs[0].get("job_id") if isinstance(jobs[0], dict) else None
    if not isinstance(job_id, str) or not job_id.strip():
        raise SmokeFailure("create response did not contain a job ID")
    return job_id.strip()


def _poll_job(
    client: httpx.Client,
    *,
    job_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_marker: tuple[object, ...] | None = None
    while time.monotonic() < deadline:
        payload = _response_json(
            client.get(f"/api/jobs/{job_id}"),
            operation="read job detail",
        )
        progress = payload.get("progress")
        progress = progress if isinstance(progress, dict) else {}
        marker = (
            payload.get("status"),
            progress.get("stage"),
            progress.get("percent"),
            progress.get("message"),
        )
        if marker != last_marker:
            print(
                "[poll] "
                f"status={marker[0]} stage={marker[1]} "
                f"percent={marker[2]} message={marker[3]}"
            )
            last_marker = marker
        status = payload.get("status")
        if status == "succeeded":
            return payload
        if status in {"failed", "cancelled"}:
            raise SmokeFailure(
                f"job {job_id} ended as {status}: {payload.get('errors')!r}"
            )
        time.sleep(poll_interval_seconds)
    raise SmokeFailure(
        f"job {job_id} did not finish within {timeout_seconds:g} seconds; "
        "verify the independent Worker and internal model connectivity"
    )


def _download(
    client: httpx.Client,
    *,
    url: str,
    destination: Path,
    operation: str,
) -> None:
    response = client.get(url)
    if response.is_error:
        raise SmokeFailure(
            f"{operation} failed with HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )
    try:
        destination.write_bytes(response.content)
    except OSError as exc:
        raise SmokeFailure(f"cannot write {operation}: {destination}") from exc


def _validate_result(
    detail: dict[str, Any],
    *,
    expected_direction_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = detail.get("calculation_book_output")
    if not isinstance(output, dict):
        raise SmokeFailure("job detail is missing calculation_book_output")
    summary = output.get("ai_rebar_suggestion")
    if not isinstance(summary, dict):
        raise SmokeFailure(
            "AI recommendation summary is missing; internal model/Skill did not complete"
        )
    for field in ("model", "skill_version", "skill_sha256"):
        value = summary.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SmokeFailure(f"AI recommendation summary has no {field}")
    suggested = summary.get("suggested_direction_count")
    blank = summary.get("blank_direction_count")
    if (
        isinstance(suggested, bool)
        or not isinstance(suggested, int)
        or isinstance(blank, bool)
        or not isinstance(blank, int)
        or suggested < 0
        or blank < 0
    ):
        raise SmokeFailure("AI recommendation direction counts are invalid")
    if suggested + blank != expected_direction_count:
        raise SmokeFailure(
            "AI recommendation conservation failed: "
            f"suggested {suggested} + blank {blank} != "
            f"{expected_direction_count}"
        )
    warnings = output.get("warnings")
    if not isinstance(warnings, list):
        raise SmokeFailure("job detail warnings are invalid")
    fatal_warnings = sorted(
        {
            str(warning.get("code"))
            for warning in warnings
            if isinstance(warning, dict)
            and warning.get("code") in FATAL_AI_WARNING_REASONS
        }
    )
    if fatal_warnings:
        diagnostics = "; ".join(
            f"{code}: {FATAL_AI_WARNING_REASONS[code]}"
            for code in fatal_warnings
        )
        raise SmokeFailure(f"real AI smoke has fatal warning(s): {diagnostics}")
    blank_with_reason = sum(
        len(warning.get("blank_fields", []))
        for warning in warnings
        if isinstance(warning, dict)
        and isinstance(warning.get("blank_fields"), list)
        and isinstance(warning.get("reason"), str)
        and warning["reason"].strip()
    )
    if blank_with_reason != blank:
        raise SmokeFailure(
            "blank-direction reason conservation failed: "
            f"{blank_with_reason} reasons for {blank} blank directions"
        )
    return output, summary


def run(args: argparse.Namespace) -> dict[str, object]:
    archive = args.archive.resolve()
    if archive.suffix.lower() != ".rar":
        raise SmokeFailure("the approved smoke input must be a .rar archive")
    archive_sha256 = _sha256(archive)
    if archive_sha256 != APPROVED_ARCHIVE_SHA256:
        raise SmokeFailure(
            "archive SHA256 mismatch: "
            f"got {archive_sha256}, expected {APPROVED_ARCHIVE_SHA256}"
        )
    if not args.include_slab_stress:
        raise SmokeFailure(
            "--include-slab-stress is required for the approved 5-slab smoke"
        )
    if args.timeout_seconds <= 0 or args.poll_interval_seconds <= 0:
        raise SmokeFailure("poll and timeout values must be greater than zero")
    if args.request_timeout_seconds <= 0:
        raise SmokeFailure("request timeout must be greater than zero")

    output_dir = args.output_dir.resolve()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SmokeFailure(f"cannot create output directory: {output_dir}") from exc

    try:
        with httpx.Client(
            base_url=str(args.api_base_url).rstrip("/"),
            timeout=args.request_timeout_seconds,
            follow_redirects=False,
        ) as client:
            token = _resolve_token(client, args)
            client.headers["Authorization"] = f"Bearer {token}"
            preflight = _preflight(
                client,
                archive=archive,
                reinforcement_source=args.reinforcement_source,
                include_slab_stress=args.include_slab_stress,
            )
            counts = _validate_preflight(preflight)
            params = _load_params(args.params_json)
            params.update(
                {
                    "preflight_token": preflight.get("preflight_token"),
                    "reinforcement_source": "ai_suggested",
                    "include_slab_stress": True,
                    "confirm_ai_normalization": False,
                }
            )
            job_id = _create_job(client, params=params)
            detail = _poll_job(
                client,
                job_id=job_id,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
            output, summary = _validate_result(
                detail,
                expected_direction_count=counts["recommendation_directions"],
            )
            artifacts = detail.get("artifacts")
            if not isinstance(artifacts, dict):
                raise SmokeFailure("job detail is missing artifacts")
            word_url = artifacts.get("calculation_docx_download_url")
            log_url = artifacts.get("calculation_log_download_url")
            if not isinstance(word_url, str) or not word_url:
                raise SmokeFailure("Word download URL is unavailable")
            if not isinstance(log_url, str) or not log_url:
                raise SmokeFailure("diagnostic log download URL is unavailable")
            word_path = output_dir / f"{job_id}-calculation-book.docx"
            log_path = output_dir / f"{job_id}-calculation-book.log"
            _download(
                client,
                url=word_url,
                destination=word_path,
                operation="Word download",
            )
            _download(
                client,
                url=log_url,
                destination=log_path,
                operation="diagnostic log download",
            )
    except httpx.HTTPError as exc:
        raise SmokeFailure(
            "API request failed; verify API/Worker/internal-model reachability: "
            f"{exc.__class__.__name__}"
        ) from exc

    try:
        if not word_path.read_bytes().startswith(b"PK"):
            raise SmokeFailure("downloaded Word file is not a DOCX package")
        records = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure("downloaded artifact validation failed") from exc
    if not records or records[-1].get("event") != "task_completed":
        raise SmokeFailure("diagnostic log has no durable task_completed record")

    result: dict[str, object] = {
        "task_id": job_id,
        "archive_sha256": archive_sha256,
        "model": summary["model"],
        "skill_id": summary.get("skill_id"),
        "skill_version": summary["skill_version"],
        "skill_sha256": summary["skill_sha256"],
        **counts,
        "suggested_direction_count": summary["suggested_direction_count"],
        "blank_direction_count": summary["blank_direction_count"],
        "repair_round_count": summary.get("repair_round_count", 0),
        "warning_count": output.get("warning_count", 0),
        "word_path": str(word_path),
        "log_path": str(log_path),
    }
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except SmokeFailure as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("[FAIL] smoke test interrupted", file=sys.stderr)
        return 130
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
