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
from src.models import (
    BBox,
    DocContext,
    FrameMeta,
    FrameRuntime,
    GlobalDocParams,
    Job,
    JobType,
    PageInfo,
    SheetSet,
    TitleblockFields,
)
from src.pipeline.executor import PipelineExecutor
from src.pipeline.packager import Packager
from src.workload.calculator import WorkloadCalculator


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
            "is_upgrade": "",
            "upgrade_sheet_codes": "",
        },
    )

    doc_ctx = PipelineExecutor._build_doc_context(
        executor,
        job,
        {"frames": [], "sheet_sets": []},
    )

    assert doc_ctx.params.project_no == "2016"
    assert doc_ctx.params.cover_variant == "通用"
    assert doc_ctx.params.is_upgrade is False
    assert doc_ctx.params.upgrade_sheet_codes == ""


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


def test_build_doc_context_accepts_same_code_multipage_page1_as_primary_doc_frame(
    sample_frame: FrameMeta,
) -> None:
    executor = object.__new__(PipelineExecutor)
    executor.spec = cast(Any, SimpleNamespace(
        doc_generation={"rules": {}},
        get_mappings=lambda: {},
    ))

    page1 = deepcopy(sample_frame)
    page1.titleblock.internal_code = "18185BE-JGS01"
    page1.titleblock.external_code = "PC5BE011001B25C42SD"
    page1.titleblock.engineering_no = "1818"
    page1.titleblock.subitem_no = "BE"
    page1.titleblock.discipline = "结构"
    page1.titleblock.revision = "A"
    page1.titleblock.status = "CFC"
    page1.titleblock.page_index = 1
    page1.titleblock.page_total = 2
    page1.raw_extracts["same_code_multipage"] = {
        "family_id": "family-001",
        "page_index": 1,
        "page_total": 2,
    }

    page2 = deepcopy(sample_frame)
    page2.titleblock.internal_code = "18185BE-JGS01"
    page2.titleblock.external_code = "PC5BE011001B25C42SD"
    page2.titleblock.page_index = 2
    page2.titleblock.page_total = 2
    page2.raw_extracts["same_code_multipage"] = {
        "family_id": "family-001",
        "page_index": 2,
        "page_total": 2,
    }

    job = Job(
        job_id="job-doc-context-same-code-page1",
        job_type=JobType.DELIVERABLE,
        project_no="1818",
        params={
            "project_no": "1818",
            "cover_variant": "通用",
            "classification": "非密",
            "subitem_name": "应急指挥中心",
            "album_title_cn": "测试图册",
            "wbs_code": "WBS-001",
            "file_category": "图纸",
            "ied_status": "编制",
            "ied_doc_type": "图册",
        },
    )

    doc_ctx = PipelineExecutor._build_doc_context(
        executor,
        job,
        {"frames": [page1, page2], "sheet_sets": []},
    )

    assert doc_ctx.params.engineering_no == "1818"
    assert doc_ctx.params.subitem_no == "BE"
    assert doc_ctx.params.discipline == "结构"
    assert doc_ctx.params.revision == "A"
    assert doc_ctx.params.doc_status == "CFC"


def test_build_doc_context_falls_forward_to_first_readable_sequential_frame(
    sample_frame: FrameMeta,
) -> None:
    executor = object.__new__(PipelineExecutor)
    executor.spec = cast(Any, SimpleNamespace(
        doc_generation={"rules": {}},
        get_mappings=lambda: {},
    ))

    frame_002 = deepcopy(sample_frame)
    frame_002.runtime.frame_id = "frame-002"
    frame_002.titleblock.internal_code = "20261RS-JGS65-002"
    frame_002.titleblock.engineering_no = "2026"
    frame_002.titleblock.subitem_no = "RS"
    frame_002.titleblock.discipline = "结构"
    frame_002.titleblock.revision = "B"
    frame_002.titleblock.status = "CFC"

    frame_003 = deepcopy(sample_frame)
    frame_003.runtime.frame_id = "frame-003"
    frame_003.titleblock.internal_code = "20261RS-JGS65-003"
    frame_003.titleblock.engineering_no = "2026"
    frame_003.titleblock.subitem_no = "RS"
    frame_003.titleblock.discipline = "结构"
    frame_003.titleblock.revision = "C"
    frame_003.titleblock.status = "APVD"

    job = Job(
        job_id="job-doc-context-fall-forward",
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
            "ied_status": "编制",
            "ied_doc_type": "图册",
        },
    )

    doc_ctx = PipelineExecutor._build_doc_context(
        executor,
        job,
        {"frames": [frame_003, frame_002], "sheet_sets": []},
    )

    assert doc_ctx.params.engineering_no == "2026"
    assert doc_ctx.params.subitem_no == "RS"
    assert doc_ctx.params.discipline == "结构"
    assert doc_ctx.params.revision == "B"
    assert doc_ctx.params.doc_status == "CFC"


