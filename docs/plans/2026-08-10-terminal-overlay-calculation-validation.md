# Terminal Overlay and Calculation Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Support safe direct overlay updates to `D:\FanBanServer`, validate all calculation-book parameters during preflight with simultaneous inline errors, and remove false Office COM probe failures.

**Architecture:** Keep `CalculationBookParams` as the single validation source for preflight and final creation, but move relationship checks to field locations that the UI can render. Make the full deployment package overlay-safe by shipping the account CSV as a seed and initializing it only when absent. Build Office worker arguments without empty optional values.

**Tech Stack:** FastAPI, Pydantic v2, React/TypeScript, Vitest, pytest, PowerShell 5.1, Python deployment package builder.

---

### Task 1: Return field-specific calculation parameter errors

**Files:**
- Modify: `backend/src/calculation_book/models.py`
- Test: `backend/tests/unit/calculation_book/test_models.py`
- Test: `backend/tests/unit/test_module7_api.py`

**Step 1: Write the failing tests**

Add a model test that sets `document_name="11111"`, equal raft/roof elevations, and equal minimum/maximum temperatures, then asserts one validation result contains locations `document_name`, `roof_top_elevation`, and `factory_extreme_max_temperature`. Add an API test that asserts `detail.param_errors` uses the same keys and Chinese messages.

**Step 2: Run tests to verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_models.py backend/tests/unit/test_module7_api.py -q
```

Expected: the new test sees only `params_json` or one root error.

**Step 3: Implement field-specific validators**

Replace the sequential model-level relationship checks with field validators whose locations are the editable fields. Each validator must preserve the existing Chinese rule and allow Pydantic to collect all independent failures. Keep final create validation unchanged.

**Step 4: Run tests to verify GREEN**

Run the command from Step 2 and confirm all selected tests pass.

### Task 2: Validate parameters before archive preflight

**Files:**
- Modify: `API/app/routers/jobs.py`
- Modify: `API/app/runtime.py`
- Modify: `frontend/src/platform/api/types.ts`
- Modify: `frontend/src/platform/api/httpAdapter.ts`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- Test: `backend/tests/unit/test_module7_api.py`
- Test: `frontend/src/platform/api/httpAdapter.test.ts`

**Step 1: Write failing API and adapter tests**

Assert the preflight endpoint rejects invalid `params_json` before calling archive preflight, and that the adapter includes full current parameters in the preflight multipart body.

**Step 2: Run tests to verify RED**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_module7_api.py -q
cd frontend
npm.cmd test -- --run src/platform/api/httpAdapter.test.ts
```

Expected: preflight ignores parameters and multipart data lacks `params_json`.

**Step 3: Implement shared preflight validation**

Add `params_json` to the preflight request. Parse and validate it with `CalculationBookParams`; return the same `{upload_errors, param_errors}` envelope as final creation. Only invoke archive inspection after parameter validation succeeds.

**Step 4: Run tests to verify GREEN**

Repeat Step 2 and confirm both suites pass.

### Task 3: Mark every invalid field and explain every error

**Files:**
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.module.css`
- Test: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`

**Step 1: Write failing interaction tests**

Return three parameter errors from preflight. Assert all three controls have `aria-invalid="true"`, all three inline reasons are visible, the summary names all fields, and no input receives forced focus. Change one field and assert only its error clears.

**Step 2: Run test to verify RED**

```powershell
cd frontend
npm.cmd test -- --run src/features/calculation-book/CalculationBookWorkspace.test.tsx
```

Expected: summary still says “第一个错误字段” and focus is moved.

**Step 3: Implement the UI behavior**

Keep the complete `fieldErrors` map, derive field labels from schema for the summary, remove first-invalid-field focus, focus the alert summary only when needed for accessibility, and ensure `[aria-invalid="true"]` has a visible red border and pale red background. `updateValue` continues clearing only the changed key.

**Step 4: Run test to verify GREEN**

Repeat Step 2.

### Task 4: Make direct overlay packages preserve account data

**Files:**
- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `backend/tests/unit/test_terminal_deploy_builder.py`
- Modify: `backend/tests/unit/test_terminal_install_plan.py`
- Modify: `documents/终端实装安装计划.md`

**Step 1: Write failing package and documentation tests**

Assert a full package contains an account seed outside the live `documents_bin/姓名角色表.csv` path, `init_storage.ps1` copies the seed only when the live file is absent, and the installation plan says: stop service, overlay directly into `D:\FanBanServer`, run post-overlay commands, then deep health checks.

**Step 2: Run tests to verify RED**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_terminal_deploy_builder.py backend/tests/unit/test_terminal_install_plan.py -q
```

Expected: the live account CSV remains in the package and the plan still references `D:\FanBanUpdate`.

**Step 3: Implement overlay-safe packaging and commands**

Move the packaged default account table to `install/seeds/姓名角色表.csv`. Generate idempotent initialization that copies it to `documents_bin/姓名角色表.csv` only if missing. Rewrite the update section around direct overlay and remove staging `robocopy` instructions.

**Step 4: Run tests to verify GREEN**

Repeat Step 2.

### Task 5: Remove empty Office worker arguments

**Files:**
- Modify: `tools/probe_target_env.ps1`
- Test: `backend/tests/unit/test_probe_target_env.py`
- Test: `backend/tests/integration/test_probe_target_env.py`

**Step 1: Write the failing test**

Add a PowerShell-backed test that captures the arguments used for `word_com` and `excel_com` and asserts no null or empty argument is passed. Preserve template arguments for export/template tasks.

**Step 2: Run test to verify RED**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_probe_target_env.py backend/tests/integration/test_probe_target_env.py -q
```

Expected: direct COM tasks include empty template arguments.

**Step 3: Build arguments conditionally**

Construct the fixed worker argument list first, append template path/label switches only when their values are non-empty, then invoke the bounded child process. Keep all existing diagnostic paths and timeout handling.

**Step 4: Run test to verify GREEN**

Repeat Step 2.

### Task 6: Full verification and package rebuild

**Files:**
- Verify all files above
- Rebuild: `build/fanban-terminal-deploy`
- Rebuild: `build/AI测试终端部署包.zip`

**Step 1: Run focused backend and PowerShell tests**

Run all tests changed in Tasks 1-5 with a short Windows temp root and run Ruff on changed Python files.

**Step 2: Run frontend verification**

```powershell
cd frontend
npm.cmd test -- --run
npm.cmd run build
```

**Step 3: Rebuild and verify the full package**

Run `tools/build_terminal_deploy.py --skip-frontend-build`, validate every manifest hash, parse all packaged PowerShell scripts, run packaged account/workload and calculation probes, then rebuild and test `AI测试终端部署包.zip` and its SHA-256 file.

**Step 4: Commit path-scoped changes**

Stage only the files listed in this plan. Preserve the pre-existing `documents/快速启动.txt` and `backend/tests/unit/test_quick_start_commands.py` changes.

