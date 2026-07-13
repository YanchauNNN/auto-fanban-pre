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
    PageInfo,
    SheetSet,
    TitleblockFields,
)


def _make_frame(
    *,
    internal_code: str,
    external_code: str | None,
    page_index: int,
    page_total: int,
    paper_variant_id: str = "CNPE_A0",
    revision: str | None = "A",
    status: str | None = "CFC",
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
        revision=revision,
        status=status,
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


def test_group_frames_accepts_total_then_index_page_markers_for_same_code_family() -> None:
    grouper = SameCodeMultipageGrouper()
    page1 = _make_frame(
        internal_code="20162SD-JGS03-002",
        external_code="JD2SDH11002B25C42SD",
        page_index=2,
        page_total=1,
    )
    page2 = _make_frame(
        internal_code="20162SD-JGS03-002",
        external_code="JD2SDH11002B25C42SD",
        page_index=2,
        page_total=2,
    )

    families = grouper.group_frames([page1, page2])

    assert len(families) == 1
    meta1 = page1.raw_extracts["same_code_multipage"]
    meta2 = page2.raw_extracts["same_code_multipage"]
    assert meta1["page_index"] == 1
    assert meta2["page_index"] == 2
    assert meta1["page_total"] == 2
    assert meta2["page_total"] == 2
    assert output_name_for_frame(page1) == "JD2SDH11002B25C42SDA1@2CFC (20162SD-JGS03-002)"
    assert output_name_for_frame(page2) == "JD2SDH11002B25C42SDA2@2CFC (20162SD-JGS03-002)"


def test_group_frames_does_not_pair_001_marker_family() -> None:
    grouper = SameCodeMultipageGrouper()
    master = _make_frame(
        internal_code="18185NF-JGS19-001",
        external_code="PC5NFZ31001B25C42SD",
        page_index=1,
        page_total=1,
        paper_variant_id="CNPE_A0",
        revision=None,
        status="CFC",
    )
    marker_page = _make_frame(
        internal_code="18185NF-JGS19-001",
        external_code=None,
        page_index=2,
        page_total=2,
        paper_variant_id="CNPE_A0+1/2",
        revision="A",
        status=None,
    )
    marker_page.raw_extracts["A4_page_marker_meta"] = {
        "internal_code": "18185NF-JGS19-001",
        "revision": "A",
    }

    families = grouper.group_frames([master, marker_page])

    assert families == []
    assert "same_code_multipage" not in master.raw_extracts
    assert "same_code_multipage" not in marker_page.raw_extracts
    assert output_name_for_frame(master) == "PC5NFZ31001B25C42SD (18185NF-JGS19-001)"


def test_group_frames_leaves_001_external_sequence_correction_to_sheet_set_grouping() -> None:
    grouper = SameCodeMultipageGrouper()
    sibling = _make_frame(
        internal_code="18185NF-JGS19-002",
        external_code="PC5NFZ31002B25C42SD",
        page_index=1,
        page_total=1,
        paper_variant_id="CNPE_A0",
    )
    master = _make_frame(
        internal_code="18185NF-JGS19-001",
        external_code="PC5NFZ31002B25C42SD",
        page_index=1,
        page_total=1,
        paper_variant_id="CNPE_A0",
        revision=None,
        status="CFC",
    )
    marker_page = _make_frame(
        internal_code="18185NF-JGS19-001",
        external_code=None,
        page_index=2,
        page_total=2,
        paper_variant_id="CNPE_A0+1/2",
        revision="A",
        status=None,
    )
    marker_page.raw_extracts["A4_page_marker_meta"] = {
        "internal_code": "18185NF-JGS19-001",
        "revision": "A",
    }

    families = grouper.group_frames([sibling, master, marker_page])

    assert families == []
    assert sibling.titleblock.external_code == "PC5NFZ31002B25C42SD"
    assert master.titleblock.external_code == "PC5NFZ31002B25C42SD"
    assert not marker_page.titleblock.external_code
    assert output_name_for_frame(master) == "PC5NFZ31002B25C42SD (18185NF-JGS19-001)"


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

    assert CADDXFExecutor._name_for_frame(page1) == "JD2RSG11005B25C42SDA1@2CFC (20162RS-JGS03-005)"
    assert CADDXFExecutor._name_for_frame(page2) == "JD2RSG11005B25C42SDA2@2CFC (20162RS-JGS03-005)"
    assert output_name_for_frame(page1) == "JD2RSG11005B25C42SDA1@2CFC (20162RS-JGS03-005)"
    assert output_name_for_frame(page2) == "JD2RSG11005B25C42SDA2@2CFC (20162RS-JGS03-005)"


def test_cad_executor_sheet_set_entry_keeps_non_a4_page_media() -> None:
    master = _make_frame(
        internal_code="18185NF-JGS19-001",
        external_code="PC5NFZ31001B25C42SD",
        page_index=1,
        page_total=2,
        paper_variant_id="CNPE_A0",
    )
    marker_page = _make_frame(
        internal_code="18185NF-JGS19-001",
        external_code="PC5NFZ31001B25C42SD",
        page_index=2,
        page_total=2,
        paper_variant_id="CNPE_A0+1/2",
    )
    pages = [
        PageInfo(page_index=1, outer_bbox=master.runtime.outer_bbox, has_titleblock=True, frame_meta=master),
        PageInfo(page_index=2, outer_bbox=marker_page.runtime.outer_bbox, has_titleblock=False, frame_meta=marker_page),
    ]
    sheet_set = SheetSet(
        sheet_set_type="001_MARKER_FAMILY",
        paper="CNPE_A0",
        cluster_id="cluster-001",
        page_total=2,
        pages=pages,
        master_page=pages[0],
    )

    executor = object.__new__(CADDXFExecutor)
    executor.spec = cast(Any, SimpleNamespace(
        get_paper_variants=lambda: {
            "CNPE_A0": SimpleNamespace(W=1189.0, H=841.0),
            "CNPE_A0+1/2": SimpleNamespace(W=1486.0, H=841.0),
        },
    ))
    executor._paper_media_name_for_variant = lambda variant_id: f"media:{variant_id}"  # type: ignore[method-assign]

    entry = executor._build_sheet_set_entry(sheet_set)

    assert [page["paper_variant_id"] for page in entry["pages"]] == ["CNPE_A0", "CNPE_A0+1/2"]
    assert [page["paper_size_mm"] for page in entry["pages"]] == [[1189.0, 841.0], [1486.0, 841.0]]
    assert [page["paper_media_name"] for page in entry["pages"]] == [
        "media:CNPE_A0",
        "media:CNPE_A0+1/2",
    ]


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
