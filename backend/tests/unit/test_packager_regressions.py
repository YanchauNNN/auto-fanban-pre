from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.models import (
    BBox,
    FrameMeta,
    FrameRuntime,
    Job,
    JobType,
    PageInfo,
    SheetSet,
    TitleblockFields,
)
from src.pipeline.packager import Packager


def test_packager_flattens_zip_root_and_excludes_manifest(tmp_path: Path) -> None:
    job = Job(
        job_id="job-package-flat",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
        params={"project_no": "2026"},
    )

    drawings_dir = tmp_path / "output" / "drawings"
    drawings_dir.mkdir(parents=True)
    (drawings_dir / "drawing-001.dwg").write_text("dwg", encoding="utf-8")
    (drawings_dir / "drawing-001.pdf").write_text("pdf", encoding="utf-8")

    docs_dir = tmp_path / "output" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "封面.docx").write_text("docx", encoding="utf-8")
    (docs_dir / "设计文件.xlsx").write_text("xlsx", encoding="utf-8")

    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")

    zip_path = Packager().package(job)

    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(zf.namelist())

    assert names == [
        "drawing-001.dwg",
        "drawing-001.pdf",
        "封面.docx",
        "设计文件.xlsx",
    ]


def test_packager_rejects_duplicate_root_names(tmp_path: Path) -> None:
    job = Job(
        job_id="job-package-duplicate",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
        params={"project_no": "2026"},
    )

    drawings_dir = tmp_path / "output" / "drawings"
    drawings_dir.mkdir(parents=True)
    (drawings_dir / "目录.xlsx").write_text("drawing-xlsx", encoding="utf-8")

    docs_dir = tmp_path / "output" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "目录.xlsx").write_text("doc-xlsx", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate packaged filename"):
        Packager().package(job)


def test_generate_manifest_includes_deliverable_outputs_and_filtered_flags(tmp_path: Path) -> None:
    job = Job(
        job_id="job-package-manifest",
        job_type=JobType.DELIVERABLE,
        project_no="2026",
        work_dir=tmp_path,
        input_files=[tmp_path / "source.dwg"],
        params={"project_no": "2026"},
        flags=[
            "[DRAW001 (20261RS-JGS65-001)] PLOT_WINDOW_USED",
            "[DRAW001 (20261RS-JGS65-001)] PLOT_FROM_SOURCE_WINDOW",
            "[DRAW001 (20261RS-JGS65-001)] PAPER_SIZE_MISMATCH",
            "[DRAW001 (20261RS-JGS65-001)] PAPER_SIZE_AUTO_FIXED",
        ],
    )
    job.input_files[0].write_text("dwg", encoding="utf-8")

    frame = FrameMeta(
        runtime=FrameRuntime(
            frame_id="frame-001",
            source_file=tmp_path / "source.dxf",
            outer_bbox=BBox(xmin=0, ymin=0, xmax=10, ymax=10),
            paper_variant_id="CNPE_A1",
            pdf_path=tmp_path / "output" / "drawings" / "drawing-001.pdf",
            dwg_path=tmp_path / "output" / "drawings" / "drawing-001.dwg",
        ),
        titleblock=TitleblockFields(
            internal_code="20261RS-JGS65-001",
            external_code="DRAW001",
            revision="A",
            status="CFC",
        ),
    )
    frame.runtime.flags = [
        "PLOT_WINDOW_USED",
        "PLOT_FROM_SOURCE_WINDOW",
        "PAPER_SIZE_MISMATCH",
        "PAPER_SIZE_AUTO_FIXED",
    ]

    master_frame = FrameMeta(
        runtime=FrameRuntime(
            frame_id="frame-002",
            source_file=tmp_path / "source.dxf",
            outer_bbox=BBox(xmin=0, ymin=0, xmax=10, ymax=10),
            pdf_path=tmp_path / "output" / "drawings" / "drawing-002.pdf",
        ),
        titleblock=TitleblockFields(
            internal_code="20261RS-JGS65-002",
            external_code="DRAW002",
            revision="A",
            status="CFC",
        ),
    )
    master_page = PageInfo(
        page_index=1,
        outer_bbox=master_frame.runtime.outer_bbox,
        has_titleblock=True,
        frame_meta=master_frame,
    )
    sheet_set = SheetSet(
        cluster_id="sheet-set-002",
        page_total=4,
        generated_page_count=4,
        pages=[master_page],
        master_page=master_page,
        flags=["PLOT_WINDOW_USED"],
        dwg_path=tmp_path / "output" / "drawings" / "drawing-002.dwg",
        pdf_path=tmp_path / "output" / "drawings" / "drawing-002.pdf",
    )

    docs_dir = tmp_path / "output" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "cover.docx").write_text("doc", encoding="utf-8")
    (docs_dir / "design.xlsx").write_text("xlsx", encoding="utf-8")

    manifest_path = Packager().generate_manifest(
        job,
        context={"frames": [frame], "sheet_sets": [sheet_set]},
    )

    manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["flags"] == ["[DRAW001 (20261RS-JGS65-001)] PAPER_SIZE_AUTO_FIXED"]
    assert manifest["drawings"][0]["flags"] == ["PAPER_SIZE_AUTO_FIXED"]
    assert manifest["drawings"][1]["flags"] == []
    assert manifest["drawings"][1]["dwg_path"] == str(tmp_path / "output" / "drawings" / "drawing-002.dwg")
    assert manifest["deliverable_outputs"] == {
        "dwg_count": 2,
        "pdf_count": 2,
        "documents": [
            {"name": "cover.docx", "kind": "docx"},
            {"name": "design.xlsx", "kind": "xlsx"},
        ],
        "drawings": [
            {
                "name": "DRAW001ACFC (20261RS-JGS65-001)",
                "internal_code": "20261RS-JGS65-001",
                "dwg_name": "drawing-001.dwg",
                "pdf_name": "drawing-001.pdf",
                "page_total": 1,
            },
            {
                "name": "DRAW002ACFC (20261RS-JGS65-002)",
                "internal_code": "20261RS-JGS65-002",
                "dwg_name": "drawing-002.dwg",
                "pdf_name": "drawing-002.pdf",
                "page_total": 4,
            },
        ],
    }
