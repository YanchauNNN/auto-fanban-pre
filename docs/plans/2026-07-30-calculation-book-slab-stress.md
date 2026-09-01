# Calculation Book Optional Slab Stress Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an Excel-backed, user-selectable slab-stress workflow that recognizes five or seven slab figure groups, renders them before wall results, preserves the independent finite-element model image, and passes a formal smoke test built from the approved RAR.

**Architecture:** Keep the existing calculation-book job, preflight token, OCR, wall matching, and DOCX download flow. Extend the archive and workbook contracts with explicit slab domain objects, bind the slab toggle into the preflight token, and render a separate ordered slab loop before the existing wall loop. The workbook remains the only source of actual reinforcement specifications.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, openpyxl, python-docx/docxtpl, React 18, TypeScript, Vite/Vitest, CSS Modules, pytest.

---

### Task 1: Add the slab toggle to the business and API contract

**Files:**
- Modify: `documents/参数规范.yaml:839-873`
- Modify: `backend/src/calculation_book/models.py:18-72`
- Modify: `backend/tests/unit/calculation_book/test_models.py`
- Modify: `API/app/routers/jobs.py:156-171`
- Modify: `API/app/runtime.py:595-854`
- Modify: `backend/tests/unit/test_module7_api.py:2180-2240`

**Step 1: Write the failing model test**

Add tests asserting:

```python
params = CalculationBookParams.model_validate({
    **valid_payload,
    "include_slab_stress": True,
})
assert params.include_slab_stress is True

defaults = CalculationBookParams.model_validate(valid_payload)
assert defaults.include_slab_stress is False
```

**Step 2: Run the model test and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_models.py -q
```

Expected: FAIL because `include_slab_stress` is rejected as an extra field.

**Step 3: Add the minimal backend and YAML field**

Add to `CalculationBookParams`:

```python
include_slab_stress: bool = False
```

Add a YAML-backed calculation-book field:

```yaml
- { key: "include_slab_stress", label: "包含楼板应力", type: "checkbox", required: false, default: false }
```

Extend the calculation-book schema type handling so `checkbox` remains a checkbox instead of falling back to text.

**Step 4: Write the failing API preflight binding test**

Extend the module API test so preflight posts:

```python
data={"include_slab_stress": "true"}
```

Then assert the cached token contains:

```python
assert token_entry["include_slab_stress"] is True
```

Submit the task with the opposite value and assert a 422 parameter error instructing the user to preflight again.

**Step 5: Run the API test and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_module7_api.py -k calculation_book -q
```

Expected: FAIL because the preflight endpoint does not accept or bind the toggle.

**Step 6: Implement preflight parameter binding**

Add a form field to the router:

```python
include_slab_stress: bool = Form(False)
```

Pass it through `ApiRuntime.preflight_calculation_book`, store it in `_calculation_preflight_tokens`, and compare it with `params.include_slab_stress` during creation. A token produced for one toggle value must not be reusable for the other.

**Step 7: Run tests and commit**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_models.py backend/tests/unit/test_module7_api.py -k "calculation_book or slab" -q
```

Expected: PASS.

Commit:

```powershell
git add documents/参数规范.yaml backend/src/calculation_book/models.py backend/tests/unit/calculation_book/test_models.py API/app/routers/jobs.py API/app/runtime.py backend/tests/unit/test_module7_api.py
git commit -m "feat: bind optional slab stress to calculation preflight"
```

### Task 2: Recognize slab figures and make model/layout selection deterministic

**Files:**
- Modify: `backend/src/calculation_book/archive.py:10-214`
- Modify: `backend/tests/unit/calculation_book/test_archive.py`

**Step 1: Write failing archive tests**

Cover:

```python
assert [
    (figure.elevation, figure.position, figure.direction)
    for figure in contents.slab_figures
] == [
    ("11.2", "TOP", "X"),
    ("11.2", "TOP", "Y"),
    ("11.2", "BOTTOM", "X"),
    ("11.2", "BOTTOM", "Y"),
    ("11.2", None, "Z"),
]
```

Add a seven-figure case with mixed-case `Middle`, and failures for:

- only `Middle-X`
- missing `TOP-Y`
- missing `Z`
- two supported images in `01`
- two supported images in `02`

Assert slab files are not present in `ignored_root_images`.

**Step 2: Run the archive tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_archive.py -q
```

