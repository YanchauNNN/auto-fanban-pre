from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = (
    REPO_ROOT
    / "tools"
    / "ai"
    / "building-structure-standards"
    / "assets"
    / "data"
    / "audit_catalog.json"
)
ONLINE_ONLY_MARKER = "仅提供在线阅读服务"
WITHDRAWN_MARKER = "废止标准不提供标准文本阅读服务"
NO_READING_MARKER = "暂不提供在线阅读服务"


def reconcile(catalog_path: Path) -> list[str]:
    records = json.loads(catalog_path.read_text(encoding="utf-8"))
    updated: list[str] = []
    checked_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    with httpx.Client(follow_redirects=True, timeout=15) as client:
        for record in records:
            if not record.get("official_fulltext_url"):
                continue
            detail_url = str(record.get("official_source_url") or "")
            if not detail_url.startswith("https://openstd.samr.gov.cn/"):
                continue
            response = client.get(detail_url)
            response.raise_for_status()
            if not any(
                marker in response.text
                for marker in (ONLINE_ONLY_MARKER, WITHDRAWN_MARKER, NO_READING_MARKER)
            ):
                continue
            record["official_fulltext_url"] = ""
            record["evidence_checked_at"] = checked_at
            if ONLINE_ONLY_MARKER in response.text:
                record["downloadability"] = "仅在线阅读"
                record["authorization"] = "仅允许在线阅读"
                record["evidence_note"] = (
                    "国家标准全文公开系统明确说明该标准涉及国际标准版权保护，"
                    "仅提供在线阅读服务，不提供离线下载。"
                )
            elif WITHDRAWN_MARKER in response.text:
                record["downloadability"] = "无官方全文"
                record["authorization"] = "无离线下载入口"
                record["evidence_note"] = (
                    "国家标准全文公开系统明确说明废止标准不提供标准文本阅读服务。"
                )
            else:
                record["downloadability"] = "无官方全文"
                record["authorization"] = "无离线下载入口"
                record["evidence_note"] = (
                    "国家标准全文公开系统明确说明该采标标准因版权保护暂不提供在线阅读服务，"
                    "也不提供离线下载。"
                )
            updated.append(str(record.get("standard_code") or ""))

    catalog_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="纠正国家标准官网仅在线阅读条目的下载能力标记。"
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    updated = reconcile(args.catalog)
    print(json.dumps({"updated_count": len(updated), "codes": updated}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
