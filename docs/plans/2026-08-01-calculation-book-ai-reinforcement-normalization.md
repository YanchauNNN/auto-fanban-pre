# Calculation Book AI Reinforcement Normalization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect non-standard reinforcement workbooks before task creation, invoke the configured large model and normalization Skill inside the queued calculation-book task, validate structured wall/slab fields deterministically, generate all certain content, leave ambiguous content blank, and surface completion warnings in task details.

**Architecture:** A strict deterministic inspector decides whether AI is needed. For non-standard workbooks, the Worker converts XLSX cells to a bounded JSON snapshot and invokes the existing OpenAI-compatible gateway with `reinforcement_table_normalizer`; Pydantic and the existing exact rebar parsers then validate the model JSON. The processor receives validated schedules plus warning evidence, renders unresolved wall/slab fields as blanks, completes the task, and exposes grouped warnings through the existing job-detail API.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, openpyxl, existing OpenAI-compatible chat client, pytest, React 18, TypeScript, Vite/Vitest, CSS Modules.

---

### Task 1: Strict standard-format inspection and lossless workbook snapshot

**Files:**
- Create: `backend/src/calculation_book/reinforcement_workbook.py`
- Test: `backend/tests/unit/calculation_book/test_reinforcement_workbook.py`
- Modify: `backend/src/calculation_book/archive.py`

**Step 1: Write the failing standard-detection tests**

Add tests proving:

```python
def test_standard_template_not_require_ai(tmp_path: Path) -> None:
    path = build_workbook(
        wall_headers=[
            "构件编号及位置",
            "单侧水平钢筋(对称配筋)",
            "单侧竖向钢筋(对称配筋)",
            "拉筋",
        ],
        wall_rows=[["S7159 墙", "1 28@200", "1D28间距200", "12@200x400"]],
    )
    inspection = inspect_reinforcement_workbook(path, include_slab=True)
    assert inspection.requires_ai_normalization is False


def test_nonstandard_wall_or_selected_slab_requires_ai(tmp_path: Path) -> None:
    path = build_workbook(
        wall_headers=["墙号", "水平筋(X)", "竖向筋(Y)", "拉筋(Z)"],
        wall_rows=[["S7159", "双层D28@200", "D28@200", "C12@200x400"]],
        slab_headers=["楼层", "上部X", "上部Y", "下部X", "下部Y", "拉筋"],
    )
    inspection = inspect_reinforcement_workbook(path, include_slab=True)
    assert inspection.requires_ai_normalization is True
    assert {reason.scope for reason in inspection.reasons} == {"wall", "slab"}
```

Add a snapshot test asserting each non-empty cell retains `sheet`, `row`, `column`, `address`, `value`, `formula`, and merged-range membership.

**Step 2: Run tests and verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_reinforcement_workbook.py -q
```

Expected: collection fails because `reinforcement_workbook` does not exist.

**Step 3: Implement the minimal inspector and snapshot**

Create immutable models:

```python
@dataclass(frozen=True)
class FormatReason:
    scope: Literal["wall", "slab"]
    code: str
    sheet: str | None
    message: str


@dataclass(frozen=True)
class WorkbookFormatInspection:
    requires_ai_normalization: bool
    reasons: tuple[FormatReason, ...]
    wall_sheet: str | None
    slab_sheet: str | None


def inspect_reinforcement_workbook(
    path: Path,
    *,
    include_slab: bool,
) -> WorkbookFormatInspection: ...