Expected: FAIL because slab files are ignored and `01/02` select the first image.

**Step 3: Implement explicit slab archive types**

Add:

```python
@dataclass(frozen=True)
class SlabReinforcementFigure:
    elevation: str
    position: str | None
    direction: str
    path: Path
    sort_key: tuple[float, int, int]
```

Use case-insensitive patterns equivalent to:

```python
r"^(?P<elevation>[+-]?\d+(?:\.\d+)?)-(?P<position>TOP|MIDDLE|BOTTOM)-(?P<direction>[XY])$"
r"^(?P<elevation>[+-]?\d+(?:\.\d+)?)-Z$"
```

Normalize elevation through `Decimal` so `11.20` and `11.2` share the stable key `11.2`.

Add `slab_figures` to `CalculationArchiveContents`. Validate complete Top/Bottom X/Y and Z for each elevation; if either Middle direction occurs, require both.

Replace `_first_image` with `_single_image` that rejects zero or more than one supported file.

**Step 4: Run archive tests and commit**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_archive.py -q
```

Expected: PASS.

Commit:

```powershell
git add backend/src/calculation_book/archive.py backend/tests/unit/calculation_book/test_archive.py
git commit -m "feat: recognize slab figures in calculation archives"
```

### Task 3: Parse the `楼板配筋` worksheet and calculate exact linear areas

**Files:**
- Modify: `backend/src/calculation_book/reinforcement_input.py`
- Modify: `backend/tests/unit/calculation_book/test_reinforcement_input.py`
- Modify: `documents_bin/计算书模板文件.xlsx`
- Modify: `documents_bin/calculation_book/计算书模板文件.xlsx`

**Step 1: Write failing parser tests**

Create a workbook fixture with:

```text
Sheet: 楼板配筋
标高 | 顶层水平 | 顶层竖向 | 中层水平 | 中层竖向 | 底层水平 | 底层竖向 | 纵向拉筋
11.2m | 1D36@200 | 1D40@200 | [blank] | [blank] | 1D36@200 | 1D40@200 | 1D16@200
```

Assert:

```python
schedule = load_slab_reinforcement_schedule(path)
row = schedule.rows[0]
assert row.elevation == "11.2"
assert row.top_x.source_cell == "B2"
assert row.bottom_y.source_cell == "G2"
assert row.z.selected.actual_area == pytest.approx(
    math.pi * 8**2 * 5
)
assert row.z.selected.canonical_specification == "1D16间距200"
```

Add failures for duplicate normalized elevations, missing exact headers, missing required cells, and a two-spacing grid specification in any slab cell.

**Step 2: Run parser tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_reinforcement_input.py -q
```

Expected: FAIL because no slab worksheet loader exists and wall Z requires a grid.

**Step 3: Implement a separate slab schedule**

Add immutable types:

```python
@dataclass(frozen=True)
class SlabReinforcementCell:
    parsed: ParsedRebarCell
    source_cell: str

@dataclass(frozen=True)
class NormalizedSlabReinforcementRow:
    elevation: str
    top_x: SlabReinforcementCell
    top_y: SlabReinforcementCell
    middle_x: SlabReinforcementCell | None
    middle_y: SlabReinforcementCell | None
    bottom_x: SlabReinforcementCell
    bottom_y: SlabReinforcementCell
    z: SlabReinforcementCell
    source_sheet: str
    source_row: int
```

Expose:

```python
def parse_linear_rebar_cell(value: object) -> ParsedRebarCell:
    return parse_rebar_cell(value, direction="X")

def load_slab_reinforcement_schedule(
    path: Path,
    *,
    required: bool,
) -> SlabReinforcementSchedule | None:
    ...
```

The slab loader must inspect only the sheet named `楼板配筋`, use exact normalized header names, retain cell addresses, and parse all seven reinforcement columns with the linear formula. It must not alter wall-grid Z behavior.

**Step 4: Update both business workbook templates**

Use the spreadsheet skill and bundled artifact runtime. Preserve all existing sheets and styles, add one `楼板配筋` sheet with the approved eight headers, and keep data rows empty in the reusable templates.

