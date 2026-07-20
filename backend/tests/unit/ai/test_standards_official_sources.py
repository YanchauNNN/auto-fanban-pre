from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

import pytest

from src.ai.standards_audit import AuditRecord
from src.ai.standards_official_sources import (
    AtlasOfficialClient,
    IndustryStandardClient,
    NationalStandardClient,
    _find_openstd_detail_url,
    apply_official_evidence,
    parse_atlas_result,
    parse_industry_result,
    parse_openstd_detail,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "standards"


def test_parse_openstd_current_exposes_metadata_without_claiming_automatic_download() -> None:
    html = (FIXTURES / "openstd_current.html").read_text(encoding="utf-8")

    evidence = parse_openstd_detail(
        html,
        "https://openstd.samr.gov.cn/bzgk/std/newGbInfo"
        "?hcno=BFD788F1742125DC8E9922E38F6167BD",
    )

    assert evidence.standard_code == "GB/T 14684-2022"
    assert evidence.standard_name == "建设用砂"
    assert evidence.official_status == "现行"
    assert evidence.publication_date == "2022-04-15"
    assert evidence.implementation_date == "2022-11-01"
    assert evidence.replaced_standard == "GB/T 14684-2011"
    assert evidence.downloadability == "可人工下载"
    assert evidence.official_fulltext_url.endswith(
        "/bzgk/std/showGb?type=download&hcno=BFD788F1742125DC8E9922E38F6167BD"
    )
    assert "自动下载未授权" in evidence.evidence_note


def test_find_openstd_detail_supports_current_javascript_result_link() -> None:
    html = (FIXTURES / "openstd_search.html").read_text(encoding="utf-8")

    detail_url = _find_openstd_detail_url(html, "GB/T 14684-2022")

    assert detail_url.endswith(
        "/bzgk/std/newGbInfo?hcno=BFD788F1742125DC8E9922E38F6167BD"
    )


def test_parse_openstd_replaced_records_replacement_and_no_fulltext() -> None:
    html = (FIXTURES / "openstd_replaced.html").read_text(encoding="utf-8")

    evidence = parse_openstd_detail(
        html,
        "https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=OLD",
    )

    assert evidence.official_status == "废止"
    assert evidence.replacement_standard == "GB/T 14684-2022"
    assert evidence.downloadability == "无官方全文"
    assert evidence.official_fulltext_url == ""


def test_parse_industry_result_returns_metadata_only() -> None:
    payload = json.loads((FIXTURES / "industry_result.json").read_text(encoding="utf-8"))

    evidence = parse_industry_result(payload, requested_code="NB/T 20401-2017")

    assert evidence.standard_name == "核电厂初步设计文件内容深度规定"
    assert evidence.official_status == "现行"
    assert evidence.publication_date == "2017-02-10"
    assert evidence.implementation_date == "2017-07-01"
    assert evidence.issuing_authority == "国家能源局"
    assert evidence.official_source_url.endswith(
        "/stdDetail/c7e0abc898abe7e5a56099227d3de07f"
    )
    assert evidence.downloadability == "仅元数据"
    assert evidence.official_fulltext_url == ""


def test_parse_atlas_result_requires_licensed_copy() -> None:
    html = (FIXTURES / "atlas_result.html").read_text(encoding="utf-8")

    evidence = parse_atlas_result(
        html,
        requested_code="22G101-1",
        result_url="https://www.chinabuilding.com.cn/search?q=22G101-1",
    )

    assert evidence.official_status == "正版可购"
    assert evidence.downloadability == "需正版获取"
    assert evidence.authorization == "单位授权待确认"
    assert evidence.confidentiality == "内部"


@pytest.mark.parametrize(
    ("client", "code"),
    [
        (NationalStandardClient(), "GB/T 14684-2022"),
        (IndustryStandardClient(), "NB/T 20401-2017"),
        (AtlasOfficialClient(), "22G101-1"),
    ],
)
def test_network_failure_is_explicit_not_misreported_as_not_found(
    monkeypatch: pytest.MonkeyPatch,
    client: object,
    code: str,
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise URLError("simulated offline")

    monkeypatch.setattr(client, "_request", fail)
    record = AuditRecord.from_source_row(
        {
            "Id": 1,
            "CodeStd": code,
            "NameStd": "测试规范",
            "Department": "建筑结构所",
            "Major": "结构",
        }
    )

    updated = apply_official_evidence(record, client.lookup(code))

    assert updated.official_status == "核验失败"
    assert "simulated offline" in updated.evidence_note
    assert updated.official_status != "未找到"