def test_build_doc_context_normalizes_discipline_from_1818_titleblock_hint(
    sample_frame: FrameMeta,
) -> None:
    executor = object.__new__(PipelineExecutor)
    executor.spec = cast(Any, SimpleNamespace(
        doc_generation={"rules": {}},
        get_mappings=lambda: {
            "discipline_to_code": {"结构": "JG"},
            "discipline_to_en": {"结构": "Structural Engineering"},
        },
    ))

    master_frame = deepcopy(sample_frame)
    master_frame.titleblock.internal_code = "18185NE-JGS11-001"
    master_frame.titleblock.discipline = "\uc368\ubbd0\nStructure"

    master_page = PageInfo(
        page_index=1,
        outer_bbox=master_frame.runtime.outer_bbox,
        has_titleblock=True,
        frame_meta=master_frame,
    )
    sheet_set = SheetSet(
        cluster_id="sheet-set-1818",
        page_total=1,
        pages=[master_page],
        master_page=master_page,
    )

    job = Job(
        job_id="job-doc-context-1818-discipline",
        job_type=JobType.DELIVERABLE,
        project_no="1818",
        params={
            "project_no": "1818",
            "cover_variant": "\u901a\u7528",
            "classification": "\u975e\u5bc6",
            "subitem_name": "\u53cd\u5e94\u5806\u5382\u623f",
            "album_title_cn": "\u6d4b\u8bd5\u56fe\u518c",
            "album_title_en": "Test Album",
            "wbs_code": "WBS-001",
            "file_category": "\u56fe\u7eb8",
            "ied_status": "\u53d1\u5e03",
            "ied_doc_type": "\u56fe\u518c",
        },
    )

    doc_ctx = PipelineExecutor._build_doc_context(
        executor,
        job,
        {"frames": [], "sheet_sets": [sheet_set]},
    )

    assert doc_ctx.params.discipline == "\u7ed3\u6784"


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


def test_stage_generate_docs_skips_ied_when_disabled(tmp_path: Path) -> None:
    executor = object.__new__(PipelineExecutor)
    executor._update_progress = MagicMock()
    executor.doc_param_validator = cast(Any, SimpleNamespace(validate=lambda ctx: []))
    executor.derivation = cast(Any, SimpleNamespace(compute=lambda ctx: ctx.derived))
    executor.cover_gen = MagicMock()
    executor.catalog_gen = MagicMock()
    executor.design_gen = MagicMock()
    executor.ied_gen = MagicMock()
    executor._build_doc_context = MagicMock(
        return_value=DocContext(
            params=GlobalDocParams(project_no="2026", include_ied_plan=False),
            frames=[],
            sheet_sets=[],
        )
    )

    job = Job(
        job_id="job-doc-no-ied",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
        params={"include_ied_plan": False},
    )

    PipelineExecutor._stage_generate_docs(executor, job, {"frames": [], "sheet_sets": []})

    executor.cover_gen.generate.assert_called_once()
    executor.catalog_gen.generate.assert_called_once()
    executor.design_gen.generate.assert_called_once()
    executor.ied_gen.generate.assert_not_called()
    assert job.artifacts.ied_xlsx is None


