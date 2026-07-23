from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from src.audit_check.models import ScanTextItem
from src.audit_check.standard_review import StandardEntry, StandardLibraryLoader, StandardReviewEngine
from src.models import BBox


def _write_standard_workbook(path: Path) -> Path:
    workbook = Workbook()
    sheet1 = workbook.active
    assert sheet1 is not None
    sheet1.title = "DatProjInfo"
    sheet1.append(["Id", "NumbProj"])
    sheet1.append(["序号", "项目号"])

    sheet = workbook.create_sheet("DatStdItem")
    sheet.append(
        [
            "Id",
            "CodeStd",
            "NameStd",
            "Version",
            "Prefix",
            "Debug",
            "Department",
            "Major",
            "Status",
            "Comment",
        ]
    )
    sheet.append(["序号", "标准号", "标准名称", "版本", "前缀", "调试信息", "部门", "专业", "状态", "备注"])
    sheet.append([1, "GB 51058", "核电厂抗震设计标准", 2014, "GB", None, "土建所", "结构", "生效", None])
    sheet.append([2, "GB 18030-2022", "信息技术 中文编码字符集", 2022, "GB", None, "核电工艺所", "三维布置", "生效", None])
    sheet.append([3, "NB/T 20001", "压水堆核电厂核岛机械设备设计规范", "2020", "NB/T", None, "土建所", "结构", "生效", None])
    workbook.save(path)
    workbook.close()
    return path


def _item(text: str, *, x: float = 0.0, y: float = 0.0) -> ScanTextItem:
    return ScanTextItem(
        raw_text=text,
        entity_type="DBText",
        internal_code="20161RC-JGS01-001",
        position_x=x,
        position_y=y,
        text_bbox=BBox(xmin=x, ymin=y - 2.0, xmax=x + max(len(text), 1) * 3.0, ymax=y + 2.0),
    )


def test_standard_library_loader_reads_sheet2_and_normalizes_code_year(tmp_path: Path) -> None:
    workbook = _write_standard_workbook(tmp_path / "规范库.xlsx")

    entries = StandardLibraryLoader().load(workbook)

    by_code = {entry.canonical_code: entry for entry in entries}
    assert by_code["GB 51058-2014"].code_without_year == "GB 51058"
    assert by_code["GB 51058-2014"].expected_year == "2014"
    assert by_code["GB 51058-2014"].expected_name == "核电厂抗震设计标准"
    assert by_code["GB 51058-2014"].source_sheet == "DatStdItem"
    assert by_code["GB 51058-2014"].source_row == 3

    assert "GB 18030-2022" in by_code
    assert "GB 18030-2022-2022" not in by_code
    assert by_code["NB/T 20001-2020"].department == "土建所"


def test_standard_review_accepts_matching_code_year_and_nearby_name(tmp_path: Path) -> None:
    entries = StandardLibraryLoader().load(_write_standard_workbook(tmp_path / "规范库.xlsx"))
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [
            _item("GB 51058-2014", x=10.0, y=100.0),
            _item("核 电 厂 抗震设计标准", x=120.0, y=102.0),
        ]
    )

    assert findings == []


def test_standard_review_flags_wrong_year_without_cross_entity_stitching(tmp_path: Path) -> None:
    entries = StandardLibraryLoader().load(_write_standard_workbook(tmp_path / "规范库.xlsx"))
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [
            _item("GB 51058-2011", x=10.0, y=100.0),
            _item("核电厂抗震设计标准", x=120.0, y=100.0),
            _item("GB 51058-", x=10.0, y=130.0),
            _item("2011", x=60.0, y=130.0),
        ]
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("GB 51058-2011", "standard_review_year"),
    ]
    assert findings[0].details == {
        "issue_type": "year_mismatch",
        "actual_code": "GB 51058-2011",
        "expected_code": "GB 51058-2014",
        "actual_year": "2011",
        "expected_year": "2014",
        "expected_name": "核电厂抗震设计标准",
    }


def test_standard_review_flags_wrong_nearby_name(tmp_path: Path) -> None:
    entries = StandardLibraryLoader().load(_write_standard_workbook(tmp_path / "规范库.xlsx"))
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [
            _item("GB 51058-2014", x=10.0, y=100.0),
            _item("城镇供热管网设计标准", x=120.0, y=101.0),
            _item("核电厂抗震设计标准", x=120.0, y=140.0),
        ]
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("GB 51058-2014", "standard_review_name"),
    ]
    assert findings[0].details == {
        "issue_type": "name_mismatch",
        "actual_code": "GB 51058-2014",
        "expected_code": "GB 51058-2014",
        "actual_name": "城镇供热管网设计标准",
        "expected_name": "核电厂抗震设计标准",
    }


def test_standard_review_flags_missing_nearby_name(tmp_path: Path) -> None:
    entries = StandardLibraryLoader().load(_write_standard_workbook(tmp_path / "standards.xlsx"))
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [
            _item("GB 51058-2014", x=10.0, y=100.0),
            _item("unrelated note", x=120.0, y=140.0),
        ]
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("GB 51058-2014", "standard_review_name"),
    ]
    assert findings[0].details is not None
    assert findings[0].details["issue_type"] == "name_missing"
    assert findings[0].details["actual_code"] == "GB 51058-2014"
    assert findings[0].details["expected_code"] == "GB 51058-2014"
    assert findings[0].details["actual_name"] == ""


def test_standard_review_normalizes_fullwidth_punctuation_and_hyphens(tmp_path: Path) -> None:
    entries = StandardLibraryLoader().load(_write_standard_workbook(tmp_path / "规范库.xlsx"))
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [
            _item("ＧＢ ５１０５８—２０１４", x=10.0, y=100.0),
            _item("核电厂抗震设计标准", x=120.0, y=100.0),
        ]
    )

    assert findings == []


