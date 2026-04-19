from __future__ import annotations

from pathlib import Path

import fitz
from pypdf import PdfReader

from src.audit_check.models import AuditFinding
from src.config import SpecLoader, reload_config
from src.models import BBox, FrameMeta, FrameRuntime, PageInfo, SheetSet, TitleblockFields
from src.pipeline.preview_pdf_service import PreviewPdfService


def _configure_env(monkeypatch, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    documents_dir = repo_root / "documents"
    spec_path = next(documents_dir.glob("*规范.yaml"))
    runtime_spec_path = next(documents_dir.glob("*规范_运行期.yaml"))
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(spec_path))
    monkeypatch.setenv("FANBAN_RUNTIME_SPEC_PATH", str(runtime_spec_path))
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    SpecLoader.clear_cache()
    reload_config()


def _write_pdf(path: Path, labels: list[str], *, width: float = 1000, height: float = 700) -> None:
    doc = fitz.open()
    for label in labels:
        page = doc.new_page(width=width, height=height)
        page.insert_text((72, 72), label, fontsize=18)
    doc.save(path)
    doc.close()


def _make_frame(*, pdf_path: Path, internal_code: str, seq: str) -> FrameMeta:
    return FrameMeta(
        runtime=FrameRuntime(
            frame_id=f"frame-{seq}",
            source_file=pdf_path.with_suffix(".dxf"),
            cad_source_file=pdf_path.with_suffix(".dwg"),
            outer_bbox=BBox(xmin=0, ymin=0, xmax=1000, ymax=700),
            outer_vertices=[],
            paper_variant_id="CNPE_A1",
            sx=1.0,
            sy=1.0,
            geom_scale_factor=50.0,
            roi_profile_id="BASE10",
            pdf_path=pdf_path,
        ),
        titleblock=TitleblockFields(
            internal_code=internal_code,
            external_code=f"EXTERNAL-{seq}",
            revision="A",
            status="CFC",
        ),
    )


def test_build_preview_merges_outputs_in_user_visible_order(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    frame_pdf = tmp_path / "frame.pdf"
    sheet_pdf = tmp_path / "sheet.pdf"
    _write_pdf(frame_pdf, ["frame-001"])
    _write_pdf(sheet_pdf, ["sheet-001", "sheet-002"])

    frame = _make_frame(pdf_path=frame_pdf, internal_code="20261RS-JGS65-001", seq="001")
    master = _make_frame(pdf_path=frame_pdf, internal_code="20261RS-JGS65-002", seq="002")
    sheet_set = SheetSet(
        cluster_id="cluster-1",
        page_total=2,
        generated_page_count=2,
        pdf_path=sheet_pdf,
        pages=[
            PageInfo(page_index=1, outer_bbox=BBox(xmin=0, ymin=0, xmax=500, ymax=700), frame_meta=master),
            PageInfo(page_index=2, outer_bbox=BBox(xmin=500, ymin=0, xmax=1000, ymax=700)),
        ],
        master_page=PageInfo(
            page_index=1,
            outer_bbox=BBox(xmin=0, ymin=0, xmax=500, ymax=700),
            frame_meta=master,
        ),
    )

    result = PreviewPdfService().build_preview(
        job_id="job-preview-plain",
        output_dir=tmp_path / "preview",
        frames=[frame],
        sheet_sets=[sheet_set],
        findings=[],
    )

    assert result.mode == "plain"
    assert result.pdf_path.exists()
    reader = PdfReader(str(result.pdf_path))
    assert len(reader.pages) == 3
    assert "frame-001" in (reader.pages[0].extract_text() or "")
    assert "sheet-001" in (reader.pages[1].extract_text() or "")
    assert "sheet-002" in (reader.pages[2].extract_text() or "")


def test_build_preview_draws_red_boxes_for_positioned_findings(monkeypatch, tmp_path: Path) -> None:
    _configure_env(monkeypatch, tmp_path)
    frame_pdf = tmp_path / "frame.pdf"
    _write_pdf(frame_pdf, ["frame-001"], width=1000, height=700)
    frame = _make_frame(pdf_path=frame_pdf, internal_code="20261RS-JGS65-001", seq="001")

    findings = [
        AuditFinding(
            raw_text="BAD",
            matched_text="BAD",
            matched_project_nos=["2026"],
            context_kind="foreign",
            confidence="high",
            entity_type="MText",
            field_context="titleblock_internal_code",
            internal_code="20261RS-JGS65-001",
            position_x=850,
            position_y=90,
        )
    ]

    result = PreviewPdfService().build_preview(
        job_id="job-preview-annotated",
        output_dir=tmp_path / "preview",
        frames=[frame],
        sheet_sets=[],
        findings=findings,
    )

    assert result.mode == "annotated"
    doc = fitz.open(result.pdf_path)
    try:
        drawings = doc[0].get_drawings()
        assert drawings, "expected at least one visible rectangle drawing on annotated preview"
    finally:
        doc.close()


def test_build_preview_skips_non_positioned_findings_without_forcing_annotation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)
    frame_pdf = tmp_path / "frame.pdf"
    _write_pdf(frame_pdf, ["frame-001"])
    frame = _make_frame(pdf_path=frame_pdf, internal_code="20261RS-JGS65-001", seq="001")

    findings = [
        AuditFinding(
            raw_text="BAD",
            matched_text="BAD",
            matched_project_nos=["2026"],
            context_kind="foreign",
            confidence="high",
            entity_type="MText",
            field_context="titleblock_internal_code",
            internal_code="20261RS-JGS65-001",
            position_x=None,
            position_y=None,
        )
    ]

    result = PreviewPdfService().build_preview(
        job_id="job-preview-no-box",
        output_dir=tmp_path / "preview",
        frames=[frame],
        sheet_sets=[],
        findings=findings,
    )

    assert result.mode == "plain"
    assert result.pdf_path.exists()