def test_stage_generate_docs_uses_catalog_page_count_when_catalog_pdf_export_fails(
    tmp_path: Path,
) -> None:
    executor = object.__new__(PipelineExecutor)
    executor._update_progress = MagicMock()
    executor.doc_param_validator = cast(Any, SimpleNamespace(validate=lambda ctx: []))
    executor.derivation = cast(Any, SimpleNamespace(compute=lambda ctx: ctx.derived))
    executor.cover_gen = MagicMock()
    executor.ied_gen = MagicMock()

    catalog_result = SimpleNamespace(
        xlsx_path=tmp_path / "output" / "docs" / "catalog.xlsx",
        pdf_path=tmp_path / "output" / "docs" / "catalog.pdf",
        page_count=3,
        pdf_export_error=RuntimeError("Workbook.ExportAsFixedFormat failed"),
    )
    catalog_result.xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_result.xlsx_path.write_text("xlsx", encoding="utf-8")
    generate_with_diagnostics = MagicMock(return_value=catalog_result)
    executor.catalog_gen = cast(Any, SimpleNamespace(
        generate_with_diagnostics=generate_with_diagnostics,
    ))

    captured: dict[str, Any] = {}

    def generate_design(ctx: DocContext, docs_dir: Path) -> Path:
        captured["catalog_page_total"] = ctx.derived.catalog_page_total
        output = docs_dir / "设计文件.xlsx"
        output.write_text("design", encoding="utf-8")
        return output

    executor.design_gen = cast(Any, SimpleNamespace(generate=generate_design))
    executor._build_doc_context = MagicMock(
        return_value=DocContext(
            params=GlobalDocParams(project_no="2026", include_ied_plan=False),
            frames=[],
            sheet_sets=[],
        )
    )

    job = Job(
        job_id="job-doc-catalog-pdf-warning",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
        params={"include_ied_plan": False},
    )

    PipelineExecutor._stage_generate_docs(executor, job, {"frames": [], "sheet_sets": []})

    generate_with_diagnostics.assert_called_once()
    assert captured["catalog_page_total"] == 3
    assert any(
        "目录PDF导出失败" in flag and "Workbook.ExportAsFixedFormat failed" in flag
        for flag in job.flags
    )
    assert job.progress.details["catalog_pdf_export_error"] == "Workbook.ExportAsFixedFormat failed"
    assert "RuntimeError: Workbook.ExportAsFixedFormat failed" in job.progress.details[
        "catalog_pdf_export_traceback"
    ]
    assert job.artifacts.docs_dir == tmp_path / "output" / "docs"


def test_catalog_pdf_export_failure_is_warning_not_fatal(tmp_path: Path) -> None:
    job = Job(
        job_id="job-doc-export-failure",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
    )
    job.add_flag("目录PDF导出失败: Excel导出PDF失败: 无法创建 Excel.Application")

    PipelineExecutor._raise_if_fatal_export_errors(job)


def test_catalog_pdf_export_failure_still_allows_package_zip(tmp_path: Path) -> None:
    output_docs = tmp_path / "output" / "docs"
    output_drawings = tmp_path / "output" / "drawings"
    output_docs.mkdir(parents=True)
    output_drawings.mkdir(parents=True)
    (output_docs / "catalog.xlsx").write_text("catalog", encoding="utf-8")
    (output_drawings / "drawing.pdf").write_bytes(b"%PDF-1.4\n")

    executor = object.__new__(PipelineExecutor)
    executor._update_progress = MagicMock()
    executor._require_work_dir = MagicMock(return_value=tmp_path)
    executor.packager = Packager()
    executor.workload_calculator = WorkloadCalculator()
    executor._generate_preview_pdf = MagicMock()

    job = Job(
        job_id="job-doc-export-package",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
    )
    job.add_flag("目录PDF导出失败: Excel导出PDF失败: 无法创建 Excel.Application")

    PipelineExecutor._stage_package(executor, job, {"frames": [], "sheet_sets": []})
    PipelineExecutor._raise_if_fatal_export_errors(job)

    assert job.artifacts.package_zip is not None
    assert job.artifacts.package_zip.exists()
    with zipfile.ZipFile(job.artifacts.package_zip, "r") as zf:
        assert "catalog.xlsx" in zf.namelist()
        assert "drawing.pdf" in zf.namelist()


