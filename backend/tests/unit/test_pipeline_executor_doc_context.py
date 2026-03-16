from __future__ import annotations

import json
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from src.cad.titleblock_consistency import TitleblockConsistencyService
from src.models import DocContext, FrameMeta, GlobalDocParams, Job, JobType, PageInfo, SheetSet
from src.pipeline.executor import PipelineExecutor
from src.pipeline.packager import Packager


def test_build_doc_context_prefers_job_project_no_without_duplicate_kwargs() -> None:
    executor = object.__new__(PipelineExecutor)
    executor.spec = cast(Any, SimpleNamespace(
        doc_generation={"rules": {}},
        get_mappings=lambda: {},
    ))

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


def test_build_doc_context_inherits_required_titleblock_fields_from_sheet_set_master(
    sample_frame: FrameMeta,
) -> None:
    executor = object.__new__(PipelineExecutor)
    executor.spec = cast(Any, SimpleNamespace(
        doc_generation={"rules": {}},
        get_mappings=lambda: {},
    ))

    master_frame = deepcopy(sample_frame)
    master_frame.titleblock.internal_code = "20261RS-JGS65-001"
    master_frame.titleblock.engineering_no = "2026"
    master_frame.titleblock.subitem_no = "JGS65"
    master_frame.titleblock.discipline = "结构"
    master_frame.titleblock.revision = "A"
    master_frame.titleblock.status = "CFC"

    master_page = PageInfo(
        page_index=1,
        outer_bbox=master_frame.runtime.outer_bbox,
        has_titleblock=True,
        frame_meta=master_frame,
    )
    sheet_set = SheetSet(
        cluster_id="sheet-set-001",
        page_total=1,
        pages=[master_page],
        master_page=master_page,
    )

    job = Job(
        job_id="job-doc-context-sheet-set",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        params={
            "project_no": "2026",
            "cover_variant": "通用",
            "classification": "非密",
            "subitem_name": "反应堆厂房",
            "album_title_cn": "测试图册",
            "wbs_code": "WBS-001",
            "file_category": "图纸",
            "ied_status": "发布",
            "ied_doc_type": "图册",
        },
    )

    doc_ctx = PipelineExecutor._build_doc_context(
        executor,
        job,
        {"frames": [], "sheet_sets": [sheet_set]},
    )

    assert doc_ctx.params.engineering_no == "2026"
    assert doc_ctx.params.subitem_no == "JGS65"
    assert doc_ctx.params.discipline == "结构"
    assert doc_ctx.params.revision == "A"
    assert doc_ctx.params.doc_status == "CFC"


def test_doc_context_get_frame_001_falls_back_to_sheet_set_master(sample_frame: FrameMeta) -> None:
    master_frame = deepcopy(sample_frame)
    master_frame.titleblock.internal_code = "20261RS-JGS65-001"

    master_page = PageInfo(
        page_index=1,
        outer_bbox=master_frame.runtime.outer_bbox,
        has_titleblock=True,
        frame_meta=master_frame,
    )
    sheet_set = SheetSet(
        cluster_id="sheet-set-001",
        page_total=1,
        pages=[master_page],
        master_page=master_page,
    )

    ctx = DocContext(
        params=GlobalDocParams(project_no="2026"),
        frames=[],
        sheet_sets=[sheet_set],
    )

    frame_001 = ctx.get_frame_001()

    assert frame_001 is not None
    assert frame_001.titleblock.internal_code == "20261RS-JGS65-001"


def test_stage_generate_docs_raises_on_doc_param_validation_errors(tmp_path: Path) -> None:
    executor = object.__new__(PipelineExecutor)
    executor._update_progress = MagicMock()
    executor.doc_param_validator = cast(Any, SimpleNamespace(
        validate=lambda ctx: ["文档参数缺失: engineering_no", "文档参数缺失: revision"],
    ))
    executor._build_doc_context = MagicMock(return_value=SimpleNamespace())

    job = Job(
        job_id="job-doc-validation-fail",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
    )

    with pytest.raises(RuntimeError, match="文档参数校验失败"):
        PipelineExecutor._stage_generate_docs(executor, job, {"frames": [], "sheet_sets": []})

    assert "文档参数缺失: engineering_no" in job.errors
    assert "文档参数缺失: revision" in job.errors
    assert "文档参数校验失败" in job.flags
    assert job.artifacts.docs_dir is None
    assert job.artifacts.ied_xlsx is None


