# Calculation Book Compact Presets Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add browser-local calculation-book presets and redesign the calculation-book input phase so common desktop viewports can complete the form with little or no vertical scrolling.

**Architecture:** Add a calculation-book-specific localStorage module instead of coupling to deliverable presets. `CalculationBookWorkspace` owns preset interaction state, applies only current schema fields, recomputes derived project names, preserves the selected archive, and invalidates stale preflight state. The input phase becomes a compact two-column workspace with a white upload control, preset controls in the left rail, collapsed archive help, and a four-column desktop field grid.

**Tech Stack:** React 18, TypeScript, CSS Modules, Vitest, Testing Library, browser localStorage, Vite.

---

### Task 1: Add calculation-book preset persistence

**Files:**
- Create: `frontend/src/features/calculation-book/calculationBookPresets.test.ts`
- Create: `frontend/src/features/calculation-book/calculationBookPresets.ts`

**Step 1: Write the failing storage tests**

Cover real localStorage behavior for create, update-in-place, rename, delete, `updatedAt` sorting, corrupt JSON fallback, schema filtering, stale select fallback, project-name derivation, and slab-toggle preservation.

The central expectations are:

```ts
const preset = createCalculationBookPreset("11.45m 方案", schema, {
  project_no: "2016",
  project_name: "derived",
  include_slab_stress: "true",
  version: "A",
});
saveCalculationBookPreset(preset);
expect(preset.values.project_name).toBeUndefined();
expect(preset.values.include_slab_stress).toBe("true");

const applied = applyCalculationBookPreset(schema, initialValues, {
  ...preset,
  values: { project_no: "2016", removed_field: "old" },
});
expect(applied.project_name).toBe("浙江金七门核电厂1、2号机组");
expect(applied.removed_field).toBeUndefined();
```

**Step 2: Run the test and verify RED**

Run:

```powershell
npm.cmd test -- --run src/features/calculation-book/calculationBookPresets.test.ts
```

Expected: FAIL because the preset module does not exist.

**Step 3: Implement the minimal preset module**

Expose this API:

```ts
export type CalculationBookPreset = {
  id: string;
  name: string;
  values: Record<string, string>;
  updatedAt: string;
};

export function loadCalculationBookPresets(): CalculationBookPreset[];
export function createCalculationBookPreset(
  name: string,
  schema: CalculationBookSchema,
  values: Record<string, string>,
): CalculationBookPreset;
export function updateCalculationBookPreset(
  id: string,
  name: string,
  schema: CalculationBookSchema,
  values: Record<string, string>,
): CalculationBookPreset;
export function saveCalculationBookPreset(preset: CalculationBookPreset): CalculationBookPreset[];
export function renameCalculationBookPreset(id: string, name: string): CalculationBookPreset[];
export function deleteCalculationBookPreset(id: string): CalculationBookPreset[];
export function applyCalculationBookPreset(
  schema: CalculationBookSchema,
  currentValues: Record<string, string>,
  preset: CalculationBookPreset,
): Record<string, string>;
```

Use `auto-fanban.calculation-book-presets`. Save current schema fields except `project_name` and any `derivedFrom` field. On apply, ignore unknown fields, preserve defaults for missing fields, validate selects against current options, and recompute `project_name` from `project_no`.

**Step 4: Run the test and verify GREEN**

Run the Task 1 command again. Expected: all preset tests PASS.

**Step 5: Commit**

```powershell
git add frontend/src/features/calculation-book/calculationBookPresets.ts frontend/src/features/calculation-book/calculationBookPresets.test.ts
git commit -m "feat: add calculation book presets"
```

### Task 2: Add preset interaction to the calculation-book workspace

**Files:**
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`

**Step 1: Write failing component tests**

Use the existing `Harness`, real user events, and localStorage. Test saving, selecting and applying, updating without duplication, renaming, deleting, accessible success/error messages, restoring `include_slab_stress`, recomputing `project_name`, retaining the selected RAR/ZIP, and invalidating existing preflight state.

**Step 2: Run the focused component test and verify RED**

```powershell
npm.cmd test -- --run src/features/calculation-book/CalculationBookWorkspace.test.tsx
```

Expected: new assertions fail because preset controls are absent.

**Step 3: Implement preset state and handlers**

Add state for saved presets, selected ID, editable preset name, error text, and updated notice. Implement save, apply, update, rename, delete, and selection handlers. Applying a preset must preserve `archive`, replace form values through `applyCalculationBookPreset`, clear field/form errors, and call `resetPreflight()`.

When the modal opens, reload stored presets and reset transient preset UI state without deleting saved presets.

**Step 4: Add accessible left-rail controls**

Use stable labels and actions:

- `计算书方案名称`
- `已保存计算书方案`
- `保存为新方案`
- `应用方案`
- `更新当前方案`
- `重命名`
- `删除`

Expose errors and “已更新配置” through `aria-live="polite"`.

**Step 5: Run the component test and verify GREEN**

Run the Task 2 command again. Expected: all workspace tests PASS.

**Step 6: Commit**

```powershell
git add frontend/src/features/calculation-book/CalculationBookWorkspace.tsx frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx
git commit -m "feat: manage calculation book presets"
```

### Task 3: Restructure the input phase for compact desktop use

**Files:**
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.module.css`

