from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.ai.standards_downloader import (  # noqa: E402
    FetchedResource,
    UnsafeDownloadError,
    classify_unavailable,
    download_record,
    inspect_existing_download,
    is_public_authorized_candidate,
)

DEFAULT_SKILL_ROOT = REPO_ROOT / "tools" / "ai" / "building-structure-standards"
DEFAULT_CATALOG = DEFAULT_SKILL_ROOT / "assets" / "data" / "audit_catalog.json"
DEFAULT_SOURCE_MANIFEST = (
    DEFAULT_SKILL_ROOT / "assets" / "data" / "source_manifest.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "build" / "建筑结构总图规范语料_509"
_HTTP_CLIENT: httpx.Client | None = None


def acquire_catalog(
    *,
    catalog_path: Path,
    source_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    records = _load_json(catalog_path)
    if not isinstance(records, list) or len(records) != 509:
        raise ValueError(f"审计目录必须正好包含 509 条，实际为 {len(records)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    entries_by_id: dict[str, dict[str, Any]] = {}
    local_sources = _include_existing_authorized_sources(
        records=records,
        source_manifest_path=source_manifest_path,
        output_dir=output_dir,
    )
    entries_by_id.update(local_sources)

    for index, record in enumerate(records, start=1):
        source_id = str(record.get("source_id") or "")
        code = str(record.get("standard_code") or "")
        if source_id in entries_by_id:
            status = entries_by_id[source_id]["acquisition_status"]
            print(f"[{index:03d}/509] {code}: {status}", flush=True)
            continue

        if is_public_authorized_candidate(record):
            existing = inspect_existing_download(record, output_dir)
            if existing is not None:
                entry = _base_entry(record)
                entry.update(
                    {
                        "acquisition_status": existing.status,
                        "download_url": existing.source_url,
                        "final_url": existing.final_url,
                        "local_file": existing.path.name if existing.path else "",
                        "sha256": existing.sha256,
                        "size_bytes": existing.size_bytes,
                        "acquisition_note": existing.note,
                    }
                )
                entries_by_id[source_id] = entry
                print(f"[{index:03d}/509] {code}: {existing.status}", flush=True)
                continue
            print(f"[{index:03d}/509] {code}: requesting_official_source", flush=True)
            try:
                result = download_record(record, output_dir, fetcher=_fetch_with_httpx)
                entry = _base_entry(record)
                entry.update(
                    {
                        "acquisition_status": result.status,
                        "download_url": result.source_url,
                        "final_url": result.final_url,
                        "local_file": result.path.name if result.path else "",
                        "sha256": result.sha256,
                        "size_bytes": result.size_bytes,
                        "acquisition_note": result.note,
                    }
                )
            except UnsafeDownloadError as exc:
                entry = _failure_entry(record, "unsafe_source_rejected", str(exc))
            except (OSError, TimeoutError, ValueError, httpx.HTTPError) as exc:
                entry = _failure_entry(record, "download_failed", str(exc))
        else:
            entry = _failure_entry(
                record,
                classify_unavailable(record),
                _unavailable_note(record),
            )
        entries_by_id[source_id] = entry
        print(
            f"[{index:03d}/509] {code}: {entry['acquisition_status']}",
            flush=True,
        )

    entries = [entries_by_id[str(record.get("source_id") or "")] for record in records]
    manifest = _write_reports(
        entries=entries,
        catalog_path=catalog_path,
        output_dir=output_dir,
    )
    return manifest


def _include_existing_authorized_sources(
    *,
    records: list[dict[str, Any]],
    source_manifest_path: Path,
    output_dir: Path,
) -> dict[str, dict[str, Any]]:
    source_manifest = _load_json(source_manifest_path)
    sources = source_manifest.get("sources", []) if isinstance(source_manifest, dict) else []
    result: dict[str, dict[str, Any]] = {}
    records_by_code = {
        _normalize_code(str(record.get("standard_code") or "")): record
        for record in records
    }
    source_root = source_manifest_path.parent
    for source in sources:
        code = str(source.get("standard_code") or "")
        record = records_by_code.get(_normalize_code(code))
        if record is None:
            continue
        relative_path = Path(str(source.get("source_path") or ""))
        source_path = source_root / relative_path
        if not source_path.is_file():
            continue
        destination = output_dir / source_path.name
        shutil.copy2(source_path, destination)
        entry = _base_entry(record)
        entry.update(
            {
                "acquisition_status": "existing_authorized_local_file",
                "download_url": str(source.get("official_source_url") or ""),
                "final_url": str(source.get("official_source_url") or ""),
                "local_file": destination.name,
                "sha256": _sha256(destination),
                "size_bytes": destination.stat().st_size,
                "acquisition_note": "已授权语料包中的现有全文，已复制到统一目录。",
            }
        )
        result[str(record.get("source_id") or "")] = entry

    authorized_source_dir = source_root / "sources"
    for source_path in sorted(authorized_source_dir.glob("*")):
        if not source_path.is_file():
            continue
        normalized_stem = _normalize_code(source_path.stem)
        record = next(
            (
                item
                for item in records
                if _normalize_code(str(item.get("standard_code") or ""))
                in normalized_stem
            ),
            None,
        )
        if record is None or str(record.get("source_id") or "") in result:
            continue
        destination = output_dir / source_path.name
        shutil.copy2(source_path, destination)
        entry = _base_entry(record)
        entry.update(
            {
                "acquisition_status": "existing_authorized_local_file",
                "download_url": record.get("official_source_url", ""),
                "final_url": record.get("official_source_url", ""),
                "local_file": destination.name,
                "sha256": _sha256(destination),
                "size_bytes": destination.stat().st_size,
                "acquisition_note": "已授权语料目录中的现有全文，已复制到统一目录。",
            }
        )
        result[str(record.get("source_id") or "")] = entry
    return result


def _base_entry(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": record.get("source_id"),
        "standard_code": record.get("standard_code", ""),
        "standard_name": record.get("standard_name", ""),
        "source_type": record.get("source_type", ""),
        "official_status": record.get("official_status", ""),
        "replacement_standard": record.get("replacement_standard", ""),
        "official_source_url": record.get("official_source_url", ""),
        "official_fulltext_url": record.get("official_fulltext_url", ""),
        "downloadability": record.get("downloadability", ""),
        "authorization": record.get("authorization", ""),
        "confidentiality": record.get("confidentiality", ""),
    }


def _failure_entry(
    record: dict[str, Any],
    status: str,
    note: str,
) -> dict[str, Any]:
    entry = _base_entry(record)
    entry.update(
        {
            "acquisition_status": status,
            "download_url": record.get("official_fulltext_url", ""),
            "final_url": "",
            "local_file": "",
            "sha256": "",
            "size_bytes": 0,
            "acquisition_note": note,
        }
    )
    return entry


def _unavailable_note(record: dict[str, Any]) -> str:
    downloadability = str(record.get("downloadability") or "")
    authorization = str(record.get("authorization") or "")
    if downloadability == "需内部提供":
        return "需由内部文控或资料所有者提供已授权原件；未从外部网络搜索替代副本。"
    if downloadability == "需正版获取":
        return "需通过正版购买或单位许可取得；未使用镜像、网盘或转载全文。"
    if downloadability == "仅元数据":
        return "官方平台仅提供元数据，未发现可归档的官方公开全文入口。"
    if downloadability == "无官方全文":
        return "审计未发现官方全文入口。"
    if downloadability == "仅在线阅读":
        return "官网因版权限制仅允许在线阅读，未授权离线下载和打包。"
    return f"需继续核验官方来源或授权；当前授权状态：{authorization or '未记录'}。"


def _write_reports(
    *,
    entries: list[dict[str, Any]],
    catalog_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    status_counts = dict(sorted(Counter(e["acquisition_status"] for e in entries).items()))
    acquired = [entry for entry in entries if entry.get("local_file")]
    acquired_files = sorted({str(entry["local_file"]) for entry in acquired})
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "catalog_file": str(catalog_path.resolve()),
        "catalog_sha256": _sha256(catalog_path),
        "record_count": len(entries),
        "acquired_record_count": len(acquired),
        "acquired_file_count": len(acquired_files),
        "remaining_count": len(entries) - len(acquired),
        "status_counts": status_counts,
        "policy": (
            "仅下载官方公开全文或复制已明确授权的本地语料；不绕过登录、付费、会话、"
            "验证码或访问控制，不使用镜像、网盘及非授权转载。"
        ),
        "entries": entries,
    }
    manifest_path = output_dir / "下载清单.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    columns = [
        "source_id",
        "standard_code",
        "standard_name",
        "source_type",
        "acquisition_status",
        "downloadability",
        "authorization",
        "confidentiality",
        "official_status",
        "replacement_standard",
        "official_source_url",
        "official_fulltext_url",
        "download_url",
        "final_url",
        "local_file",
        "sha256",
        "size_bytes",
        "acquisition_note",
    ]
    with (output_dir / "逐条获取结果.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(entries)

    with (output_dir / "未获取清单.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(entry for entry in entries if not entry.get("local_file"))

    readme = (
        "# 建筑结构总图规范语料统一目录\n\n"
        f"- 审计记录：{len(entries)} 条\n"
        f"- 已覆盖审计记录：{len(acquired)} 条\n"
        f"- 已取得 PDF 文件：{len(acquired_files)} 个\n"
        f"- 尚未取得：{len(entries) - len(acquired)} 条\n"
        f"- 状态统计：{json.dumps(status_counts, ensure_ascii=False)}\n\n"
        "实际规范文件与现有 HAF 文件均直接放在本目录。逐条证据、官方来源、"
        "授权状态、哈希和失败原因见《下载清单.json》及两个 CSV。\n\n"
        "本目录不包含需要购买、内部文控提供或尚未确认离线使用权的全文。\n"
    )
    (output_dir / "README_下载说明.md").write_text(readme, encoding="utf-8")
    return manifest


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_code(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


def _fetch_with_httpx(url: str) -> FetchedResource:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.Client(follow_redirects=True, timeout=8)
    response = _HTTP_CLIENT.get(
        url,
        headers={
            "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        },
    )
    response.raise_for_status()
    return FetchedResource(
        final_url=str(response.url),
        content_type=response.headers.get("Content-Type", ""),
        body=response.content,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="逐条获取 509 条建筑结构总图规范中的官方公开或已授权全文。"
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = acquire_catalog(
        catalog_path=args.catalog,
        source_manifest_path=args.source_manifest,
        output_dir=args.output,
    )
    print(json.dumps({key: manifest[key] for key in (
        "record_count", "acquired_record_count", "acquired_file_count", "remaining_count", "status_counts"
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