def build_workbook_snapshot(path: Path, *, max_non_empty_cells: int) -> dict[str, object]: ...
```

The standard inspector must accept the actual template's plain `1 22@200` notation and canonical D/C notation. It must not trigger on an unused slab sheet when `include_slab=False`. Reuse archive workbook discovery rather than adding another archive entrance.

**Step 4: Run tests and verify GREEN**

Run the same pytest command. Expected: all tests pass.

**Step 5: Commit**

```powershell
git add backend/src/calculation_book/reinforcement_workbook.py backend/src/calculation_book/archive.py backend/tests/unit/calculation_book/test_reinforcement_workbook.py
git commit -m "feat: inspect calculation reinforcement workbook format"
```

### Task 2: Structured wall/slab model output and deterministic validation

**Files:**
- Create: `backend/src/calculation_book/ai_reinforcement_schema.py`
- Modify: `backend/src/calculation_book/reinforcement_input.py`
- Test: `backend/tests/unit/calculation_book/test_ai_reinforcement_schema.py`
- Test: `backend/tests/unit/calculation_book/test_reinforcement_input.py`

**Step 1: Write failing schema and conservation tests**

Cover:

```python
def test_model_payload_validates_wall_and_five_group_slab() -> None:
    payload = AiReinforcementPayload.model_validate(
        {
            "schema_version": "1",
            "rows": [
                {
                    "kind": "wall",
                    "status": "normalized",
                    "source_sheet": "配筋结果",
                    "source_row": 3,
                    "source_cells": {"wall": "A3", "X": "B3", "Y": "C3", "Z": "D3"},
                    "wall_id": "S7159",
                    "X": "1D28间距200",
                    "Y": "1D28间距200",
                    "Z": "1C12间距200*400",
                },
                {
                    "kind": "slab",
                    "status": "normalized",
                    "source_sheet": "楼板结果",
                    "source_row": 2,
                    "elevation": "11.45",
                    "top_x": "1D36间距200",
                    "top_y": "1D40间距200",
                    "middle_x": None,
                    "middle_y": None,
                    "bottom_x": "1D36间距200",
                    "bottom_y": "1D40间距200",
                    "z": "1D16间距200",
                },
            ],
        }
    )
    result = validate_ai_reinforcement_payload(payload, snapshot=SNAPSHOT)
    assert result.wall_schedule.rows[0].wall_id == "S7159"
    assert result.slab_schedule.rows[0].middle_x is None
```

Also assert that duplicate source rows, nonexistent source addresses, missing wall rows, malformed specs, and `source_count != normalized + needs_review` fail. Assert local `needs_review` fields remain `None` and become warnings instead of raising.

**Step 2: Run tests and verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_ai_reinforcement_schema.py backend/tests/unit/calculation_book/test_reinforcement_input.py -q
```

Expected: import/behavior failures for the missing schema and partial slab support.

**Step 3: Implement the schema and validator**

Use a discriminated Pydantic union for `wall` and `slab` rows. The model must not accept an `actual_area` field. Validation must call `normalize_wall_id`, `parse_rebar_cell`, `parse_linear_rebar_cell`, and `normalize_slab_elevation`; it must never trust model calculations.

Return:

```python
@dataclass(frozen=True)
class ReinforcementNormalizationWarning:
    code: str
    scope: str
    identity: str | None
    direction: str | None
    source_sheet: str
    source_row: int
    source_cells: dict[str, str]
    original_values: dict[str, str]
    reason: str
    blank_fields: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedAiReinforcement:
    wall_schedule: ReinforcementSchedule
    slab_schedule: SlabReinforcementSchedule | None
    warnings: tuple[ReinforcementNormalizationWarning, ...]
    source_row_count: int
```

**Step 4: Run tests and verify GREEN**

Run the same pytest command. Expected: all tests pass.

**Step 5: Commit**

```powershell
git add backend/src/calculation_book/ai_reinforcement_schema.py backend/src/calculation_book/reinforcement_input.py backend/tests/unit/calculation_book/test_ai_reinforcement_schema.py backend/tests/unit/calculation_book/test_reinforcement_input.py
git commit -m "feat: validate AI reinforcement fields deterministically"
```

### Task 3: Worker-side large-model Skill invocation