def test_stage_split_uses_steel_liner_plot_style_when_two_titles_match(
    tmp_path: Path,
    sample_frame: FrameMeta,
) -> None:
    executor = object.__new__(PipelineExecutor)
    executor._require_work_dir = MagicMock(return_value=tmp_path)
    executor._update_progress = MagicMock()

    source_dxf = tmp_path / "source.dxf"
    frame_001 = deepcopy(sample_frame)
    frame_001.runtime.source_file = source_dxf
    frame_001.titleblock.internal_code = "20161RC-JGS07-001"
    frame_001.titleblock.title_cn = "钢衬里布置图"
    frame_002 = deepcopy(sample_frame)
    frame_002.runtime.source_file = source_dxf
    frame_002.titleblock.internal_code = "20161RC-JGS07-002"
    frame_002.titleblock.title_cn = "钢衬里详图"

    execute_source_dxf = MagicMock(return_value={"frames": [], "sheet_sets": [], "errors": []})
    executor.cad_dxf_executor = cast(Any, SimpleNamespace(
        group_by_source_dxf=lambda frames, sheet_sets: {
            source_dxf: {"frames": frames, "sheet_sets": sheet_sets},
        },
        execute_source_dxf=execute_source_dxf,
    ))
    job = Job(
        job_id="job-steel-liner-split",
        job_type=JobType.DELIVERABLE,
        project_no="2016",
        work_dir=tmp_path,
        params={},
    )

    PipelineExecutor._stage_split_cad_dxf(
        executor,
        job,
        {"frames": [frame_001, frame_002], "sheet_sets": []},
    )

    execute_source_dxf.assert_called_once()
    assert execute_source_dxf.call_args.kwargs["plot_style_key"] == "steel_liner"


def test_stage_package_writes_manifest_before_zip_and_records_artifacts(tmp_path: Path) -> None:
    executor = object.__new__(PipelineExecutor)
    executor._update_progress = MagicMock()
    executor.packager = Packager()
    executor.workload_calculator = WorkloadCalculator()

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

    stage_timings = [
        {
            "stage": "GENERATE_DOCS",
            "started_at": "2026-03-25T10:00:00",
            "finished_at": "2026-03-25T10:00:01",
            "duration_ms": 1000.0,
            "status": "succeeded",
        }
    ]

    PipelineExecutor._stage_package(
        executor,
        job,
        {"frames": [], "sheet_sets": [], "stage_timings": stage_timings},
    )

    assert job.artifacts.package_zip == tmp_path / "package.zip"
    assert job.artifacts.drawings_dir == drawings_dir
    assert job.artifacts.docs_dir == docs_dir
    assert job.artifacts.package_zip is not None
    assert job.artifacts.package_zip.exists()

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["package_zip"] == str(tmp_path / "package.zip")
    assert manifest["artifacts"]["drawings_dir"] == str(drawings_dir)
    assert manifest["artifacts"]["docs_dir"] == str(docs_dir)
    assert manifest["stage_timings"] == stage_timings

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
    assert "SCALE_FIX_SKIPPED" in frame.runtime.flags
    report_path = tmp_path / "work" / "titleblock_consistency" / "consistency_report.json"
    assert report_path.exists()


