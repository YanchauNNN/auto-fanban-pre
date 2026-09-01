from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

OFFICIAL_DOWNLOAD_HOSTS = frozenset(
    {
        "openstd.samr.gov.cn",
        "std.samr.gov.cn",
        "www.mee.gov.cn",
        "mee.gov.cn",
        "nnsa.mee.gov.cn",
        "www.mohurd.gov.cn",
        "mohurd.gov.cn",
    }
)
PUBLIC_DOWNLOADABILITY = frozenset({"可下载", "可人工下载", "公开下载"})
UNAVAILABLE_STATUS_BY_DOWNLOADABILITY = {
    "需内部提供": "internal_source_required",
    "需正版获取": "licensed_copy_required",
    "仅元数据": "metadata_only",
    "无官方全文": "no_official_fulltext",
    "仅在线阅读": "online_reading_only",
    "待官方核验": "official_verification_required",
    "需发行机构核验": "publisher_verification_required",
}


class UnsafeDownloadError(ValueError):
    """Raised when a requested or redirected URL is outside the official allow-list."""


@dataclass(frozen=True)
class FetchedResource:
    final_url: str
    content_type: str
    body: bytes


@dataclass(frozen=True)
class DownloadResult:
    source_id: str
    standard_code: str
    status: str
    source_url: str
    final_url: str = ""
    path: Path | None = None
    sha256: str = ""
    size_bytes: int = 0
    note: str = ""


Fetcher = Callable[[str], FetchedResource]


def is_public_authorized_candidate(record: Mapping[str, object]) -> bool:
    return bool(
        str(record.get("official_fulltext_url") or "").strip()
        and str(record.get("confidentiality") or "").strip() == "公开"
        and str(record.get("downloadability") or "").strip() in PUBLIC_DOWNLOADABILITY
    )


def classify_unavailable(record: Mapping[str, object]) -> str:
    downloadability = str(record.get("downloadability") or "").strip()
    return UNAVAILABLE_STATUS_BY_DOWNLOADABILITY.get(
        downloadability,
        "not_publicly_downloadable",
    )


def fetch_resource(url: str, *, timeout_seconds: int = 30) -> FetchedResource:
    _require_official_host(url)
    request = Request(
        url,
        headers={
            "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        return FetchedResource(
            final_url=response.geturl(),
            content_type=response.headers.get("Content-Type", ""),
            body=response.read(),
        )


def download_record(
    record: Mapping[str, object],
    output_dir: Path,
    *,
    fetcher: Fetcher = fetch_resource,
) -> DownloadResult:
    source_id = str(record.get("source_id") or "")
    standard_code = str(record.get("standard_code") or "")
    source_url = str(record.get("official_fulltext_url") or "").strip()
    if not is_public_authorized_candidate(record):
        return DownloadResult(
            source_id=source_id,
            standard_code=standard_code,
            status="not_authorized_for_automatic_download",
            source_url=source_url,
            note="记录不是公开且提供官方全文入口的可下载语料。",
        )

    _require_official_host(source_url)
    resource = fetcher(source_url)
    _require_official_host(resource.final_url)

    if _looks_like_html(resource):
        return DownloadResult(
            source_id=source_id,
            standard_code=standard_code,
            status="manual_interaction_required",
            source_url=source_url,
            final_url=resource.final_url,
            note="官方入口返回详情页而非全文；未绕过会话、登录或人工交互。",
        )
    if not resource.body.startswith(b"%PDF-"):
        return DownloadResult(
            source_id=source_id,
            standard_code=standard_code,
            status="invalid_content",
            source_url=source_url,
            final_url=resource.final_url,
            note="响应既不是有效 PDF，也不是可归档的 HTML 正文。",
        )
    if len(resource.body) < 1024:
        return DownloadResult(
            source_id=source_id,
            standard_code=standard_code,
            status="invalid_content",
            source_url=source_url,
            final_url=resource.final_url,
            note="PDF 响应过小，未作为规范全文保存。",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(
        standard_code,
        str(record.get("standard_name") or "未命名标准"),
    )
    path = output_dir / filename
    path.write_bytes(resource.body)
    digest = hashlib.sha256(resource.body).hexdigest()
    return DownloadResult(
        source_id=source_id,
        standard_code=standard_code,
        status="downloaded",
        source_url=source_url,
        final_url=resource.final_url,
        path=path,
        sha256=digest,
        size_bytes=len(resource.body),
        note="已从官方公开全文入口下载并通过 PDF 文件头校验。",
    )


def _require_official_host(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in OFFICIAL_DOWNLOAD_HOSTS:
        raise UnsafeDownloadError(f"拒绝访问或跟随非官方域名：{host or url}")


def _looks_like_html(resource: FetchedResource) -> bool:
    content_type = resource.content_type.lower()
    prefix = resource.body.lstrip()[:256].lower()
    return "text/html" in content_type or prefix.startswith((b"<!doctype html", b"<html"))


def safe_filename(code: str, name: str) -> str:
    raw = f"{code}_{name}".strip("_ ") or "未命名标准"
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw)
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" .")
    return f"{sanitized[:180]}.pdf"


def inspect_existing_download(
    record: Mapping[str, object],
    output_dir: Path,
) -> DownloadResult | None:
    standard_code = str(record.get("standard_code") or "")
    path = output_dir / safe_filename(
        standard_code,
        str(record.get("standard_name") or "未命名标准"),
    )
    if not path.is_file():
        return None
    body = path.read_bytes()
    if not body.startswith(b"%PDF-") or len(body) < 1024:
        return None
    return DownloadResult(
        source_id=str(record.get("source_id") or ""),
        standard_code=standard_code,
        status="existing_official_browser_download",
        source_url=str(record.get("official_fulltext_url") or ""),
        final_url=str(record.get("official_fulltext_url") or ""),
        path=path,
        sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
        note="已通过官网浏览器下载入口取得并通过 PDF 文件头校验。",
    )