**Files:**
- Create: `backend/src/ai/reinforcement_task_normalizer.py`
- Modify: `backend/src/ai/chat_client.py`
- Modify: `API/app/routers/ai.py`
- Modify: `backend/src/config/runtime_config.py`
- Modify: `documents/参数规范_运行期.yaml`
- Modify: `documents/AI/参数规范_AI.yaml`
- Modify: `tools/ai/reinforcement-table-normalizer/SKILL.md`
- Modify: `tools/ai/reinforcement-table-normalizer/references/normalization-rules.md`
- Test: `backend/tests/unit/ai/test_reinforcement_task_normalizer.py`
- Test: `backend/tests/unit/ai/test_chat_client.py`

**Step 1: Write the failing gateway/Skill tests**

Use a fake client that records messages and returns JSON in plain text and fenced JSON. Assert:

```python
result = normalizer.normalize(
    workbook_path=workbook,
    include_slab=True,
)
assert fake_client.calls == 1
assert "reinforcement_table_normalizer" in fake_client.messages[0][0]["content"]
assert "不得返回实际配筋面积" in fake_client.messages[0][0]["content"]
assert result.wall_schedule.rows[0].wall_id == "S7159"
assert result.slab_schedule is not None
```

Add failures for gateway timeout, non-JSON output, invalid Schema, and missing Skill files.

**Step 2: Run tests and verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/ai/test_reinforcement_task_normalizer.py backend/tests/unit/ai/test_chat_client.py -q
```

Expected: missing service/factory failures.

**Step 3: Implement a reusable client factory and task normalizer**

Move the existing `build_chat_client(spec)` construction from the API router into `backend/src/ai/chat_client.py` so chat and task Workers share one gateway configuration. Implement:

```python
class ReinforcementTaskNormalizer:
    def __init__(self, *, client: ChatClientProtocol, skill_root: Path, limits: Limits): ...

    def normalize(self, *, workbook_path: Path, include_slab: bool) -> ValidatedAiReinforcement:
        snapshot = build_workbook_snapshot(...)
        messages = build_messages(skill_files=..., snapshot=snapshot, include_slab=include_slab)
        completion = self.client.complete(messages)
        payload = parse_json_content(completion.content)
        return validate_ai_reinforcement_payload(payload, snapshot=snapshot)
```

Add YAML-backed limits for maximum cells, snapshot characters, timeout, and Skill root. Do not log workbook contents or API keys.

**Step 4: Run tests and verify GREEN**

Run the same pytest command. Expected: all tests pass.

**Step 5: Commit**

```powershell
git add backend/src/ai/reinforcement_task_normalizer.py backend/src/ai/chat_client.py API/app/routers/ai.py backend/src/config/runtime_config.py documents/参数规范_运行期.yaml documents/AI/参数规范_AI.yaml tools/ai/reinforcement-table-normalizer backend/tests/unit/ai
git commit -m "feat: invoke reinforcement Skill in task worker"
```

### Task 4: Conditional preflight trigger and user confirmation contract

**Files:**
- Modify: `backend/src/calculation_book/models.py`
- Modify: `backend/src/calculation_book/preflight.py`
- Modify: `API/app/runtime.py`
- Modify: `API/app/routers/jobs.py`
- Modify: `backend/tests/unit/calculation_book/test_preflight.py`
- Modify: `backend/tests/unit/test_module7_api.py`

**Step 1: Write failing API tests**

Add tests for three contracts:

```python
standard = client.post("/api/jobs/calculation-books/preflight", files=STANDARD)
assert standard.json()["requires_ai_normalization"] is False

nonstandard = client.post("/api/jobs/calculation-books/preflight", files=NONSTANDARD)
assert nonstandard.status_code == 200
assert nonstandard.json()["requires_ai_normalization"] is True
assert nonstandard.json()["ai_confirmation_message"] == (
    "您上传的墙体配筋表非标准格式，程序将启动人工智能。"
)

rejected = client.post("/api/jobs/calculation-books", data=without_confirmation)
assert rejected.status_code == 422
accepted = client.post("/api/jobs/calculation-books", data=with_confirmation)
assert accepted.status_code == 201
```

Verify that the immutable server-side preflight cache, not a client-supplied boolean alone, controls `job.options["ai_reinforcement_normalization"]`.

**Step 2: Run tests and verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_preflight.py backend/tests/unit/test_module7_api.py -q
```

