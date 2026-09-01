from __future__ import annotations

from src.ai.standards_audit_pipeline import (
    build_audit_records,
    official_lookup_code,
)
from src.ai.standards_official_sources import OfficialEvidence


class FakeClient:
    def __init__(self, status: str) -> None:
        self.status = status
        self.calls: list[str] = []

    def lookup(self, code: str) -> OfficialEvidence:
        self.calls.append(code)
        return OfficialEvidence(
            standard_code=code,
            official_status=self.status,
            publication_date="2024-01-01",
            official_source_url=f"https://official.example/{code}",
            downloadability="仅元数据",
            authorization="仅元数据；全文需另行授权",
            confidentiality="公开",
            evidence_checked_at="2026-07-20T00:00:00+00:00",
            evidence_note="fixture",
        )


def source_row(
    code: str,
    *,
    source_id: int = 1,
    major: str = "结构",
) -> dict[str, object]:
    return {
        "Id": source_id,
        "CodeStd": code,
        "NameStd": f"{code} 名称",
        "Department": "建筑结构所",
        "Major": major,
        "Status": "",
        "Comment": "",
    }


def test_official_lookup_code_removes_local_revision_annotations() -> None:
    assert official_lookup_code("GB 6722-2014(2017局部修订)") == "GB 6722-2014"
    assert official_lookup_code("GB/T 50838-2015（局部修订）") == "GB/T 50838-2015"
    assert official_lookup_code("NB/T 20401-2017") == "NB/T 20401-2017"


def test_build_audit_records_routes_public_standards_and_preserves_order() -> None:
    national = FakeClient("现行")
    industry = FakeClient("废止")
    records = build_audit_records(
        [
            source_row("GB/T 14684-2022", source_id=1),
            source_row("NB/T 20401-2017", source_id=2),
        ],
        national_client=national,
        industry_client=industry,
        max_workers=1,
    )

    assert [record.source_id for record in records] == [1, 2]
    assert national.calls == ["GB/T 14684-2022"]
    assert industry.calls == ["NB/T 20401-2017"]
    assert records[0].official_status == "现行"
    assert records[1].official_status == "废止"
    assert records[0].replacement_standard == "无官方替代信息"
    assert records[0].included_in_corpus is False


def test_build_audit_records_fails_closed_for_licensed_and_internal_sources() -> None:
    records = build_audit_records(
        [
            source_row("22G101-1", source_id=1),
            source_row("2024JT001", source_id=2),
            source_row("CP 001-2024", source_id=3),
            source_row("HAF 101-2023", source_id=4),
        ],
        max_workers=1,
    )

    atlas, jt, cp, haf = records
    assert atlas.downloadability == "需正版获取"
    assert atlas.authorization == "单位授权待确认"
    assert "chinabuilding.com.cn" in atlas.official_source_url
    assert jt.downloadability == "需内部提供"
    assert cp.downloadability == "需内部提供"
    assert jt.confidentiality == cp.confidentiality == "受控"
    assert "内部文控" in jt.official_source_url
    assert "nnsa.mee.gov.cn" in haf.official_source_url
    assert all(record.included_in_corpus is False for record in records)


def test_every_row_has_explicit_status_source_authorization_and_confidentiality() -> None:
    records = build_audit_records(
        [
            source_row("22G101-1", source_id=1),
            source_row("2024JT001", source_id=2),
            source_row("CP 001-2024", source_id=3),
            source_row("未知文件", source_id=4),
        ],
        max_workers=1,
    )

    for record in records:
        assert record.official_status
        assert record.replacement_standard
        assert record.official_source_url
        assert record.downloadability
        assert record.authorization
        assert record.confidentiality
        assert record.evidence_note