Render and inspect the new sheet before saving both workbooks.

**Step 5: Run parser and workbook verification**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_reinforcement_input.py -q
```

Expected: PASS.

Inspect both final workbooks to confirm the existing wall sheet is unchanged and `楼板配筋!A1:H1` matches the contract.

**Step 6: Commit**

```powershell
git add backend/src/calculation_book/reinforcement_input.py backend/tests/unit/calculation_book/test_reinforcement_input.py documents_bin/计算书模板文件.xlsx documents_bin/calculation_book/计算书模板文件.xlsx
git commit -m "feat: read slab reinforcement from calculation workbook"
```

### Task 4: Match, OCR, and preflight five or seven slab groups

**Files:**
- Create: `backend/src/calculation_book/slab.py`
- Create: `backend/tests/unit/calculation_book/test_slab.py`
- Modify: `backend/src/calculation_book/preflight.py`
- Modify: `backend/tests/unit/calculation_book/test_preflight.py`

**Step 1: Write failing slab-domain tests**

Define the desired API:

```python
assignments = match_slab_reinforcement(
    recognized_figures,
    slab_schedule,
)
assert [item.kind for item in assignments] == [
    "top_x",
    "bottom_x",
    "top_y",
    "bottom_y",
    "z",
]
```

For Middle data assert:

```python
assert [item.kind for item in assignments] == [
    "top_x",
    "middle_x",
    "bottom_x",
    "top_y",
    "middle_y",
    "bottom_y",
    "z",
]
```

Add failures for no matching Excel elevation and an incomplete Middle Excel row.

**Step 2: Run the new test and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_slab.py -q
```

Expected: collection FAIL because `slab.py` does not exist.

**Step 3: Implement the minimal slab domain**

Add:

```python
@dataclass(frozen=True)
class RecognizedSlabFigure:
    source: SlabReinforcementFigure
    reading: StressLegendReading

@dataclass(frozen=True)
class SlabReinforcementAssignment:
    elevation: str
    kind: str
    figure: RecognizedSlabFigure
    cell: SlabReinforcementCell
```

`match_slab_reinforcement` must:

- group by normalized elevation
- match exactly one Excel row
- choose the approved output order
- require Middle cells only when Middle images exist
- never infer a reinforcement specification

**Step 4: Write failing preflight tests**

Call:

```python
result = run_calculation_book_preflight(
    ...,
    include_slab_stress=True,
)
```

Assert:

```python
assert result["slab"]["enabled"] is True
assert result["slab"]["elevation_count"] == 1
assert [item["kind"] for item in result["slab"]["groups"][0]["items"]] == [
    "top_x", "bottom_x", "top_y", "bottom_y", "z",
]
assert result["slab"]["groups"][0]["items"][0]["source_cell"] == "B2"
```

When disabled, assert no slab OCR calls occur and slab filenames are returned under an informational `slab_ignored_by_choice` warning rather than `ignored_root_images`.

**Step 5: Run preflight tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_preflight.py -q
```

Expected: FAIL because preflight has no toggle or slab payload.

**Step 6: Implement preflight integration**

Add `include_slab_stress: bool = False` to the pure preflight function. Load and match the slab schedule only when enabled. OCR slab X/Y using their direction and slab Z using `Z`, preserving the existing zero-SMX rule.

Return the approved evidence without mixing slab items into wall confirmation candidates.

**Step 7: Run tests and commit**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_slab.py backend/tests/unit/calculation_book/test_preflight.py -q
```

Expected: PASS.

Commit:

```powershell
git add backend/src/calculation_book/slab.py backend/tests/unit/calculation_book/test_slab.py backend/src/calculation_book/preflight.py backend/tests/unit/calculation_book/test_preflight.py
git commit -m "feat: preflight optional slab stress groups"
```

### Task 5: Render slab narratives, transition text, and true superscript units

**Files:**
- Modify: `backend/src/calculation_book/narrative.py`
- Modify: `backend/tests/unit/calculation_book/test_narrative.py`
- Modify: `backend/src/calculation_book/processor.py`
- Modify: `backend/tests/unit/calculation_book/test_processor.py`
- Modify: `backend/src/calculation_book/templates.py`
- Modify: `backend/tests/unit/calculation_book/test_templates.py`
- Modify: `documents_bin/calculation_book/内部结构计算书.docx`
- Modify: `documents_bin/calculation_book/核岛厂房计算书.docx`