def test_standard_review_accepts_code_and_name_in_same_text_box_without_y_matching() -> None:
    entries = [
        StandardEntry(
            canonical_code="GB 50496-2018",
            code_without_year="GB 50496",
            expected_year="2018",
            expected_name="大体积混凝土施工标准",
            source_sheet="DatStdItem",
            source_row=1,
        ),
        StandardEntry(
            canonical_code="GB 50204-2015",
            code_without_year="GB 50204",
            expected_year="2015",
            expected_name="混凝土结构工程施工质量验收规范",
            source_sheet="DatStdItem",
            source_row=2,
        ),
    ]
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [
            _item(
                "GB 50496-2018:大体积混凝土施工标准；\n"
                "GB 50204-2015:混凝土结构工程施工质量验收规范。",
                x=10.0,
                y=100.0,
            )
        ]
    )

    assert findings == []


def test_standard_review_flags_wrong_name_in_same_text_box() -> None:
    entries = [
        StandardEntry(
            canonical_code="GB 50496-2018",
            code_without_year="GB 50496",
            expected_year="2018",
            expected_name="大体积混凝土施工标准",
            source_sheet="DatStdItem",
            source_row=1,
        )
    ]
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [_item("GB 50496-2018:混凝土结构工程施工规范；", x=10.0, y=100.0)]
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("GB 50496-2018", "standard_review_name"),
    ]
    assert findings[0].details is not None
    assert findings[0].details["issue_type"] == "name_mismatch"
    assert findings[0].details["actual_name"] == "混凝土结构工程施工规范"
    assert findings[0].details["expected_name"] == "大体积混凝土施工标准"


def test_standard_review_flags_wrong_year_in_same_text_box() -> None:
    entries = [
        StandardEntry(
            canonical_code="GB 51058-2014",
            code_without_year="GB 51058",
            expected_year="2014",
            expected_name="精神专科医院建筑设计规范",
            source_sheet="DatStdItem",
            source_row=1,
        )
    ]
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [_item("GB 51058-2011:精神专科医院建筑设计规范；", x=10.0, y=100.0)]
    )

    assert [(finding.matched_text, finding.context_kind) for finding in findings] == [
        ("GB 51058-2011", "standard_review_year"),
    ]
    assert findings[0].details is not None
    assert findings[0].details["actual_year"] == "2011"
    assert findings[0].details["expected_year"] == "2014"


def test_standard_review_accepts_standard_code_format_variants() -> None:
    entries = [
        StandardEntry(
            canonical_code="GB/T 51058-2014",
            code_without_year="GB/T 51058",
            expected_year="2014",
            expected_name="精神专科医院建筑设计规范",
            source_sheet="DatStdItem",
            source_row=1,
        )
    ]
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [
            _item("GB／T51058—2014：精神专科医院建筑设计规范", x=10.0, y=100.0),
            _item("GBT 51058 2014：精神专科医院建筑设计规范", x=10.0, y=120.0),
            _item("GB/T\n51058（2014）：精神专科医院建筑设计规范", x=10.0, y=140.0),
        ]
    )

    assert findings == []


def test_standard_review_accepts_bracketed_name_before_code_in_same_entity() -> None:
    entries = [
        StandardEntry(
            canonical_code="GB 51058-2014",
            code_without_year="GB 51058",
            expected_year="2014",
            expected_name="核电厂抗震设计标准",
            source_sheet="DatStdItem",
            source_row=1,
        )
    ]
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate([_item("《核电厂抗震设计标准》（GB 51058-2014）")])

    assert findings == []


def test_standard_review_pairs_multiple_bracketed_names_in_one_entity() -> None:
    entries = [
        StandardEntry(
            canonical_code="GB/T 14685-2022",
            code_without_year="GB/T 14685",
            expected_year="2022",
            expected_name="建设用卵石、碎石",
            source_sheet="DatStdItem",
            source_row=1,
        ),
        StandardEntry(
            canonical_code="GB/T 14684-2022",
            code_without_year="GB/T 14684",
            expected_year="2022",
            expected_name="建设用砂",
            source_sheet="DatStdItem",
            source_row=2,
        ),
    ]
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [_item("《建设用卵石、碎石》GB/T 14685-2022、《建设用砂》GB/T 14684-2022")]
    )

    assert findings == []


def test_standard_review_does_not_use_unrelated_nearby_note_when_same_entity_has_name() -> None:
    entries = [
        StandardEntry(
            canonical_code="GB 50108-2008",
            code_without_year="GB 50108",
            expected_year="2008",
            expected_name="地下工程防水技术规范",
            source_sheet="DatStdItem",
            source_row=1,
        )
    ]
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [
            _item("《地下工程防水技术规范》（GB 50108-2008）", x=0.0, y=100.0),
            _item("2根DN50钢套管", x=30.0, y=100.0),
        ]
    )

    assert findings == []


def test_standard_review_accepts_same_entity_name_with_edition_after_code() -> None:
    entries = [
        StandardEntry(
            canonical_code="GB/T 50010-2010",
            code_without_year="GB/T 50010",
            expected_year="2010",
            expected_name="混凝土结构设计标准（2024年版）",
            source_sheet="DatStdItem",
            source_row=1,
        )
    ]
    engine = StandardReviewEngine(entries, same_line_y_tolerance=5.0)

    findings = engine.evaluate(
        [_item("《混凝土结构设计标准》 (GB/T 50010-2010)（2024年版）")]
    )

    assert findings == []
