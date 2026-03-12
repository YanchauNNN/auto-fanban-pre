"""
图签提取器单元测试（模块3）
"""

from __future__ import annotations

from pathlib import Path

import ezdxf

from src.cad.titleblock_extractor import TextItem, TitleblockExtractor
from src.models import BBox, FrameMeta, FrameRuntime


def _item(text: str, x: float = 0.0, y: float = 0.0) -> TextItem:
    return TextItem(
        x=x,
        y=y,
        text=text,
        bbox=None,
        text_height=2.5,
        source="test",
    )


def test_roi_restore_formula() -> None:
    extractor = TitleblockExtractor()
    outer = BBox(xmin=0.0, ymin=0.0, xmax=200.0, ymax=100.0)
    roi = extractor._restore_roi(outer, [10.0, 20.0, 30.0, 40.0], sx=2.0, sy=3.0)
    assert roi.xmin == 160.0
    assert roi.xmax == 180.0
    assert roi.ymin == 90.0
    assert roi.ymax == 120.0


def test_parse_internal_code_full_and_short() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["internal_code"].parse

    code, _ = extractor._parse_internal_code([_item("ABC1234-ABCDE-001")], parse_cfg)
    assert code == "ABC1234-ABCDE-001"

    code, _ = extractor._parse_internal_code([_item("ABC1234-ABCDE")], parse_cfg)
    assert code == "ABC1234-ABCDE"


def test_parse_internal_code_recombines_fragmented_lines() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["internal_code"].parse

    code, album = extractor._parse_internal_code(
        [
            _item("20261NH-JGS51-", x=10.0, y=10.0),
            _item("008", x=80.0, y=7.0),
        ],
        parse_cfg,
    )

    assert code == "20261NH-JGS51-008"
    assert album == "51"


def test_parse_external_code_fixed19() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["external_code"].parse
    items = [_item("DOC.NO JD1NHT11T01B25C42SD")]
    code = extractor._parse_external_code(items, parse_cfg)
    assert code == "JD1NHT11T01B25C42SD"


def test_parse_title_bilingual() -> None:
    extractor = TitleblockExtractor()
    items = [
        _item("中文标题", x=10.0, y=100.0),
        _item("English Title", x=10.0, y=90.0),
    ]
    title_cn, title_en = extractor._parse_title_bilingual(items)
    assert title_cn == "中文标题"
    assert title_en == "English Title"


def test_parse_page_info_with_x() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["page_info"].parse
    items = [_item("共2张 第X张")]
    total, idx = extractor._parse_page_info(items, parse_cfg)
    assert total == 2
    assert idx == 1


def test_pick_top_by_y() -> None:
    extractor = TitleblockExtractor()
    items = [_item("A", y=10.0), _item("B", y=5.0)]
    assert extractor._pick_top_by_y(items) == "A"


def test_scale_mismatch_flag() -> None:
    extractor = TitleblockExtractor()
    runtime = FrameRuntime(
        frame_id="f1",
        source_file=Path("sample.dxf"),
        outer_bbox=BBox(xmin=0.0, ymin=0.0, xmax=100.0, ymax=50.0),
        geom_scale_factor=1.0,
    )
    frame = FrameMeta(runtime=runtime)
    frame.titleblock.scale_denominator = 2.0

    extractor._check_scale_mismatch(frame)

    assert frame.runtime.scale_mismatch is True
    assert extractor.scale_mismatch_flag in frame.runtime.flags


def test_extract_fields_reuses_loaded_text_items_for_same_dxf(
    tmp_path, monkeypatch
) -> None:
    dxf_path = tmp_path / "sample.dxf"
    doc = ezdxf.new("R2018")
    doc.modelspace().add_text("ANCHOR", dxfattribs={"insert": (10, 10), "height": 2.5})
    doc.saveas(dxf_path)

    extractor = TitleblockExtractor()
    extractor.anchor_texts = []

    original_readfile = ezdxf.readfile
    calls = {"count": 0}

    def counting_readfile(path):
        calls["count"] += 1
        return original_readfile(path)

    monkeypatch.setattr("src.cad.titleblock_extractor.ezdxf.readfile", counting_readfile)

    frame1 = FrameMeta(
        runtime=FrameRuntime(
            frame_id="f1",
            source_file=dxf_path,
            outer_bbox=BBox(xmin=0.0, ymin=0.0, xmax=200.0, ymax=100.0),
            roi_profile_id="BASE10",
        )
    )
    frame2 = FrameMeta(
        runtime=FrameRuntime(
            frame_id="f2",
            source_file=dxf_path,
            outer_bbox=BBox(xmin=0.0, ymin=0.0, xmax=200.0, ymax=100.0),
            roi_profile_id="BASE10",
        )
    )

    extractor.extract_fields(dxf_path, frame1)
    extractor.extract_fields(dxf_path, frame2)

    assert calls["count"] == 1
