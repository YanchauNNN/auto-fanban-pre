# Building Structure Standards Offline Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Audit all 509 building/structure/site-plan records, build and validate an authorized offline standards corpus, package it as a private Skill, and verify it from the deployed `D:\FanBanServer` application.

**Architecture:** Use a deterministic acquisition audit and source registry as the gate for corpus ingestion. Parse authorized PDF/HTML sources into clause-, table-, and page-anchored SQLite records, expose them through a self-contained query script, and integrate the Skill through the existing read-only Context Skill and terminal packaging flow.

**Tech Stack:** Python 3.10+, SQLite FTS5, pypdf/pdfplumber, HTMLParser, pytest, FastAPI, PowerShell, `@oai/artifact-tool`, React/Vite browser smoke tests.

---

### Task 1: Define Audit Records and Extract the 509-Item Baseline

**Files:**
- Create: `backend/src/ai/standards_audit.py`
- Test: `backend/tests/unit/ai/test_standards_audit.py`

**Step 1: Write the failing tests**

Cover:

- Standard-number normalization including non-breaking spaces and missing spaces.
- Source classification for GB, GB/T, industry standards, HAF, atlases, CP, JT, and project specifications.
- Default acquisition, authorization, and confidentiality policy.
- Extraction of exactly 509 building/structure/site-plan records from an exported JSON baseline.

**Step 2: Run the tests to verify RED**

```powershell
python -m pytest backend/tests/unit/ai/test_standards_audit.py -q
```

Expected: FAIL because `standards_audit` does not exist.

**Step 3: Implement the minimal model and classifiers**

Create typed audit records, normalization, classification, default policy, and JSON serialization. Keep uncertain values explicit as `待核验`.

**Step 4: Run the tests to verify GREEN**

Expected: PASS.

**Step 5: Commit**

```powershell
git add backend/src/ai/standards_audit.py backend/tests/unit/ai/test_standards_audit.py
git commit -m "feat: model standards acquisition audit"
```

### Task 2: Add Official Metadata Clients

**Files:**
- Modify: `backend/src/ai/standards_audit.py`
- Modify: `backend/tests/unit/ai/test_standards_audit.py`
- Create: `backend/tests/fixtures/standards/openstd_current.html`
- Create: `backend/tests/fixtures/standards/openstd_replaced.html`
- Create: `backend/tests/fixtures/standards/industry_result.html`
- Create: `backend/tests/fixtures/standards/atlas_result.html`

**Step 1: Write failing parser tests**

Assert extraction of:

- Official code, name, current/replaced state, dates, replacement relation, detail URL, and download-button presence.
- Industry-standard metadata without claiming full-text availability.
- Atlas purchase/licensing status without treating unofficial PDFs as sources.
- Network errors as `核验失败`, never as `未找到` or success.

**Step 2: Run the tests to verify RED**

Expected: FAIL because official clients do not exist.

**Step 3: Implement minimal read-only clients**

Use standard-library HTTP and HTML parsing with bounded timeout, official-domain allowlists, rate limiting, cached responses, and clear evidence fields. Do not bypass authentication, CAPTCHA, redirect guards, or paid access.

**Step 4: Run the tests to verify GREEN**

Expected: PASS.

**Step 5: Run representative live probes**

Probe one GB/T, one GB, one industry standard, one HAF record, and one atlas. Save response metadata under ignored `storage/research/standards-skill/`.

**Step 6: Commit**

```powershell
git add backend/src/ai/standards_audit.py backend/tests/unit/ai/test_standards_audit.py backend/tests/fixtures/standards
git commit -m "feat: audit official standards metadata"
```

### Task 3: Generate and Visually Verify the 509-Item Audit Workbook

**Files:**
- Create: `storage/research/standards-skill/audit_records.json` (ignored)
- Create: `storage/research/standards-skill/build_audit_workbook.mjs` (ignored)
- Create: `outputs/019f7eb5-8fc3-7071-9d34-f893e1506fd8/建筑结构总图规范语料获取审计表.xlsx` (artifact)

**Step 1: Export the source workbook rows through `@oai/artifact-tool`**

Read `DatStdItem`, filter `Department=建筑结构所`, and assert 509 rows.

**Step 2: Run live metadata auditing**

Merge official evidence into each record. Preserve unresolved states and source errors.

**Step 3: Build the audit workbook**

Create:

- `审计总览`
- `语料获取审计`
- `字段说明`

Include filters, frozen headers, conditional formatting, source URLs, authorization, confidentiality, local hash, and evidence notes.

**Step 4: Verify workbook data**

Inspect summary totals, audit-row count, representative records, and formula-error scan.

**Step 5: Render and visually inspect every sheet**

Fix clipping, unreadable wrapping, missing headers, and misleading colors.

### Task 4: Select the First Validation Corpus