**Step 1: Write failing narrative tests**

Add a separate slab narrative entry point:

```python
text = build_slab_reinforcement_narrative(
    elevation="11.2",
    kind="top_x",
    reading=reading,
    rebar_specification="1排36@200",
    actual_area=math.pi * 18**2 * 5,
)
assert text.startswith("11.2m楼板顶层水平钢筋")
```

Cover maximum-value, mostly-less-than, and zero-Z construction wording.

Keep the narrative content unit-neutral at run boundaries so the renderer can format `2` as superscript instead of embedding plain `mm2`.

**Step 2: Run narrative tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_narrative.py -q
```

Expected: FAIL because the slab narrative function does not exist.

**Step 3: Implement slab narrative labels**

Use an explicit map:

```python
SLAB_KIND_LABELS = {
    "top_x": "楼板顶层水平",
    "middle_x": "楼板中层水平",
    "bottom_x": "楼板底层水平",
    "top_y": "楼板顶层竖向",
    "middle_y": "楼板中层竖向",
    "bottom_y": "楼板底层竖向",
    "z": "楼板纵向拉筋",
}
```

Reuse `select_calculation_reference` and area formatting. Do not copy the numeric results from the reference DOCX.

**Step 4: Write failing processor/template tests**

Build a five-group archive and workbook. With `include_slab_stress=True`, assert:

- `figure_count` includes wall and slab figures
- slab captions precede wall captions
- section title is `7.1 楼板与墙体单侧配筋计算结果`
- the exact wall transition sentence appears after the last slab paragraph
- `02/model.png` is embedded in the model paragraph

Inspect the DOCX XML:

```python
superscript_runs = [
    run for run in paragraph.runs
    if run.font.superscript and run.text == "2"
]
assert superscript_runs
assert "mm2" not in all_visible_text
```

Repeat with `include_slab_stress=False` and assert the existing wall-only title and no slab content.

Run the same contract against both templates.

**Step 5: Run processor/template tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_processor.py backend/tests/unit/calculation_book/test_templates.py -q
```

Expected: FAIL because the templates and processor have no slab loop or rich superscript unit support.

**Step 6: Implement processor context**

Load the slab schedule and recognized slab figures only when `params.include_slab_stress` is true. Build:

```python
context.update({
    "include_slab_stress": params.include_slab_stress,
    "slab_reinforcement_figures": slab_rows,
    "wall_transition_text": wall_transition_rich_text,
})
```

Use `docxtpl.RichText` or explicit post-render `python-docx` runs so every unit is represented as `mm` + superscript run `2` + `/m`. Apply the same helper to wall narratives, slab narratives, captions, table headers, and transition text.

Do not use Unicode `²` as a substitute for Word superscript formatting in the final verification.

**Step 7: Update and validate both DOCX templates**

Using `python-docx`/docxtpl:

- conditionally switch the 7.1 heading
- insert the slab loop before the wall loop
- insert the fixed transition paragraph before wall figures
- preserve existing paragraph styles, image widths, page breaks, and wall loop

Run `validate_template_context` against both templates before rendering.