Expected: missing fields and current 422 behavior for nonstandard workbooks.

**Step 3: Implement the conditional preflight**

Add `confirm_ai_normalization: bool = False` to `CalculationBookParams`. In `preflight_calculation_book`, inspect the workbook first. For nonstandard workbooks, cache the archive and trigger reasons without running model normalization. For standard workbooks, keep the existing full deterministic preflight.

Do not call the large model from the HTTP request. Store `requires_ai_normalization` in the preflight token entry and copy it into immutable job options during creation.

**Step 4: Run tests and verify GREEN**

Run the same pytest command. Expected: all tests pass.

**Step 5: Commit**

```powershell
git add backend/src/calculation_book/models.py backend/src/calculation_book/preflight.py API/app/runtime.py API/app/routers/jobs.py backend/tests/unit/calculation_book/test_preflight.py backend/tests/unit/test_module7_api.py
git commit -m "feat: require confirmation before task AI normalization"
```

### Task 5: AI normalization stage in queued calculation-book jobs

**Files:**
- Modify: `backend/src/calculation_book/executor.py`
- Modify: `backend/src/calculation_book/processor.py`
- Modify: `API/app/runtime.py`
- Test: `backend/tests/unit/calculation_book/test_executor.py`
- Modify: `backend/tests/unit/calculation_book/test_processor.py`
- Modify: `backend/tests/unit/test_api_runtime_worker_queue.py`

**Step 1: Write failing Worker tests**

Inject a fake `ReinforcementTaskNormalizer` and assert:

```python
executor.execute(ai_job)
assert normalizer.calls == 1
assert recorded_stages[0] == "AI_REINFORCEMENT_NORMALIZATION"
assert job.progress.details["ai_reinforcement_normalization"]["skill_id"] == (
    "reinforcement_table_normalizer"
)

executor.execute(standard_job)
assert normalizer.calls == 0
```

Assert the Worker persists model profile, raw/normalized/review counts, duration, and validation outcome but not workbook cell contents.

**Step 2: Run tests and verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_executor.py backend/tests/unit/calculation_book/test_processor.py backend/tests/unit/test_api_runtime_worker_queue.py -q
```

Expected: missing stage/dependency-injection failures.

**Step 3: Implement Worker integration**

Add `AI_REINFORCEMENT_NORMALIZATION` to `CalculationBookStage`. Let `CalculationBookJobExecutor` accept an optional normalizer factory for tests. Pass validated schedule overrides and warnings into `CalculationBookProcessor.process`; standard jobs continue loading the workbook directly.

Whole-payload failures mark the task failed. Local `needs_review` warnings remain data and do not raise.

**Step 4: Run tests and verify GREEN**

Run the same pytest command. Expected: all tests pass.

**Step 5: Commit**

```powershell
git add backend/src/calculation_book/executor.py backend/src/calculation_book/processor.py API/app/runtime.py backend/tests/unit/calculation_book/test_executor.py backend/tests/unit/calculation_book/test_processor.py backend/tests/unit/test_api_runtime_worker_queue.py
git commit -m "feat: normalize nonstandard reinforcement in calculation jobs"
```

### Task 6: Blank unresolved wall/slab content without stopping generation

**Files:**
- Modify: `backend/src/calculation_book/matching.py`
- Modify: `backend/src/calculation_book/slab.py`
- Modify: `backend/src/calculation_book/processor.py`
- Modify: `backend/src/calculation_book/narrative.py`
- Modify: `backend/tests/unit/calculation_book/test_matching.py`
- Modify: `backend/tests/unit/calculation_book/test_slab.py`
- Modify: `backend/tests/unit/calculation_book/test_processor.py`

**Step 1: Write failing unresolved-output tests**

Cover duplicate rows, `-1/-2`, image-only walls, workbook-only walls, and one unresolved slab direction. Assert the processor completes and:

```python
assert unresolved_wall["x_spec"] == ""
assert unresolved_wall["x_calc"] == ""
assert unresolved_figure["narrative"] == ""
assert unresolved_slab_figure["narrative"] == ""
assert result.warnings[0].blank_fields
```

Render a DOCX fixture and assert the image and wall/elevation heading remain while reinforcement text is blank.

**Step 2: Run tests and verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_matching.py backend/tests/unit/calculation_book/test_slab.py backend/tests/unit/calculation_book/test_processor.py -q
```

