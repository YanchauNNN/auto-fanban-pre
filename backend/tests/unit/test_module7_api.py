from __future__ import annotations

import json
import sys
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from src.config import SpecLoader, reload_config
from src.models import Job, JobStatus, JobType


class FakeJobProcessor:
    def __call__(self, job: Job) -> None:
        job.work_dir = Path(job.work_dir or "")
        if job.job_type == JobType.AUDIT_REPLACE:
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
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            job.artifacts.reports_dir = reports_dir
            job.artifacts.report_xlsx = report_xlsx
            job.artifacts.report_json = report_json
            job.progress.details["findings_count"] = 2
            job.progress.details["affected_drawings_count"] = 1
            job.progress.details["top_wrong_texts"] = ["2016", "JD"]
            job.progress.details["top_internal_codes"] = ["1234567-JGS01-001"]
            job.mark_succeeded()
            return

        job.mark_running(stage="GENERATE_DOCS")
        job.progress.message = "processing"

        package_zip = job.work_dir / "package.zip"
        ied_xlsx = job.work_dir / "ied" / "IED计划.xlsx"
        ied_xlsx.parent.mkdir(parents=True, exist_ok=True)
        package_zip.write_bytes(b"PK\x03\x04test")
        ied_xlsx.write_bytes(b"ied")

        job.artifacts.package_zip = package_zip
        job.artifacts.ied_xlsx = ied_xlsx
        job.artifacts.drawings_dir = job.work_dir / "output" / "drawings"
        job.artifacts.docs_dir = job.work_dir / "output" / "docs"
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


def _create_client(monkeypatch, tmp_path: Path, processor=None) -> TestClient:
    _configure_api_env(monkeypatch, tmp_path)
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from API.app.main import create_app

    app = create_app(job_processor=processor or FakeJobProcessor())
    return TestClient(app)


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

    deliverable = DeliverableExecutor()
    audit = AuditExecutor()
    monkeypatch.setattr("API.app.runtime.PipelineExecutor", lambda: deliverable)
    monkeypatch.setattr("API.app.runtime.AuditCheckExecutor", lambda: audit)

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

    assert deliverable.calls == ["job-deliverable"]
    assert audit.calls == ["job-audit"]
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

    project_section = next(
        section for section in payload["deliverable"]["sections"] if section["id"] == "project"
    )
    project_no = next(field for field in project_section["fields"] if field["key"] == "project_no")
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

    assert "2016" in project_no["options"]
    assert project_no["required"] is False
    assert "DWG" in project_no["desc"]
    assert "2016" in project_no["desc"]
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


def test_create_audit_check_processes_job_and_exposes_report_download(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/jobs/audit-replace",
            data={
                "mode": "check",
                "params_json": json.dumps({"project_no": "2016"}, ensure_ascii=False),
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
        assert detail["findings_count"] == 2
        assert detail["affected_drawings_count"] == 1
        assert detail["top_wrong_texts"] == ["2016", "JD"]
        assert detail["top_internal_codes"] == ["1234567-JGS01-001"]

        report_download = client.get(f"/api/jobs/{job_id}/download/report")
        assert report_download.status_code == 200
        workbook = load_workbook(filename=BytesIO(report_download.content))
        assert workbook.sheetnames[0] == "Summary"


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
                    {"project_no": "2016", "batch_id": "batch-shared-1"},
                    ensure_ascii=False,
                ),
            },
            files=[("files[]", ("2016-A01.dwg", b"dwg", "application/acad"))],
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["batch_id"] == "batch-shared-1"
    assert payload["jobs"][0]["batch_id"] == "batch-shared-1"


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
    job_dir = storage_root / "jobs" / stale_job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "job.json").write_text(
        stale_job.model_dump_json(indent=2),
        encoding="utf-8",
    )

    with TestClient(create_app(job_processor=FakeJobProcessor())) as client:
        response = client.get(f"/api/jobs/{stale_job.job_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert "service_restarted_before_completion" in payload["errors"]
