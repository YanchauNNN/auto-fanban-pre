# Building Standards Full Corpus Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the offline building standards Skill from one indexed PDF to a restartable 504-PDF corpus with secure local/UNC source resolution, page evidence, downloads, probes, and PDF-free deployment packaging.

**Architecture:** Keep SQLite and the current ContextSkill integration. Add a manifest-backed source resolver shared by the Skill and API, then expose only source-id-based evidence endpoints. Build the corpus incrementally with explicit per-source/page quality states and selective OCR instead of parsing every document into memory.

**Tech Stack:** Python 3.10+, FastAPI/Starlette, PyMuPDF, SQLite FTS5, PowerShell, React/Vite/Vitest, pytest.

---

### Task 1: Source access configuration and resolver

**Files:**
- Modify: `documents/AI/参数规范_AI.yaml`
- Modify: `backend/src/config/ai/ai_spec.py`
- Modify: `backend/src/ai/building_standards_skill.py`
- Create: `backend/src/ai/standards_source_resolver.py`
- Test: `backend/tests/unit/ai/test_standards_source_resolver.py`
- Test: `backend/tests/unit/ai/test_ai_spec.py`

**Steps:**
1. Write failing tests for local-first resolution, per-file UNC fallback, path traversal rejection, PDF signature checking and missing files.
2. Run the focused tests and confirm failures are caused by the missing resolver/configuration.
3. Add Pydantic configuration and the resolver with no arbitrary path input.
4. Run the focused tests and existing AI spec tests.

### Task 2: Standards evidence API

**Files:**
- Modify: `API/app/routers/ai.py`
- Modify: `tools/ai/building-structure-standards/scripts/standards_query.py`
- Test: `backend/tests/unit/ai/test_standards_evidence_api.py`
- Test: `backend/tests/unit/ai/test_standards_query.py`

**Steps:**
1. Write failing API tests for page PNG, inline PDF, download, page bounds and missing source.
2. Add `source_id` and relative source path to query results without exposing absolute paths.
3. Implement `FileResponse` document/download endpoints and bounded PyMuPDF page rendering.
4. Verify response headers, content signatures and error codes.

### Task 3: Safe frontend evidence links

**Files:**
- Modify: `frontend/src/features/ai-chat/AiMessageContent.tsx`
- Modify: `frontend/src/features/ai-chat/AiMessageContent.test.tsx`
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.tsx`
- Create or modify: `frontend/src/features/ai-chat/StandardsEvidencePreview.tsx`

**Steps:**
1. Write failing Vitest cases that allow only `/api/ai/standards/...` and reject other relative, `file:`, UNC and script links.
2. Implement strict URL parsing and a page-evidence preview action.
3. Keep normal external `http/https` links using `noopener noreferrer`.
4. Run focused frontend tests.

### Task 4: Optional model page-image evidence

**Files:**
- Modify: `backend/src/ai/context_skills.py`
- Modify: `backend/src/ai/chat_service.py`
- Modify: `backend/src/ai/building_standards_skill.py`
- Test: `backend/tests/unit/ai/test_building_standards_skill.py`
- Test: `backend/tests/unit/ai/test_chat_service.py`

**Steps:**
1. Write failing tests for image-intent detection, page count limits and text-only fallback.
2. Extend Skill context with bounded image evidence descriptors.
3. Render only retrieved pages and append them to the current user multimodal content.
4. Ensure model/profile image support is an explicit configuration gate.
5. Run focused Skill and chat service tests.

### Task 5: Probe and prepare-terminal integration

**Files:**
- Modify: `tools/probe_target_env.ps1`
- Modify: `tools/ai/test_ai_model_connectivity.ps1`
- Modify: `backend/src/deploy/terminal_package.py`
- Test: `backend/tests/unit/test_terminal_deploy_builder.py`
- Test: `backend/tests/unit/ai/test_ai_connectivity_script.py`

**Steps:**
1. Add failing tests for the new probe JSON fields and generated runtime environment lines.
2. Implement directory enumeration and sample PDF read checks for primary and fallback roots.
3. Make `prepare_terminal.ps1` select a usable root and write both environment variables.
4. Treat primary success plus fallback failure as warning, fallback-only success as pass with warning, and double failure as blocking.
5. Run deployment builder and probe script tests.

### Task 6: PDF-free deployment placeholder

**Files:**
- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `tools/ai/package_building_standards_skill.py`
- Test: `backend/tests/unit/test_terminal_deploy_builder.py`
- Test: `backend/tests/unit/ai/test_standards_package.py`

**Steps:**
1. Write a failing package test asserting no `.pdf` exists in the deployment output.
2. Add a generated `documents/规范下载/README_规范文件放置说明.txt`.
3. Exclude Skill source PDFs while retaining SQLite, manifests, scripts and validation reports.
4. Verify full and delta package behavior.

### Task 7: Incremental corpus V2 and 504-file manifest

**Files:**
- Modify: `tools/ai/building-structure-standards/scripts/build_corpus.py`
- Modify: `tools/ai/building-structure-standards/scripts/standards_query.py`
- Create: `tools/ai/building-structure-standards/scripts/inventory_sources.py`
- Create: `tools/ai/building-structure-standards/assets/data/full_source_manifest.json`
- Test: `backend/tests/unit/ai/test_standards_corpus_parser.py`
- Test: `backend/tests/unit/ai/test_standards_query.py`

**Steps:**
1. Write failing tests for per-source transactions, resume, hash duplicate/conflict states, empty-page quality status and FTS5 BM25 queries.
2. Implement streaming/incremental writes without materializing every ParsedSource.
3. Generate a manifest from all PDFs under `documents/规范下载` without copying source files.
4. Run a representative text/scanned/table/conflict sample build and rerun it to prove resume behavior.
5. Record exact indexed, partial, OCR-needed, conflict and failed counts.

### Task 8: Verification

**Steps:**
1. Run all building standards backend tests.
2. Run all AI backend tests and API integration tests.
3. Run full frontend Vitest and production build.
4. Build a terminal deployment directory and assert that it contains the placeholder but no standards PDFs.
5. Run the generated environment probe against a temporary local source and fallback source fixture.
6. Report the 504-file manifest totals separately from the smaller fully parsed sample totals; do not claim full OCR completion unless every source has a terminal status.