def test_stage_fix_titleblock_consistency_marks_out_of_range_scale_without_autofix(
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
    frame.runtime.geom_scale_factor = 48.81569160211338
    frame.runtime.sx = 48.81569160211338
    frame.runtime.sy = 48.81569160211338
    frame.titleblock.paper_size_text = "A1"
    frame.titleblock.scale_text = "1:50"
    frame.titleblock.scale_denominator = 50
    frame.raw_extracts = {
        "图幅": [
            {"text": "A", "x": 10.0, "y": 0.0},
            {"text": "1", "x": 20.0, "y": 0.0},
        ],
        "比例": [
            {"text": "1", "x": 10.0, "y": 0.0},
            {"text": ":", "x": 15.0, "y": 0.0},
            {"text": "50", "x": 20.0, "y": 0.0},
        ],
    }

    executor.titleblock_consistency = TitleblockConsistencyService()
    executor.titleblock_consistency_bridge = cast(
        Any,
        SimpleNamespace(
            apply=MagicMock(),
        ),
    )

    job = Job(
        job_id="job-consistency-scale-out-of-range",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
    )

    PipelineExecutor._stage_fix_titleblock_consistency(executor, job, {"frames": [frame], "sheet_sets": []})

    assert frame.titleblock.scale_text == "1:50"
    assert frame.titleblock.scale_denominator == 50
    assert "SCALE_MISMATCH" in frame.runtime.flags
    assert "SCALE_FIX_SKIPPED" in frame.runtime.flags
    assert "SCALE_CANDIDATE_OUT_OF_RANGE" in frame.runtime.flags
    executor.titleblock_consistency_bridge.apply.assert_not_called()


def test_stage_fix_titleblock_consistency_autofixes_a4_marker_revision(
    tmp_path: Path,
) -> None:
    executor = object.__new__(PipelineExecutor)
    executor.config = cast(
        Any,
        SimpleNamespace(
            deliverable_consistency_fix=SimpleNamespace(enabled=True),
        ),
    )
    executor._update_progress = MagicMock()
    executor.titleblock_consistency = TitleblockConsistencyService()

    source_dwg = tmp_path / "source.dwg"
    source_dwg.write_text("dwg", encoding="utf-8")
    corrected = tmp_path / "work" / "titleblock_consistency" / "source.consistency.dwg"

    master = FrameMeta(
        runtime=FrameRuntime(
            frame_id="master-a4",
            source_file=source_dwg,
            cad_source_file=source_dwg,
            outer_bbox=BBox(xmin=0, ymin=0, xmax=100, ymax=100),
            paper_variant_id="CNPE_A4",
        ),
        titleblock=TitleblockFields(
            internal_code="18185NE-JGS11-001",
            revision="A",
            page_index=1,
            page_total=2,
        ),
    )
    slave = FrameMeta(
        runtime=FrameRuntime(
            frame_id="slave-a4",
            source_file=source_dwg,
            cad_source_file=source_dwg,
            outer_bbox=BBox(xmin=0, ymin=100, xmax=100, ymax=200),
            paper_variant_id="CNPE_A4",
        ),
        titleblock=TitleblockFields(page_index=2, page_total=2),
        raw_extracts={
            "A4_page_marker": [
                {
                    "text": "18185NE-JGS11-001(B)",
                    "x": 95.0,
                    "y": 190.0,
                    "bbox": {"xmin": 80.0, "ymin": 185.0, "xmax": 99.0, "ymax": 195.0},
                }
            ],
            "A4_page_marker_meta": {"internal_code": "18185NE-JGS11-001", "revision": "B"},
        },
    )
    master_page = PageInfo(
        page_index=1,
        outer_bbox=master.runtime.outer_bbox,
        has_titleblock=True,
        frame_meta=master,
    )
    slave_page = PageInfo(
        page_index=2,
        outer_bbox=slave.runtime.outer_bbox,
        has_titleblock=False,
        frame_meta=slave,
    )
    sheet_set = SheetSet(
        cluster_id="sheet-set-a4-marker-fix",
        page_total=2,
        pages=[master_page, slave_page],
        master_page=master_page,
    )

    captured_plans: list[Any] = []

    def _apply(**kwargs: Any) -> dict[str, Any]:
        captured_plans.extend(kwargs["plans"])
        corrected.parent.mkdir(parents=True, exist_ok=True)
        corrected.write_text("fixed", encoding="utf-8")
        return {"errors": []}

    executor.titleblock_consistency_bridge = cast(Any, SimpleNamespace(apply=_apply))

    job = Job(
        job_id="job-consistency-fix-a4-marker",
        job_type=JobType.DELIVERABLE,
        project_no="1818",
        work_dir=tmp_path,
    )

    PipelineExecutor._stage_fix_titleblock_consistency(
        executor,
        job,
        {"frames": [], "sheet_sets": [sheet_set]},
    )

    assert [plan.field_name for plan in captured_plans] == ["a4_marker_revision"]
    assert slave.runtime.cad_source_file == corrected
    assert "A4_MARKER_REVISION_MISMATCH" in slave.runtime.flags
    assert "A4_MARKER_REVISION_AUTO_FIXED" in slave.runtime.flags
    assert slave.raw_extracts["A4_page_marker_meta"]["revision"] == "A"
