from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from openpyxl import load_workbook

from src.doc_gen.design import DesignFileGenerator
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


def _make_frame(seq: int, *, paper_size_text: str, discipline: str) -> FrameMeta:
    runtime = FrameRuntime(
        frame_id=str(uuid4()),
        source_file=Path("demo.dxf"),
        outer_bbox=BBox(xmin=0, ymin=0, xmax=100, ymax=100),
    )
    titleblock = TitleblockFields(
        internal_code=f"1234567-JG001-{seq:03d}",
        external_code=f"JD1NHT11{seq:03d}B25C42SD",
        title_cn=f"图纸{seq}",
        title_en=f"Drawing {seq}",
        revision="A",
        status="CFC",
        page_total=1,
        paper_size_text=paper_size_text,
        discipline=discipline,
    )
    return FrameMeta(runtime=runtime, titleblock=titleblock)


def _build_context() -> DocContext:
    params = GlobalDocParams(
        project_no="2016",
        engineering_no="1234",
        subitem_no="JG001",
        subitem_name="子项名称",
        discipline="结 构",
        album_title_cn="测试图册",
        cover_revision="A",
        doc_status="CFC",
        wbs_code="WBS-001",
        file_category="图纸",
        classification="非密",
        work_hours="88",
    )
    derived = DerivedFields(
        album_internal_code="1234567-JG001",
        cover_external_code="JD1NHT11F01B25C42SD",
        cover_internal_code="1234567-JG001-FM",
        cover_title_cn="测试图册封面",
        catalog_external_code="JD1NHT11T01B25C42SD",
        catalog_internal_code="1234567-JG001-TM",
        catalog_title_cn="测试图册目录",
        catalog_revision="A",
        catalog_page_total=2,
        design_phase="施工图设计",
    )
    frame_001 = _make_frame(1, paper_size_text="A4", discipline="结 构")
    master_page = PageInfo(
        page_index=1,
        outer_bbox=frame_001.runtime.outer_bbox,
        has_titleblock=True,
        frame_meta=frame_001,
    )
    return DocContext(
        params=params,
        derived=derived,
        frames=[_make_frame(2, paper_size_text="A 0", discipline="结 构")],
        sheet_sets=[
            SheetSet(
                cluster_id="sheet-set-001",
                page_total=1,
                pages=[master_page],
                master_page=master_page,
            ),
        ],
    )


def test_design_includes_001_and_maps_paper_size_and_discipline(temp_dir: Path) -> None:
    gen = DesignFileGenerator()
    ctx = _build_context()
    output_xlsx = temp_dir / "设计文件.xlsx"

    gen._write_design(
        template_path="documents_bin/设计文件模板.xlsx",
        output_path=output_xlsx,
        bindings=gen.spec.get_design_bindings(),
        ctx=ctx,
    )

    ws = load_workbook(output_xlsx).active

    assert ws["E4"].value == "1234567-JG001-001"
    assert ws["S4"].value == "A4图纸"
    assert ws["N4"].value == "结构"
    assert ws["E5"].value == "1234567-JG001-002"
    assert ws["S5"].value == "A0"
    assert ws["N5"].value == "结构"
