from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import uuid4

from openpyxl import Workbook, load_workbook

from src.doc_gen.catalog import CatalogGenerator
from src.interfaces import IPDFExporter
from src.models import (
    BBox,
    DerivedFields,
    DocContext,
    FrameMeta,
    FrameRuntime,
    GlobalDocParams,
    PageInfo,
    SheetSet,
    TitleblockFields,
)


class DummyPDFExporter:
    def export_xlsx_to_pdf(self, xlsx_path: Path, pdf_path: Path) -> None:
        pdf_path.write_bytes(b"%PDF-1.4\n%dummy\n")

    def count_pdf_pages(self, pdf_path: Path) -> int:
        return 2


def _make_frame(seq: int) -> FrameMeta:
    code = f"1234567-JG001-{seq:03d}"
    runtime = FrameRuntime(
        frame_id=str(uuid4()),
        source_file=Path("demo.dxf"),
        outer_bbox=BBox(xmin=0, ymin=0, xmax=100, ymax=100),
    )
    titleblock = TitleblockFields(
        internal_code=code,
        external_code=f"JD1NHT11{seq:03d}B25C42SD",
        title_cn=f"图纸{seq}",
        title_en=f"Drawing {seq}",
        revision="A",
        status="CFC",
        page_total=1,
    )
    return FrameMeta(runtime=runtime, titleblock=titleblock)


def _build_context(project_no: str = "2016") -> DocContext:
    params = GlobalDocParams(
        project_no=project_no,
        engineering_no="1234",
        subitem_no="JG001",
        album_title_cn="测试图册",
        album_title_en="Test Album",
        cover_revision="A",
        doc_status="CFC",
        upgrade_start_seq=2,
        upgrade_end_seq=3,
        upgrade_note_text="升版",
    )
    derived = DerivedFields(
        album_code="01",
        cover_internal_code="1234567-JG001-FM",
        catalog_internal_code="1234567-JG001-TM",
        cover_external_code="JD1NHT11F01B25C42SD",
        catalog_external_code="JD1NHT11T01B25C42SD",
        cover_title_cn="测试图册封面",
        catalog_title_cn="测试图册目录",
        cover_title_en="Test Album Cover",
        catalog_title_en="Test Album Contents",
        catalog_revision="A",
    )
    frames = [_make_frame(3), _make_frame(1), _make_frame(2)]
    return DocContext(params=params, derived=derived, frames=frames)


def _build_context_with_sheet_set_001() -> DocContext:
    ctx = _build_context()
    frame_001 = _make_frame(1)
    frame_001.titleblock.paper_size_text = "A4"
    frame_001.titleblock.page_total = 1
    master_page = PageInfo(
        page_index=1,
        outer_bbox=frame_001.runtime.outer_bbox,
        has_titleblock=True,
        frame_meta=frame_001,
    )
    ctx.frames = [_make_frame(3), _make_frame(2)]
    ctx.sheet_sets = [
        SheetSet(
            cluster_id="sheet-set-001",
            page_total=7,
            pages=[master_page],
            master_page=master_page,
        ),
    ]
    return ctx


def test_catalog_row_order_and_upgrade_note() -> None:
    gen = CatalogGenerator(pdf_exporter=cast(IPDFExporter, DummyPDFExporter()))
    ctx = _build_context()
    rows = gen._build_detail_rows(ctx)

    assert rows[0]["type"] == "cover"
    assert rows[1]["type"] == "catalog"
    assert [r["internal_code"] for r in rows[2:]] == [
        "1234567-JG001-001",
        "1234567-JG001-002",
        "1234567-JG001-003",
    ]
    assert rows[2]["upgrade_note"] == ""
    assert rows[3]["upgrade_note"] == "升版"
    assert rows[4]["upgrade_note"] == "升版"


def test_catalog_1818_title_in_same_cell_with_newline() -> None:
    gen = CatalogGenerator(pdf_exporter=cast(IPDFExporter, DummyPDFExporter()))
    ctx = _build_context(project_no="1818")
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    bindings = gen.spec.get_catalog_bindings()

    row_data = {
        "internal_code": "1234567-JG001-001",
        "external_code": "JD1NHT11001B25C42SD",
        "title_cn": "中文标题",
        "title_en": "English Title",
        "revision": "A",
        "status": "CFC",
        "page_total": 1,
        "upgrade_note": "",
    }
    gen._write_detail_row(ws, 9, row_data, bindings, ctx)

    assert ws["E9"].value == "中文标题\nEnglish Title"


def test_catalog_backfill_page_count(temp_dir: Path) -> None:
    gen = CatalogGenerator(pdf_exporter=cast(IPDFExporter, DummyPDFExporter()))
    ctx = _build_context()
    bindings = gen.spec.get_catalog_bindings()
    output_xlsx = temp_dir / "目录.xlsx"

    gen._write_catalog(
        template_path="documents_bin/目录模板文件.xlsx",
        output_path=output_xlsx,
        bindings=bindings,
        ctx=ctx,
    )
    gen._backfill_page_count(output_xlsx, 3, bindings)

    ws = load_workbook(output_xlsx).active
    assert ws is not None
    assert ws["H10"].value == 3


def test_catalog_writes_album_code_into_merged_title_cell_and_includes_sheet_set_001(
    temp_dir: Path,
) -> None:
    gen = CatalogGenerator(pdf_exporter=cast(IPDFExporter, DummyPDFExporter()))
    ctx = _build_context_with_sheet_set_001()
    bindings = gen.spec.get_catalog_bindings()
    output_xlsx = temp_dir / "目录.xlsx"

    gen._write_catalog(
        template_path="documents_bin/目录模板文件.xlsx",
        output_path=output_xlsx,
        bindings=bindings,
        ctx=ctx,
    )

    ws = load_workbook(output_xlsx).active
    assert ws is not None

    assert ws["D3"].value == "第01图册图纸(文件)目录"
    assert ws["B11"].value == "1234567-JG001-001"
    assert ws["D11"].value == "JD1NHT11001B25C42SD"
    assert ws["D1"].value == "测试图册"
    assert ws["H11"].value == 7


def test_catalog_writes_1818_album_titles_into_header_cells(temp_dir: Path) -> None:
    gen = CatalogGenerator(pdf_exporter=cast(IPDFExporter, DummyPDFExporter()))
    ctx = _build_context(project_no="1818")
    bindings = gen.spec.get_catalog_bindings()
    output_xlsx = temp_dir / "目录-1818.xlsx"

    gen._write_catalog(
        template_path="documents_bin/1818图册目录模板.xlsx",
        output_path=output_xlsx,
        bindings=bindings,
        ctx=ctx,
    )

    ws = load_workbook(output_xlsx).active
    assert ws is not None

    assert ws["D1"].value == "测试图册"
    assert ws["D2"].value == "Test Album"
    assert ws["D4"].value == "第01图册图纸(文件)目录"


def test_catalog_excel_com_paths_use_pdf_exporter_retry_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source_text = (repo_root / "backend" / "src" / "doc_gen" / "catalog.py").read_text(
        encoding="utf-8",
    )

    assert "PDFExporter._prepare_excel_path_for_com(" in source_text
    assert "PDFExporter._open_excel_workbook(" in source_text
    assert "PDFExporter._retry_excel_com_call(" in source_text

