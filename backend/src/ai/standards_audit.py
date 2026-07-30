from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

_TARGET_DEPARTMENT = "建筑结构所"
_TARGET_MAJORS = frozenset({"建筑", "结构", "总图"})
_DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\uff0d": "-",
    }
)
_INDUSTRY_PREFIXES = (
    "AQ",
    "CJJ",
    "DL",
    "EJ",
    "JC",
    "JG",
    "JGJ",
    "JT",
    "JTG",
    "JTS",
    "NB",
    "SH",
    "SL",
    "TD",
    "YB",
)


@dataclass(frozen=True)
class AcquisitionPolicy:
    downloadability: str
    authorization: str
    confidentiality: str


@dataclass
class AuditRecord:
    source_id: int
    original_code: str
    standard_code: str
    standard_name: str
    department: str
    major: str
    source_status: str
    source_comment: str
    source_type: str
    official_status: str
    replacement_standard: str
    replaced_standard: str
    publication_date: str
    implementation_date: str
    issuing_authority: str
    official_source_url: str
    official_fulltext_url: str
    downloadability: str
    authorization: str
    confidentiality: str
    evidence_checked_at: str
    evidence_note: str
    local_file: str
    local_sha256: str
    parse_status: str
    included_in_corpus: bool

    @classmethod
    def from_source_row(cls, row: dict[str, Any]) -> AuditRecord:
        original_code = _string(row.get("CodeStd"))
        standard_code = normalize_standard_code(original_code)
        source_type = classify_standard(standard_code)
        policy = default_acquisition_policy(source_type)
        return cls(
            source_id=int(row.get("Id") or 0),
            original_code=original_code,
            standard_code=standard_code,
            standard_name=_string(row.get("NameStd")),
            department=_string(row.get("Department")),
            major=_string(row.get("Major")),
            source_status=_string(row.get("Status")),
            source_comment=_string(row.get("Comment")),
            source_type=source_type,
            official_status="待核验",
            replacement_standard="待核验",
            replaced_standard="待核验",
            publication_date="",
            implementation_date="",
            issuing_authority="",
            official_source_url="",
            official_fulltext_url="",
            downloadability=policy.downloadability,
            authorization=policy.authorization,
            confidentiality=policy.confidentiality,
            evidence_checked_at="",
            evidence_note="",
            local_file="",
            local_sha256="",
            parse_status="未解析",
            included_in_corpus=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_standard_code(value: Any) -> str:
    code = _string(value).translate(_DASH_TRANSLATION).replace("\u00a0", " ")
    code = re.sub(r"\s+", " ", code).strip().upper()
    code = re.sub(
        r"^(GB(?:/T|/Z|Z/T|J)?)(?=\d)",
        r"\1 ",
        code,
    )
    code = re.sub(
        rf"^({'|'.join(_INDUSTRY_PREFIXES)})(/T)?(?=\d)",
        lambda match: f"{match.group(1)}{match.group(2) or ''} ",
        code,
    )
    return code


def classify_standard(value: Any) -> str:
    code = normalize_standard_code(value)
    if re.match(r"^GB/T(?:\s|$)", code):
        return "国家推荐性标准"
    if re.match(r"^GB(?:\s|J\b|Z/T\b|/Z\b)", code):
        return "国家强制性标准"
    if code.startswith("HAF "):
        return "核安全法规"
    if code.startswith("CP "):
        return "内部CP标准"
    if re.match(r"^\d{4}JT\d", code):
        return "内部JT技术规格"
    if re.match(r"^\d{2}[A-Z]{1,3}\d", code):
        return "国家建筑标准设计图集"
    if re.match(rf"^({'|'.join(_INDUSTRY_PREFIXES)})(?:/T)?(?:\s|$)", code):
        return "行业标准"
    if re.match(r"^T/[A-Z0-9]+", code):
        return "团体标准"
    return "项目文件或待分类"


def default_acquisition_policy(source_type: str) -> AcquisitionPolicy:
    if source_type == "国家建筑标准设计图集":
        return AcquisitionPolicy(
            downloadability="需正版获取",
            authorization="单位授权待确认",
            confidentiality="内部",
        )
    if source_type in {"内部CP标准", "内部JT技术规格", "项目文件或待分类"}:
        return AcquisitionPolicy(
            downloadability="需内部提供",
            authorization="内部授权待确认",
            confidentiality="受控",
        )
    return AcquisitionPolicy(
        downloadability="待官方核验",
        authorization="待确认",
        confidentiality="公开",
    )


def filter_target_rows(rows: Iterable[dict[str, Any]]) -> list[AuditRecord]:
    return [
        AuditRecord.from_source_row(row)
        for row in rows
        if _string(row.get("Department")) == _TARGET_DEPARTMENT
        and _string(row.get("Major")) in _TARGET_MAJORS
        and _string(row.get("CodeStd"))
    ]


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()
