from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import build_corpus as corpus


def enrich_with_ocr(
    current: corpus.ParsedSource, baseline: corpus.ParsedSource
) -> corpus.ParsedSource:
    if current.source_sha256 != baseline.source_sha256:
        raise ValueError("cannot merge OCR from a different PDF")
    if [page.page_number for page in current.pages] != [
        page.page_number for page in baseline.pages
    ]:
        raise ValueError("baseline physical pages do not match cached PDF pages")
    for page, prior in zip(current.pages, baseline.pages, strict=True):
        if prior.ocr_text:
            page.ocr_text = prior.ocr_text
            page.ocr_confidence = prior.ocr_confidence
            page.ocr_provenance = dict(prior.ocr_provenance)
            page.quality_flags = list(
                dict.fromkeys([*page.quality_flags, *prior.quality_flags])
            )
            if prior.quality_status in {"review_required", "failed"}:
                page.quality_status = "review_required"
        if not page.printed_page:
            page.printed_page = prior.printed_page
    return current


class BaselineSources:
    """Read-only, content-addressed access to prior native/OCR candidates."""

    def __init__(self, databases: list[Path | str]) -> None:
        self.sources: dict[str, tuple[Path, int, str]] = {}
        for value in databases:
            path = Path(value).resolve(strict=True)
            database_sha = corpus._sha256(path)
            connection = self._connect(path)
            try:
                for row in connection.execute(
                    "SELECT source_id, source_sha256 FROM sources"
                ):
                    self.sources[row["source_sha256"]] = (
                        path,
                        row["source_id"],
                        database_sha,
                    )
            finally:
                connection.close()

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def read(self, sha256: str, spec: corpus.SourceSpec) -> corpus.ParsedSource | None:
        match = self.sources.get(sha256)
        if match is None:
            return None
        path, source_id, database_sha = match
        pages = []
        tables = []
        connection = self._connect(path)
        try:
            for record in connection.execute(
                "SELECT * FROM pages WHERE source_id=? ORDER BY page_number",
                (source_id,),
            ):
                row = dict(record)
                text_source = str(row.get("text_source") or "native")
                provenance: dict[str, Any] = json.loads(
                    row.get("ocr_provenance_json") or "{}"
                )
                provenance.update(
                    {
                        "source_sha256": sha256,
                        "physical_page": row["page_number"],
                        "baseline_database_sha256": database_sha,
                        "reuse_status": "candidate",
                        "parser_version": corpus.PARSER_VERSION,
                    }
                )
                pages.append(
                    corpus.PageRecord(
                        page_number=row["page_number"],
                        printed_page=row["printed_page"],
                        text=row["text"],
                        anchor=row["anchor"],
                        native_text=row.get(
                            "native_text",
                            row["text"] if text_source == "native" else "",
                        ),
                        ocr_text=row.get("ocr_text", ""),
                        text_source=text_source,
                        ocr_confidence=float(row.get("ocr_confidence") or 0),
                        quality_status=row.get(
                            "quality_status", row.get("quality", "review_required")
                        ),
                        quality_flags=json.loads(row.get("quality_flags_json") or "[]"),
                        ocr_provenance=provenance,
                    )
                )
            for record in connection.execute(
                "SELECT * FROM standard_tables WHERE source_id=?", (source_id,)
            ):
                row = dict(record)
                tables.append(
                    corpus.TableRecord(
                        table_id=row["table_id"],
                        page_number=row["page_number"],
                        rows=json.loads(row["rows_json"]),
                        markdown=row["markdown"],
                        anchor=row["anchor"],
                        quality_status=row.get("quality_status", "review_required"),
                        table_label=row.get("table_label", ""),
                        quality_flags=json.loads(row.get("quality_flags_json") or "[]")
                        + (
                            ["legacy_table_candidate"]
                            if "quality_status" not in row
                            else []
                        ),
                    )
                )
        finally:
            connection.close()
        if not pages or [page.page_number for page in pages] != list(
            range(1, len(pages) + 1)
        ):
            raise ValueError(
                f"baseline has missing/duplicate physical pages for {sha256}"
            )
        return corpus.ParsedSource(spec, sha256, pages, [], tables)