Expected: `ManualConfirmationRequired`, missing optional assignment types, or missing blank rows.

**Step 3: Implement tolerant matching and rendering**

Allow `ReinforcementAssignment.rebar_row` and slab `rebar_cell` to be `None`. Preserve image groups as assignments even when workbook data is missing. Remove task-blocking confirmation checks; turn duplicate/split/mismatch conditions into structured warnings and blank only the affected fields.

Keep whole-archive failures such as missing X/Y/Z images as hard failures.

**Step 4: Run tests and verify GREEN**

Run the same pytest command. Expected: all tests pass.

**Step 5: Commit**

```powershell
git add backend/src/calculation_book/matching.py backend/src/calculation_book/slab.py backend/src/calculation_book/processor.py backend/src/calculation_book/narrative.py backend/tests/unit/calculation_book
git commit -m "feat: leave ambiguous calculation reinforcement blank"
```

### Task 7: Persist and expose calculation-book warnings in task details

**Files:**
- Modify: `backend/src/calculation_book/executor.py`
- Modify: `API/app/runtime.py`
- Modify: `backend/tests/unit/test_module7_api.py`

**Step 1: Write the failing detail-response test**

Assert a succeeded calculation task returns:

```python
assert detail["calculation_book_output"]["ai_normalized"] is True
assert detail["calculation_book_output"]["warning_count"] == 2
assert detail["calculation_book_output"]["warnings"][0] == {
    "code": "duplicate_reinforcement_rows",
    "scope": "wall",
    "identity": "S7157",
    "direction": None,
    "source_sheet": "Sheet1",
    "source_row": 28,
    "source_cells": {"wall": "A28", "X": "B28", "Y": "C28", "Z": "D28"},
    "reason": "同一墙体存在重复配筋行",
    "blank_fields": ["X", "Y", "Z"],
}
```

