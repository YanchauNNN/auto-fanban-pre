from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .standards_audit import AuditRecord, normalize_standard_code


OPENSTD_BASE_URL = "https://openstd.samr.gov.cn"
OPENSTD_SEARCH_URL = f"{OPENSTD_BASE_URL}/bzgk/std/std_list"
INDUSTRY_BASE_URL = "https://hbba.sacinfo.org.cn"
ATLAS_SEARCH_URL = "https://www.chinabuilding.com.cn/search"


@dataclass
class OfficialEvidence:
    standard_code: str = ""
    standard_name: str = ""
    official_status: str = ""
    replacement_standard: str = ""
    replaced_standard: str = ""
    publication_date: str = ""
    implementation_date: str = ""
    issuing_authority: str = ""
    official_source_url: str = ""
    official_fulltext_url: str = ""
    downloadability: str = ""
    authorization: str = ""
    confidentiality: str = ""
    evidence_checked_at: str = ""
    evidence_note: str = ""

    @classmethod
    def failure(cls, message: str, source_url: str = "") -> OfficialEvidence:
        return cls(
            official_status="核验失败",
            official_source_url=source_url,
            evidence_checked_at=_checked_at(),
            evidence_note=f"官方来源核验失败：{message}",
        )


class _MetadataClient:
    timeout_seconds = 20

    def _request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        request_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            **(headers or {}),
        }
        request = Request(url, data=data, headers=request_headers)
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read()


class NationalStandardClient(_MetadataClient):
    def lookup(self, standard_code: str) -> OfficialEvidence:
        normalized = normalize_standard_code(standard_code)
        search_url = f"{OPENSTD_SEARCH_URL}?{urlencode({'p.p2': normalized})}"
        try:
            search_html = self._request(search_url).decode("utf-8", "replace")
            detail_url = _find_openstd_detail_url(search_html, normalized)
            if not detail_url:
                return OfficialEvidence(
                    standard_code=normalized,
                    official_status="官方未匹配",
                    official_source_url=search_url,
                    downloadability="无官方全文",
                    evidence_checked_at=_checked_at(),
                    evidence_note="国家标准全文公开系统未匹配到标准编号。",
                )
            detail_html = self._request(
                detail_url,
                headers={"Referer": search_url},
            ).decode("utf-8", "replace")
            return parse_openstd_detail(detail_html, detail_url)
        except (OSError, URLError, ValueError) as exc:
            return OfficialEvidence.failure(str(exc), search_url)


class IndustryStandardClient(_MetadataClient):
    def lookup(self, standard_code: str) -> OfficialEvidence:
        normalized = normalize_standard_code(standard_code)
        endpoint = f"{INDUSTRY_BASE_URL}/stdQueryList"
        body = urlencode(
            {
                "current": "1",
                "size": "15",
                "key": normalized,
            }
        ).encode("utf-8")
        try:
            payload = json.loads(
                self._request(
                    endpoint,
                    data=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": f"{INDUSTRY_BASE_URL}/stdList",
                    },
                ).decode("utf-8", "replace")
            )
            return parse_industry_result(payload, requested_code=normalized)
        except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
            return OfficialEvidence.failure(str(exc), endpoint)


class AtlasOfficialClient(_MetadataClient):
    def lookup(self, standard_code: str) -> OfficialEvidence:
        normalized = normalize_standard_code(standard_code)
        search_url = f"{ATLAS_SEARCH_URL}?{urlencode({'q': normalized})}"
        try:
            html = self._request(search_url).decode("utf-8", "replace")
            return parse_atlas_result(
                html,
                requested_code=normalized,
                result_url=search_url,
            )
        except (OSError, URLError, ValueError) as exc:
            return OfficialEvidence.failure(str(exc), search_url)


