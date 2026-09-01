# Calculation Book AI and Cover Code Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make reinforcement normalization tolerant of harmless model wrapper/extras while preserving strict business validation, and fill the six cover-code cells from YAML-backed project, plant, fixed, and level-code data.

**Architecture:** Keep business values and retry counts in the existing YAML sources of truth. Extend the generic calculation-book schema/model/context pipeline and template placeholders, while splitting model-output extraction from strict normalized payload validation so safe extras can be ignored and invalid responses can be corrected within a configured bound.

**Tech Stack:** FastAPI, Pydantic v2, Python/docxtpl/python-docx, React/Vite/Vitest, pytest, YAML.

---

### Task 1: AI tolerant extraction and correction loop

**Files:**
- Modify: `backend/tests/unit/ai/test_reinforcement_task_normalizer.py`
- Modify: `backend/src/ai/reinforcement_task_normalizer.py`
- Modify: `backend/src/calculation_book/executor.py`
- Modify: `backend/src/config/mechanism_spec.py`
- Modify: `documents/参数规范-3.yaml`
- Modify: `tools/ai/reinforcement-table-normalizer/SKILL.md`
- Modify: `tools/ai/reinforcement-table-normalizer/references/normalization-rules.md`

1. Add failing tests for harmless nested extra fields, JSON embedded in a code block or explanation, ambiguous/malformed candidates, first-failure correction success, and correction exhaustion.
2. Run the focused normalizer tests and confirm the expected failures.
3. Add bounded JSON-object candidate extraction, permissive input models, unchanged strict business validation, and configured correction attempts.
4. Strengthen Skill minimal-output examples and exact `review_sources` shape.
5. Run the focused normalizer/executor/mechanism tests until green.

### Task 2: YAML-backed six-cell cover code

**Files:**
- Modify: `documents/参数规范.yaml`
- Modify: `backend/tests/unit/calculation_book/test_models.py`
- Modify: `backend/tests/unit/calculation_book/test_processor.py`
- Modify: `backend/tests/unit/test_module7_api.py`
- Modify: `backend/src/config/spec_loader.py`
- Modify: `backend/src/calculation_book/models.py`
- Modify: `backend/src/calculation_book/processor.py`

1. Add failing tests for YAML project-code lookup, `level_code` validation/normalization, `JDXNHR` context generation, and nonblocking missing 2035 mapping.
2. Run the focused backend tests and confirm the expected failures.
3. Add YAML enum codes, calculation-book cover-code rules, and the YAML form field.
4. Implement generic spec lookup and context assembly; add a warning when the project code is absent.
5. Run focused backend tests until green.

### Task 3: Frontend dynamic level-code validation

**Files:**
- Modify: `frontend/src/platform/api/types.ts`
- Modify: `frontend/src/features/schema/schema.ts`
- Modify: `frontend/src/features/schema/schema.test.ts`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`

1. Add failing tests proving the YAML field appears, accepts one letter, uppercases it, rejects other input, and participates in presets/submission.
2. Run the focused Vitest files and confirm the expected failures.
3. Extend generic calculation-book field metadata with pattern/max-length/uppercase rules and use those rules in rendering and validation.
4. Run focused frontend tests until green.

### Task 4: Template placeholders and visual verification

**Files:**
- Modify: `documents_bin/calculation_book/内部结构计算书.docx`
- Modify: `documents_bin/calculation_book/核岛厂房计算书.docx`
- Modify: `backend/tests/unit/calculation_book/test_templates.py`

1. Add failing template-contract tests for all six variables.
2. Back up and patch only the six existing visible cells in both current templates, preserving the user's modified factory template.
3. Render representative internal/factory outputs through Word/PDF/PNG and inspect every rendered page for new layout defects.
4. Run template and processor tests until green.

### Task 5: Full verification and real smoke

1. Run the complete backend pytest suite relevant to calculation book, configuration, metadata and API.
2. Run full frontend `npm test` and `npm run build`.
3. Run the supplied real RAR through `development_minimax`, API and Worker; verify final Word, job warnings and diagnostic log.
4. Compare `git status`/diff against the initial dirty state and confirm no unrelated files changed.
5. Commit only the calculation-book implementation, tests, YAML, Skill and the two requested templates.

