from __future__ import annotations

from pathlib import Path

import pytest

from src.ai.standards_downloader import (
    FetchedResource,
    UnsafeDownloadError,
    classify_unavailable,
    download_record,
    inspect_existing_download,
    is_public_authorized_candidate,
    safe_filename,
)


def _record(**overrides: str) -> dict[str, str]:
    record = {
        "source_id": "STD-0001",
        "standard_code": "GB/T 1234-2024",
        "standard_name": "测试标准",
        "official_fulltext_url": (
            "https://openstd.samr.gov.cn/bzgk/std/showGb?type=download&hcno=ABC"
        ),
        "downloadability": "可人工下载",
        "authorization": "待确认",
        "confidentiality": "公开",
    }
    record.update(overrides)
    return record


def test_only_public_records_with_an_official_fulltext_url_are_candidates() -> None:
    assert is_public_authorized_candidate(_record())
    assert not is_public_authorized_candidate(_record(confidentiality="内部"))
    assert not is_public_authorized_candidate(_record(official_fulltext_url=""))
    assert not is_public_authorized_candidate(_record(downloadability="需正版获取"))


@pytest.mark.parametrize(
    ("downloadability", "expected"),
    [
        ("需内部提供", "internal_source_required"),
        ("需正版获取", "licensed_copy_required"),
        ("仅元数据", "metadata_only"),
        ("无官方全文", "no_official_fulltext"),
        ("仅在线阅读", "online_reading_only"),
        ("待官方核验", "official_verification_required"),
    ],
)
def test_unavailable_records_keep_their_real_reason(
    downloadability: str,
    expected: str,
) -> None:
    assert classify_unavailable(_record(downloadability=downloadability)) == expected


def test_download_record_saves_a_real_pdf_and_hash(tmp_path: Path) -> None:
    pdf = b"%PDF-1.7\n" + b"0" * 2048

    def fetch(_url: str) -> FetchedResource:
        return FetchedResource(
            final_url="https://openstd.samr.gov.cn/files/example.pdf",
            content_type="application/pdf",
            body=pdf,
        )

    result = download_record(_record(), tmp_path, fetcher=fetch)

    assert result.status == "downloaded"
    assert result.path is not None
    assert result.path.read_bytes() == pdf
    assert result.sha256 == "8209e55d5b9c865c698b0e288dda23c90a5d9f5296b6fee71d353ceb3c517cb2"
    assert result.path.name == "GB_T 1234-2024_测试标准.pdf"


def test_download_record_rejects_html_detail_page_as_manual_interaction(
    tmp_path: Path,
) -> None:
    def fetch(_url: str) -> FetchedResource:
        return FetchedResource(
            final_url="https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=ABC",
            content_type="text/html;charset=UTF-8",
            body=b"<html><title>standard detail</title></html>",
        )

    result = download_record(_record(), tmp_path, fetcher=fetch)

    assert result.status == "manual_interaction_required"
    assert result.path is None
    assert not list(tmp_path.iterdir())


def test_download_record_rejects_redirect_to_unapproved_host(tmp_path: Path) -> None:
    def fetch(_url: str) -> FetchedResource:
        return FetchedResource(
            final_url="https://mirror.example.com/example.pdf",
            content_type="application/pdf",
            body=b"%PDF-1.7\n" + b"0" * 2048,
        )

    with pytest.raises(UnsafeDownloadError, match="非官方域名"):
        download_record(_record(), tmp_path, fetcher=fetch)


def test_existing_browser_download_is_recognized_and_hashed(tmp_path: Path) -> None:
    pdf = b"%PDF-1.7\n" + b"browser" * 300
    path = tmp_path / safe_filename("GB/T 1234-2024", "测试标准")
    path.write_bytes(pdf)

    result = inspect_existing_download(_record(), tmp_path)

    assert result is not None
    assert result.status == "existing_official_browser_download"
    assert result.path == path
    assert result.sha256 == "7f00c92759ee823f9d7cfbfa4aeeb82e03fb3c6cdfafeb4b550ba202a80b7b9c"
