from __future__ import annotations


def make_document_output_name(
    *,
    external_code: str | None,
    revision: str | None,
    status: str | None,
    internal_code: str | None,
    fallback_name: str,
) -> str:
    external = (external_code or "").strip()
    rev = (revision or "").strip()
    doc_status = (status or "").strip()
    internal = (internal_code or "").strip()

    if external and internal:
        prefix = f"{external}{rev}{doc_status}" if rev and doc_status else external
        return f"{prefix} ({internal})"
    if internal:
        return internal
    if external:
        return external
    return fallback_name
