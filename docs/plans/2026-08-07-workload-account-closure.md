# Workload Closure and Account UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Close the task-group submission/archive/workload lifecycle and redesign the existing workload and account modules without changing the deployed frontend/backend connection contract.

**Architecture:** Add one shared, idempotent task-group completion coordinator and one summary-publish callback at the management-service boundary. Keep the existing job detail route and compose a task-group workflow panel into it; refactor the existing workload/account feature modules rather than adding another top-level management surface.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, pytest, React 18, TypeScript, TanStack Query, React Router, CSS Modules, Vitest/Testing Library.

---

### Task 1: Lock submission readiness and YAML personnel preservation

**Files:**
- Modify: `backend/src/task_groups/submit_guards.py`
- Modify: `backend/src/task_groups/service.py`
- Modify: `documents/参数规范.yaml`
- Test: `backend/tests/integration/test_task_group_submit_flow.py`
- Test: `backend/tests/unit/test_workflow_input_validator.py`

**Step 1: Write failing tests**

Add focused tests proving that queued/running/failed groups, missing children, failed children, and missing required artifacts cannot be submitted, while a completed group can be submitted. Assert `can_submit` uses the same readiness rule. Add a normalization test proving `ied_discipline_leader` survives through `workflow.preserve_fields`.

**Step 2: Verify RED**

Run:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest -c backend\pyproject.toml backend\tests\integration\test_task_group_submit_flow.py backend\tests\unit\test_workflow_input_validator.py -p no:cacheprovider -q
```

Expected: the new readiness/preservation assertions fail for the missing behavior.

**Step 3: Implement the minimum rule**

Create a side-effect-free readiness inspection used by both `ensure_submit_allowed` and `_permissions`. Validate group status, child status, and declared artifact paths. Rename the YAML key to `preserve_fields` and include `ied_discipline_leader`.

**Step 4: Verify GREEN**

Run the command from Step 2 and expect all tests to pass.

### Task 2: Publish management mutations and unify archive completion

**Files:**
- Create: `backend/src/task_groups/completion_service.py`
- Modify: `backend/src/task_groups/service.py`
- Modify: `backend/src/archive/retry_worker.py`
- Modify: `API/app/management_services.py`
- Test: `backend/tests/unit/test_archive_retry_worker.py`
- Test: `backend/tests/integration/test_task_group_submit_flow.py`
- Test: `backend/tests/unit/test_api_runtime_worker_queue.py`

**Step 1: Write failing tests**

Add tests proving that every management mutation invokes a group-summary publisher, that approval archive success and retry archive success both settle workload and mark the group succeeded, and that repeated completion remains idempotent. Add a production-mode test showing the SQLite summary returned by `/api/jobs` changes after a management mutation without waiting for startup backfill.

**Step 2: Verify RED**

Run the three target test files and confirm failures are caused by the missing publisher/coordinator.

**Step 3: Implement the coordinator**

Introduce a small `TaskGroupCompletionService` that owns settlement-trigger evaluation and post-archive completion. Inject a `group_updated` callback and make task-group mutations persist then publish. Construct the retry worker after the coordinator and pass the same completion path to both approval and retry.

**Step 4: Verify GREEN**

Run the target tests and expect all to pass.

### Task 3: Add the task-group workflow panel to the existing detail route

**Files:**
- Create: `frontend/src/features/task-groups/TaskGroupWorkflowPanel.tsx`
- Create: `frontend/src/features/task-groups/TaskGroupWorkflowPanel.module.css`
- Create: `frontend/src/features/task-groups/TaskGroupWorkflowPanel.test.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Reuse: `frontend/src/app/TaskGroupConflictDialog.tsx`

**Step 1: Write failing component and route tests**

Cover: task-group management detail loads only on `/task-groups/:jobId`; ready creators see “提交审批”; non-ready groups show a reason and no active submit button; archive and duplicate conflicts open the existing confirmation dialog and resubmit with the correct flag; successful submission invalidates task/group/workflow/account queries.

**Step 2: Verify RED**

Run the new component test and focused `App.test.tsx` cases. Expect failure because the panel is not mounted.

**Step 3: Implement the panel**

Keep `JobDetailPage` responsible for runtime outputs and mount the new panel only in task-group mode. Load management detail in parallel with runtime detail. Build the workflow rail from YAML-exposed node labels and current task-group state; do not hardcode backend addresses.

**Step 4: Verify GREEN**

Run the focused frontend tests and expect all to pass.

### Task 4: Redesign the workload module as a compact operations surface

**Files:**
- Modify: `frontend/src/features/workload/WorkloadPage.tsx`
- Modify: `frontend/src/features/workload/WorkloadPage.module.css`
- Modify: `frontend/src/features/workload/WorkloadPage.test.tsx`

**Step 1: Write failing behavior/structure tests**

Assert the four-key-metric command strip, clear “待我处理” grouping, compact scope/filter toolbar, YAML-driven node labels, approval affordance, internal result regions, and accessible loading/error states.

**Step 2: Verify RED**

Run `npm.cmd test -- src/features/workload/WorkloadPage.test.tsx` and confirm the new assertions fail.

**Step 3: Implement the restrained two-column layout**

Remove the decorative duplicate hero, reduce card chrome, promote the single next action, and keep long monitor/history lists internally scrollable. Preserve existing query keys, approval and repair behavior.

**Step 4: Verify GREEN**

Run the focused test and expect it to pass.

### Task 5: Redesign personal account and account administration

**Files:**
- Modify: `frontend/src/features/account/AccountPage.tsx`
- Modify: `frontend/src/features/account/AccountPage.module.css`
- Modify: `frontend/src/features/account/AccountPage.test.tsx`
- Modify: `frontend/src/features/account/AccountAdminPage.tsx`
- Modify: `frontend/src/features/account/AccountAdminPage.module.css`
- Modify: `frontend/src/features/account/AccountAdminPage.test.tsx`

**Step 1: Write failing tests**

Cover the compact identity/security/workload layout, password feedback, visible admin counts, local account search, persistent invalid-row affordance, two-pane edit/create flow, and archive-root setting.

**Step 2: Verify RED**

Run the two account test files and confirm the new assertions fail.

**Step 3: Implement the layout**

Reuse existing mutations and modal behavior. Add only local derived search state; avoid a second account-management route or duplicate top-level navigation.

**Step 4: Verify GREEN**

Run the focused tests and expect them to pass.

### Task 6: Visual, connection, and full regression verification

**Files:**
- Verify: `frontend/src/platform/api/apiBaseUrl.test.ts`
- Verify: `frontend/src/tooling/viteProxy.test.ts`
- Verify: `frontend/src/app/App.test.tsx`
- Verify: all backend management tests
- Capture: `output/playwright/workload-account-*.png`

**Step 1: Run backend regression**

Run all management/workflow/workload/archive tests with a short Windows temporary directory and expect zero failures.

**Step 2: Run frontend regression**

Run `npm.cmd test` and `npm.cmd run build`. Confirm the same-origin `/api` and configurable proxy tests still pass.

**Step 3: Run real-browser inspection**

Start an isolated API/worker/frontend stack using the existing same-origin proxy contract. Inspect workload, personal account, account admin, and task-group detail at 1600×900 and 1366×768. Verify keyboard focus, dialogs, primary actions and internal scrolling; save screenshots under `output/playwright/`.

**Step 4: Obtain two-stage review**

Have a spec reviewer compare the implementation to this plan, then have the dedicated UI reviewer inspect aesthetics and usability. Resolve all critical/important findings and rerun affected tests.

