# Standards Reviewed Evidence Implementation Plan

> **For Codex:** Execute the existing standards-quality plan in this worktree, with failing regression tests before implementation.

**Goal:** Close the four original-page counterexamples without changing their expected answers, promoting unreviewed pages, running bulk OCR, or replacing the active corpus.

**Architecture:** Keep the 504-source candidate and all native/OCR pages unchanged. Replay narrowly scoped, PDF-SHA256-bound visual transcription reviews onto a separate candidate database; retain the original record and review provenance. Separate record transcription quality from standard currency/authorization checks, and keep the latter blocking final design advice.

**Tech Stack:** Existing Python, SQLite, PyMuPDF, pytest and skill packaging; no additional runtime dependencies or model calls.

## Progress And Target

- Existing fixes committed as `0bb22b9`; push attempted twice but the GitHub connection reset, and an independent HTTPS request timed out. No force push or global network changes.
- Original 504-source active database is protected. Candidate: 50,410 pages, 158,684 clauses, 59,559 table records. Old native pages/tables are preserved.
- Prior independent acceptance: 0/4; safety regression: 6/6. Candidate still has 83 sources without recognized clauses and 7,306 low-text pages. These are not in this execution batch.
- Final product remains an offline, backend-hosted, citable standards skill usable by development MiniMax and terminal Qwen. This batch validates the correction loop, not all 504 standards or engineering decisions.

## Tasks

1. [x] Verify current changes, rerun AI tests, commit scoped files; attempt push and report network failure.
2. [x] Visually review GB 50223 p7, GB 50367 p22-23, GB 50098 p15-17; retain rendered-page hashes and transcribe complete target records, including table headers and notes.
3. [x] Add failing tests in `backend/tests/unit/ai/test_standards_reviews.py`: valid replay, cross-PDF/stale-text rejection, cross-page coverage, adjacent-record isolation, tamper rejection, original-DB preservation and source-status gating.
4. [x] Implement `tools/ai/building-structure-standards/scripts/standards_reviews.py` and `apply_evidence_reviews.py`; add bounded record-level review consumption to `standards_query.py` without changing source status or raw pages. Store reviewed data in `assets/data/reviewed_evidence_20260903.json`, separate from the validation set.
5. [x] Run the replay tool against a separate `storage/ai/standards-reviewed-20260903/` output. Rerun original independent references unchanged, check all native pages/tables preserved, and verify unrelated records remain restricted.
6. [x] Run relevant unit/AI/package tests, update handoff with results and remaining deployment/quality gaps. No active-database replacement, service restart, full OCR or main changes.

The plan was moved from ignored `docs/plans/` to the repository's versioned `documents/AI/plans/` convention. Results are recorded in `documents/AI/规范定向复核执行结果_20260903.md`. The original GitHub push remains blocked by connectivity; this task does not claim it succeeded.

## Contract

- Reviews cover a complete clause (including continuation pages) or a complete table, never imply page/book approval.
- A review binds to actual PDF SHA256, code, record id, physical page span, original-record fingerprint, reviewed text/cells, printed-page labels, reviewer, method, review timestamp and rendered-page hashes.
- Mismatched PDF/text, missing pages, duplicate or malformed records fail the offline replay before output publication. Query-time changed records invalidate the review.
- Raw native/OCR pages and original table data are preserved; original corrected records are additionally retained in the review audit table. Reviewed text becomes searchable.
- `quality_status` describes the record's content quality; `design_advice_allowed` still requires valid source status, authorization, normative role and complete evidence. A visual transcription review is not engineering approval.
- No answers are generated from the database under test to rewrite the original independent gold file.

## Verification

Run from `E:\project\auto-fanban-pre\.worktrees\codex-calculation-ai-unified` with the existing `backend/.venv`, fresh short TEMP basetemp and `-o addopts= -p no:cacheprovider`:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/ai/test_standards_reviews.py backend/tests/unit/ai/test_standards_query_safety.py -q -o addopts= -p no:cacheprovider
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/ai -q -o addopts= -p no:cacheprovider
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_terminal_deploy_builder.py -q -o addopts= -p no:cacheprovider
```

Expected: original 4 counterexamples pass only after verified corrections; non-reviewed/source-status negative cases remain blocked. Any failed content assertion remains explicit, and no whole-corpus accuracy claim follows from this small reference set.
