from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .models import AuditFinding, ScanTextItem

_SPACE_RE = re.compile(r"\s+")
_YEAR_SUFFIX_RE = re.compile(r"^(?P<base>.+?)[\s\-—–－]+(?P<year>\d{4})$")
_HYPHEN_TRANSLATION = str.maketrans({"—": "-", "–": "-", "－": "-", "﹣": "-", "‐": "-"})


@dataclass(frozen=True, slots=True)
class StandardEntry:
    canonical_code: str
    code_without_year: str
    expected_year: str | None
    expected_name: str
    source_sheet: str
    source_row: int
    department: str | None = None
    major: str | None = None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class _CodeCandidate:
    item: ScanTextItem
    entry: StandardEntry
    actual_code: str
    actual_year: str | None
    start: int
    end: int


class StandardLibraryLoader:
    """Read standard-code metadata from the structured standard library workbook."""

    def load(self, workbook_path: str | Path, *, sheet_name: str = "DatStdItem") -> list[StandardEntry]:
        path = Path(workbook_path)
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            worksheet = workbook[sheet_name] if sheet_name in workbook.sheetnames else workbook[workbook.sheetnames[1]]
            rows = worksheet.iter_rows(values_only=True)
            try:
                header_values = next(rows)
            except StopIteration:
                return []
            headers = self._headers_from_values(header_values)
            entries: list[StandardEntry] = []
            for row_number, row_values in enumerate(rows, start=2):
                raw_code = self._cell_text(self._row_value(row_values, headers["code"]))
                raw_name = self._cell_text(self._row_value(row_values, headers["name"]))
                if not raw_code or not raw_name or raw_code == "标准号":
                    continue
                raw_version = self._cell_text(self._optional_row_value(row_values, headers, "version"))
                code_without_year, expected_year, canonical_code = _canonicalize_standard_code(
                    raw_code,
                    raw_version,
                )
                if not canonical_code:
                    continue
                entries.append(
                    StandardEntry(
                        canonical_code=canonical_code,
                        code_without_year=code_without_year,
                        expected_year=expected_year,
                        expected_name=raw_name,
                        source_sheet=worksheet.title,
                        source_row=row_number,
                        department=self._optional_cell(row_values, headers, "department"),
                        major=self._optional_cell(row_values, headers, "major"),
                        status=self._optional_cell(row_values, headers, "status"),
                    )
                )
            return entries
        finally:
            workbook.close()

    @staticmethod
    def _headers_from_values(header_values: tuple[Any, ...]) -> dict[str, int]:
        aliases = {
            "code": {"CodeStd", "标准号"},
            "name": {"NameStd", "标准名称"},
            "version": {"Version", "版本"},
            "department": {"Department", "部门"},
            "major": {"Major", "专业"},
            "status": {"Status", "状态"},
        }
        found: dict[str, int] = {}
        for column, raw in enumerate(header_values):
            if raw is None:
                continue
            value = str(raw).strip()
            for key, names in aliases.items():
                if value in names:
                    found[key] = column
        if "code" not in found or "name" not in found:
            raise ValueError("standard library requires CodeStd/NameStd columns")
        return found

    @staticmethod
    def _cell_text(value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if text.endswith(".0") and text[:-2].isdigit():
            return text[:-2]
        return text

    def _optional_cell(
        self,
        row_values: tuple[Any, ...],
        headers: dict[str, int],
        key: str,
    ) -> str | None:
        return self._cell_text(self._optional_row_value(row_values, headers, key)) or None

    @staticmethod
    def _optional_row_value(
        row_values: tuple[Any, ...],
        headers: dict[str, int],
        key: str,
    ) -> object | None:
        column = headers.get(key)
        if column is None:
            return None
        return StandardLibraryLoader._row_value(row_values, column)

    @staticmethod
    def _row_value(row_values: tuple[Any, ...], column: int) -> object | None:
        if column >= len(row_values):
            return None
        return row_values[column]


class StandardReviewEngine:
    def __init__(self, entries: list[StandardEntry], *, same_line_y_tolerance: float) -> None:
        self.entries = entries
        self.same_line_y_tolerance = float(same_line_y_tolerance)
        self._base_entries: dict[str, list[StandardEntry]] = {}
        for entry in entries:
            self._base_entries.setdefault(_normalize_code_key(entry.code_without_year), []).append(entry)
        self._base_patterns = [
            (entry, self._compile_code_pattern(entry.code_without_year))
            for entry in entries
            if entry.expected_year
        ]

    def evaluate(self, items: list[ScanTextItem]) -> list[AuditFinding]:
        code_candidates = self._find_code_candidates(items)
        findings: list[AuditFinding] = []
        for candidate in code_candidates:
            findings.extend(self._year_findings(candidate))
            findings.extend(self._name_findings(candidate, items))
        return findings

    def _find_code_candidates(self, items: list[ScanTextItem]) -> list[_CodeCandidate]:
        candidates: list[_CodeCandidate] = []
        seen: set[tuple[str | None, str, str]] = set()
        for item in items:
            normalized = _normalize_code_text(item.raw_text)
            if not normalized:
                continue
            for pattern_entry, pattern in self._base_patterns:
                for match in pattern.finditer(normalized):
                    actual_year = str(match.group("year") or "")
                    entries = self._base_entries.get(_normalize_code_key(pattern_entry.code_without_year), [])
                    entry = self._select_expected_entry(entries, actual_year) or pattern_entry
                    actual_code = _normalize_standard_code_display(match.group(0))
                    key = (item.entity_handle, actual_code, entry.canonical_code)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(
                        _CodeCandidate(
                            item=item,
                            entry=entry,
                            actual_code=actual_code,
                            actual_year=actual_year,
                            start=match.start(),
                            end=match.end(),
                        )
                    )
        return candidates

    @staticmethod
    def _select_expected_entry(entries: list[StandardEntry], actual_year: str) -> StandardEntry | None:
        for entry in entries:
            if entry.expected_year == actual_year:
                return entry
        return entries[0] if entries else None

    def _year_findings(self, candidate: _CodeCandidate) -> list[AuditFinding]:
        expected_year = candidate.entry.expected_year
        if not expected_year or candidate.actual_year == expected_year:
            return []
        return [
            self._finding(
                candidate=candidate,
                context_kind="standard_review_year",
                details={
                    "issue_type": "year_mismatch",
                    "actual_code": candidate.actual_code,
                    "expected_code": candidate.entry.canonical_code,
                    "actual_year": candidate.actual_year or "",
                    "expected_year": expected_year,
                    "expected_name": candidate.entry.expected_name,
                },
            )
        ]

    def _name_findings(self, candidate: _CodeCandidate, items: list[ScanTextItem]) -> list[AuditFinding]:
        name_item = self._nearest_name_item(candidate, items)
        if name_item is None:
            return [
                self._finding(
                    candidate=candidate,
                    context_kind="standard_review_name",
                    details={
                        "issue_type": "name_missing",
                        "actual_code": candidate.actual_code,
                        "expected_code": candidate.entry.canonical_code,
                        "actual_name": "",
                        "expected_name": candidate.entry.expected_name,
                    },
                )
            ]
        actual_name = str(name_item.raw_text or "").strip()
        if _name_matches(actual_name, candidate.entry.expected_name):
            return []
        return [
            self._finding(
                candidate=candidate,
                context_kind="standard_review_name",
                details={
                    "issue_type": "name_mismatch",
                    "actual_code": candidate.actual_code,
                    "expected_code": candidate.entry.canonical_code,
                    "actual_name": actual_name,
                    "expected_name": candidate.entry.expected_name,
                },
            )
        ]

    def _nearest_name_item(
        self,
        candidate: _CodeCandidate,
        items: list[ScanTextItem],
    ) -> ScanTextItem | None:
        code_y = _item_y(candidate.item)
        if code_y is None:
            return None
        code_x = _item_x(candidate.item) or 0.0
        nearby: list[tuple[float, float, ScanTextItem]] = []
        for item in items:
            if item is candidate.item:
                continue
            text = str(item.raw_text or "").strip()
            if not text or self._looks_like_standard_code(text):
                continue
            item_y = _item_y(item)
            if item_y is None:
                continue
            y_distance = abs(item_y - code_y)
            if y_distance > self.same_line_y_tolerance:
                continue
            item_x = _item_x(item)
            x_distance = abs((item_x or 0.0) - code_x)
            nearby.append((y_distance, x_distance, item))
        if not nearby:
            return None
        return sorted(nearby, key=lambda row: (row[0], row[1]))[0][2]

    def _looks_like_standard_code(self, text: str) -> bool:
        normalized = _normalize_code_text(text)
        return any(pattern.search(normalized) for _, pattern in self._base_patterns)

    @staticmethod
    def _compile_code_pattern(code_without_year: str) -> re.Pattern[str]:
        normalized = _normalize_standard_code_display(code_without_year)
        escaped = re.escape(normalized)
        escaped = escaped.replace(r"\ ", r"\s*")
        return re.compile(rf"(?<![A-Z0-9]){escaped}\s*-\s*(?P<year>\d{{4}})(?!\d)")

    @staticmethod
    def _finding(
        *,
        candidate: _CodeCandidate,
        context_kind: str,
        details: dict[str, Any],
    ) -> AuditFinding:
        return AuditFinding(
            raw_text=candidate.item.raw_text,
            matched_text=candidate.actual_code,
            matched_project_nos=[],
            context_kind=context_kind,
            confidence="high",
            entity_type=candidate.item.entity_type,
            field_context=candidate.item.field_context,
            internal_code=candidate.item.internal_code,
            layout_name=candidate.item.layout_name,
            entity_handle=candidate.item.entity_handle,
            block_path=candidate.item.block_path,
            position_x=candidate.item.position_x,
            position_y=candidate.item.position_y,
            text_bbox=candidate.item.text_bbox,
            details=details,
        )


def _canonicalize_standard_code(raw_code: str, raw_version: str) -> tuple[str, str | None, str]:
    code = _normalize_standard_code_display(raw_code)
    version = str(raw_version or "").strip()
    match = _YEAR_SUFFIX_RE.match(code)
    if match:
        base = _normalize_standard_code_display(match.group("base"))
        year = match.group("year")
        return base, year, f"{base}-{year}"
    if version and re.fullmatch(r"\d{4}", version):
        return code, version, f"{code}-{version}"
    return code, None, code


def _normalize_code_text(value: str) -> str:
    return _SPACE_RE.sub(" ", unicodedata.normalize("NFKC", value or "").translate(_HYPHEN_TRANSLATION)).strip().upper()


def _normalize_standard_code_display(value: str) -> str:
    return _normalize_code_text(value)


def _normalize_code_key(value: str) -> str:
    return re.sub(r"\s+", "", _normalize_standard_code_display(value))


def _normalize_name_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").upper()
    text = text.translate(_HYPHEN_TRANSLATION)
    return re.sub(r"[\s,，、。.:：;；()（）\[\]【】《》<>_\-/\\]+", "", text)


def _name_matches(actual_name: str, expected_name: str) -> bool:
    actual = _normalize_name_key(actual_name)
    expected = _normalize_name_key(expected_name)
    return bool(expected and (actual == expected or expected in actual))


def _item_x(item: ScanTextItem) -> float | None:
    if item.text_bbox is not None:
        return float((item.text_bbox.xmin + item.text_bbox.xmax) / 2.0)
    if item.position_x is not None:
        return float(item.position_x)
    return None


def _item_y(item: ScanTextItem) -> float | None:
    if item.text_bbox is not None:
        return float((item.text_bbox.ymin + item.text_bbox.ymax) / 2.0)
    if item.position_y is not None:
        return float(item.position_y)
    return None