def parse_openstd_detail(html: str, detail_url: str) -> OfficialEvidence:
    parser = _MetadataHtmlParser()
    parser.feed(html)
    table = {key.strip("：: "): value.strip() for key, value in parser.table_rows}
    hcno = parser.download_hcno or _query_value(detail_url, "hcno")
    has_download = bool(parser.download_hcno or "xz_btn" in html)
    fulltext_url = (
        f"{OPENSTD_BASE_URL}/bzgk/std/showGb?type=download&hcno={hcno}"
        if has_download and hcno
        else ""
    )
    note = (
        "页面提供官方人工下载入口；自动下载未授权，未尝试绕过会话或访问控制。"
        if fulltext_url
        else "官方详情页未提供全文下载入口。"
    )
    def value(*labels: str) -> str:
        return _first(table, *labels) or _metadata_value(parser.texts, *labels)

    return OfficialEvidence(
        standard_code=value("标准号", "标准编号"),
        standard_name=value("中文标准名称", "标准名称"),
        official_status=value("标准状态", "状态"),
        replacement_standard=value("被代替标准", "替代标准"),
        replaced_standard=value("代替标准"),
        publication_date=value("发布日期"),
        implementation_date=value("实施日期"),
        issuing_authority=value("发布部门", "主管部门"),
        official_source_url=detail_url,
        official_fulltext_url=fulltext_url,
        downloadability="可人工下载" if fulltext_url else "无官方全文",
        authorization="待确认",
        confidentiality="公开",
        evidence_checked_at=_checked_at(),
        evidence_note=note,
    )


def parse_industry_result(
    payload: dict[str, Any],
    *,
    requested_code: str,
) -> OfficialEvidence:
    normalized = normalize_standard_code(requested_code)
    records = payload.get("records") or []
    exact = next(
        (
            item
            for item in records
            if normalize_standard_code(item.get("code")) == normalized
        ),
        None,
    )
    if exact is None:
        return OfficialEvidence(
            standard_code=normalized,
            official_status="官方未匹配",
            official_source_url=f"{INDUSTRY_BASE_URL}/stdList",
            downloadability="仅元数据",
            authorization="待确认",
            confidentiality="公开",
            evidence_checked_at=_checked_at(),
            evidence_note="全国标准信息公共服务平台行业标准备案未匹配到标准编号。",
        )
    detail_url = f"{INDUSTRY_BASE_URL}/stdDetail/{exact.get('pk', '')}"
    return OfficialEvidence(
        standard_code=normalize_standard_code(exact.get("code")),
        standard_name=str(exact.get("chName") or "").strip(),
        official_status=str(exact.get("status") or "").strip(),
        publication_date=_epoch_millis_date(exact.get("issueDate")),
        implementation_date=_epoch_millis_date(exact.get("actDate")),
        issuing_authority=str(exact.get("chargeDept") or "").strip(),
        official_source_url=detail_url,
        downloadability="仅元数据",
        authorization="待确认",
        confidentiality="公开",
        evidence_checked_at=_checked_at(),
        evidence_note="行业标准备案平台提供元数据；未发现可授权收录的官方全文入口。",
    )


def parse_atlas_result(
    html: str,
    *,
    requested_code: str,
    result_url: str,
) -> OfficialEvidence:
    normalized = normalize_standard_code(requested_code)
    parser = _MetadataHtmlParser()
    parser.feed(html)
    text = " ".join(parser.texts)
    matched = normalized.replace(" ", "") in text.replace(" ", "").upper()
    purchase_url = next(
        (
            urljoin(result_url, href)
            for label, href in parser.links
            if "购买" in label or "正版" in label
        ),
        "",
    )
    return OfficialEvidence(
        standard_code=normalized,
        standard_name=next(
            (
                item.strip()
                for item in parser.headings
                if normalized.replace(" ", "") in item.replace(" ", "").upper()
            ),
            "",
        ),
        official_status="正版可购" if matched and purchase_url else "待人工核验",
        official_source_url=purchase_url or result_url,
        downloadability="需正版获取",
        authorization="单位授权待确认",
        confidentiality="内部",
        evidence_checked_at=_checked_at(),
        evidence_note="正版图集仅记录官方检索/购买入口；未下载、未复制未授权内容。",
    )