**Files:**
- Create: `storage/research/standards-skill/validation_selection.json` (ignored)
- Test: `backend/tests/unit/ai/test_standards_validation_selection.py`

**Step 1: Write failing selection tests**

Require about 20 records covering:

- GB and GB/T;
- NB/T and JGJ/JGJ/T;
- HAF;
- licensed atlas;
- internal JT and CP;
- at least one current/replaced pair where evidence exists.

Require the selector to keep unavailable licensed/internal documents in the validation set with `source_required` instead of fabricating content.

**Step 2: Run tests to verify RED**

Expected: FAIL because the selector does not exist.

**Step 3: Implement deterministic selection**

Prefer records with official status evidence and representative subject coverage. Record why each item was selected.

**Step 4: Run tests to verify GREEN**

Expected: PASS.

### Task 5: Build PDF/HTML Parsing and Anchoring

**Files:**
- Create: `backend/src/ai/standards_corpus.py`
- Test: `backend/tests/unit/ai/test_standards_corpus.py`
- Create: `backend/tests/fixtures/standards/sample_standard.pdf`
- Create: `backend/tests/fixtures/standards/sample_standard.html`

**Step 1: Write failing PDF parser tests**

Cover:

- Page-preserving extraction.
- Clause hierarchy and clause number recognition.
- Table number/title/cell extraction.
- Continuation tables and page anchors.
- Scanned or empty pages reported as `ocr_required`.

**Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/ai/test_standards_corpus.py -q
```

Expected: FAIL because the parser does not exist.

**Step 3: Implement minimal PDF parsing**

Use bundled PDF libraries, retain page boundaries and source hashes, and fail closed on unreadable pages.

**Step 4: Write and verify failing HTML parser tests**

Cover heading hierarchy, numbered clauses, tables, footnotes, and source-element anchors.

**Step 5: Implement minimal HTML parsing**

Strip navigation/scripts while preserving normative text and table structure.

**Step 6: Run tests to verify GREEN**

Expected: PASS.

**Step 7: Render representative PDF pages**

Verify clause, table, and page anchors against rendered page images.

**Step 8: Commit**

```powershell
git add backend/src/ai/standards_corpus.py backend/tests/unit/ai/test_standards_corpus.py backend/tests/fixtures/standards
git commit -m "feat: parse and anchor standards documents"
```

### Task 6: Create the Offline Skill and SQLite Index

**Files:**
- Create: `tools/ai/building-structure-standards-skill/`
- Create: `tools/ai/building-structure-standards-skill/SKILL.md`
- Create: `tools/ai/building-structure-standards-skill/agents/openai.yaml`
- Create: `tools/ai/building-structure-standards-skill/scripts/standards_query.py`
- Create: `tools/ai/building-structure-standards-skill/scripts/build_standards_index.py`
- Create: `tools/ai/building-structure-standards-skill/scripts/validate_standards_skill.py`
- Create: `tools/ai/building-structure-standards-skill/references/query-guide.md`
- Test: `backend/tests/unit/ai/test_building_standards_query.py`

**Step 1: Initialize the Skill with `init_skill.py`**

Use the approved name `building-structure-standards` and create only required `scripts`, `references`, and `assets` resources.

**Step 2: Write failing query tests**

Cover `standard`, `clause`, `search`, `compare`, `document`, and `health`.

**Step 3: Verify RED**

Expected: FAIL because the query/index scripts are placeholders.

**Step 4: Implement SQLite schema and query operations**

Use exact standard-number and clause indexes plus Chinese lexical search. Return structured evidence with standard, clause, page, source, status, authorization, and warnings.

**Step 5: Build the first corpus**

Ingest only source documents whose audit state permits inclusion. Missing licensed/internal sources remain audit gaps and are excluded from text tables.

**Step 6: Run tests and validator**

Expected: query tests and Skill validator PASS.

**Step 7: Validate Skill metadata**

Run `quick_validate.py` and regenerate `agents/openai.yaml` if required.

**Step 8: Commit**

```powershell
git add tools/ai/building-structure-standards-skill backend/tests/unit/ai/test_building_standards_query.py
git commit -m "feat: add offline building standards skill"
```

### Task 7: Build the Standard-Answer Validation Suite

**Files:**
- Create: `tools/ai/building-structure-standards-skill/references/validation-cases.json`
- Modify: `tools/ai/building-structure-standards-skill/scripts/validate_standards_skill.py`
- Test: `backend/tests/unit/ai/test_building_standards_validation.py`

**Step 1: Write failing validation-runner tests**

Require schema checks, deterministic expected identifiers, expected status/warnings, and top-k limits.

**Step 2: Verify RED**

Expected: FAIL because validation cases and runner behavior are missing.

**Step 3: Add 50-100 cases**

Target 80 cases across:

- exact clauses;
- current/replaced versions;
- cross-standard guidance;
- standards with tables;
- missing diagrams;
- unauthorized/missing sources;
- insufficient evidence;
- conflicting applicability assumptions.

**Step 4: Run the full suite**

Expected: all cases pass or have an explicit approved gap reason. A missing source is not a passing answer case.

**Step 5: Commit**

```powershell
git add tools/ai/building-structure-standards-skill backend/tests/unit/ai/test_building_standards_validation.py
git commit -m "test: validate offline standards retrieval"
```

### Task 8: Integrate the Skill with Chat and YAML

**Files:**
- Create: `backend/src/ai/building_standards_skill.py`
- Modify: `API/app/routers/ai.py`
- Modify: `documents/AI/参数规范_AI.yaml`
- Test: `backend/tests/unit/ai/test_building_standards_skill.py`
- Modify: `backend/tests/unit/ai/test_ai_spec.py`
- Modify: `backend/tests/unit/ai/test_ai_chat.py`

**Step 1: Write failing integration tests**

Cover trigger terms, standard-number detection, follow-up context, missing payload, query errors, evidence compaction, and YAML registration.

**Step 2: Verify RED**

Expected: FAIL because the handler is not registered.

**Step 3: Implement minimal Context Skill**

Run the local query script in a bounded subprocess, inject evidence as untrusted read-only context, and require the model to cite standard, clause, page, and version.

**Step 4: Run targeted tests**

Expected: PASS.

**Step 5: Commit**

```powershell
git add backend/src/ai/building_standards_skill.py API/app/routers/ai.py documents/AI/参数规范_AI.yaml backend/tests/unit/ai
git commit -m "feat: connect building standards skill to AI chat"
```

### Task 9: Package and Install the Private Offline Corpus

**Files:**
- Create: `tools/ai/install_building_standards_skill.ps1`
- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `backend/tests/unit/test_terminal_deploy_builder.py`
- Modify: `tools/ai/test_ai_model_connectivity.ps1`
- Modify: `backend/tests/unit/ai/test_ai_connectivity_script.py`
- Create: `documents/AI/建筑结构总图规范Skill部署说明.md`
- Create: `documents/AI/building-structure-standards-private-offline-2026-07-20.zip` (ignored)

**Step 1: Write failing installer and package tests**

Cover safe ZIP paths, required files, staged replacement, backup restoration, missing corpus failure, and terminal-package inclusion.

**Step 2: Verify RED**

Expected: FAIL because packaging support is missing.

**Step 3: Implement installer and terminal integration**

Do not copy the source archive into the terminal package. Install only the validated payload and set `FANBAN_BUILDING_STANDARDS_SKILL_ROOT`.

**Step 4: Add connectivity probes**

Check manifest hashes, SQLite counts, validation results, and representative query output.

**Step 5: Generate manifest, corpus report, hashes, and private ZIP**

Include only audit-authorized source and derived files.

**Step 6: Run targeted tests and clean-install validation**

Expected: PASS.

**Step 7: Commit tracked implementation**

```powershell
git add tools/ai/install_building_standards_skill.ps1 backend/src/deploy/terminal_package.py backend/tests/unit/test_terminal_deploy_builder.py tools/ai/test_ai_model_connectivity.ps1 backend/tests/unit/ai/test_ai_connectivity_script.py documents/AI/建筑结构总图规范Skill部署说明.md
git commit -m "feat: package building standards offline skill"
```

### Task 10: Deploy to `D:\FanBanServer` and Smoke-Test

**Files:**
- Modify only if fresh deployment verification exposes a covered defect.

**Step 1: Build production frontend and terminal package**

```powershell
cd frontend
npm test -- --run
npm run build
```

Run backend targeted and full relevant suites before packaging.

**Step 2: Deploy the package to `D:\FanBanServer`**

Use the repository's supported deployment entrypoints and preserve existing installation backups/configuration.

**Step 3: Verify local offline capability**

Temporarily deny or avoid external network for the local query subprocess only. Run `health`, exact-standard, clause, and search queries from the deployed Skill.

**Step 4: Restore model connectivity and run the real probe**

Run the deployed connectivity script with the configured development/terminal model profile. Do not claim this proves a fully disconnected model environment.

**Step 5: Run real browser smoke tests**

Verify:

- exact standard question;
- clause question;
- replaced-standard warning;
- cross-standard design suggestion with assumptions;
- insufficient-evidence response;
- automatic Skill trigger and follow-up;
- citations include standard, clause/page, and version;
- no console errors.

Capture desktop screenshots and logs under `frontend/output/playwright/`.

**Step 6: Final verification**

Run:

```powershell
git diff --check
git status --short
python -m pytest <all affected backend tests> -q
cd frontend
npm test -- --run
npm run build
```

Reconcile the six requested phases against delivered artifacts and report unresolved licensing/source gaps separately.
