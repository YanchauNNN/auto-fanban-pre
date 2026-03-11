from __future__ import annotations

from types import SimpleNamespace

from src.models import Job, JobType
from src.pipeline.executor import PipelineExecutor


def test_build_doc_context_prefers_job_project_no_without_duplicate_kwargs() -> None:
    executor = object.__new__(PipelineExecutor)
    executor.spec = SimpleNamespace(
        doc_generation={"rules": {}},
        get_mappings=lambda: {},
    )

    job = Job(
        job_id="job-doc-context-1",
        job_type=JobType.DELIVERABLE,
        project_no="2016",
        params={
            "project_no": "2016",
            "cover_variant": "通用",
            "classification": "非密",
            "upgrade_start_seq": "",
            "upgrade_end_seq": "",
        },
    )

    doc_ctx = PipelineExecutor._build_doc_context(
        executor,
        job,
        {"frames": [], "sheet_sets": []},
    )

    assert doc_ctx.params.project_no == "2016"
    assert doc_ctx.params.cover_variant == "通用"
    assert doc_ctx.params.upgrade_start_seq is None
    assert doc_ctx.params.upgrade_end_seq is None