**Step 2: Run the test and verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_module7_api.py -q
```

Expected: missing `calculation_book_output.warnings` fields.

**Step 3: Implement persistence and serialization**

Persist warnings in `job.progress.details["calculation_book_warnings"]`; serialize only sanitized structured fields. Do not overload free-text `flags`, because the UI needs grouped evidence.

**Step 4: Run the test and verify GREEN**

Run the same pytest command. Expected: pass.

**Step 5: Commit**

```powershell
git add backend/src/calculation_book/executor.py API/app/runtime.py backend/tests/unit/test_module7_api.py
git commit -m "feat: expose calculation reinforcement warnings"
```

### Task 8: Frontend AI confirmation and attractive completed-task warnings

**Files:**
- Modify: `frontend/src/platform/api/types.ts`
- Modify: `frontend/src/platform/api/httpAdapter.ts`
- Modify: `frontend/src/platform/api/httpAdapter.test.ts`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.module.css`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`
- Create: `frontend/src/features/calculation-book/CalculationBookTaskWarnings.tsx`
- Create: `frontend/src/features/calculation-book/CalculationBookTaskWarnings.module.css`
- Create: `frontend/src/features/calculation-book/CalculationBookTaskWarnings.test.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`

**Step 1: Write failing UI tests**

Test:

```tsx
expect(
  screen.getByText("您上传的墙体配筋表非标准格式，程序将启动人工智能。"),
).toBeInTheDocument();
expect(screen.getByRole("button", { name: "确认并开始任务" })).toBeEnabled();
```

For completed task details assert:

```tsx
expect(screen.getByText("AI 已规范化非标准配筋表")).toBeInTheDocument();
expect(screen.getByText("需人工补充 3 项")).toBeInTheDocument();
expect(screen.getByText("S7157")).toBeInTheDocument();
expect(screen.getByText("Sheet1 · 第 28 行")).toBeInTheDocument();
```

Also verify no warning panel is rendered for standard tasks with zero warnings, keyboard focus reaches expansion controls, and warning items use text labels in addition to color.

**Step 2: Run tests and verify RED**

Run:

```powershell
Set-Location frontend
npm test -- src/features/calculation-book/CalculationBookWorkspace.test.tsx src/features/calculation-book/CalculationBookTaskWarnings.test.tsx src/app/App.test.tsx src/platform/api/httpAdapter.test.ts
```

Expected: missing fields/components/text.

**Step 3: Implement the UI**

Use a confirmation card in the creation workspace and a separate warning component in task details. Group by `scope` and `identity`; show source evidence, reason, and blank fields. Reuse existing task-detail spacing, radius, colors, and typography. Do not add another top-level module entrance.

**Step 4: Run focused tests and verify GREEN**

Run the same npm test command. Expected: pass.

**Step 5: Request the existing page-design subagent review**

Ask `page_design_review_v2` to review the live calculation task creation and completed-task warning views for hierarchy, density, accessibility, responsive behavior, and consistency with current drawing-task details. Apply only concrete findings and rerun focused tests.

**Step 6: Commit**

```powershell
git add frontend/src/platform/api frontend/src/features/calculation-book frontend/src/app/App.tsx frontend/src/app/App.test.tsx
git commit -m "feat: show AI reinforcement warnings in task details"
```

### Task 9: Full verification and real business feasibility proof

**Files:**
- Modify if needed: `backend/tests/integration/test_calculation_book_ai_normalization.py`
- Create: `backend/tests/integration/test_calculation_book_ai_normalization.py`
- Verify: `E:/project/auto-fanban-pre/test/文档/6层11.45~15/6层11.45~15.95m 结果云图.rar`
- Verify: `E:/project/auto-fanban-pre/test/张行反馈/墙体配筋结果.xlsx`

**Step 1: Add an end-to-end integration test with a fake gateway**

The test must exercise `POST /api/jobs/calculation-books/preflight`, confirmation, job creation, Worker normalization, generated DOCX, succeeded detail payload, and download URL. Assert the fake gateway is called only for nonstandard input.

**Step 2: Run backend focused tests**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book backend/tests/unit/ai/test_reinforcement_task_normalizer.py backend/tests/unit/test_module7_api.py backend/tests/integration/test_calculation_book_ai_normalization.py -q
```

Expected: zero failures.

**Step 3: Run full backend tests**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests -q
```

Expected: zero failures; report exact pass/skip counts.

**Step 4: Run frontend tests and build**

```powershell
Set-Location frontend
npm test
npm run build
```

Expected: all tests pass and Vite build exits 0.

**Step 5: Run a live configured-model capability probe**

Start the isolated test API/Worker, submit the nonstandard workbook through the formal calculation-book task flow, and verify job metadata records:

- `skill_id=reinforcement_table_normalizer`;
- configured model profile/name;
- model call count greater than zero;
- wall and slab source-row conservation;
- backend validation success;
- no model call for the standard template.

If the configured model gateway is unavailable, report the exact gateway error separately; do not substitute the fake-gateway result as proof of live-model feasibility.

**Step 6: Run the real archive smoke test**

Use the real RAR and updated embedded workbook. Record preflight token, whether AI was required, job ID, final status, output path, warning count, blank identities/directions, and download verification. Inspect the generated DOCX around at least one normal wall, one blank wall warning, and all slab sections.

**Step 7: Commit integration coverage**

```powershell
git add backend/tests/integration/test_calculation_book_ai_normalization.py
git commit -m "test: cover task AI reinforcement normalization"
```

**Step 8: Final handoff**

Report separately:

- code implemented;
- focused/full tests passed;
- live configured-model activation proof;
- real RAR smoke result;
- files still not merged into `main`;
- remaining gateway, model-context, or business-format risks.
