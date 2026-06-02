from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from src.config import SpecLoader, reload_config
from src.models import Job, JobStatus, JobType
from src.pipeline.shared_prep import SharedPrepArtifacts, SharedPrepService


class FakeFontPreflightService:
    def __init__(self) -> None:
        self.replacement_options = [
            {
                "label": "SimSun (simsun.ttc)",
                "value": "simsun.ttc",
                "family": "SimSun",
                "path": r"C:\Windows\Fonts\simsun.ttc",
                "kind": "ttf",
            },
            {
                "label": "simplex.shx (AutoCAD SHX)",
                "value": "simplex.shx",
                "family": "simplex",
                "path": r"D:\Program Files\AUTOCAD\AutoCAD 2022\Fonts\simplex.shx",
                "kind": "shx",
            },
            {
                "label": "romans.shx (AutoCAD SHX)",
                "value": "romans.shx",
                "family": "romans",
                "path": r"D:\Program Files\AUTOCAD\AutoCAD 2022\Fonts\romans.shx",
                "kind": "shx",
            },
        ]
        self.inspect_calls: list[dict[str, object]] = []
        self.list_requests: list[list[str]] = []

    def list_replacement_options(self, *, missing_kinds: list[str] | None = None) -> list[dict[str, str]]:
        requested = [str(kind or "").strip().lower() for kind in (missing_kinds or []) if str(kind or "").strip()]
        self.list_requests.append(requested)
        if not requested:
            return list(self.replacement_options)
        return [
            option
            for option in self.replacement_options
            if str(option.get("kind") or "").strip().lower() in requested
        ]

    def list_replacement_options_by_kind(
        self,
        *,
        missing_kinds: list[str] | None = None,
    ) -> dict[str, list[dict[str, str]]]:
        requested = [str(kind or "").strip().lower() for kind in (missing_kinds or []) if str(kind or "").strip()]
        return {
            kind: [
                option
                for option in self.replacement_options
                if str(option.get("kind") or "").strip().lower() == kind
            ]
            for kind in requested
        }

    def default_replacement_fonts(
        self,
        *,
        missing_kinds: list[str] | None = None,
        missing_fonts: list[dict[str, object]] | None = None,
    ) -> dict[str, str]:
        requested = [str(kind or "").strip().lower() for kind in (missing_kinds or []) if str(kind or "").strip()]
        defaults = {
            "ttf": "simsun.ttc",
            "shx": "simplex.shx",
            "bigfont": "romans.shx",
        }
        return {kind: defaults[kind] for kind in requested if kind in defaults}

    def validate_replacement_font(self, font_name: str, *, kind: str | None = None) -> bool:
        normalized_kind = str(kind or "").strip().lower()
        return any(
            option["value"] == font_name
            and (
                not normalized_kind
                or str(option.get("kind") or "").strip().lower() == normalized_kind
            )
            for option in self.replacement_options
        )

    def inspect_dwg(
        self,
        *,
        source_dwg: Path,
        replacement_policy: str = "none",
        replacement_font: str | None = None,
        replacement_fonts: dict[str, str] | None = None,
        font_compatibility_mode: bool = False,
        workspace_dir: Path | None = None,
        slot_runtime: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self.inspect_calls.append(
            {
                "source_dwg": source_dwg,
                "replacement_policy": replacement_policy,
                "replacement_font": replacement_font,
                "replacement_fonts": replacement_fonts,
                "font_compatibility_mode": font_compatibility_mode,
                "workspace_dir": workspace_dir,
                "slot_runtime": slot_runtime,
            }
        )
        filename = source_dwg.name
        if filename.startswith("missing-font"):
            return {
                "filename": filename,
                "status": "missing_fonts",
                "missing_fonts": [
                    {
                        "style_name": "STYLE1",
                        "font_name": "missing.shx",
                        "bigfont_name": "",
                        "kind": "shx",
                        "used_in_block": True,
                    }
                ],
                "detected_style_count": 3,
                "missing_style_count": 1,
                "font_replacement_applied": replacement_policy == "replace_missing",
                "replacement_font": replacement_font,
                "replacement_fonts": replacement_fonts or {},
                "replaced_style_count": 1 if replacement_policy == "replace_missing" else 0,
            }

        return {
            "filename": filename,
            "status": "ok",
            "missing_fonts": [],
            "detected_style_count": 2,
            "missing_style_count": 0,
            "font_replacement_applied": False,
            "replacement_font": None,
            "replaced_style_count": 0,
        }


class FakeJobProcessor:
    def __call__(self, job: Job) -> None:
        job.work_dir = Path(job.work_dir or "")
        if job.job_type == JobType.AUDIT_REPLACE:
            mode = str(job.options.get("mode", "")).strip().lower()
            if mode == "replace":
                job.mark_running(stage="AUDIT_REPLACE")
                job.progress.message = "replacing"
                reports_dir = job.work_dir / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                report_xlsx = reports_dir / "report.xlsx"
                report_json = reports_dir / "report.json"
                replaced_dwg = job.work_dir / "replaced.dwg"
                workbook = Workbook()
                summary_sheet = workbook.active
                assert summary_sheet is not None
                summary_sheet.title = "Summary"
                summary_sheet.append(["source_filename", job.source_filename or "upload.dwg"])
                summary_sheet.append(["source_project_no", job.params.get("source_project_no", "")])
                summary_sheet.append(["target_project_no", job.params.get("target_project_no", "")])
                summary_sheet.append(["replacement_count", 2])
                workbook.save(report_xlsx)
                workbook.close()
                replaced_dwg.write_bytes(b"dwg-replaced")
                report_json.write_text(
                    json.dumps(
                        {
                            "replacement_count": 2,
                            "source_project_no": job.params.get("source_project_no", ""),
                            "target_project_no": job.params.get("target_project_no", ""),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                job.artifacts.reports_dir = reports_dir
                job.artifacts.report_xlsx = report_xlsx
                job.artifacts.report_json = report_json
                job.artifacts.replaced_dwg = replaced_dwg
                job.progress.details["replacement_count"] = 2
                job.progress.details["factory_index_map"] = {
                    "applied": True,
                    "action_count": 1,
                    "report_json": str(reports_dir / "factory-index-map.json"),
                    "message": "",
                }
                job.mark_succeeded()
                return

            job.mark_running(stage="AUDIT_CHECK")
            job.progress.message = "auditing"
            reports_dir = job.work_dir / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            report_xlsx = reports_dir / "report.xlsx"
            report_json = reports_dir / "report.json"
            workbook = Workbook()
            summary_sheet = workbook.active
            assert summary_sheet is not None
            summary_sheet.title = "Summary"
            summary_sheet.append(["source_filename", job.source_filename or "upload.dwg"])
            summary_sheet.append(["project_no", job.project_no])
            summary_sheet.append(["findings_count", 2])
            summary_sheet.append(["affected_drawings_count", 1])
            workbook.save(report_xlsx)
            workbook.close()
            report_json.write_text(
                json.dumps(
                    {
                        "findings_count": 2,
                        "affected_drawings_count": 1,
                        "top_wrong_texts": ["2016", "JD"],
                        "top_internal_codes": ["1234567-JGS01-001"],
                        "finding_groups": [
                            {
                                "matched_text": "2016",
                                "count": 1,
                                "internal_codes": ["1234567-JGS01-001"],
                            },
                            {
                                "matched_text": "JD",
                                "count": 1,
                                "internal_codes": ["1234567-JGS01-001"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            preview_dir = job.work_dir / "output" / "preview"
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview_pdf = preview_dir / "preview-annotated.pdf"
            preview_pdf.write_bytes(b"%PDF-annotated")
            job.artifacts.reports_dir = reports_dir
            job.artifacts.report_xlsx = report_xlsx
            job.artifacts.report_json = report_json
            job.artifacts.preview_pdf = preview_pdf
            job.artifacts.preview_mode = "annotated"
            job.progress.details["findings_count"] = 2
            job.progress.details["affected_drawings_count"] = 1
            job.progress.details["top_wrong_texts"] = ["2016", "JD"]
            job.progress.details["top_internal_codes"] = ["1234567-JGS01-001"]
            job.mark_succeeded()
            return

        if bool(job.options.get("split_only")):
            job.mark_running(stage="EXPORT_PDF_AND_DWG")
            job.progress.message = "split only"
            package_zip = job.work_dir / "package.zip"
            drawings_dir = job.work_dir / "output" / "drawings"
            drawings_dir.mkdir(parents=True, exist_ok=True)
            package_zip.write_bytes(b"PK\x03\x04split-only")
            (drawings_dir / "drawing-001.dwg").write_bytes(b"dwg")
            (drawings_dir / "drawing-001.pdf").write_bytes(b"pdf")
            (job.work_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "deliverable_outputs": {
                            "dwg_count": 1,
                            "pdf_count": 1,
                            "documents": [],
                            "drawings": [
                                {
                                    "name": "DRAW001 (20261RS-JGS65-001)",
                                    "internal_code": "20261RS-JGS65-001",
                                    "dwg_name": "drawing-001.dwg",
                                    "pdf_name": "drawing-001.pdf",
                                    "page_total": 1,
                                }
                            ],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            job.artifacts.package_zip = package_zip
            job.artifacts.drawings_dir = drawings_dir
            job.mark_succeeded()
            return

        job.mark_running(stage="GENERATE_DOCS")
        job.progress.message = "processing"

        package_zip = job.work_dir / "package.zip"
        ied_xlsx = job.work_dir / "ied" / "IED计划.xlsx"
        drawings_dir = job.work_dir / "output" / "drawings"
        docs_dir = job.work_dir / "output" / "docs"
        drawings_dir.mkdir(parents=True, exist_ok=True)
        docs_dir.mkdir(parents=True, exist_ok=True)
        package_zip.write_bytes(b"PK\x03\x04test")
        include_ied_plan = job.params.get("include_ied_plan", True)
        if bool(include_ied_plan):
            ied_xlsx.parent.mkdir(parents=True, exist_ok=True)
            ied_xlsx.write_bytes(b"ied")
        (drawings_dir / "drawing-001.dwg").write_bytes(b"dwg")
        (drawings_dir / "drawing-001.pdf").write_bytes(b"pdf")
        (drawings_dir / "drawing-002.dwg").write_bytes(b"dwg")
        (drawings_dir / "drawing-002.pdf").write_bytes(b"pdf")
        preview_dir = job.work_dir / "output" / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_pdf = preview_dir / "preview-plain.pdf"
        preview_pdf.write_bytes(b"%PDF-plain")
        (docs_dir / "cover.docx").write_text("cover", encoding="utf-8")
        (docs_dir / "cover.pdf").write_text("cover-pdf", encoding="utf-8")
        (docs_dir / "design.xlsx").write_text("design", encoding="utf-8")
        (job.work_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "drawings": [
                        {
                            "name": "DRAW001 (20261RS-JGS65-001)",
                            "type": "single_frame",
                            "internal_code": "20261RS-JGS65-001",
                            "pdf_path": str(drawings_dir / "drawing-001.pdf"),
                            "dwg_path": str(drawings_dir / "drawing-001.dwg"),
                            "page_total": 1,
                            "flags": [
                                "PLOT_WINDOW_USED",
                                "PLOT_FROM_SOURCE_WINDOW",
                                "PAPER_SIZE_MISMATCH",
                                "PAPER_SIZE_AUTO_FIXED",
                            ],
                        },
                        {
                            "name": "DRAW002 (20261RS-JGS65-002)",
                            "type": "a4_sheet_set",
                            "internal_code": "20261RS-JGS65-002",
                            "pdf_path": str(drawings_dir / "drawing-002.pdf"),
                            "dwg_path": str(drawings_dir / "drawing-002.dwg"),
                            "page_total": 4,
                            "flags": ["PLOT_WINDOW_USED"],
                        },
                    ],
                    "deliverable_outputs": {
                        "dwg_count": 2,
                        "pdf_count": 2,
                        "documents": [
                            {"name": "cover.docx", "kind": "docx"},
                            {"name": "cover.pdf", "kind": "pdf"},
                            {"name": "design.xlsx", "kind": "xlsx"},
                        ],
                        "drawings": [
                            {
                                "name": "DRAW001 (20261RS-JGS65-001)",
                                "internal_code": "20261RS-JGS65-001",
                                "dwg_name": "drawing-001.dwg",
                                "pdf_name": "drawing-001.pdf",
                                "page_total": 1,
                            },
                            {
                                "name": "DRAW002 (20261RS-JGS65-002)",
                                "internal_code": "20261RS-JGS65-002",
                                "dwg_name": "drawing-002.dwg",
                                "pdf_name": "drawing-002.pdf",
                                "page_total": 4,
                            },
                        ],
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        job.artifacts.package_zip = package_zip
        job.artifacts.ied_xlsx = ied_xlsx if bool(include_ied_plan) else None
        job.artifacts.drawings_dir = drawings_dir
        job.artifacts.docs_dir = docs_dir
        job.artifacts.preview_pdf = preview_pdf
        job.artifacts.preview_mode = "plain"
        job.flags = [
            "[DRAW001 (20261RS-JGS65-001)] PLOT_WINDOW_USED",
            "[DRAW001 (20261RS-JGS65-001)] PLOT_FROM_SOURCE_WINDOW",
            "[DRAW001 (20261RS-JGS65-001)] PAPER_SIZE_MISMATCH",
            "[DRAW001 (20261RS-JGS65-001)] PAPER_SIZE_AUTO_FIXED",
        ]
        job.mark_succeeded()


def _configure_api_env(monkeypatch, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    spec_path = repo_root / "documents" / "参数规范.yaml"
    runtime_spec_path = repo_root / "documents" / "参数规范_运行期.yaml"

    monkeypatch.setenv("FANBAN_SPEC_PATH", str(spec_path))
    monkeypatch.setenv("FANBAN_RUNTIME_SPEC_PATH", str(runtime_spec_path))
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("FANBAN_UPLOAD_LIMITS__MAX_FILES", "3")
    monkeypatch.setenv("FANBAN_UPLOAD_LIMITS__MAX_TOTAL_MB", "1")

    SpecLoader.clear_cache()
    reload_config()


def _authenticate_test_client(client: TestClient, account_id: str = "hbjjswd") -> None:
    response = client.post("/api/auth/login", json={"account_id": account_id, "password": "password"})
    assert response.status_code == 200
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})


class AuthenticatedTestClient(TestClient):
    def __enter__(self):
        client = super().__enter__()
        _authenticate_test_client(client)
        return client


def _create_client(monkeypatch, tmp_path: Path, processor=None, font_service=None) -> TestClient:
    _configure_api_env(monkeypatch, tmp_path)
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.main import create_app

    app = create_app(
        job_processor=processor or FakeJobProcessor(),
        font_preflight_service=cast(Any, font_service),
    )
    return AuthenticatedTestClient(app)


def _deliverable_params() -> dict[str, str]:
    return {
        "project_no": "2016",
        "classification": "非密",
        "subitem_name": "示例子项",
        "album_title_cn": "示例图册",
        "wbs_code": "WBS-001",
        "file_category": "1 总体文件",
        "ied_status": "编制",
        "ied_doc_type": "图册",
        "cover_variant": "通用",
    }


def _poll_job(client: TestClient, job_id: str, timeout_sec: float = 3.0) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        detail = client.get(f"/api/jobs/{job_id}")
        assert detail.status_code == 200
        payload = detail.json()
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout_sec}s")


def test_health_endpoint_returns_runtime_status(monkeypatch, tmp_path: Path) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.get("/api/system/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["ready"] is True
    assert "storage_writable" in payload
    assert "worker_alive" in payload
    assert "active_doc_jobs" in payload
    assert "active_total_jobs" in payload


def test_ping_endpoint_reports_http_process_without_runtime_health_probe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        def _health_should_not_run() -> dict[str, object]:
            raise AssertionError("ping must not call runtime.health")

        client.app.state.runtime.health = _health_should_not_run
        response = client.get("/api/system/ping")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "server_time" in payload


def test_pipeline_job_processor_dispatches_audit_jobs(monkeypatch) -> None:
    from API.app.runtime import PipelineJobProcessor

    class DeliverableExecutor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def execute(self, job: Job) -> None:
            self.calls.append(job.job_id)

    class AuditExecutor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def execute(self, job: Job) -> None:
            self.calls.append(job.job_id)

    class ReplaceExecutor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def execute(self, job: Job) -> None:
            self.calls.append(job.job_id)

    deliverable = DeliverableExecutor()
    audit = AuditExecutor()
    replace = ReplaceExecutor()
    monkeypatch.setattr("API.app.runtime.PipelineExecutor", lambda: deliverable)
    monkeypatch.setattr("API.app.runtime.AuditCheckExecutor", lambda: audit)
    monkeypatch.setattr("API.app.runtime.AuditReplaceExecutor", lambda: replace)

    processor = PipelineJobProcessor()
    processor(Job(job_id="job-deliverable", job_type=JobType.DELIVERABLE, project_no="2016"))
    processor(
        Job(
            job_id="job-audit",
            job_type=JobType.AUDIT_REPLACE,
            project_no="2016",
            options={"mode": "check"},
        ),
    )
    processor(
        Job(
            job_id="job-replace",
            job_type=JobType.AUDIT_REPLACE,
            project_no="1818",
            options={"mode": "replace"},
        ),
    )

    assert deliverable.calls == ["job-deliverable"]
    assert audit.calls == ["job-audit"]
    assert replace.calls == ["job-replace"]


def test_pipeline_job_processor_exposes_slot_bound_phase_for_deliverables(monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.runtime import PipelineJobProcessor

    class DeliverableExecutor:
        def __init__(self) -> None:
            self.phase_calls: list[str] = []

        def execute_slot_bound_phase(self, job: Job):
            self.phase_calls.append(job.job_id)
            return None

        def execute(self, job: Job) -> None:
            raise AssertionError("deliverable should use execute_slot_bound_phase")

    deliverable = DeliverableExecutor()
    monkeypatch.setattr("API.app.runtime.PipelineExecutor", lambda **_: deliverable)

    processor = PipelineJobProcessor()
    result = processor.execute_slot_bound_phase(
        Job(job_id="job-deliverable", job_type=JobType.DELIVERABLE, project_no="2016")
    )

    assert result is None
    assert deliverable.phase_calls == ["job-deliverable"]


def test_health_endpoint_allows_local_frontend_origin(monkeypatch, tmp_path: Path) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.get(
            "/api/system/health",
            headers={"Origin": "http://127.0.0.1:5175"},
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5175"


def test_health_reports_autocad_unready_when_runner_path_blank_and_autodetect_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FANBAN_MODULE5_EXPORT__CAD_RUNNER__ACCORECONSOLE_EXE", "")
    monkeypatch.setenv("FANBAN_AUTOCAD_INSTALL_DIR", "")
    monkeypatch.setenv("FANBAN_AUTOCAD__CTB_PATH", "")
    reload_config()
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app import runtime as runtime_module
    from API.app.main import create_app

    monkeypatch.setattr(
        runtime_module,
        "resolve_autocad_paths",
        lambda configured_install_dir=None: SimpleNamespace(accoreconsole_exe=None),
        raising=False,
    )

    with TestClient(create_app(job_processor=FakeJobProcessor())) as client:
        response = client.get("/api/system/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["autocad_ready"] is False


def test_form_schema_returns_deliverable_fields_and_options(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.get("/api/meta/form-schema")

    assert response.status_code == 200
    payload = response.json()
    assert payload["upload_limits"]["max_files"] == 3
    assert payload["deliverable"]["sections"]
    assert "2016" in payload["audit_replace"]["project_options"]
    assert payload["audit_replace"]["factory_index_maps"]["source_variant_options"]["2016"] == [
        "1",
        "2",
    ]
    assert payload["audit_replace"]["factory_index_maps"]["target_variant_options"]["1916"] == [
        "3",
        "4",
    ]
    assert payload["audit_replace"]["project_units"]["1915"] == ["1", "2"]
    assert payload["audit_replace"]["source_unit_options"]["2016"] == [
        {"value": "1", "label": "1号机组/岛"},
        {"value": "2", "label": "2号机组/岛"},
    ]
    assert payload["audit_replace"]["source_unit_options"]["1916"] == [
        {"value": "3", "label": "3号机组/岛"},
        {"value": "4", "label": "4号机组/岛"},
    ]
    assert payload["audit_replace"]["target_unit_options"]["1915"] == [
        {"value": "1", "label": "1号机组/岛"},
        {"value": "2", "label": "2号机组/岛"},
    ]
    assert payload["audit_replace"]["target_unit_options"]["2016"] == [
        {"value": "1", "label": "1号机组/岛"},
        {"value": "2", "label": "2号机组/岛"},
    ]
    assert payload["audit_check"]["unit_consistency"]["enabled"] is True
    assert payload["audit_check"]["unit_consistency"]["project_units"]["2016"] == ["1", "2"]
    assert payload["audit_check"]["unit_consistency"]["project_units"]["1916"] == ["3", "4"]
    assert payload["management"]["account"]["valid_roles"]
    assert payload["management"]["account"]["admin_created_default_password"] == "password"
    assert payload["management"]["workflow"]["factor"]["min"] == 0.8
    assert payload["management"]["workflow"]["terminal_status"] == "three_review_approved"
    assert payload["management"]["workflow"]["status_labels"]["three_review_approved"] == "三审通过"
    assert payload["management"]["workflow"]["node_labels"]["one_review"] == "一审"
    assert payload["management"]["workflow"]["empty_current_node_label"] == "未进入审批"
    assert payload["management"]["workload"]["settlement_trigger"] == "archive_success"
    assert payload["management"]["workload"]["status_options"]
    assert "admin" in payload["management"]["workload"]["scope_roles"]
    assert payload["management"]["archive"]["status_labels"]["succeeded"] == "已归档"

    project_section = next(
        section for section in payload["deliverable"]["sections"] if section["id"] == "project"
    )
    project_no = next(field for field in project_section["fields"] if field["key"] == "project_no")
    unit_no = next(field for field in project_section["fields"] if field["key"] == "unit_no")
    file_category = next(
        field
        for section in payload["deliverable"]["sections"]
        for field in section["fields"]
        if field["key"] == "file_category"
    )
    ied_design_type = next(
        field
        for section in payload["deliverable"]["sections"]
        for field in section["fields"]
        if field["key"] == "ied_design_type"
    )
    ied_responsible_unit = next(
        field
        for section in payload["deliverable"]["sections"]
        for field in section["fields"]
        if field["key"] == "ied_responsible_unit"
    )
    ied_person_qual_category = next(
        field
        for section in payload["deliverable"]["sections"]
        for field in section["fields"]
        if field["key"] == "ied_person_qual_category"
    )
    include_ied_plan = next(
        field
        for section in payload["deliverable"]["sections"]
        for field in section["fields"]
        if field["key"] == "include_ied_plan"
    )

    assert "2016" in project_no["options"]
    assert "1915" in project_no["options"]
    assert project_no["required"] is False
    assert "DWG" in project_no["desc"]
    assert "2016" in project_no["desc"]
    assert unit_no["required"] is False
    assert unit_no["options"] == ["1", "2", "3", "4", "5", "6"]
    assert "1 总体文件" in file_category["options"]
    assert ied_design_type["required_when"] == "ied_status == '发布'"
    assert ied_design_type["type"] == "combobox"
    assert ied_design_type["allow_custom_input"] is True
    assert ied_design_type["filterable"] is True
    assert ied_design_type["options"][:3] == ["安装技术要求", "常规岛厂房设计", "初步设计"]
    assert ied_responsible_unit["required_when"] == "ied_status == '发布'"
    assert ied_responsible_unit["type"] == "combobox"
    assert ied_responsible_unit["allow_custom_input"] is True
    assert ied_responsible_unit["filterable"] is True
    assert ied_responsible_unit["options"][:3] == [
        "河北分公司-核工程研究设计所-电仪室",
        "公用系统所-水工工艺二室",
        "河北分公司-电气自动化所-仪控一室",
    ]
    assert ied_person_qual_category["options"] == [
        "非核安全物项",
        "非核压力容器",
        "非核压力管道",
        "一般核安全物项-军工",
        "一般核安全物项-民用",
        "核安全承压机械设备-军工-甲级",
        "核安全承压机械设备-军工-乙级",
        "核安全承压机械设备-民用-甲级",
        "核安全承压机械设备-民用-乙级",
    ]
    assert include_ied_plan["type"] == "checkbox"
    assert include_ied_plan["default"] is True


def test_create_batch_requires_ied_publish_fields_when_status_is_publish(
    monkeypatch,
    tmp_path: Path,
) -> None:
    params = _deliverable_params()
    params["ied_status"] = "发布"

    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(params, ensure_ascii=False)},
            files=[("files[]", ("A01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["param_errors"]["ied_submitted_plan_date"] == ["required"]
    assert payload["detail"]["param_errors"]["ied_publish_plan_date"] == ["required"]
    assert payload["detail"]["param_errors"]["ied_external_plan_date"] == ["required"]
    assert payload["detail"]["param_errors"]["ied_design_type"] == ["required"]
    assert payload["detail"]["param_errors"]["ied_chief_designer"] == ["required"]
    assert payload["detail"]["param_errors"]["ied_responsible_unit"] == ["required"]


def test_create_batch_rejects_non_dwg_upload(monkeypatch, tmp_path: Path) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(_deliverable_params(), ensure_ascii=False)},
            files=[("files[]", ("bad.txt", b"nope", "text/plain"))],
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["upload_errors"]["files"] == ["only .dwg files are allowed"]


def test_preflight_fonts_returns_missing_fonts_and_replacement_options(monkeypatch, tmp_path: Path) -> None:
    font_service = FakeFontPreflightService()

    with _create_client(monkeypatch, tmp_path, font_service=font_service) as client:
        response = client.post(
            "/api/jobs/preflight-fonts",
            files=[
                ("files[]", ("missing-font.dwg", b"dwg-a", "application/acad")),
                ("files[]", ("ok-font.dwg", b"dwg-b", "application/acad")),
            ],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requires_confirmation"] is True
    assert payload["replacement_options"] == [
        {
            "label": "simplex.shx (AutoCAD SHX)",
            "value": "simplex.shx",
            "family": "simplex",
            "path": r"D:\Program Files\AUTOCAD\AutoCAD 2022\Fonts\simplex.shx",
            "kind": "shx",
        },
        {
            "label": "romans.shx (AutoCAD SHX)",
            "value": "romans.shx",
            "family": "romans",
            "path": r"D:\Program Files\AUTOCAD\AutoCAD 2022\Fonts\romans.shx",
            "kind": "shx",
        },
    ]
    assert payload["replacement_options_by_kind"] == {
        "shx": [
            {
                "label": "simplex.shx (AutoCAD SHX)",
                "value": "simplex.shx",
                "family": "simplex",
                "path": r"D:\Program Files\AUTOCAD\AutoCAD 2022\Fonts\simplex.shx",
                "kind": "shx",
            },
            {
                "label": "romans.shx (AutoCAD SHX)",
                "value": "romans.shx",
                "family": "romans",
                "path": r"D:\Program Files\AUTOCAD\AutoCAD 2022\Fonts\romans.shx",
                "kind": "shx",
            },
        ]
    }
    assert payload["default_replacement_fonts"] == {"shx": "simplex.shx"}
    assert font_service.list_requests[-1] == ["shx"]
    assert payload["default_replacement_font"] == "simplex.shx"
    assert payload["files"] == [
        {
            "filename": "missing-font.dwg",
            "status": "missing_fonts",
            "missing_fonts": [
                {
                    "style_name": "STYLE1",
                    "font_name": "missing.shx",
                    "bigfont_name": "",
                    "kind": "shx",
                    "used_in_block": True,
                }
            ],
            "detected_style_count": 3,
            "missing_style_count": 1,
            "font_replacement_applied": False,
            "replacement_font": None,
            "replacement_fonts": {},
            "replaced_style_count": 0,
        },
        {
            "filename": "ok-font.dwg",
            "status": "ok",
            "missing_fonts": [],
            "detected_style_count": 2,
            "missing_style_count": 0,
            "font_replacement_applied": False,
            "replacement_font": None,
            "replaced_style_count": 0,
        },
    ]


def test_preflight_fonts_keeps_file_results_when_replacement_inventory_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FailingReplacementInventoryFontService(FakeFontPreflightService):
        def list_replacement_options(self, *, missing_kinds: list[str] | None = None):  # noqa: ANN201
            raise RuntimeError("font inventory unavailable")

        def list_replacement_options_by_kind(  # noqa: ANN201
            self,
            *,
            missing_kinds: list[str] | None = None,
        ):
            raise RuntimeError("font inventory unavailable")

        def default_replacement_fonts(  # noqa: ANN201
            self,
            *,
            missing_kinds: list[str] | None = None,
            missing_fonts: list[dict[str, object]] | None = None,
        ):
            raise RuntimeError("font inventory unavailable")

    with _create_client(
        monkeypatch,
        tmp_path,
        font_service=FailingReplacementInventoryFontService(),
    ) as client:
        response = client.post(
            "/api/jobs/preflight-fonts",
            files=[("files[]", ("missing-font.dwg", b"dwg-a", "application/acad"))],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requires_confirmation"] is True
    assert payload["replacement_options"] == []
    assert payload["replacement_options_by_kind"] == {}
    assert payload["default_replacement_fonts"] == {}
    assert payload["files"][0]["status"] == "missing_fonts"


def test_preflight_fonts_uses_ascii_working_copy_for_non_ascii_upload_names(
    monkeypatch,
    tmp_path: Path,
) -> None:
    font_service = FakeFontPreflightService()

    with _create_client(monkeypatch, tmp_path, font_service=font_service) as client:
        response = client.post(
            "/api/jobs/preflight-fonts",
            files=[("files[]", ("20261NH-JGS51-B合并版.dwg", b"dwg-a", "application/acad"))],
        )

    assert response.status_code == 200
    assert len(font_service.inspect_calls) == 1
    source_path = font_service.inspect_calls[0]["source_dwg"]
    assert isinstance(source_path, Path)
    assert source_path.suffix.lower() == ".dwg"
    assert source_path.name != "20261NH-JGS51-B合并版.dwg"
    assert all(ord(ch) < 128 for ch in source_path.name)


def test_create_batch_preserves_source_filename_but_stores_ascii_upload_copy(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(_deliverable_params(), ensure_ascii=False)},
            files=[("files[]", ("20261NH-JGS51-B合并版.dwg", b"dwg", "application/acad"))],
        )

        assert response.status_code == 201
        payload = response.json()
        job_id = payload["jobs"][0]["job_id"]
        assert payload["jobs"][0]["source_filename"] == "20261NH-JGS51-B合并版.dwg"

        detail = _poll_job(client, job_id)
        assert detail["source_filename"] == "20261NH-JGS51-B合并版.dwg"

    uploads_dir = tmp_path / "storage" / "jobs" / job_id / "uploads"
    stored_files = list(uploads_dir.iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].suffix.lower() == ".dwg"
    assert stored_files[0].name != "20261NH-JGS51-B合并版.dwg"
    assert all(ord(ch) < 128 for ch in stored_files[0].name)


def test_create_batch_preserves_cjk_params_in_job_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    params = _deliverable_params()

    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(params, ensure_ascii=False)},
            files=[("files[]", ("A01.dwg", b"dwg", "application/acad"))],
        )

        assert response.status_code == 201
        payload = response.json()
        job_id = payload["jobs"][0]["job_id"]
        _poll_job(client, job_id)

    job_payload = json.loads(
        (tmp_path / "storage" / "jobs" / job_id / "job.json").read_text(encoding="utf-8")
    )

    assert job_payload["params"]["classification"] == params["classification"]
    assert job_payload["params"]["subitem_name"] == params["subitem_name"]
    assert job_payload["params"]["album_title_cn"] == params["album_title_cn"]
    assert job_payload["params"]["file_category"] == params["file_category"]
    assert job_payload["params"]["ied_status"] == params["ied_status"]
    assert job_payload["params"]["ied_doc_type"] == params["ied_doc_type"]
    assert job_payload["params"]["cover_variant"] == params["cover_variant"]


def test_create_batch_rejects_replace_missing_without_replacement_font(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path, font_service=FakeFontPreflightService()) as client:
        response = client.post(
            "/api/jobs/batch",
            data={
                "params_json": json.dumps(
                    {
                        **_deliverable_params(),
                        "font_replace_policy": "replace_missing",
                    },
                    ensure_ascii=False,
                )
            },
            files=[("files[]", ("missing-font.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["param_errors"]["font_replacement_font"] == [
        "required_when_font_replace_policy_is_replace_missing"
    ]


def test_create_batch_accepts_kind_specific_font_replacements(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path, font_service=FakeFontPreflightService()) as client:
        response = client.post(
            "/api/jobs/batch",
            data={
                "params_json": json.dumps(
                    {
                        **_deliverable_params(),
                        "font_replace_policy": "replace_missing",
                        "font_replacement_fonts": {"ttf": "simsun.ttc"},
                    },
                    ensure_ascii=False,
                )
            },
            files=[("files[]", ("missing-font.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 201


def test_create_batch_rejects_missing_required_param(monkeypatch, tmp_path: Path) -> None:
    params = _deliverable_params()
    params.pop("album_title_cn")

    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(params, ensure_ascii=False)},
            files=[("files[]", ("A01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["param_errors"]["album_title_cn"] == ["required"]


def test_create_batch_split_only_skips_document_param_validation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={
                "params_json": json.dumps({"project_no": ""}, ensure_ascii=False),
                "split_only": "true",
            },
            files=[("files[]", ("20261RS-JGS65.dwg", b"dwg", "application/acad"))],
        )

        assert response.status_code == 201
        payload = response.json()
        job_id = payload["jobs"][0]["job_id"]
        assert payload["jobs"][0]["job_mode"] == "split_only"
        assert payload["jobs"][0]["task_role"] == "仅拆图"
        detail = _poll_job(client, job_id)

    job_payload = json.loads(
        (tmp_path / "storage" / "jobs" / job_id / "job.json").read_text(encoding="utf-8")
    )
    assert job_payload["project_no"] == "2026"
    assert job_payload["options"]["split_only"] is True
    assert detail["artifacts"]["package_available"] is True


def test_create_batch_infers_project_no_from_uploaded_filename_when_blank(
    monkeypatch,
    tmp_path: Path,
) -> None:
    params = _deliverable_params()
    params["project_no"] = ""

    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(params, ensure_ascii=False)},
            files=[("files[]", ("2026-A01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["jobs"][0]["project_no"] == "2026"


def test_create_batch_uses_inferred_project_no_for_required_when_validation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    params = _deliverable_params()
    params["project_no"] = ""

    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(params, ensure_ascii=False)},
            files=[("files[]", ("1818-A01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["param_errors"]["subitem_name_en"] == ["required"]
    assert payload["detail"]["param_errors"]["album_title_en"] == ["required"]


def test_create_batch_falls_back_to_default_project_no_when_not_inferable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    params = _deliverable_params()
    params.pop("project_no")

    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(params, ensure_ascii=False)},
            files=[("files[]", ("sample-A01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["jobs"][0]["project_no"] == "2016"


def test_create_audit_check_rejects_when_project_no_cannot_be_inferred(
    monkeypatch,
    tmp_path: Path,
) -> None:
    params = {"project_no": ""}

    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "check",
                "params_json": json.dumps(params, ensure_ascii=False),
            },
            files=[("files[]", ("sample-A01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["param_errors"]["project_no"] == ["required_for_audit_check"]


def test_create_audit_check_requires_unit_no_for_unit_consistency_project(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "check",
                "params_json": json.dumps({"project_no": "2026"}, ensure_ascii=False),
            },
            files=[("files[]", ("sample-A01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["param_errors"]["unit_no"] == ["required_for_unit_consistency"]


def test_create_audit_check_infers_unit_no_from_filename(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "check",
                "params_json": json.dumps({"project_no": "2026"}, ensure_ascii=False),
            },
            files=[("files[]", ("20261NS-JGS01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["jobs"][0]["project_no"] == "2026"


def test_create_audit_check_accepts_unlisted_unit_no_for_configured_project(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "check",
                "params_json": json.dumps(
                    {"project_no": "1907", "unit_no": "7"},
                    ensure_ascii=False,
                ),
            },
            files=[("files[]", ("19077NH-JGS01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["jobs"][0]["project_no"] == "1907"


def test_create_audit_check_processes_job_and_exposes_report_download(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "check",
                "params_json": json.dumps({"project_no": "2016", "unit_no": "1"}, ensure_ascii=False),
            },
            files=[("files[]", ("2016-A01.dwg", b"dwg", "application/acad"))],
        )

        assert response.status_code == 201
        payload = response.json()
        assert len(payload["jobs"]) == 1
        assert payload["jobs"][0]["task_kind"] == "audit_check"
        assert payload["jobs"][0]["job_mode"] == "check"

        job_id = payload["jobs"][0]["job_id"]
        detail = _poll_job(client, job_id)
        assert detail["status"] == "succeeded"
        assert detail["artifacts"]["report_available"] is True
        assert detail["artifacts"]["package_available"] is False
        assert detail["artifacts"]["preview_available"] is True
        assert detail["artifacts"]["preview_mode"] == "annotated"
        assert detail["artifacts"]["preview_download_url"] == f"/api/jobs/{job_id}/download/preview"
        assert detail["findings_count"] == 2
        assert detail["affected_drawings_count"] == 1
        assert detail["top_wrong_texts"] == ["2016", "JD"]
        assert detail["top_internal_codes"] == ["1234567-JGS01-001"]
        assert detail["finding_groups"] == [
            {
                "matched_text": "2016",
                "count": 1,
                "internal_codes": ["1234567-JGS01-001"],
            },
            {
                "matched_text": "JD",
                "count": 1,
                "internal_codes": ["1234567-JGS01-001"],
            },
        ]
        assert detail["slot_id"] is not None
        assert detail["profile_arg"] is not None
        assert detail["plot_style_key"] == "red_wider"
        assert detail["plot_resource_mode"] == "slot_private_with_shared_mirror"

        report_download = client.get(f"/api/jobs/{job_id}/download/report")
        assert report_download.status_code == 200
        workbook = load_workbook(filename=BytesIO(report_download.content))
        assert workbook.sheetnames[0] == "Summary"

        preview_download = client.get(f"/api/jobs/{job_id}/download/preview")
        assert preview_download.status_code == 200
        assert preview_download.content == b"%PDF-annotated"


def test_create_audit_check_reuses_explicit_batch_id_when_provided(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "check",
                "params_json": json.dumps(
                    {"project_no": "2016", "unit_no": "1", "batch_id": "batch-shared-1"},
                    ensure_ascii=False,
                ),
            },
            files=[("files[]", ("2016-A01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["batch_id"] == "batch-shared-1"
    assert payload["jobs"][0]["batch_id"] == "batch-shared-1"


def test_create_audit_replace_rejects_missing_or_same_project_pair(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        missing_source = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "replace",
                "params_json": json.dumps(
                    {"source_project_no": "", "target_project_no": "1818", "run_deliverable": False},
                    ensure_ascii=False,
                ),
            },
            files=[("files[]", ("1818-A01.dwg", b"dwg", "application/acad"))],
        )
        missing_target = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "replace",
                "params_json": json.dumps(
                    {"source_project_no": "2016", "target_project_no": "", "run_deliverable": False},
                    ensure_ascii=False,
                ),
            },
            files=[("files[]", ("2016-A01.dwg", b"dwg", "application/acad"))],
        )
        same_pair = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "replace",
                "params_json": json.dumps(
                    {"source_project_no": "2016", "target_project_no": "2016", "run_deliverable": False},
                    ensure_ascii=False,
                ),
            },
            files=[("files[]", ("2016-A01.dwg", b"dwg", "application/acad"))],
        )

    assert missing_source.status_code == 422
    assert missing_source.json()["detail"]["param_errors"]["source_project_no"] == ["required_for_replace"]
    assert missing_target.status_code == 422
    assert missing_target.json()["detail"]["param_errors"]["target_project_no"] == ["required_for_replace"]
    assert same_pair.status_code == 422
    assert same_pair.json()["detail"]["param_errors"]["target_project_no"] == [
        "must_differ_from_source_project_no"
    ]


def test_create_audit_replace_processes_job_without_deliverable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "replace",
                "params_json": json.dumps(
                    {
                        "source_project_no": "2016",
                        "source_island_no": "1",
                        "target_project_no": "1916",
                        "target_island_no": "3",
                        "run_deliverable": False,
                    },
                    ensure_ascii=False,
                ),
            },
            files=[("files[]", ("2016-A01.dwg", b"dwg", "application/acad"))],
        )

        assert response.status_code == 201
        payload = response.json()
        assert len(payload["jobs"]) == 1
        assert payload["jobs"][0]["task_kind"] == "audit_replace"
        assert payload["jobs"][0]["job_mode"] == "replace"

        job_id = payload["jobs"][0]["job_id"]
        detail = _poll_job(client, job_id)
        assert detail["status"] == "succeeded"
        assert detail["artifacts"]["report_available"] is True
        assert detail["artifacts"]["replaced_dwg_available"] is True
        assert detail["artifacts"]["package_available"] is False
        assert detail["artifacts"]["replaced_dwg_download_url"] == f"/api/jobs/{job_id}/download/replaced"
        assert detail["replace_summary"]["replacement_count"] == 2
        assert detail["replace_summary"]["source_project_no"] == "2016"
        assert detail["replace_summary"]["source_island_no"] == "1"
        assert detail["replace_summary"]["target_project_no"] == "1916"
        assert detail["replace_summary"]["target_island_no"] == "3"
        assert detail["factory_index_map"]["applied"] is True
        assert detail["factory_index_map"]["action_count"] == 1

        replaced_download = client.get(f"/api/jobs/{job_id}/download/replaced")
        assert replaced_download.status_code == 200
        assert replaced_download.content == b"dwg-replaced"


def test_create_audit_replace_creates_group_when_run_deliverable_enabled(
    monkeypatch,
    tmp_path: Path,
) -> None:
    params = _deliverable_params()
    params.pop("project_no")
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "replace",
                "params_json": json.dumps(
                    {
                        "source_project_no": "2016",
                        "source_island_no": "1",
                        "target_project_no": "1818",
                        "run_deliverable": True,
                        "deliverable_params": params,
                    },
                    ensure_ascii=False,
                ),
            },
            files=[("files[]", ("2016-A01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 201
    payload = response.json()
    assert len(payload["jobs"]) == 1
    group_summary = payload["jobs"][0]
    assert group_summary["is_group"] is True
    assert len(group_summary["child_job_ids"]) == 2


def test_create_audit_replace_with_deliverable_runs_replace_before_deliverable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class ReplaceThenDeliverableProcessor:
        def __call__(self, job: Job) -> None:
            job.work_dir = Path(job.work_dir or "")
            if job.job_type == JobType.AUDIT_REPLACE and str(job.options.get("mode")) == "replace":
                job.mark_running(stage="AUDIT_REPLACE")
                replaced_dwg = job.work_dir / "replaced.dwg"
                replaced_dwg.write_bytes(b"replaced-dwg")
                reports_dir = job.work_dir / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                report_xlsx = reports_dir / "report.xlsx"
                report_json = reports_dir / "report.json"
                workbook = Workbook()
                summary_sheet = workbook.active
                assert summary_sheet is not None
                summary_sheet.title = "Summary"
                summary_sheet.append(["replacement_count", 1])
                workbook.save(report_xlsx)
                workbook.close()
                report_json.write_text(
                    json.dumps(
                        {
                            "replacement_count": 1,
                            "source_project_no": "2016",
                            "target_project_no": "1818",
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                job.artifacts.replaced_dwg = replaced_dwg
                job.artifacts.report_xlsx = report_xlsx
                job.artifacts.report_json = report_json
                job.mark_succeeded()
                return

            assert job.job_type == JobType.DELIVERABLE
            assert len(job.input_files) == 1
            assert Path(job.input_files[0]).read_bytes() == b"replaced-dwg"
            job.mark_running(stage="GENERATE_DOCS")
            package_zip = job.work_dir / "package.zip"
            package_zip.write_bytes(b"PK\x03\x04deliverable")
            job.artifacts.package_zip = package_zip
            job.mark_succeeded()

    _configure_api_env(monkeypatch, tmp_path)
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.main import create_app

    params = _deliverable_params()
    params.pop("project_no")
    with AuthenticatedTestClient(
        create_app(
            job_processor=ReplaceThenDeliverableProcessor(),
            shared_prep_service=FakeSharedPrepService(),
        ),
    ) as client:
        response = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "replace",
                "params_json": json.dumps(
                    {
                        "source_project_no": "2016",
                        "source_island_no": "1",
                        "target_project_no": "1818",
                        "run_deliverable": True,
                        "deliverable_params": params,
                    },
                    ensure_ascii=False,
                ),
            },
            files=[("files[]", ("2016-A01.dwg", b"dwg", "application/acad"))],
        )

        assert response.status_code == 201
        group_id = response.json()["jobs"][0]["job_id"]
        detail = _poll_job(client, group_id, timeout_sec=5.0)
        assert detail["status"] == "succeeded"
        children = {child["task_role"]: child for child in detail["children"]}
        assert children["audit_replace"]["artifacts"]["replaced_dwg_available"] is True
        assert children["deliverable_main"]["artifacts"]["package_available"] is True


def test_create_batch_processes_jobs_and_exposes_downloads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(_deliverable_params(), ensure_ascii=False)},
            files=[
                ("files[]", ("A01.dwg", b"dwg-a", "application/acad")),
                ("files[]", ("A02.dwg", b"dwg-b", "application/acad")),
            ],
        )

        assert response.status_code == 201
        payload = response.json()
        assert payload["batch_id"]
        assert len(payload["jobs"]) == 2
        assert {item["source_filename"] for item in payload["jobs"]} == {"A01.dwg", "A02.dwg"}

        job_id = payload["jobs"][0]["job_id"]
        final_detail = _poll_job(client, job_id)
        assert final_detail["status"] == "succeeded"
        assert final_detail["artifacts"]["package_available"] is True
        assert final_detail["artifacts"]["ied_available"] is True
        assert final_detail["artifacts"]["preview_available"] is True
        assert final_detail["artifacts"]["preview_mode"] == "plain"
        assert final_detail["artifacts"]["preview_download_url"] == f"/api/jobs/{job_id}/download/preview"
        assert final_detail["deliverable_outputs"] == {
            "dwg_count": 2,
            "pdf_count": 2,
            "documents": [
                {"name": "cover.docx", "kind": "docx"},
                {"name": "cover.pdf", "kind": "pdf"},
                {"name": "design.xlsx", "kind": "xlsx"},
            ],
            "drawings": [
                {
                    "name": "DRAW001 (20261RS-JGS65-001)",
                    "internal_code": "20261RS-JGS65-001",
                    "dwg_name": "drawing-001.dwg",
                    "pdf_name": "drawing-001.pdf",
                    "page_total": 1,
                },
                {
                    "name": "DRAW002 (20261RS-JGS65-002)",
                    "internal_code": "20261RS-JGS65-002",
                    "dwg_name": "drawing-002.dwg",
                    "pdf_name": "drawing-002.pdf",
                    "page_total": 4,
                },
            ],
        }
        assert final_detail["flags"] == [
            "[DRAW001 (20261RS-JGS65-001)] PAPER_SIZE_AUTO_FIXED",
        ]
        assert final_detail["slot_id"] is not None
        assert final_detail["profile_arg"] is not None
        assert final_detail["plot_style_key"] == "red_wider"
        assert final_detail["plot_resource_mode"] == "slot_private_with_shared_mirror"

        listing = client.get("/api/jobs")
        assert listing.status_code == 200
        list_payload = listing.json()
        assert list_payload["total"] == 2
        assert list_payload["items"][0]["task_kind"] == "deliverable"

        package_download = client.get(f"/api/jobs/{job_id}/download/package")
        assert package_download.status_code == 200
        assert package_download.content.startswith(b"PK")

        ied_download = client.get(f"/api/jobs/{job_id}/download/ied")
        assert ied_download.status_code == 200
        assert ied_download.content == b"ied"

        preview_download = client.get(f"/api/jobs/{job_id}/download/preview")
        assert preview_download.status_code == 200
        assert preview_download.content == b"%PDF-plain"


def test_create_batch_without_ied_plan_hides_ied_artifact_and_download(
    monkeypatch,
    tmp_path: Path,
) -> None:
    params = _deliverable_params()
    params["include_ied_plan"] = False

    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(params, ensure_ascii=False)},
            files=[("files[]", ("A01.dwg", b"dwg-a", "application/acad"))],
        )

        assert response.status_code == 201
        job_id = response.json()["jobs"][0]["job_id"]
        final_detail = _poll_job(client, job_id)
        assert final_detail["status"] == "succeeded"
        assert final_detail["artifacts"]["ied_available"] is False
        assert final_detail["artifacts"]["ied_download_url"] is None

        ied_download = client.get(f"/api/jobs/{job_id}/download/ied")
        assert ied_download.status_code == 404


def test_list_jobs_supports_offset_limit_and_status_filtered_total(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        runtime = client.app.state.runtime
        base_time = datetime(2026, 4, 27, 9, 0, 0)
        created_ids: list[str] = []

        for index in range(5):
            job = runtime.job_manager.create_job(
                job_type=JobType.DELIVERABLE.value,
                project_no="2016",
                source_filename=f"job-{index + 1}.dwg",
            )
            job.created_at = base_time + timedelta(minutes=index)
            job.status = JobStatus.SUCCEEDED if index < 3 else JobStatus.FAILED
            runtime.job_manager.update_job(job)
            created_ids.append(job.job_id)

        paged = client.get("/api/jobs", params={"offset": 1, "limit": 2})
        assert paged.status_code == 200
        paged_payload = paged.json()
        assert paged_payload["total"] == 5
        assert [item["source_filename"] for item in paged_payload["items"]] == [
            "job-4.dwg",
            "job-3.dwg",
        ]

        filtered = client.get("/api/jobs", params={"status": "succeeded", "offset": 1, "limit": 1})
        assert filtered.status_code == 200
        filtered_payload = filtered.json()
        assert filtered_payload["total"] == 3
        assert [item["source_filename"] for item in filtered_payload["items"]] == ["job-2.dwg"]


class FakeSharedPrepService(SharedPrepService):
    def prepare(
        self,
        *,
        group_id: str,
        project_no: str | None = None,
        source_dwg: Path,
        shared_dir: Path,
        font_replace_policy: str = "none",
        font_replacement_font: str | None = None,
        font_replacement_fonts: dict[str, str] | None = None,
        font_compatibility_mode: bool = False,
        slot_runtime: dict[str, str] | None = None,
    ) -> SharedPrepArtifacts:
        shared_dir.mkdir(parents=True, exist_ok=True)
        staged_source = shared_dir / source_dwg.name
        staged_source.write_bytes(source_dwg.read_bytes())
        converted_dxf = shared_dir / "source_converted.dxf"
        (shared_dir / "prep_summary.json").write_text(
            json.dumps(
                {
                    "group_id": group_id,
                    "source_input_dwg": str(staged_source),
                    "source_converted_dxf": str(converted_dxf),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (shared_dir / "frames.json").write_text("[]", encoding="utf-8")
        (shared_dir / "sheet_sets.json").write_text("[]", encoding="utf-8")
        (shared_dir / "titleblock_extracts.json").write_text("[]", encoding="utf-8")
        (shared_dir / "audit_roi_context.json").write_text("{}", encoding="utf-8")
        converted_dxf.write_text("0\nEOF\n", encoding="utf-8")
        return SharedPrepArtifacts(
            shared_dir=shared_dir,
            source_input_dwg=staged_source,
            source_converted_dxf=converted_dxf,
            font_preflight_summary={
                "filename": staged_source.name,
                "status": "ok",
                "missing_fonts": [],
                "detected_style_count": 0,
                "missing_style_count": 0,
                "font_replacement_applied": font_replace_policy == "replace_missing",
                "replacement_font": font_replacement_font,
                "replacement_fonts": font_replacement_fonts or {},
                "font_compatibility_mode": font_compatibility_mode,
                "replaced_style_count": 0,
            },
            frames=[],
            sheet_sets=[],
        )


def test_create_batch_with_run_audit_check_returns_group_detail_and_children(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.main import create_app

    with AuthenticatedTestClient(
        create_app(
            job_processor=FakeJobProcessor(),
            shared_prep_service=FakeSharedPrepService(),
        ),
    ) as client:
        params = _deliverable_params()
        params["unit_no"] = "1"
        response = client.post(
            "/api/jobs/batch",
            data={
                "params_json": json.dumps(params, ensure_ascii=False),
                "run_audit_check": "true",
            },
            files=[("files[]", ("20261RS-JGS65.dwg", b"dwg", "application/acad"))],
        )

        assert response.status_code == 201
        payload = response.json()
        assert len(payload["jobs"]) == 1
        group_summary = payload["jobs"][0]
        assert group_summary["is_group"] is True
        assert group_summary["run_audit_check"] is True
        assert len(group_summary["child_job_ids"]) == 2

        detail = _poll_job(client, group_summary["job_id"], timeout_sec=5.0)
        assert detail["is_group"] is True
        assert detail["run_audit_check"] is True
        assert detail["flags"] == ["[DRAW001 (20261RS-JGS65-001)] PAPER_SIZE_AUTO_FIXED"]
        assert detail["artifacts"]["preview_available"] is True
        assert detail["artifacts"]["preview_mode"] == "annotated"
        assert detail["artifacts"]["preview_download_url"] == f"/api/jobs/{group_summary['job_id']}/download/preview"
        assert len(detail["children"]) == 2
        assert {child["task_role"] for child in detail["children"]} == {
            "deliverable_main",
            "audit_check",
        }
        assert {child["plot_style_key"] for child in detail["children"]} == {"red_wider"}
        assert {child["plot_resource_mode"] for child in detail["children"]} == {
            "slot_private_with_shared_mirror",
        }
        assert all(child["slot_id"] is not None for child in detail["children"])
        assert all(child["ctb_path"] for child in detail["children"])
        children = {child["task_role"]: child for child in detail["children"]}
        assert children["deliverable_main"]["artifacts"]["preview_available"] is True
        assert children["deliverable_main"]["artifacts"]["preview_mode"] == "plain"
        assert children["audit_check"]["artifacts"]["preview_available"] is True
        assert children["audit_check"]["artifacts"]["preview_mode"] == "annotated"

        preview_download = client.get(f"/api/jobs/{group_summary['job_id']}/download/preview")
        assert preview_download.status_code == 200
        assert preview_download.content == b"%PDF-annotated"

        listing = client.get("/api/jobs")
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert len(items) == 1
        assert items[0]["job_id"] == group_summary["job_id"]


def test_grouped_batches_can_run_children_concurrently(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import threading

    class ConcurrentTrackingProcessor:
        def __init__(self) -> None:
            self.inner = FakeJobProcessor()
            self.current = 0
            self.max_seen = 0
            self.lock = threading.Lock()

        def __call__(self, job: Job) -> None:
            with self.lock:
                self.current += 1
                self.max_seen = max(self.max_seen, self.current)
            try:
                time.sleep(0.15)
                self.inner(job)
            finally:
                with self.lock:
                    self.current -= 1

    _configure_api_env(monkeypatch, tmp_path)
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.main import create_app

    processor = ConcurrentTrackingProcessor()
    params = _deliverable_params()
    params["subitem_name_en"] = "Example Subitem"
    params["album_title_en"] = "Example Album"
    params["unit_no"] = "1"

    with AuthenticatedTestClient(
        create_app(
            job_processor=processor,
            shared_prep_service=FakeSharedPrepService(),
        ),
    ) as client:
        response = client.post(
            "/api/jobs/batch",
            data={
                "params_json": json.dumps(params, ensure_ascii=False),
                "run_audit_check": "true",
            },
            files=[
                ("files[]", ("18185NE-JGS11.dwg", b"dwg-a", "application/acad")),
                ("files[]", ("20261RS-JGS65.dwg", b"dwg-b", "application/acad")),
            ],
        )

        assert response.status_code == 201
        payload = response.json()
        assert len(payload["jobs"]) == 2
        for item in payload["jobs"]:
            detail = _poll_job(client, item["job_id"], timeout_sec=8.0)
            assert detail["status"] == "succeeded"

    assert processor.max_seen >= 2


def test_multi_file_batch_keeps_backlog_visible_until_worker_capacity_frees(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import threading

    class SlowTrackingProcessor:
        def __init__(self) -> None:
            self.inner = FakeJobProcessor()
            self.current = 0
            self.max_seen = 0
            self.lock = threading.Lock()

        def __call__(self, job: Job) -> None:
            with self.lock:
                self.current += 1
                self.max_seen = max(self.max_seen, self.current)
            try:
                time.sleep(0.4)
                self.inner(job)
            finally:
                with self.lock:
                    self.current -= 1

    def _wait_for_runtime_health(
        client: TestClient,
        *,
        predicate,
        timeout_sec: float = 3.0,
    ) -> dict:
        deadline = time.time() + timeout_sec
        last_payload: dict | None = None
        while time.time() < deadline:
            response = client.get("/api/system/health")
            assert response.status_code == 200
            payload = response.json()
            last_payload = payload
            if predicate(payload):
                return payload
            time.sleep(0.05)
        raise AssertionError(f"runtime health did not satisfy predicate: {last_payload}")

    _configure_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FANBAN_UPLOAD_LIMITS__MAX_FILES", "20")
    monkeypatch.setenv("FANBAN_UPLOAD_LIMITS__MAX_TOTAL_MB", "50")
    monkeypatch.setenv("FANBAN_CAD_RUNTIME__SLOT_COUNT", "4")
    monkeypatch.setenv("FANBAN_CONCURRENCY__MAX_JOBS", "4")
    SpecLoader.clear_cache()
    reload_config()

    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.main import create_app

    processor = SlowTrackingProcessor()
    with AuthenticatedTestClient(
        create_app(
            job_processor=processor,
            font_preflight_service=cast(Any, FakeFontPreflightService()),
        )
    ) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(_deliverable_params(), ensure_ascii=False)},
            files=[
                ("files[]", (f"2026-A{index:02d}.dwg", f"dwg-{index}".encode(), "application/acad"))
                for index in range(1, 9)
            ],
        )

        assert response.status_code == 201
        payload = response.json()
        assert len(payload["jobs"]) == 8

        health = _wait_for_runtime_health(
            client,
            predicate=lambda item: item["active_jobs"] >= 4,
        )
        assert health["active_jobs"] == 4
        assert health["queue_depth"] == 4

        details = [client.get(f"/api/jobs/{job['job_id']}").json() for job in payload["jobs"]]
        assert sum(detail["slot_id"] is not None for detail in details) == 4
        assert sum(detail["slot_id"] is None for detail in details) == 4

        for job in payload["jobs"]:
            detail = _poll_job(client, job["job_id"], timeout_sec=8.0)
            assert detail["status"] == "succeeded"

    assert processor.max_seen == 4


def test_slot_bound_phase_allows_next_wave_to_start_before_docs_finish(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import threading

    class PhaseAwareProcessor:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.cad_current = 0
            self.max_cad_seen = 0
            self.cad_start: dict[str, float] = {}
            self.doc_end: dict[str, float] = {}

        def __call__(self, job: Job) -> None:
            self._run_cad(job)
            self._run_docs(job)

        def execute_slot_bound_phase(self, job: Job):
            self._run_cad(job)

            def finish() -> None:
                self._run_docs(job)

            return finish

        def _run_cad(self, job: Job) -> None:
            with self.lock:
                self.cad_current += 1
                self.max_cad_seen = max(self.max_cad_seen, self.cad_current)
            job.mark_running(stage="EXPORT_PDF_AND_DWG")
            self.cad_start[job.job_id] = time.monotonic()
            time.sleep(0.2)
            with self.lock:
                self.cad_current -= 1

        def _run_docs(self, job: Job) -> None:
            job.progress.stage = "GENERATE_DOCS"
            time.sleep(0.6)
            job.mark_succeeded()
            self.doc_end[job.job_id] = time.monotonic()

    _configure_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FANBAN_UPLOAD_LIMITS__MAX_FILES", "20")
    monkeypatch.setenv("FANBAN_UPLOAD_LIMITS__MAX_TOTAL_MB", "50")
    monkeypatch.setenv("FANBAN_CONCURRENCY__MAX_JOBS", "2")
    SpecLoader.clear_cache()
    reload_config()

    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.main import create_app

    processor = PhaseAwareProcessor()
    with AuthenticatedTestClient(create_app(job_processor=processor)) as client:
        response = client.post(
            "/api/jobs/batch",
            data={"params_json": json.dumps(_deliverable_params(), ensure_ascii=False)},
            files=[
                ("files[]", (f"2026-P{index:02d}.dwg", f"dwg-{index}".encode(), "application/acad"))
                for index in range(1, 5)
            ],
        )

        assert response.status_code == 201
        payload = response.json()
        assert len(payload["jobs"]) == 4

        for job in payload["jobs"]:
            detail = _poll_job(client, job["job_id"], timeout_sec=8.0)
            assert detail["status"] == "succeeded"

    assert processor.max_cad_seen == 2
    cad_starts = sorted(processor.cad_start.values())
    doc_ends = sorted(processor.doc_end.values())
    assert len(cad_starts) == 4
    assert len(doc_ends) == 4
    assert cad_starts[2] < doc_ends[0]


def test_grouped_batch_keeps_pending_groups_in_external_queue(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import threading

    class SlowTrackingProcessor:
        def __init__(self) -> None:
            self.inner = FakeJobProcessor()
            self.current = 0
            self.max_seen = 0
            self.lock = threading.Lock()

        def __call__(self, job: Job) -> None:
            with self.lock:
                self.current += 1
                self.max_seen = max(self.max_seen, self.current)
            try:
                time.sleep(0.4)
                self.inner(job)
            finally:
                with self.lock:
                    self.current -= 1

    def _wait_for_runtime_health(
        client: TestClient,
        *,
        predicate,
        timeout_sec: float = 3.0,
    ) -> dict:
        deadline = time.time() + timeout_sec
        last_payload: dict | None = None
        while time.time() < deadline:
            response = client.get("/api/system/health")
            assert response.status_code == 200
            payload = response.json()
            last_payload = payload
            if predicate(payload):
                return payload
            time.sleep(0.05)
        raise AssertionError(f"runtime health did not satisfy predicate: {last_payload}")

    _configure_api_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FANBAN_UPLOAD_LIMITS__MAX_FILES", "20")
    monkeypatch.setenv("FANBAN_UPLOAD_LIMITS__MAX_TOTAL_MB", "50")
    monkeypatch.setenv("FANBAN_CAD_RUNTIME__SLOT_COUNT", "4")
    monkeypatch.setenv("FANBAN_CONCURRENCY__MAX_JOBS", "4")
    SpecLoader.clear_cache()
    reload_config()

    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.main import create_app

    processor = SlowTrackingProcessor()
    with AuthenticatedTestClient(
        create_app(
            job_processor=processor,
            shared_prep_service=FakeSharedPrepService(),
            font_preflight_service=cast(Any, FakeFontPreflightService()),
        )
    ) as client:
        params = _deliverable_params()
        params["subitem_name_en"] = "Example Subitem"
        params["album_title_en"] = "Example Album"
        params["unit_no"] = "1"
        response = client.post(
            "/api/jobs/batch",
            data={
                "params_json": json.dumps(params, ensure_ascii=False),
                "run_audit_check": "true",
            },
            files=[
                ("files[]", (f"2026-G{index:02d}.dwg", f"dwg-{index}".encode(), "application/acad"))
                for index in range(1, 5)
            ],
        )

        assert response.status_code == 201
        payload = response.json()
        assert len(payload["jobs"]) == 4

        health = _wait_for_runtime_health(
            client,
            predicate=lambda item: item["active_groups"] >= 2 and item["active_jobs"] >= 4,
        )
        assert health["active_groups"] == 2
        assert health["active_jobs"] == 4
        assert health["queue_depth"] == 2

        details = [client.get(f"/api/jobs/{item['job_id']}").json() for item in payload["jobs"]]
        assert sum(detail["status"] == "running" for detail in details) == 2
        assert sum(detail["status"] == "queued" for detail in details) == 2

        for item in payload["jobs"]:
            detail = _poll_job(client, item["job_id"], timeout_sec=8.0)
            assert detail["status"] == "succeeded"

    assert processor.max_seen == 4


def test_startup_recovery_marks_stale_jobs_failed(monkeypatch, tmp_path: Path) -> None:
    _configure_api_env(monkeypatch, tmp_path)
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.main import create_app

    storage_root = tmp_path / "storage"
    stale_job = Job(
        job_id="job-stale-1",
        job_type=JobType.DELIVERABLE,
        project_no="2016",
        status=JobStatus.RUNNING,
        params=_deliverable_params(),
    )
    stale_job.progress.stage = "A4_MULTIPAGE_GROUPING"
    stale_job.progress.message = "完成阶段: A4_MULTIPAGE_GROUPING"
    job_dir = storage_root / "jobs" / stale_job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(
        stale_job.model_dump_json(indent=2),
        encoding="utf-8",
    )

    with AuthenticatedTestClient(create_app(job_processor=FakeJobProcessor())) as client:
        response = client.get(f"/api/jobs/{stale_job.job_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert "service_restarted_before_completion" in payload["errors"]
    assert payload["failure_reason"] == "服务重启/中断，任务未完成"
    assert payload["stage_context"] == "中断前最后完成阶段：A4 多页合并"

    list_response = client.get("/api/jobs")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    [summary] = list_payload["items"]
    assert summary["failure_reason"] == "服务重启/中断，任务未完成"
    assert summary["stage_context"] == "中断前最后完成阶段：A4 多页合并"
