from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CODE_PATTERN = re.compile(
    r"^\s*(?P<prefix>[A-Z]{1,10}(?:\s*/?\s*T)?)\s*"
    r"(?P<number>\d+(?:\.\d+)?)\s*[-—_]\s*(?P<year>\d{4})",
    re.IGNORECASE,
)
ATLAS_PATTERN = re.compile(r"^\s*(?P<code>\d{2,4}[A-Z]{1,4}\d{2,8})\b", re.IGNORECASE)
PREFIX_ALIASES = {
    "GBT": "GB/T",
    "GBZT": "GBZ/T",
    "JGJT": "JGJ/T",
    "CJJT": "CJJ/T",
    "CJT": "CJ/T",
    "JCT": "JC/T",
    "NBT": "NB/T",
    "DLT": "DL/T",
    "SLT": "SL/T",
    "DBT": "DB/T",
    "TCECS": "T/CECS",
}


def build_inventory(
    source_root: Path | str, audit_catalog: Path | str
) -> dict[str, Any]:
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"standards source root does not exist: {root}")
    audit_records = _load_audit_catalog(audit_catalog)
    audit_index = _build_audit_index(audit_records)
    sources: list[dict[str, Any]] = []

    for pdf_path in sorted(
        root.rglob("*.pdf"), key=lambda path: path.as_posix().casefold()
    ):
        relative_path = pdf_path.relative_to(root).as_posix()
        audit_record = _match_audit_record(pdf_path.stem, audit_index)
        inferred_code, inferred_name = _infer_identity(pdf_path.stem)
        if audit_record is not None:
            standard_code = str(
                audit_record.get("standard_code") or inferred_code
            ).strip()
            standard_name = str(
                audit_record.get("standard_name") or inferred_name
            ).strip()
            metadata_source = "audit_catalog"
        elif inferred_code:
            standard_code = inferred_code
            standard_name = inferred_name
            metadata_source = "filename"
        else:
            digest = (
                hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:12].upper()
            )
            standard_code = f"UNIDENTIFIED-{digest}"
            standard_name = pdf_path.stem.strip()
            metadata_source = "unidentified"

        path_marks_deprecated = "废止" in relative_path
        official_status = str(
            (audit_record or {}).get("official_status")
            or ("废止" if path_marks_deprecated else "待核验")
        ).strip()
        sources.append(
            {
                "standard_code": standard_code,
                "standard_name": standard_name or pdf_path.stem.strip(),
                "version": _version_from_code(standard_code),
                "source_path": relative_path,
                "official_source_url": str(
                    (audit_record or {}).get("official_source_url") or ""
                ),
                "authorization": "内部离线检索已授权",
                "confidentiality": "内部离线规范资料",
                "official_status": official_status,
                "replacement_standard": str(
                    (audit_record or {}).get("replacement_standard") or ""
                ),
                "major": "建筑结构总图",
                "metadata_source": metadata_source,
                "size_bytes": pdf_path.stat().st_size,
            }
        )

    source_counts = Counter(item["standard_code"] for item in sources)
    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_root_hint": "documents/规范下载",
        "authorization_policy": (
            "Files placed in the approved offline source root are authorized for "
            "internal retrieval; original PDFs remain outside the deployment package."
        ),
        "summary": {
            "pdf_count": len(sources),
            "audit_matched_count": sum(
                item["metadata_source"] == "audit_catalog" for item in sources
            ),
            "inferred_count": sum(
                item["metadata_source"] == "filename" for item in sources
            ),
            "unidentified_count": sum(
                item["metadata_source"] == "unidentified" for item in sources
            ),
            "duplicate_standard_code_count": sum(
                count > 1 for count in source_counts.values()
            ),
        },
        "sources": sources,
    }


def _load_audit_catalog(path: Path | str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("audit catalog must be a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def _build_audit_index(
    records: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    indexed = [
        (_compact_code(str(record.get("standard_code") or "")), record)
        for record in records
    ]
    return sorted(
        [(key, record) for key, record in indexed if key],
        key=lambda item: len(item[0]),
        reverse=True,
    )


def _match_audit_record(
    stem: str,
    audit_index: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    compact_stem = _compact_code(stem)
    for key, record in audit_index:
        if key in compact_stem:
            return record
    return None


def _compact_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _infer_identity(stem: str) -> tuple[str, str]:
    normalized_stem = stem.replace("／", "/").replace("－", "-")
    normalized_stem = re.sub(
        r"^\s*\d{3}\s*[-_]\s*(?=(?:\d{2,4}[A-Z]|[A-Z]))",
        "",
        normalized_stem,
    )
    normalized_stem = re.sub(
        r"^([A-Z]{1,12})\s*-\s*T(?=\s)",
        r"\1/T",
        normalized_stem,
        flags=re.IGNORECASE,
    )
    normalized_stem = re.sub(
        r"^T\s+CECS(?=\s)",
        "T/CECS",
        normalized_stem,
        flags=re.IGNORECASE,
    )
    upper = normalized_stem.upper()
    match = CODE_PATTERN.match(upper)
    if match:
        compact_prefix = re.sub(r"[^A-Z]", "", match.group("prefix").upper())
        prefix = PREFIX_ALIASES.get(compact_prefix, compact_prefix)
        code = f"{prefix} {match.group('number')}-{match.group('year')}"
        return code, _clean_title(normalized_stem[match.end() :])
    atlas = ATLAS_PATTERN.match(upper)
    if atlas:
        return atlas.group("code").upper(), _clean_title(normalized_stem[atlas.end() :])
    year_match = re.search(r"[-—_]\s*((?:19|20)\d{2})", upper)
    if year_match:
        code_prefix = upper[: year_match.start()].strip(" -—_:/")
        if re.search(r"[A-Z]", code_prefix) and re.search(r"\d", code_prefix):
            code_prefix = re.sub(r"\s*[/_-]\s*T\b", "/T", code_prefix)
            code_prefix = re.sub(r"\s+", " ", code_prefix)
            code_prefix = re.sub(r"([A-Z/])(?=\d)", r"\1 ", code_prefix)
            code = f"{code_prefix}-{year_match.group(1)}"
            return code, _clean_title(normalized_stem[year_match.end() :])
    return "", stem.strip()


def _clean_title(value: str) -> str:
    return re.sub(r"^[\s_\-—:：]+", "", value).strip()


def _version_from_code(code: str) -> str:
    matches = re.findall(r"(?:19|20)\d{2}", code)
    return matches[-1] if matches else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory offline building standards PDFs."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--audit-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_inventory(args.source_root, args.audit_catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
