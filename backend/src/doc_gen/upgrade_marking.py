from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_SEPARATOR_RE = re.compile(r"[、，,。.；;]+")
_RANGE_SEP_RE = re.compile(r"[~-]")
_VALID_NUMBER_RE = re.compile(r"^\d{1,3}$")
_VALID_REVISION_RE = re.compile(r"^[A-Z0-9]+$")


@dataclass(frozen=True)
class UpgradeEntry:
    revision: str
    sheet_codes: list[str]
    is_added: bool = False


class UpgradeSheetCodeParseError(ValueError):
    def __init__(self, invalid_fragments: list[str]):
        self.invalid_fragments = invalid_fragments
        fragments = ", ".join(self.invalid_fragments)
        super().__init__(f"invalid upgrade sheet code fragments: {fragments}")


class UpgradeEntryParseError(ValueError):
    def __init__(self, error_code: str, detail: str = ""):
        self.error_code = error_code
        self.detail = detail
        message = f"invalid upgrade entries: {error_code}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


def get_upgrade_note_text(project_no: str | None) -> str:
    return "升版 upgrade" if str(project_no or "").strip() == "1818" else "升版"


def get_added_note_text(project_no: str | None) -> str:
    return "新增Add" if str(project_no or "").strip() == "1818" else "新增"


def parse_upgrade_sheet_codes(raw_value: str | None) -> list[str]:
    text = str(raw_value or "").strip()
    if not text:
        return []

    fragments = [fragment.strip() for fragment in _SEPARATOR_RE.split(text) if fragment.strip()]
    codes: set[str] = set()
    invalid_fragments: list[str] = []

    for fragment in fragments:
        try:
            for code in _parse_fragment(fragment):
                codes.add(code)
        except ValueError:
            invalid_fragments.append(fragment)

    if invalid_fragments:
        raise UpgradeSheetCodeParseError(invalid_fragments=invalid_fragments)

    return sorted(codes)


def parse_upgrade_entries(raw_value: Any) -> list[UpgradeEntry]:
    payload = _load_upgrade_entries_payload(raw_value)
    if not payload:
        return []

    if not isinstance(payload, list):
        raise UpgradeEntryParseError("not_a_list")

    entries: list[UpgradeEntry] = []
    code_owner: dict[str, int] = {}

    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise UpgradeEntryParseError("entry_not_object", str(index))

        revision = str(item.get("revision") or "").strip().upper()
        raw_sheet_codes = str(item.get("sheet_codes") or "").strip()
        is_added = _coerce_bool(item.get("is_added"))

        if not revision and not raw_sheet_codes and not is_added:
            continue
        if not revision or _VALID_REVISION_RE.fullmatch(revision) is None:
            raise UpgradeEntryParseError("invalid_revision", str(index))

        try:
            sheet_codes = parse_upgrade_sheet_codes(raw_sheet_codes)
        except UpgradeSheetCodeParseError as exc:
            raise UpgradeEntryParseError("invalid_sheet_codes", ",".join(exc.invalid_fragments)) from exc

        if is_added and not sheet_codes:
            raise UpgradeEntryParseError("added_without_sheet_codes", str(index))

        for code in sheet_codes:
            if code in code_owner:
                raise UpgradeEntryParseError("duplicate_sheet_code", code)
            code_owner[code] = index

        entries.append(UpgradeEntry(revision=revision, sheet_codes=sheet_codes, is_added=is_added))

    return entries


def resolve_highest_upgrade_revision(entries: list[UpgradeEntry]) -> str:
    revisions = [entry.revision for entry in entries if entry.revision]
    if not revisions:
        return ""
    return max(revisions, key=_revision_sort_key)


def _parse_fragment(fragment: str) -> list[str]:
    range_parts = [part.strip() for part in _RANGE_SEP_RE.split(fragment)]
    separators = _RANGE_SEP_RE.findall(fragment)

    if not separators:
        return [_normalize_code(fragment)]

    if len(separators) != 1 or len(range_parts) != 2:
        raise ValueError(fragment)

    start = _normalize_code(range_parts[0])
    end = _normalize_code(range_parts[1])
    start_no = int(start)
    end_no = int(end)

    if start_no > end_no:
        raise ValueError(fragment)

    return [f"{number:03d}" for number in range(start_no, end_no + 1)]


def _normalize_code(value: str) -> str:
    text = value.strip()
    if not _VALID_NUMBER_RE.fullmatch(text):
        raise ValueError(value)

    number = int(text)
    if number < 1 or number > 999:
        raise ValueError(value)

    return f"{number:03d}"


def _load_upgrade_entries_payload(raw_value: Any) -> Any:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return []
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise UpgradeEntryParseError("invalid_json", exc.msg) from exc
    return raw_value


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _revision_sort_key(revision: str) -> tuple[tuple[int, int | str], ...]:
    parts = re.findall(r"[A-Z]+|\d+", revision.upper())
    if not parts:
        return ((0, revision.upper()),)

    key: list[tuple[int, int | str]] = []
    for part in parts:
        if part.isdigit():
            key.append((1, int(part)))
        else:
            key.append((0, part))
    return tuple(key)
