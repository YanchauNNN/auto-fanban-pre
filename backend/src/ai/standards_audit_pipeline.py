from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus

from .standards_audit import AuditRecord, filter_target_rows, normalize_standard_code
from .standards_official_sources import (
    IndustryStandardClient,
    NationalStandardClient,
    OfficialEvidence,
    apply_official_evidence,
)

NATIONAL_TYPES = frozenset({"国家强制性标准", "国家推荐性标准"})
INDUSTRY_TYPES = frozenset({"行业标准"})


class OfficialClient(Protocol):
    def lookup(self, standard_code: str) -> OfficialEvidence: ...


def official_lookup_code(value: Any) -> str:
    normalized = normalize_standard_code(value)
    normalized = re.sub(r"[（(].*$", "", normalized).strip()
    return normalized


def build_audit_records(
    rows: Iterable[dict[str, Any]],
    *,
    national_client: OfficialClient | None = None,
    industry_client: OfficialClient | None = None,
    max_workers: int = 4,
) -> list[AuditRecord]:
    records = filter_target_rows(rows)
    national = national_client or NationalStandardClient()
    industry = industry_client or IndustryStandardClient()
    pending: dict[object, list[int]] = {}
    submitted: dict[tuple[str, str], object] = {}

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        for index, record in enumerate(records):
            if record.source_type in NATIONAL_TYPES:
                lookup_code = official_lookup_code(record.standard_code)
                key = ("national", lookup_code)
                future = submitted.get(key)
                if future is None:
                    future = executor.submit(national.lookup, lookup_code)
                    submitted[key] = future
                    pending[future] = []
                pending[future].append(index)
            elif record.source_type in INDUSTRY_TYPES:
                lookup_code = official_lookup_code(record.standard_code)
                key = ("industry", lookup_code)
                future = submitted.get(key)
                if future is None:
                    future = executor.submit(industry.lookup, lookup_code)
                    submitted[key] = future
                    pending[future] = []
                pending[future].append(index)
            else:
                apply_official_evidence(record, _static_evidence(record))

        for future in as_completed(pending):
            try:
                evidence = future.result()
            except Exception as exc:  # defensive: a client must not abort the audit
                evidence = OfficialEvidence.failure(str(exc))
            for index in pending[future]:
                apply_official_evidence(records[index], evidence)

    for record in records:
        _finalize_record(record)
    return records


def _static_evidence(record: AuditRecord) -> OfficialEvidence:
    checked_at = _checked_at()
    encoded = quote_plus(record.standard_code)
    if record.source_type == "国家建筑标准设计图集":
        return OfficialEvidence(
            official_status="正版来源待核验",
            replacement_standard="待正版发行渠道核验",
            replaced_standard="待正版发行渠道核验",
            official_source_url=(
                f"https://www.chinabuilding.com.cn/search?q={encoded}"
            ),
            downloadability="需正版获取",
            authorization="单位授权待确认",
            confidentiality="内部",
            evidence_checked_at=checked_at,
            evidence_note=(
                "规范库只有目录记录，未发现正版图集文件；必须由单位采购或提供"
                "已授权副本后才能进入离线语料。"
            ),
        )
    if record.source_type in {"内部JT技术规格", "内部CP标准", "项目文件或待分类"}:
        return OfficialEvidence(
            official_status="内部文控待核验",
            replacement_standard="待内部文控核验",
            replaced_standard="待内部文控核验",
            official_source_url="内部文控系统（待接入）",
            downloadability="需内部提供",
            authorization="内部授权待确认",
            confidentiality="受控",
            evidence_checked_at=checked_at,
            evidence_note=(
                "规范库只有目录记录，当前工作区未发现源文件；需由内部文控提供"
                "受控版本、有效性证明和离线使用授权。"
            ),
        )
    if record.source_type == "核安全法规":
        return OfficialEvidence(
            official_status="待国家核安全局核验",
            replacement_standard="待官方核验",
            replaced_standard="待官方核验",
            official_source_url="https://nnsa.mee.gov.cn/",
            downloadability="待官方核验",
            authorization="需确认全文离线使用权",
            confidentiality="公开",
            evidence_checked_at=checked_at,
            evidence_note=(
                "已锚定国家核安全局官方入口；编号和全文需在官方法规标准栏目人工复核。"
            ),
        )
    if record.source_type == "团体标准":
        return OfficialEvidence(
            official_status="发行机构待核验",
            replacement_standard="待发行机构核验",
            replaced_standard="待发行机构核验",
            official_source_url=f"https://www.ttbz.org.cn/?s={encoded}",
            downloadability="需发行机构核验",
            authorization="需发行机构授权",
            confidentiality="公开",
            evidence_checked_at=checked_at,
            evidence_note="团体标准须向发布团体核验有效性和全文离线使用授权。",
        )
    return OfficialEvidence(
        official_status="待人工核验",
        replacement_standard="待人工核验",
        replaced_standard="待人工核验",
        official_source_url="内部文控系统（待接入）",
        downloadability=record.downloadability,
        authorization=record.authorization,
        confidentiality=record.confidentiality,
        evidence_checked_at=checked_at,
        evidence_note="未识别为可自动查询的公共标准，需人工确认来源和授权。",
    )


def _finalize_record(record: AuditRecord) -> None:
    if (
        record.source_type in NATIONAL_TYPES | INDUSTRY_TYPES
        and record.official_status not in {"核验失败", "官方未匹配", "待核验"}
    ):
        if record.replacement_standard == "待核验":
            record.replacement_standard = "无官方替代信息"
        if record.replaced_standard == "待核验":
            record.replaced_standard = "无官方被替代信息"
    record.included_in_corpus = bool(
        record.local_file
        and record.local_sha256
        and record.parse_status == "已解析"
        and record.authorization not in {
            "待确认",
            "单位授权待确认",
            "内部授权待确认",
            "需确认全文离线使用权",
            "需发行机构授权",
        }
    )


def _checked_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成建筑结构总图规范语料审计 JSON")
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--request-timeout", type=int, default=8)
    args = parser.parse_args(argv)

    source_rows = json.loads(args.input_json.read_text(encoding="utf-8"))
    national = NationalStandardClient()
    industry = IndustryStandardClient()
    national.timeout_seconds = max(1, args.request_timeout)
    industry.timeout_seconds = max(1, args.request_timeout)
    records = build_audit_records(
        source_rows,
        national_client=national,
        industry_client=industry,
        max_workers=args.max_workers,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(
            [record.to_dict() for record in records],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