**Step 8: Run tests, render both templates, and commit**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book/test_narrative.py backend/tests/unit/calculation_book/test_processor.py backend/tests/unit/calculation_book/test_templates.py -q
```

Expected: PASS.

Render representative outputs from both templates to PDF/PNG and visually inspect the 7.1 pages.

Commit:

```powershell
git add backend/src/calculation_book/narrative.py backend/tests/unit/calculation_book/test_narrative.py backend/src/calculation_book/processor.py backend/tests/unit/calculation_book/test_processor.py backend/src/calculation_book/templates.py backend/tests/unit/calculation_book/test_templates.py documents_bin/calculation_book/内部结构计算书.docx documents_bin/calculation_book/核岛厂房计算书.docx
git commit -m "feat: render slab reinforcement in calculation books"
```

### Task 6: Expose slab evidence in the frontend without duplicate inputs

**Files:**
- Modify: `frontend/src/platform/api/types.ts:14-94`
- Modify: `frontend/src/platform/api/httpAdapter.ts:331-350,1037-1145`
- Modify: `frontend/src/platform/api/httpAdapter.test.ts`
- Modify: `frontend/src/features/schema/schema.ts:299-338`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.module.css`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`
- Modify: `frontend/src/app/App.test.tsx`

**Step 1: Write failing adapter tests**

Add a raw payload containing:

```typescript
slab: {
  enabled: true,
  elevation_count: 1,
  groups: [{
    elevation: "11.2",
    items: [{
      kind: "top_x",
      label: "水平顶层",
      image_filename: "11.2-top-x.JPEG",
      source_cell: "B2",
      original_text: "1D36@200",
      canonical_specification: "1D36间距200",
      narrative_specification: "1排36@200",
      actual_area: 5089.38,
      smn: 0,
      smx: 4888,
      legend_values: [],
      is_zero_result: false,
    }],
  }],
}
```

Assert camel-case normalization and that preflight posts `include_slab_stress=true`.

**Step 2: Run adapter tests and verify RED**

Run:

```powershell
cd frontend
npm test -- src/platform/api/httpAdapter.test.ts
```

Expected: FAIL because the adapter accepts only the file and ignores slab evidence.

**Step 3: Extend types and adapter**

Add `checkbox` to `CalculationBookField["type"]`. Add typed slab evidence to `CalculationBookPreflightResult`. Change:

```typescript
preflightCalculationBook?: (
  archive: File,
  options: { includeSlabStress: boolean },
) => Promise<CalculationBookPreflightResult>;
```

Append `include_slab_stress` to preflight `FormData`.

**Step 4: Write failing workspace tests**

Cover:

- checkbox is visible once and defaults unchecked
- checking it sends `{ includeSlabStress: true }`
- no slab reinforcement text inputs exist
- enabled preflight shows one elevation and five ordered evidence rows
- seven rows appear when Middle evidence is present
- disabled preflight shows the informational ignored message
- changing the checkbox invalidates prior preflight
- keyboard focus, Escape, and confirmation flow remain intact

**Step 5: Run workspace tests and verify RED**

Run:

```powershell
cd frontend
npm test -- src/features/calculation-book/CalculationBookWorkspace.test.tsx
```

Expected: FAIL because the checkbox and slab review do not exist.

**Step 6: Implement the restrained UI**

Visual thesis: a calm engineering preflight surface with one explicit scope toggle and compact evidence rows.

Content plan:

- keep the existing ZIP structure panel
- place one scope toggle below the ZIP checklist
- show slab evidence as a single section grouped by elevation
- keep wall evidence and manual confirmation unchanged

Interaction thesis:

- toggling slab scope immediately invalidates old preflight state
- review focus moves to the slab summary only after successful preflight
- status changes use existing restrained transitions and respect reduced motion

Use the existing design tokens and CSS module. Do not add a second upload control, extra cards for every datum, or editable reinforcement controls.

Render units in the browser as `mm²/m`; the Word superscript requirement remains separately verified in DOCX XML.

**Step 7: Run frontend tests and commit**

Run:

```powershell
cd frontend
npm test -- src/platform/api/httpAdapter.test.ts src/features/calculation-book/CalculationBookWorkspace.test.tsx src/app/App.test.tsx
npm test
npm run build
```

Expected: all PASS.

Commit:

```powershell
git add frontend/src/platform/api/types.ts frontend/src/platform/api/httpAdapter.ts frontend/src/platform/api/httpAdapter.test.ts frontend/src/features/schema/schema.ts frontend/src/features/calculation-book/CalculationBookWorkspace.tsx frontend/src/features/calculation-book/CalculationBookWorkspace.module.css frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx frontend/src/app/App.test.tsx
git commit -m "feat: add slab stress scope and evidence to calculation UI"
```

### Task 7: Run independent page design and usability review

**Files:**
- Review: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- Review: `frontend/src/features/calculation-book/CalculationBookWorkspace.module.css`
- Modify only if needed: the same files and their tests

**Step 1: Start the frontend and capture the real interaction**

Run:

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Exercise unchecked, checked-five-group, checked-seven-group, warning, and validation states.

**Step 2: Ask the existing `page_design_review_v2` sub-agent to review**

Request a bounded review for:

- visual hierarchy
- toggle discoverability
- evidence scanability
- duplicate-control avoidance
- focus/keyboard behavior
- responsive behavior
- Chinese utility copy

Require actionable findings with priority and file/line references. The reviewer must not edit files.

**Step 3: Write failing tests for accepted behavior fixes**

For every accepted functional/accessibility finding, add or update a Vitest assertion first and run it to confirm RED.

**Step 4: Apply minimal fixes**

Modify only the workspace component/CSS needed to close accepted findings. Do not restyle unrelated application surfaces.

**Step 5: Verify and commit**

Run:

```powershell
cd frontend
npm test -- src/features/calculation-book/CalculationBookWorkspace.test.tsx
npm test
npm run build
```

Expected: PASS.

Commit only if review caused changes:

```powershell
git add frontend/src/features/calculation-book/CalculationBookWorkspace.tsx frontend/src/features/calculation-book/CalculationBookWorkspace.module.css frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx
git commit -m "fix: refine slab preflight usability"
```

### Task 8: Formal smoke test from the approved RAR

**Files:**
- Source only: `E:\project\auto-fanban-pre\test\文档\6层11.45~15\6层11.45~15.95m 结果云图.rar`
- Source only: `E:\project\auto-fanban-pre\test\文档\6层11.45~15\6层11.45~15.95m 结果传图\JDXNHQ10001B25C42GN(2016XNH-JGSJ06).docx`
- Temporary smoke input: `build/calculation-book-slab-smoke/`
- Final generated artifact: job storage under the formal task ID

**Step 1: Extract the approved RAR into a bounded build directory**

Use Windows `tar` to extract the RAR. Flatten only the single source top-level folder when assembling the formal ZIP; preserve root figures and `01/02`.

Verify the source inventory includes:

```text
01/image001.jpg
02/111.bmp
11.2-top-x.JPEG
11.2-top-y.JPEG
11.2-BOTTOM-x.JPEG
11.2-BOTTOM-y.JPEG
11.2-Z.JPEG
```

**Step 2: Build a smoke workbook copy**

Copy the updated workbook template into the smoke directory and fill `楼板配筋` for `11.2` with the actual specifications needed by this business sample. Do not modify the reusable template data rows.

Use the relevant real N-wall reinforcement workbook already used for this business sample, preserving all wall rows.

**Step 3: Assemble the formal ZIP**

Create one ZIP with:

- all real root wall/slab images
- one combined reinforcement workbook
- real `01/image001.jpg`
- real `02/111.bmp`

Do not use the previous synthetic ZIP or replace `01/02` with stress images.

**Step 4: Run formal preflight and create the job**

Submit through:

```text
POST /api/jobs/calculation-books/preflight
POST /api/jobs/calculation-books
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/download/calculation-book
```

Record the preflight token, batch ID, job ID, output directory, and final DOCX path.

**Step 5: Verify data and document semantics**

Assert:

- preflight reports one slab elevation and five slab items
- the five items are in the approved order
- all five source cells point to `楼板配筋`
- exact actual areas match workbook specifications
- all wall figures still process
- the finite-element model embedded in section 6 hashes to the real `02/111.bmp` image or its deterministic converted representation

**Step 6: Render and visually inspect the final DOCX**

Render every page. Check section 7.1 against the supplied reference structure:

- slab figures and narratives are correctly paired
- transition sentence appears exactly once after slabs
- wall results begin immediately after the transition
- every `mm2` uses a superscript `2`
- no clipped text, stretched images, overlap, blank pages, or broken pagination

**Step 7: Run the full regression suite**

Run:

```powershell
python -m pytest backend/tests/unit/calculation_book -q
python -m pytest backend/tests/unit/test_module7_api.py -k calculation_book -q
cd frontend
npm test
npm run build
```

Expected: PASS.

**Step 8: Final verification commit**

If smoke-driven fixes are required, add a failing regression test before each fix, then commit:

```powershell
git add <only smoke-driven source and test files>
git commit -m "fix: close real slab calculation smoke gaps"
```

Do not commit extracted RAR contents, temporary ZIPs, rendered pages, tokens, or job-storage artifacts.