**Step 1: Write failing semantic-layout tests**

Assert that “上传压缩包” is visible, the native file input retains its accessible name, the slab toggle remains directly available, and a `details` element titled “压缩包结构要求” is initially closed while still containing the required filenames.

**Step 2: Run the workspace test and verify RED**

Run the Task 2 command. Expected: FAIL because the old upload copy and expanded tree remain.

**Step 3: Implement the semantic restructure**

Move upload above the slab toggle. Change empty upload copy to “上传压缩包”. Put the long archive description, required tree, and validation notes inside a default-closed native `<details>` titled “压缩包结构要求”. Place presets between the slab toggle and archive details. Preserve submit behavior, focus trapping, error summaries, and selected-file display.

**Step 4: Implement compact CSS**

Use these desktop targets, adapting only where existing selectors require it:

```css
.dialog { width: min(1360px, calc(100vw - 24px)); }
.content { grid-template-columns: 240px minmax(0, 1fr); gap: 0.75rem; }
.fieldGrid { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.52rem 0.62rem; }
.field input, .field select { min-height: 38px; }
.uploadBox { background: #fff; }
```

Reduce header, steps, content, fieldset, and footer vertical padding without reducing readable label sizes. Use a two-column preset action grid. At medium widths reduce the form to two or three columns; below 900px stack the panels and allow normal scrolling.

**Step 5: Run focused tests and verify GREEN**

```powershell
npm.cmd test -- --run src/features/calculation-book/calculationBookPresets.test.ts src/features/calculation-book/CalculationBookWorkspace.test.tsx
```

Expected: all focused calculation-book tests PASS.

**Step 6: Commit**

```powershell
git add frontend/src/features/calculation-book/CalculationBookWorkspace.tsx frontend/src/features/calculation-book/CalculationBookWorkspace.module.css frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx
git commit -m "style: compact calculation book task setup"
```

### Task 4: Verify responsive usability in the running application

**Files:**
- Modify only for a verified defect: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- Modify only for a verified defect: `frontend/src/features/calculation-book/CalculationBookWorkspace.module.css`
- Test only for a verified defect: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`

**Step 1: Start or reuse feature services**

Use frontend `127.0.0.1:5174` and backend `127.0.0.1:8010`. Verify backend health before UI testing.

**Step 2: Check desktop viewports**

At 1366×768 and 1629×1150 verify the upload label, computed white background, initial collapsed help, visible preset controls, footer reachability, no overlap, and the no/minimal-scroll goal.

**Step 3: Check narrow viewports**

At 900px and 489px verify stacking, focus visibility, no horizontal overflow, and no sticky-header overlap.

**Step 4: Fix only observed issues**

For behavior defects, add a failing test before the fix. For pure visual defects, capture the before-state, make the smallest CSS change, and recheck the same viewport and computed style.

**Step 5: Request independent design review**

Use a dedicated page-design subagent to review density, hierarchy, affordance, accessibility, and the desktop no-scroll goal. Address blocking findings and re-run affected checks.

### Task 5: Full frontend verification and handoff

**Files:**
- Verify: all modified frontend files
- Verify: `docs/plans/2026-08-03-calculation-book-compact-presets-design.md`
- Verify: `docs/plans/2026-08-03-calculation-book-compact-presets-implementation.md`

**Step 1: Run focused tests**

```powershell
npm.cmd test -- --run src/features/calculation-book/calculationBookPresets.test.ts src/features/calculation-book/CalculationBookWorkspace.test.tsx
```

Expected: PASS with zero failures.

**Step 2: Run the full frontend suite**

```powershell
npm.cmd test
```

Expected: PASS with zero failures.

**Step 3: Run the production build**

```powershell
npm.cmd run build
```

Expected: exit code 0. Existing bundle-size or Browserslist notices may remain, but no TypeScript or Vite errors are allowed.

**Step 4: Check the final diff and worktree**

```powershell
git diff --check
git status --short
git log -6 --oneline
```

Confirm there are no unrelated changes and the worktree is clean after the final commit.

**Step 5: Commit review fixes if needed**

```powershell
git add frontend/src/features/calculation-book docs/plans/2026-08-03-calculation-book-compact-presets-implementation.md
git commit -m "fix: refine calculation book preset workspace"
```
