# Calculation Book Compact Wall Review Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add the internal-code example and make AI wall evidence compact in calculation-book review and confirmation without hiding exceptions or X/Y/Z evidence.

**Architecture:** Keep `documents/参数规范.yaml` as the field metadata source and reuse the existing placeholder pipeline. Add an AI-only wall evidence presentation inside `ReviewPanel`: one batch status, a responsive wall index with per-wall details, and a confirmation-phase outer disclosure. Preserve the provided-reinforcement layout.

**Tech Stack:** React 19, TypeScript, CSS Modules, Vitest, Testing Library, YAML-backed schema metadata.

---

### Task 1: Internal-code example from business YAML

**Files:**
- Modify: `documents/参数规范.yaml:843`
- Modify: `backend/tests/unit/calculation_book/test_config.py:230-250`

**Step 1: Write the failing test**

Load the real business YAML and assert the calculation-book `internal_code` field exposes the requested placeholder:

```py
def test_calculation_book_business_schema_exposes_internal_code_example() -> None:
    business_spec = yaml.safe_load(
        (REPO_ROOT / "documents" / "参数规范.yaml").read_text(encoding="utf-8")
    )
    fields = business_spec["calculation_book"]["fields"]
    field = next(item for item in fields if item["key"] == "internal_code")
    assert field["placeholder"] == "例如：20161NH-JGS01"
```

**Step 2: Run the test to verify it fails**

Run: `uv run --project backend pytest backend/tests/unit/calculation_book/test_config.py::test_calculation_book_business_schema_exposes_internal_code_example -q`

Expected: FAIL with missing `placeholder`.

**Step 3: Add the YAML metadata**

Change the calculation-book field entry to:

```yaml
- { key: "internal_code", label: "内部编号", type: "text", required: true, placeholder: "例如：20161NH-JGS01" }
```

Keep `FieldGroup` unchanged because it already renders `field.placeholder`.

**Step 4: Run the focused test**

Run: `uv run --project backend pytest backend/tests/unit/calculation_book/test_config.py::test_calculation_book_business_schema_exposes_internal_code_example -q`

Expected: PASS.

### Task 2: Compact AI wall evidence in review and confirmation

**Files:**
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx:1147-1405`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.module.css:903-968,1190-1320`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx:727-900`

**Step 1: Add multi-wall fixtures and failing behavior tests**

Extend the AI-suggested test fixture to contain several walls. Assert that:

```ts
expect(screen.getAllByText(/配筋建议将在任务生成过程中/)).toHaveLength(1);
expect(screen.queryByText("等待任务生成 AI 建议")).not.toBeInTheDocument();
```

Assert review phase shows a compact wall index, opening one wall reveals its X/Y/Z evidence, and no unrelated wall opens.

Assert confirmation phase renders a disclosure named like `已核验逐墙证据（N 组）`, closed by default; opening it restores all wall IDs and single-wall details.

Add a provided-reinforcement assertion that `配筋表第 N 行` remains visible.

**Step 2: Run the focused tests to verify RED**

Run: `npm test -- src/features/calculation-book/CalculationBookWorkspace.test.tsx -t "无实配钢筋|逐墙证据|确认提交"`

Expected: FAIL because every wall is currently a full-width row and repeats the waiting copy in both phases.

**Step 3: Implement the minimal shared presentation**

Inside `ReviewPanel`:

- Correct the step badge to `03 · 确认提交` in confirmation phase.
- Render one AI batch note above the wall index.
- For AI mode, render walls in a new responsive grid. Each wall summary contains its ID and a concise direction-completeness label; its open content continues to render the existing three `DirectionEvidence` components.
- Wrap the AI wall evidence section in a phase-keyed outer `<details>` only during confirmation so it starts closed after the phase transition.
- Keep review-phase AI index visible and keep the provided-reinforcement branch unchanged.
- Keep OCR review, warnings and slab errors outside the confirmation disclosure.

**Step 4: Add compact responsive styles**

- Use `repeat(auto-fit, minmax(...))` for the wall index.
- Make an opened wall span all columns.
- Keep summaries at least 44px high, with a visible focus state and text status.
- At mobile width use two columns; retain the existing one-column X/Y/Z evidence cards.
- Do not add an inner scroll container.

**Step 5: Run focused tests to verify GREEN**

Run: `npm test -- src/features/calculation-book/CalculationBookWorkspace.test.tsx`

Expected: PASS.

### Task 3: Regression and visual verification

**Files:**
- Verify: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`
- Verify: `frontend/src/features/schema/schema.test.ts`

**Step 1: Run calculation-book and schema tests**

Run: `npm test -- src/features/calculation-book/CalculationBookWorkspace.test.tsx src/features/schema/schema.test.ts`

Expected: PASS with zero failures.

**Step 2: Run the full frontend suite**

Run: `npm test`

Expected: PASS with zero failures.

**Step 3: Build production frontend**

Run: `npm run build`

Expected: exit 0 with no TypeScript or Vite build errors.

**Step 4: Render and inspect**

Start the existing calculation-book test frontend only if not already running. Inspect at desktop and mobile widths:

- second-step common AI waiting state appears once;
- wall index is compact and opens a wall across full width;
- third-step evidence is closed by default;
- exception panels remain visible;
- no clipping or horizontal overflow.

**Step 5: Review and commit only in-scope files**

Request a spec-compliance review, then a code-quality review. Preserve all unrelated dirty backend files. Stage only the YAML, calculation-book component, CSS module, tests, design and implementation plan before committing.
