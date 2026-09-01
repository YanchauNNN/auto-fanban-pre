from __future__ import annotations


def test_standard_code_normalization_handles_workbook_variants() -> None:
    from src.ai.standards_audit import normalize_standard_code

    assert normalize_standard_code("GB/T\u00a014684-2022") == "GB/T 14684-2022"
    assert normalize_standard_code("  nb/t 20401—2017 ") == "NB/T 20401-2017"
    assert normalize_standard_code("GB18173.2-2014") == "GB 18173.2-2014"
    assert normalize_standard_code("19J102-1、19G613") == "19J102-1、19G613"


def test_standard_source_classification_covers_target_families() -> None:
    from src.ai.standards_audit import classify_standard

    assert classify_standard("GB 50207-2012") == "国家强制性标准"
    assert classify_standard("GB/T 14684-2022") == "国家推荐性标准"
    assert classify_standard("NB/T 20401-2017") == "行业标准"
    assert classify_standard("JGJ 63-2006") == "行业标准"
    assert classify_standard("HAF 101-2023") == "核安全法规"
    assert classify_standard("23J909") == "国家建筑标准设计图集"
    assert classify_standard("CP 05JT0101") == "内部CP标准"
    assert classify_standard("1907JT0101") == "内部JT技术规格"
    assert classify_standard("无") == "项目文件或待分类"


def test_default_policy_fails_closed_for_licensed_and_internal_sources() -> None:
    from src.ai.standards_audit import default_acquisition_policy

    public = default_acquisition_policy("国家推荐性标准")
    assert public.downloadability == "待官方核验"
    assert public.authorization == "待确认"
    assert public.confidentiality == "公开"

    atlas = default_acquisition_policy("国家建筑标准设计图集")
    assert atlas.downloadability == "需正版获取"
    assert atlas.authorization == "单位授权待确认"
    assert atlas.confidentiality == "内部"

    internal = default_acquisition_policy("内部JT技术规格")
    assert internal.downloadability == "需内部提供"
    assert internal.authorization == "内部授权待确认"
    assert internal.confidentiality == "受控"


def test_audit_record_preserves_source_row_and_serializes_explicit_unknowns() -> None:
    from src.ai.standards_audit import AuditRecord

    record = AuditRecord.from_source_row(
        {
            "Id": 17,
            "CodeStd": "GB/T\u00a014684-2022",
            "NameStd": "建设用砂",
            "Department": "建筑结构所",
            "Major": "结构",
            "Status": "",
            "Comment": None,
        }
    )

    payload = record.to_dict()
    assert payload["source_id"] == 17
    assert payload["standard_code"] == "GB/T 14684-2022"
    assert payload["source_type"] == "国家推荐性标准"
    assert payload["official_status"] == "待核验"
    assert payload["replacement_standard"] == "待核验"
    assert payload["official_source_url"] == ""
    assert payload["included_in_corpus"] is False


def test_filter_target_rows_returns_exactly_509_building_structure_records() -> None:
    from src.ai.standards_audit import filter_target_rows

    target_rows = [
        {
            "Id": index,
            "CodeStd": f"GB {50000 + index}-2020",
            "NameStd": f"测试规范 {index}",
            "Department": "建筑结构所",
            "Major": ("建筑", "结构", "总图")[index % 3],
        }
        for index in range(509)
    ]
    excluded = [
        {
            "Id": 900,
            "CodeStd": "GB 1-2020",
            "NameStd": "其他部门",
            "Department": "民用所",
            "Major": "建筑",
        },
        {
            "Id": 901,
            "CodeStd": "GB 2-2020",
            "NameStd": "其他专业",
            "Department": "建筑结构所",
            "Major": "暖通",
        },
    ]

    records = filter_target_rows([*target_rows, *excluded])

    assert len(records) == 509
    assert {record.major for record in records} == {"建筑", "结构", "总图"}
