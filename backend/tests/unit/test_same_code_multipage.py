from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from src.cad.cad_dxf_executor import CADDXFExecutor
from src.cad.same_code_multipage import SameCodeMultipageGrouper
from src.cad.splitter import output_name_for_frame
from src.models import (
    BBox,
    DocContext,
    FrameMeta,
    FrameRuntime,
    GlobalDocParams,
    TitleblockFields,
)


def _make_frame(
    *,
    internal_code: str,
    external_code: str,
    page_index: int,
    page_total: int,
    paper_variant_id: str = "CNPE_A0",
) -> FrameMeta:
    runtime = FrameRuntime(
        frame_id=str(uuid4()),
        source_file=Path("demo.dxf"),
        outer_bbox=BBox(xmin=0, ymin=0, xmax=1189, ymax=841),
        paper_variant_id=paper_variant_id,
        sx=1.0,
        sy=1.0,
    )
    titleblock = TitleblockFields(
        internal_code=internal_code,
        external_code=external_code,
        revision="A",
        status="CFC",
        title_cn="测试图纸",
        title_en="Test Drawing",
        page_index=page_index,
        page_total=page_total,
    )
    return FrameMeta(runtime=runtime, titleblock=titleblock)


def test_group_frames_marks_non_a4_same_code_family() -> None:
    grouper = SameCodeMultipageGrouper()
    page1 = _make_frame(
        internal_code="20162RS-JGS03-005",
        external_code="JD2RSG11005B25C42SD",
        page_index=1,
        page_total=2,
    )
    page2 = _make_frame(
        internal_code="20162RS-JGS03-005",
        external_code="JD2RSG11005B25C42SD",
        page_index=2,
        page_total=2,
    )

    families = grouper.group_frames([page1, page2])

    assert len(families) == 1
    meta1 = page1.raw_extracts["same_code_multipage"]
    meta2 = page2.raw_extracts["same_code_multipage"]
    assert meta1["family_id"] == meta2["family_id"]
    assert meta1["page_index"] == 1
    assert meta2["page_index"] == 2
    assert meta1["page_total"] == 2


def test_group_frames_skips_a4_pages() -> None:
    grouper = SameCodeMultipageGrouper()
    page1 = _make_frame(
        internal_code="20162RS-JGS03-001",
        external_code="JD2RSG11001B25C42SD",
        page_index=1,
        page_total=4,
        paper_variant_id="CNPE_A4",
    )
    page2 = _make_frame(
        internal_code="20162RS-JGS03-001",
        external_code="JD2RSG11001B25C42SD",
        page_index=2,
        page_total=4,
        paper_variant_id="CNPE_A4",
    )

    families = grouper.group_frames([page1, page2])

    assert families == []
    assert "same_code_multipage" not in page1.raw_extracts


def test_doc_context_collapses_same_code_family_and_uses_family_page_total() -> None:
    grouper = SameCodeMultipageGrouper()
    page2 = _make_frame(
        internal_code="20162RS-JGS03-005",
        external_code="JD2RSG11005B25C42SD",
        page_index=2,
        page_total=2,
    )
    page1 = _make_frame(
        internal_code="20162RS-JGS03-005",
        external_code="JD2RSG11005B25C42SD",
        page_index=1,
        page_total=2,
    )
    grouper.group_frames([page2, page1])

    ctx = DocContext(
        params=GlobalDocParams(project_no="1907"),
        frames=[page2, page1],
    )

    frames = ctx.get_sorted_document_frames()
    assert len(frames) == 1
    assert frames[0].titleblock.page_index == 1
    assert ctx.get_page_total_for_frame(frames[0]) == 2


def test_cad_executor_allows_same_code_family_and_suffixes_names() -> None:
    grouper = SameCodeMultipageGrouper()
    page1 = _make_frame(
        internal_code="20162RS-JGS03-005",
        external_code="JD2RSG11005B25C42SD",
        page_index=1,
        page_total=2,
    )
    page2 = _make_frame(
        internal_code="20162RS-JGS03-005",
        external_code="JD2RSG11005B25C42SD",
        page_index=2,
        page_total=2,
    )
    grouper.group_frames([page1, page2])

    executor = object.__new__(CADDXFExecutor)
    executor.config = cast(Any, SimpleNamespace(
        multi_dwg_policy=SimpleNamespace(code_conflict="error"),
    ))

    executor._validate_duplicate_codes([page1, page2])

    assert CADDXFExecutor._name_for_frame(page1).endswith("-p1of2")
    assert CADDXFExecutor._name_for_frame(page2).endswith("-p2of2")
    assert output_name_for_frame(page1) != output_name_for_frame(page2)


def test_cad_executor_keeps_duplicate_code_error_for_unmarked_frames() -> None:
    page1 = _make_frame(
        internal_code="20162RS-JGS03-005",
        external_code="JD2RSG11005B25C42SD",
        page_index=1,
        page_total=2,
    )
    page2 = _make_frame(
        internal_code="20162RS-JGS03-005",
        external_code="JD2RSG11005B25C42SD",
        page_index=2,
        page_total=2,
    )

    executor = object.__new__(CADDXFExecutor)
    executor.config = cast(Any, SimpleNamespace(
        multi_dwg_policy=SimpleNamespace(code_conflict="error"),
    ))

    with pytest.raises(ValueError, match="检测到重复编码"):
        executor._validate_duplicate_codes([page1, page2])
