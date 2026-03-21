from __future__ import annotations

import re

_SEPARATOR_RE = re.compile(r"[、，,。\.；;]+")
_RANGE_SEP_RE = re.compile(r"[~-]")
_VALID_NUMBER_RE = re.compile(r"^\d{1,3}$")


class UpgradeSheetCodeParseError(ValueError):
    def __init__(self, invalid_fragments: list[str]):
        self.invalid_fragments = invalid_fragments
        fragments = ", ".join(self.invalid_fragments)
        super().__init__(f"invalid upgrade sheet code fragments: {fragments}")


def get_upgrade_note_text(project_no: str | None) -> str:
    return "升版 upgrade" if str(project_no or "").strip() == "1818" else "升版"


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
