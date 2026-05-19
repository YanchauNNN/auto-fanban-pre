"""
图签提取器单元测试（模块3）
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import ezdxf

from src.cad.titleblock_extractor import TextItem, TitleblockExtractor
from src.models import BBox, FrameMeta, FrameRuntime


def _item(
    text: str,
    x: float = 0.0,
    y: float = 0.0,
    *,
    bbox: BBox | None = None,
    height: float = 2.5,
) -> TextItem:
    return TextItem(
        x=x,
        y=y,
        text=text,
        bbox=bbox,
        text_height=height,
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


def test_parse_internal_code_rebuilds_suffix_from_discrete_tokens_by_x_order() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["internal_code"].parse

    code, album = extractor._parse_internal_code(
        [
            _item("20261DA-JGS01-", x=10.0, y=10.0),
            _item("0", x=80.0, y=12.0),
            _item("0", x=92.0, y=8.0),
            _item("2", x=104.0, y=11.0),
        ],
        parse_cfg,
    )

    assert code == "20261DA-JGS01-002"
    assert album == "01"


def test_parse_external_code_fixed19() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["external_code"].parse
    items = [_item("DOC.NO JD1NHT11T01B25C42SD")]
    code = extractor._parse_external_code(items, parse_cfg)
    assert code == "JD1NHT11T01B25C42SD"


def test_parse_external_code_ignores_isolated_right_side_digit_noise() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["external_code"].parse
    expected = "JD2RSH12024B25C42SD"
    items = [_item("DOC.NO", x=0.0, y=0.0, bbox=BBox(xmin=0.0, ymin=0.0, xmax=8.0, ymax=2.0))]
    for idx, char in enumerate(expected):
        x = 12.0 + idx * 10.0
        items.append(
            _item(
                char,
                x=x,
                y=0.0,
                bbox=BBox(xmin=x, ymin=0.0, xmax=x + 2.0, ymax=2.0),
            )
        )
    # stray neighbor digit on the right should not be absorbed into the 19-char code
    items.append(
        _item(
            "8",
            x=400.0,
            y=0.0,
            bbox=BBox(xmin=400.0, ymin=0.0, xmax=402.0, ymax=2.0),
        )
    )

    code = extractor._parse_external_code(items, parse_cfg)

    assert code == expected


def test_parse_external_code_keeps_leading_letter_close_to_docno_header() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["external_code"].parse
    expected = "JD2RSH12024B25C42SD"
    items = [_item("DOC.NO", x=0.0, y=0.0, bbox=BBox(xmin=0.0, ymin=0.0, xmax=8.0, ymax=2.0))]
    for idx, char in enumerate(expected):
        # first letter intentionally hugs the DOC.NO bbox boundary
        x = 8.0005 + idx * 10.0
        items.append(
            _item(
                char,
                x=x,
                y=0.0,
                bbox=BBox(xmin=x, ymin=0.0, xmax=x + 2.0, ymax=2.0),
            )
        )
    items.append(
        _item(
            "8",
            x=400.0,
            y=0.0,
            bbox=BBox(xmin=400.0, ymin=0.0, xmax=402.0, ymax=2.0),
        )
    )

    code = extractor._parse_external_code(items, parse_cfg)

    assert code == expected


def test_parse_external_code_prefers_x_order_when_characters_have_y_jitter() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["external_code"].parse
    expected = "PC5NBT40001B25C42SD"
    items = [
        _item(
            "DOC.NO",
            x=0.0,
            y=0.0,
            bbox=BBox(xmin=0.0, ymin=0.0, xmax=12.0, ymax=2.0),
        )
    ]
    for idx, char in enumerate(expected):
        x = 12.0005 + idx * 8.0
        if idx == 0:
            y = 7.1
        elif idx == 15:
            y = 21.0
        else:
            y = 0.0
        items.append(
            _item(
                char,
                x=x,
                y=y,
                bbox=BBox(xmin=x, ymin=y, xmax=x + 2.0, ymax=y + 2.0),
            )
        )
    items.append(
        _item(
            "8",
            x=200.0,
            y=0.0,
            bbox=BBox(xmin=200.0, ymin=0.0, xmax=202.0, ymax=2.0),
        )
    )

    code = extractor._parse_external_code(items, parse_cfg)

    assert code == expected


def test_parse_title_bilingual() -> None:
    extractor = TitleblockExtractor()
    items = [
        _item("中文标题", x=10.0, y=100.0),
        _item("English Title", x=10.0, y=90.0),
    ]
    title_cn, title_en = extractor._parse_title_bilingual(items)
    assert title_cn == "中文标题"
    assert title_en == "English Title"


def test_parse_title_bilingual_ignores_page_placeholder_line() -> None:
    extractor = TitleblockExtractor()
    items = [
        _item("5NE 8.450及 8.450以上预制楼梯", x=10.0, y=120.0),
        _item("模板图", x=10.0, y=110.0),
        _item("第 张 共 张", x=10.0, y=100.0),
        _item("5NE 8.450 and Above 8.450 Prefabricated Stairs", x=10.0, y=90.0),
        _item("Formwork", x=10.0, y=80.0),
    ]
    title_cn, title_en = extractor._parse_title_bilingual(items)
    assert title_cn == "5NE 8.450及 8.450以上预制楼梯\n模板图"
    assert title_en == "5NE 8.450 and Above 8.450 Prefabricated Stairs\nFormwork"


def test_parse_title_bilingual_keeps_english_subtitle_with_cjk_index() -> None:
    extractor = TitleblockExtractor()
    items = [
        _item("5NE 8.450及 8.450至12.950m间预制楼梯", x=10.0, y=120.0),
        _item("配筋图(一)", x=10.0, y=110.0),
        _item("5NE 8.450 and 8.450~12.950m Prefabricated Stairs", x=10.0, y=100.0),
        _item("Reinforcement(一)", x=10.0, y=90.0),
    ]

    title_cn, title_en = extractor._parse_title_bilingual(items)

    assert title_cn == "5NE 8.450及 8.450至12.950m间预制楼梯\n配筋图(一)"
    assert title_en == "5NE 8.450 and 8.450~12.950m Prefabricated Stairs\nReinforcement(一)"


def test_parse_title_bilingual_keeps_english_bill_of_material_with_cjk_index() -> None:
    extractor = TitleblockExtractor()
    items = [
        _item("5NE 8.450及 8.450至12.950m间预制楼梯", x=10.0, y=120.0),
        _item("钢筋表（一）", x=10.0, y=110.0),
        _item("5NE 8.450 and 8.450~12.950m Prefabricated Stairs", x=10.0, y=100.0),
        _item("Bill of Material（一）", x=10.0, y=90.0),
    ]

    title_cn, title_en = extractor._parse_title_bilingual(items)

    assert title_cn == "5NE 8.450及 8.450至12.950m间预制楼梯\n钢筋表（一）"
    assert title_en == "5NE 8.450 and 8.450~12.950m Prefabricated Stairs\nBill of Material（一）"


def test_parse_title_bilingual_treats_compact_alnum_prefix_as_chinese_title() -> None:
    extractor = TitleblockExtractor()
    items = [
        _item("2KA", x=10.0, y=120.0),
        _item("\u6a21\u677f\u56fe", x=10.0, y=110.0),
    ]

    title_cn, title_en = extractor._parse_title_bilingual(items)

    assert title_cn == "2KA\n\u6a21\u677f\u56fe"
    assert title_en is None


def test_parse_page_info_with_x() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["page_info"].parse
    items = [_item("共2张 第X张")]
    total, idx = extractor._parse_page_info(items, parse_cfg)
    assert total == 2
    assert idx == 1


def test_parse_page_info_001_homepage_reads_total_then_index_tokens() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["page_info"].parse
    items = [
        _item("4", x=10.0, y=100.0),
        _item("1", x=80.0, y=100.0),
    ]

    total, idx = extractor._parse_page_info(
        items,
        parse_cfg,
        total_then_index_tokens=True,
    )

    assert total == 4
    assert idx == 1


def test_parse_page_info_full_index_then_total_line_overrides_001_fallback_order() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["page_info"].parse
    items = [_item("第1张 共10张")]

    total, idx = extractor._parse_page_info(
        items,
        parse_cfg,
        total_then_index_tokens=True,
    )

    assert total == 10
    assert idx == 1


def test_parse_page_info_full_total_then_index_line_with_page_unit() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["page_info"].parse
    items = [_item("共10页 第1页")]

    total, idx = extractor._parse_page_info(items, parse_cfg)

    assert total == 10
    assert idx == 1


def test_parse_a4_page_marker_identity_with_parenthesized_revision() -> None:
    extractor = TitleblockExtractor()
    items = [_item("18185NE-JGS11-001(A)", x=10.0, y=100.0)]

    internal_code, revision = extractor._parse_a4_marker_identity(items)

    assert internal_code == "18185NE-JGS11-001"
    assert revision == "A"


def test_parse_a4_page_marker_identity_with_colon_revision() -> None:
    extractor = TitleblockExtractor()
    items = [_item("18185NE-JGS11-001：A", x=10.0, y=100.0)]

    internal_code, revision = extractor._parse_a4_marker_identity(items)

    assert internal_code == "18185NE-JGS11-001"
    assert revision == "A"


def test_pick_top_by_y() -> None:
    extractor = TitleblockExtractor()
    items = [_item("A", y=10.0), _item("B", y=5.0)]
    assert extractor._pick_top_by_y(items) == "A"


def test_parse_text_decodes_autocad_control_codes() -> None:
    extractor = TitleblockExtractor()
    items = [
        _item("180.000%%D", x=10.0, y=10.0),
        _item("10.000%%P", x=10.0, y=5.0),
        _item("%%C25", x=10.0, y=0.0),
    ]

    value = extractor._parse_text(items)

    assert value == "180.000°\n10.000±\n⌀25"


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


def test_item_in_roi_uses_bbox_center_instead_of_bbox_overlap() -> None:
    extractor = TitleblockExtractor()
    roi = BBox(xmin=0.0, ymin=0.0, xmax=10.0, ymax=10.0)
    item = _item(
        "Page",
        x=12.0,
        y=5.0,
        bbox=BBox(xmin=8.0, ymin=4.0, xmax=16.0, ymax=6.0),
    )

    assert extractor._item_in_roi(item, roi) is False


def test_claim_items_in_roi_is_exclusive_across_overlapping_fields() -> None:
    extractor = TitleblockExtractor()
    item = _item(
        "OVERLAP",
        x=50.0,
        y=50.0,
        bbox=BBox(xmin=45.0, ymin=45.0, xmax=55.0, ymax=55.0),
    )
    claimed: set[int] = set()

    first = extractor._claim_items_in_roi([item], BBox(xmin=0.0, ymin=0.0, xmax=100.0, ymax=100.0), claimed)
    second = extractor._claim_items_in_roi([item], BBox(xmin=40.0, ymin=40.0, xmax=60.0, ymax=60.0), claimed)

    assert first == [item]
    assert second == []


def test_frame_has_anchor_text_matches_joined_fragments_in_anchor_roi() -> None:
    extractor = TitleblockExtractor()
    frame = FrameMeta(
        runtime=FrameRuntime(
            frame_id="f-anchor",
            source_file=Path("sample.dxf"),
            outer_bbox=BBox(xmin=0.0, ymin=0.0, xmax=100.0, ymax=50.0),
            sx=1.0,
            sy=1.0,
            roi_profile_id="BASE10",
        )
    )
    profile = SimpleNamespace(
        fields={"锚点": [0.0, 40.0, 10.0, 30.0]},
        tolerance=0.5,
    )
    items = [
        _item("本文件产权属中国核电工程有限公司（", x=61.0, y=20.0),
        _item("CNPE", x=78.0, y=20.0),
        _item("）所有，未经书面许可，不得以任何方式复制、传播、发表和外传。", x=83.0, y=20.0),
    ]

    matched = extractor._frame_has_anchor_text(items, frame, profile, "BASE10")

    assert matched is True


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


def test_extract_fields_flags_empty_status_roi(tmp_path, monkeypatch) -> None:
    dxf_path = tmp_path / "sample.dxf"
    ezdxf.new("R2018").saveas(dxf_path)

    extractor = TitleblockExtractor()
    extractor.anchor_texts = []

    frame = FrameMeta(
        runtime=FrameRuntime(
            frame_id="f-empty-status",
            source_file=dxf_path,
            outer_bbox=BBox(xmin=0.0, ymin=0.0, xmax=200.0, ymax=150.0),
            roi_profile_id="BASE10",
            sx=1.0,
            sy=1.0,
        )
    )

    monkeypatch.setattr(extractor, "_load_text_items", lambda _path: [])

    extractor.extract_fields(dxf_path, frame)

    assert frame.titleblock.status is None
    assert "状态为空" in frame.runtime.flags


def test_extract_fields_keeps_page_fragments_out_of_title_roi(tmp_path, monkeypatch) -> None:
    dxf_path = tmp_path / "sample.dxf"
    ezdxf.new("R2018").saveas(dxf_path)

    extractor = TitleblockExtractor()
    extractor.anchor_texts = []

    frame = FrameMeta(
        runtime=FrameRuntime(
            frame_id="f-title",
            source_file=dxf_path,
            outer_bbox=BBox(xmin=0.0, ymin=0.0, xmax=200.0, ymax=150.0),
            roi_profile_id="BASE10",
            sx=1.0,
            sy=1.0,
        )
    )

    items = [
        _item(
            "16.50m 标高门标识平面图",
            x=80.0,
            y=35.0,
            bbox=BBox(xmin=80.0, ymin=34.0, xmax=120.0, ymax=38.0),
        ),
        _item(
            "NB level 16.50m Doors Numbering Plan",
            x=80.0,
            y=24.0,
            bbox=BBox(xmin=80.0, ymin=22.0, xmax=150.0, ymax=26.0),
        ),
        _item(
            "Page",
            x=165.0,
            y=12.0,
            bbox=BBox(xmin=160.0, ymin=11.0, xmax=170.0, ymax=13.0),
        ),
        _item(
            "第",
            x=165.0,
            y=16.0,
            bbox=BBox(xmin=160.0, ymin=15.0, xmax=170.0, ymax=17.0),
        ),
    ]

    monkeypatch.setattr(extractor, "_load_text_items", lambda _path: items)

    extractor.extract_fields(dxf_path, frame)

    title_items = frame.raw_extracts["图纸标题"]
    page_items = frame.raw_extracts["张数"]

    assert [item["text"] for item in title_items] == [
        "16.50m 标高门标识平面图",
        "NB level 16.50m Doors Numbering Plan",
    ]
    assert [item["text"] for item in page_items] == ["Page", "第"]


def test_parse_a4_page_marker_from_fragmented_coordinate_tokens() -> None:
    extractor = TitleblockExtractor()
    items = [
        _item(
            "18185NY-JGS07-001",
            x=120.0,
            y=120.0,
            bbox=BBox(xmin=120.0, ymin=120.0, xmax=220.0, ymax=150.0),
            height=30.0,
        ),
        _item(
            "(A)",
            x=230.0,
            y=120.0,
            bbox=BBox(xmin=230.0, ymin=120.0, xmax=250.0, ymax=150.0),
            height=30.0,
        ),
        _item(
            "第     张 共     张",
            x=140.0,
            y=100.0,
            bbox=BBox(xmin=140.0, ymin=100.0, xmax=240.0, ymax=130.0),
            height=30.0,
        ),
        _item(
            "7",
            x=190.0,
            y=98.0,
            bbox=BBox(xmin=190.0, ymin=98.0, xmax=198.0, ymax=128.0),
            height=30.0,
        ),
        _item(
            "10",
            x=220.0,
            y=98.0,
            bbox=BBox(xmin=220.0, ymin=98.0, xmax=236.0, ymax=128.0),
            height=30.0,
        ),
        _item(
            "Page       of",
            x=140.0,
            y=80.0,
            bbox=BBox(xmin=140.0, ymin=80.0, xmax=220.0, ymax=110.0),
            height=30.0,
        ),
        _item(
            "7",
            x=194.0,
            y=78.0,
            bbox=BBox(xmin=194.0, ymin=78.0, xmax=202.0, ymax=108.0),
            height=30.0,
        ),
        _item(
            "10",
            x=224.0,
            y=78.0,
            bbox=BBox(xmin=224.0, ymin=78.0, xmax=240.0, ymax=108.0),
            height=30.0,
        ),
    ]

    page_total, page_index = extractor._parse_page_marker_from_text(items)

    assert page_total == 10
    assert page_index == 7


def test_parse_a4_page_marker_reads_index_then_total_full_chinese_line() -> None:
    extractor = TitleblockExtractor()
    items = [_item("第2张 共10张")]

    page_total, page_index = extractor._parse_page_marker_from_text(items)

    assert page_total == 10
    assert page_index == 2


def test_parse_page_info_prefers_primary_row_and_reads_index_total_from_same_row() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["page_info"].parse
    items = [
        _item("第     张 共     张", x=10.0, y=100.0),
        _item("1", x=36.0, y=100.0),
        _item("2", x=86.0, y=100.0),
        _item("Page       of", x=10.0, y=92.0),
        _item("1", x=36.0, y=92.0),
        _item("2", x=86.0, y=92.0),
    ]

    total, idx = extractor._parse_page_info(items, parse_cfg)

    assert total == 2
    assert idx == 1


def test_parse_page_info_fragmented_index_then_total_ignores_001_token_fallback_order() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["page_info"].parse
    items = [
        _item("第     张 共     张", x=10.0, y=100.0),
        _item("1", x=36.0, y=100.0),
        _item("10", x=86.0, y=100.0),
        _item("Page       of", x=10.0, y=92.0),
        _item("1", x=36.0, y=92.0),
        _item("10", x=86.0, y=92.0),
    ]

    total, idx = extractor._parse_page_info(
        items,
        parse_cfg,
        total_then_index_tokens=True,
    )

    assert total == 10
    assert idx == 1


def test_parse_page_info_fragmented_index_then_total_allows_baseline_offset() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["page_info"].parse
    items = [
        _item("第     张 共     张", x=10.0, y=100.0, height=125.0),
        _item("Page       of", x=10.0, y=80.0, height=100.0),
        _item("10", x=86.0, y=82.0, height=125.0),
        _item("1", x=36.0, y=79.0, height=125.0),
        _item("1", x=36.0, y=89.0, height=125.0),
        _item("10", x=86.0, y=92.0, height=125.0),
    ]

    total, idx = extractor._parse_page_info(
        items,
        parse_cfg,
        total_then_index_tokens=True,
    )

    assert total == 10
    assert idx == 1


def test_parse_page_info_fragmented_total_then_index_page_unit() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["page_info"].parse
    items = [
        _item("共     页 第     页", x=10.0, y=100.0),
        _item("4", x=36.0, y=100.0),
        _item("1", x=86.0, y=100.0),
    ]

    total, idx = extractor._parse_page_info(items, parse_cfg)

    assert total == 4
    assert idx == 1


def test_parse_page_info_supports_english_row_when_primary_row_missing() -> None:
    extractor = TitleblockExtractor()
    parse_cfg = extractor.field_defs["page_info"].parse
    items = [
        _item("Page       of", x=10.0, y=92.0),
        _item("1", x=36.0, y=92.0),
        _item("2", x=86.0, y=92.0),
    ]

    total, idx = extractor._parse_page_info(items, parse_cfg)

    assert total == 2
    assert idx == 1


def test_parse_title_bilingual_non_1818_forces_all_title_lines_into_cn() -> None:
    extractor = TitleblockExtractor()
    extractor.project_no = "2026"
    items = [
        _item("应急柴油发电机厂房A列1DA", x=10.0, y=120.0),
        _item("-9.800m，-9.300m", x=10.0, y=110.0),
        _item("筏板模板图", x=10.0, y=100.0),
    ]

    title_cn, title_en = extractor._parse_title_bilingual(items)

    assert title_cn == "应急柴油发电机厂房A列1DA\n-9.800m，-9.300m\n筏板模板图"
    assert title_en is None
