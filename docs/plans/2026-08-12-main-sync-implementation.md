# Latest Main Synchronization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Merge local `main@78e087b` into `codex/calculation-ai-unified` without regressing calculation-book AI, task-group lifecycle, account/workload UI, deployment probes, or production connection behavior.

**Architecture:** Create an auditable checkpoint for the target worktree's local quick-start changes, then perform a normal Git merge and resolve every overlap semantically. Preserve the target branch as the integration architecture and add the new change-page/font behavior as bounded capabilities; verify source, configuration, frontend, probes, real task flow, and packaged output as one system.

**Tech Stack:** Git worktrees, FastAPI, Python/pytest, React/Vite/Vitest, YAML, PowerShell deployment probes, AutoCAD/AcCoreConsole, Office COM.

---

### Task 1: Protect the pre-merge worktree state

**Files:**
- Modify: `documents/快速启动.txt`
- Create: `backend/tests/unit/test_quick_start_commands.py`
- Create: `docs/plans/2026-08-12-main-sync-design.md`
- Create: `docs/plans/2026-08-12-main-sync-implementation.md`

**Steps:**

1. Confirm worktree path, branch, HEAD, status, `main` HEAD and merge base.
2. Run `uv run --project backend python -X utf8 -m pytest backend/tests/unit/test_quick_start_commands.py -q -p no:cacheprovider` with a worktree-local `UV_CACHE_DIR`.
3. Inspect `git diff --check` and the exact staged diff.
4. Commit only the four checkpoint files with `docs: checkpoint calculation AI development commands`.

### Task 2: Merge committed main history

**Files:**
- Merge all files reachable from local `main@78e087b`.

**Steps:**

1. Run `git merge --no-ff main` from the target worktree.
2. Record all unmerged paths with `git diff --name-only --diff-filter=U`.
3. Search for conflict markers with `rg -n "^(<<<<<<<|=======|>>>>>>>)"`.
4. Resolve text files minimally and regenerate build artifacts where source and binary both changed.
5. Do not commit until Tasks 3–6 pass.

### Task 3: Resolve backend and configuration overlaps

**Files:**
- Modify: `API/app/routers/jobs.py`
- Modify: `API/app/runtime.py`
- Modify: `backend/src/config/mechanism_spec.py`
- Modify: `backend/src/config/runtime_config.py`
- Modify: `backend/src/deploy/archive_runtime.py`
- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `backend/src/models/job.py`
- Modify: `backend/src/pipeline/executor.py`
- Modify: `documents/参数规范-3.yaml`
- Modify: `documents/参数规范_运行期.yaml`
- Modify related backend tests.

**Steps:**

1. Add/adjust failing contract tests for coexistence of calculation AI, task-group reconciliation, change-page extraction and font/runtime configuration.
2. Run the focused tests and verify failures reflect missing merged behavior.
3. Resolve production code and YAML by key and state-machine responsibility.
4. Run focused tests to GREEN and run Ruff on touched Python files.

### Task 4: Resolve frontend integration and layout

**Files:**
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.module.css`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/src/app/jobPresentation.ts`
- Add/merge: `frontend/src/features/change-page-extract/*`
- Modify: `frontend/src/platform/api/httpAdapter.ts`
- Modify: `frontend/src/platform/api/httpAdapter.test.ts`
- Modify: `frontend/src/platform/api/types.ts`

**Steps:**

1. Add failing tests for the new entry and API flow while asserting the existing calculation-book, account, workload, AI drawer and connection behavior remains present.
2. Resolve components and adapters without replacing the target app shell.
3. Verify focused Vitest tests.
4. Run the full frontend test suite and `npm.cmd run build`.
5. Inspect 1600×900, 1366×768 and narrow layouts, including keyboard focus and internal scrolling.

### Task 5: Reconcile templates, probes and deployment packaging

**Files:**
- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `tools/prepare_archive_runtime.py`
- Modify: deployment probe scripts and their tests as required.
- Verify: `documents_bin/计算书模板文件.xlsx`
- Verify: `documents_bin/calculation_book/计算书模板文件.xlsx`
- Modify: `documents/终端实装安装计划.md`

**Steps:**

1. Add a failing test that detects template hash drift between business source and packaged runtime copy.
2. Make package preparation copy and verify the canonical template and all new probe/plugin files.
3. Verify Office COM, CAD/AcCore, account, workload, calculation-book and change-page probes emit complete logs.
4. Run deployment-package unit tests and manifest checks.

### Task 6: End-to-end verification and merge commit

**Steps:**

1. Run targeted backend suites for runtime, worker, archive, font, change-page, calculation-book, accounts, workload and deployment.
2. Run full frontend Vitest and production build.
3. Run API and independent Worker health probes.
4. Run the approved real calculation-book RAR through the formal task API and record job ID, output directory, Word/ZIP/log artifacts and duration.
5. Build a fresh full deployment package and verify its manifest/hash against the current HEAD and `D:\FanBanServer` layout.
6. Run `git diff --check`, confirm no conflict markers and review all staged files.
7. Commit the merge only after fresh evidence is green; do not push without separate authorization.