def apply_official_evidence(
    record: AuditRecord,
    evidence: OfficialEvidence,
) -> AuditRecord:
    record_fields = {item.name for item in fields(AuditRecord)}
    for name, value in evidence.__dict__.items():
        if name in record_fields and value not in ("", None):
            setattr(record, name, value)
    return record


def _find_openstd_detail_url(html: str, standard_code: str) -> str:
    normalized_flat = normalize_standard_code(standard_code).replace(" ", "")
    candidates = re.findall(
        r"""(?:href=["'])([^"']*newGbInfo\?hcno=[A-Za-z0-9]+)[^"']*["']""",
        html,
        flags=re.IGNORECASE,
    )
    if not candidates:
        candidates = [
            f"/bzgk/std/newGbInfo?hcno={hcno}"
            for hcno in re.findall(
                r"""showInfo\(\s*["']([A-Za-z0-9]+)["']\s*\)""",
                html,
                flags=re.IGNORECASE,
            )
        ]
    if not candidates:
        return ""
    if normalized_flat not in re.sub(r"\s+", "", html).upper():
        return ""
    return urljoin(OPENSTD_BASE_URL, candidates[0].replace("&amp;", "&"))


def _query_value(url: str, key: str) -> str:
    match = re.search(rf"(?:\?|&){re.escape(key)}=([^&#]+)", url)
    return match.group(1) if match else ""


def _first(values: dict[str, str], *keys: str) -> str:
    return next((values[key] for key in keys if values.get(key)), "")


def _metadata_value(texts: list[str], *labels: str) -> str:
    for index, item in enumerate(texts):
        normalized = item.strip()
        for label in labels:
            if not normalized.startswith(label):
                continue
            tail = normalized[len(label) :].lstrip("：: ").strip()
            if tail:
                return tail
            if index + 1 < len(texts):
                return texts[index + 1].strip()
    return ""


def _epoch_millis_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(
            int(value) / 1000,
            tz=timezone(timedelta(hours=8)),
        ).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _checked_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class _MetadataHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.table_rows: list[tuple[str, str]] = []
        self.download_hcno = ""
        self.headings: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.texts: list[str] = []
        self._cell_tag = ""
        self._cell_text: list[str] = []
        self._row_cells: list[tuple[str, str]] = []
        self._heading_tag = ""
        self._heading_text: list[str] = []
        self._link_href = ""
        self._link_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attr_map = dict(attrs)
        if tag in {"th", "td"}:
            self._cell_tag = tag
            self._cell_text = []
        if tag in {"h1", "h2", "h3"}:
            self._heading_tag = tag
            self._heading_text = []
        if tag == "a":
            self._link_href = attr_map.get("href") or ""
            self._link_text = []
        classes = (attr_map.get("class") or "").split()
        if "xz_btn" in classes:
            self.download_hcno = (
                attr_map.get("data-hcno")
                or attr_map.get("data-value")
                or attr_map.get("hcno")
                or self.download_hcno
            )

    def handle_data(self, data: str) -> None:
        clean = re.sub(r"\s+", " ", data).strip()
        if clean:
            self.texts.append(clean)
            if self._cell_tag:
                self._cell_text.append(clean)
            if self._heading_tag:
                self._heading_text.append(clean)
            if self._link_href:
                self._link_text.append(clean)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell_tag == tag:
            self._row_cells.append((tag, " ".join(self._cell_text)))
            self._cell_tag = ""
            self._cell_text = []
        if tag == "tr":
            keys = [value for cell_tag, value in self._row_cells if cell_tag == "th"]
            values = [value for cell_tag, value in self._row_cells if cell_tag == "td"]
            if keys and values:
                self.table_rows.append((keys[0], values[0]))
            self._row_cells = []
        if tag == self._heading_tag:
            self.headings.append(" ".join(self._heading_text))
            self._heading_tag = ""
            self._heading_text = []
        if tag == "a" and self._link_href:
            self.links.append((" ".join(self._link_text), self._link_href))
            self._link_href = ""
            self._link_text = []
