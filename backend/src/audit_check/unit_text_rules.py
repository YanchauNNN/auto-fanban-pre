from __future__ import annotations

import re
from collections.abc import Iterable, Iterator


def mask_mtext_formatting(text: str) -> str:
    """Hide MText control sequences without changing character offsets."""
    masked = list(text)
    index = 0
    while index < len(text):
        character = text[index]
        if character in "{}":
            masked[index] = " "
            index += 1
            continue
        if character != "\\" or index + 1 >= len(text):
            index += 1
            continue

        command = text[index + 1]
        masked[index] = " "
        if command in "\\{}":
            index += 2
            continue
        if command in "LlOoKkPpXx~":
            masked[index + 1] = " "
            index += 2
            continue

        terminator = text.find(";", index + 2)
        if terminator < 0:
            masked[index + 1] = " "
            index += 2
            continue
        masked[index : terminator + 1] = [" "] * (terminator + 1 - index)
        index = terminator + 1
    return "".join(masked)


def compile_unit_text_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern_text in patterns:
        normalized = str(pattern_text or "").strip()
        if not normalized:
            continue
        pattern = re.compile(normalized, re.IGNORECASE)
        if "unit_no" not in pattern.groupindex:
            raise ValueError("unit text pattern must define a named unit_no group")
        compiled.append(pattern)
    return compiled


def compile_protected_text_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [
        re.compile(normalized, re.IGNORECASE)
        for pattern_text in patterns
        if (normalized := str(pattern_text or "").strip())
    ]


def iter_unprotected_unit_text_matches(
    text: str,
    *,
    unit_patterns: Iterable[re.Pattern[str]],
    protected_patterns: Iterable[re.Pattern[str]],
) -> Iterator[re.Match[str]]:
    visible_text = mask_mtext_formatting(text)
    protected_spans = [
        match.span()
        for pattern in protected_patterns
        for match in pattern.finditer(visible_text)
    ]
    for pattern in unit_patterns:
        for match in pattern.finditer(visible_text):
            unit_span = match.span("unit_no")
            if any(_spans_overlap(unit_span, protected_span) for protected_span in protected_spans):
                continue
            yield match


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]