def test_stage_package_writes_manifest_before_zip_and_records_artifacts(tmp_path: Path) -> None:
    executor = object.__new__(PipelineExecutor)
    executor._update_progress = MagicMock()
    executor.packager = Packager()

    job = Job(
        job_id="job-package-stage",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
        input_files=[tmp_path / "demo.dwg"],
        params={"project_no": "2026"},
    )
    job.input_files[0].write_text("demo", encoding="utf-8")

    drawings_dir = tmp_path / "output" / "drawings"
    drawings_dir.mkdir(parents=True)
    (drawings_dir / "demo.pdf").write_text("pdf", encoding="utf-8")

    docs_dir = tmp_path / "output" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "cover.docx").write_text("doc", encoding="utf-8")

    PipelineExecutor._stage_package(executor, job, {"frames": [], "sheet_sets": []})

    assert job.artifacts.package_zip == tmp_path / "package.zip"
    assert job.artifacts.drawings_dir == drawings_dir
    assert job.artifacts.docs_dir == docs_dir
    assert job.artifacts.package_zip is not None
    assert job.artifacts.package_zip.exists()

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["package_zip"] == str(tmp_path / "package.zip")
    assert manifest["artifacts"]["drawings_dir"] == str(drawings_dir)
    assert manifest["artifacts"]["docs_dir"] == str(docs_dir)

    assert job.artifacts.package_zip is not None
    with zipfile.ZipFile(job.artifacts.package_zip) as zf:
        names = set(zf.namelist())

    assert "manifest.json" not in names
    assert "demo.pdf" in names
    assert "cover.docx" in names


def test_stage_fix_titleblock_consistency_updates_working_source_and_flags(
    tmp_path: Path,
    sample_frame: FrameMeta,
) -> None:
    executor = object.__new__(PipelineExecutor)
    executor.config = cast(
        Any,
        SimpleNamespace(
            deliverable_consistency_fix=SimpleNamespace(enabled=True),
        ),
    )
    executor._update_progress = MagicMock()

    frame = FrameMeta.model_validate_json(sample_frame.model_dump_json())
    frame.runtime.source_file = tmp_path / "source.dwg"
    frame.runtime.source_file.write_text("dwg", encoding="utf-8")
    frame.runtime.cad_source_file = frame.runtime.source_file
    frame.runtime.paper_variant_id = "CNPE_A1"
    frame.runtime.geom_scale_factor = 50
    frame.titleblock.paper_size_text = "A0"
    frame.titleblock.scale_text = "1:100"
    frame.raw_extracts = {
        "图幅": [
            {"text": "A", "x": 10.0, "y": 0.0},
            {"text": "0", "x": 20.0, "y": 0.0},
        ],
        "比例": [
            {"text": "1", "x": 10.0, "y": 0.0},
            {"text": ":", "x": 15.0, "y": 0.0},
            {"text": "100", "x": 20.0, "y": 0.0},
        ],
    }

    corrected = tmp_path / "work" / "titleblock_consistency" / "source.consistency.dwg"

    executor.titleblock_consistency = TitleblockConsistencyService()
    executor.titleblock_consistency_bridge = cast(
        Any,
        SimpleNamespace(
            apply=lambda **kwargs: (corrected.parent.mkdir(parents=True, exist_ok=True), corrected.write_text("fixed", encoding="utf-8"), {"errors": []})[2],
        ),
    )

    job = Job(
        job_id="job-consistency-fix",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
    )

    PipelineExecutor._stage_fix_titleblock_consistency(executor, job, {"frames": [frame], "sheet_sets": []})

    assert frame.runtime.cad_source_file == corrected
    assert frame.titleblock.paper_size_text == "A1"
    assert frame.titleblock.scale_text == "1:50"
    assert "PAPER_SIZE_MISMATCH" in frame.runtime.flags
    assert "PAPER_SIZE_AUTO_FIXED" in frame.runtime.flags
    assert "SCALE_MISMATCH" in frame.runtime.flags
    assert "SCALE_AUTO_FIXED" in frame.runtime.flags
    report_path = tmp_path / "work" / "titleblock_consistency" / "consistency_report.json"
    assert report_path.exists()
