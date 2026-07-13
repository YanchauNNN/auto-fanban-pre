# Worker Process and SQLite Queue Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move CAD and document generation out of uvicorn into an independent worker process, backed by a SQLite queue and lightweight task summary index.

**Architecture:** The API process creates jobs, stores uploads, writes JSON records, enqueues work in SQLite, and serves status/download endpoints. A separate worker process claims SQLite queue items, runs the existing group/job execution pipeline, updates JSON records, and refreshes SQLite summaries. The frontend polls a lightweight activity endpoint instead of repeatedly fetching full job lists.

**Tech Stack:** FastAPI, Python standard `sqlite3`, existing Pydantic job/group models, React Query, PowerShell deployment scripts, existing pytest/Vitest test suites.

---

## Task 1: Add SQLite Control Store

**Files:**

- Create: `backend/src/pipeline/sqlite_queue.py`
- Test: `backend/tests/unit/test_sqlite_queue.py`

**Step 1: Write failing tests**

Cover:

- schema initialization creates `queue_items`, `worker_heartbeats`, `job_summaries`, `activity_state`
- enqueue is idempotent for unfinished items
- claim marks exactly one queued item as `claimed`
- complete marks an item `done`
- stale claim detection returns expired claimed items
- summary upsert and paged listing do not require reading job JSON

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_sqlite_queue.py -q
```

Expected: fail because module does not exist.

**Step 2: Implement minimal SQLite store**

Implement a `SQLiteQueueStore` class with:

- `__init__(db_path: Path)`
- `initialize()`
- `enqueue(item_type, item_id, priority=0, run_after=None)`
- `claim_next(worker_id, now=None)`
- `heartbeat_claim(item_type, item_id, worker_id, now=None)`
- `complete(item_type, item_id, status="done", error=None)`
- `find_stale_claims(timeout_seconds, now=None)`
- `upsert_summary(summary: Mapping[str, Any])`
- `list_summaries(status=None, offset=0, limit=100)`
- `activity()`

Use short transactions and `sqlite3.Row`. Store datetimes as ISO strings.

**Step 3: Verify tests pass**

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_sqlite_queue.py -q
```

Expected: pass.

**Step 4: Commit**

```powershell
git add backend/src/pipeline/sqlite_queue.py backend/tests/unit/test_sqlite_queue.py
git commit -m "feat: add sqlite worker queue store"
```

## Task 2: Add Summary Index Builders

**Files:**

- Create: `backend/src/pipeline/task_index.py`
- Modify: `API/app/runtime.py`
- Test: `backend/tests/unit/test_task_index.py`

**Step 1: Write failing tests**

Cover:

- job summary includes fields currently used by `HttpAdapter.normalizeSummary`
- group summary includes group-specific fields
- `failure_reason` and `stage_context` match existing runtime behavior
- reindex reads current JSON once and upserts summaries

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_task_index.py -q
```

Expected: fail because module does not exist.

**Step 2: Extract summary building logic**

Move or wrap existing `_serialize_job_summary`, `_serialize_group_summary`, and failure-normalization behavior into reusable functions/classes that API and worker can both call.

Keep API response shape unchanged.

**Step 3: Verify tests**

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_task_index.py -q
```

Expected: pass.

**Step 4: Commit**

```powershell
git add backend/src/pipeline/task_index.py API/app/runtime.py backend/tests/unit/test_task_index.py
git commit -m "feat: add task summary index builders"
```

## Task 3: Convert API Runtime to Enqueue-Only

**Files:**

- Modify: `API/app/runtime.py`
- Modify: `API/app/routers/jobs.py`
- Test: `backend/tests/unit/test_module7_api.py`
- Test: `backend/tests/unit/test_api_runtime_config.py`

**Step 1: Write failing tests**

Add tests proving:

- creating deliverable batch writes JSON and enqueues jobs, but does not call the heavy processor
- creating audit check/replace batch enqueues jobs
- grouped submissions enqueue group item
- API startup does not mark queued/running tasks as `service_restarted_before_completion`
- `health()` reports queue depth and worker state from SQLite

Run targeted tests:

```powershell
uv run --project backend pytest backend/tests/unit/test_module7_api.py backend/tests/unit/test_api_runtime_config.py -q
```

Expected: fail before implementation.

**Step 2: Inject SQLite queue store**

Add queue store initialization to `DeliverableApiRuntime`. Replace `_enqueue_job()` and `_enqueue_group()` behavior with SQLite `enqueue()`.

Do not delete worker execution methods yet; they will be moved/reused in Task 4.

**Step 3: Replace startup recovery**

Remove API-side “running means service restarted before completion” recovery. Move stale worker handling to worker startup.

**Step 4: Verify targeted tests**

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_module7_api.py backend/tests/unit/test_api_runtime_config.py -q
```

Expected: pass after updating assertions.

**Step 5: Commit**

```powershell
git add API/app/runtime.py API/app/routers/jobs.py backend/tests/unit/test_module7_api.py backend/tests/unit/test_api_runtime_config.py
git commit -m "feat: make api runtime enqueue worker tasks"
```

## Task 4: Add Worker Runtime and CLI Entry

**Files:**

- Create: `API/app/worker.py`
- Create: `backend/src/pipeline/worker_runtime.py`
- Modify: `API/app/runtime.py`
- Test: `backend/tests/unit/test_worker_runtime.py`

**Step 1: Write failing tests**

Cover:

- worker claims queued job and calls existing `_run_job` path
- worker claims group and calls existing group processing path
- worker heartbeat updates while running
- stale claimed item becomes `worker_interrupted_before_completion`
- worker completion updates queue and summary index

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_worker_runtime.py -q
```

Expected: fail because worker runtime does not exist.

**Step 2: Implement worker runtime**

Create a reusable runtime that owns:

- `JobManager`
- `GroupManager`
- `PipelineJobProcessor`
- `SharedPrepService`
- `CADSlotPool`
- worker thread pools
- queue claim loop

Move or delegate existing `_process_group`, `_run_job`, `_run_doc_job`, completion wait, and slot-bound logic out of API runtime.

**Step 3: Add CLI entry**

`API/app/worker.py` should parse minimal args or env, initialize config, start worker loop, handle Ctrl+C/termination cleanly.

**Step 4: Verify tests**

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_worker_runtime.py -q
```

Expected: pass.

**Step 5: Commit**

```powershell
git add API/app/worker.py backend/src/pipeline/worker_runtime.py API/app/runtime.py backend/tests/unit/test_worker_runtime.py
git commit -m "feat: add independent backend worker runtime"
```

## Task 5: Add Activity Endpoint and Indexed Job Listing

**Files:**

- Modify: `API/app/routers/jobs.py`
- Modify: `API/app/runtime.py`
- Test: `backend/tests/unit/test_module7_api.py`

**Step 1: Write failing tests**

Cover:

- `GET /api/jobs/activity` returns active counts and timestamps
- `GET /api/jobs` uses SQLite summaries when available
- fallback reindex works when summaries are missing
- pagination and status filter behavior remain compatible

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_module7_api.py -q
```

Expected: fail before implementation.

**Step 2: Implement endpoint**

Add `jobs_activity()` in runtime and router. Return compact JSON for frontend polling.

**Step 3: Switch list jobs**

Make `list_jobs()` read summaries from SQLite. If index is empty but JSON files exist, rebuild index once.

**Step 4: Commit**

```powershell
git add API/app/runtime.py API/app/routers/jobs.py backend/tests/unit/test_module7_api.py
git commit -m "feat: serve jobs from sqlite summary index"
```

## Task 6: Update Frontend Polling

**Files:**

- Modify: `frontend/src/platform/api/types.ts`
- Modify: `frontend/src/platform/api/httpAdapter.ts`
- Modify: `frontend/src/app/App.tsx`
- Test: `frontend/src/platform/api/httpAdapter.test.ts`
- Test: `frontend/src/app/App.test.tsx`

**Step 1: Write failing tests**

Cover:

- adapter calls `/api/jobs/activity`
- home page does not run duplicate full job list polling
- activity timestamp change triggers recent jobs refresh
- history modal still pages through `/api/jobs`

Run:

```powershell
cd frontend
npm test -- --run src/platform/api/httpAdapter.test.ts src/app/App.test.tsx
```

Expected: fail before implementation.

**Step 2: Implement adapter activity method**

Add `getJobsActivity()` to adapter and types.

**Step 3: Replace duplicate polling**

Remove `jobsActivityQuery` full list polling. Use `/api/jobs/activity` for active state and refresh trigger.

**Step 4: Verify**

Run:

```powershell
cd frontend
npm test -- --run src/platform/api/httpAdapter.test.ts src/app/App.test.tsx
npm run build
```

Expected: pass.

**Step 5: Commit**

```powershell
git add frontend/src/platform/api/types.ts frontend/src/platform/api/httpAdapter.ts frontend/src/app/App.tsx frontend/src/platform/api/httpAdapter.test.ts frontend/src/app/App.test.tsx
git commit -m "feat: poll lightweight job activity"
```

## Task 7: Update Deployment Supervisor

**Files:**

- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `tools/probe_target_env.ps1`
- Test: `backend/tests/unit/test_terminal_deploy_builder.py`
- Test: `backend/tests/unit/test_probe_target_env.py`

**Step 1: Write failing tests**

Cover generated scripts contain:

- API process command
- worker process command
- separate API and worker logs
- worker heartbeat diagnosis in health check
- no whole-backend restart on `ping_failed_listener_alive`
- Job Object still binds both children to scheduled task lifetime

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_terminal_deploy_builder.py backend/tests/unit/test_probe_target_env.py -q
```

Expected: fail before implementation.

**Step 2: Update `start_backend.ps1` template**

Supervisor starts API and worker. It restarts API based on API listener/ping and restarts worker based on heartbeat/process exit. It does not kill worker when API ping times out.

**Step 3: Update health check**

`check_health.ps1` reports API listener, worker process, worker heartbeat, queue depth, and stale claim count.

**Step 4: Verify**

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_terminal_deploy_builder.py backend/tests/unit/test_probe_target_env.py -q
```

Expected: pass.

**Step 5: Commit**

```powershell
git add backend/src/deploy/terminal_package.py tools/probe_target_env.ps1 backend/tests/unit/test_terminal_deploy_builder.py backend/tests/unit/test_probe_target_env.py
git commit -m "feat: supervise api and worker separately"
```

## Task 8: Update Runtime Config and Deployment Docs

**Files:**

- Modify: `documents/参数规范_运行期.yaml`
- Modify: `backend/src/config/runtime_config.py`
- Modify: `documents/终端实装安装计划.md`
- Test: `backend/tests/unit/test_config.py`

**Step 1: Write failing tests**

Cover new runtime config:

- queue DB path default
- worker heartbeat timeout
- worker poll interval
- stale claim policy

Run:

```powershell
uv run --project backend pytest backend/tests/unit/test_config.py -q
```

Expected: fail before implementation.

**Step 2: Add config**

Add `worker` or `queue` runtime config section. Keep defaults offline-friendly.

**Step 3: Update docs**

Document that normal install commands stay the same, but backend restart now manages API and worker.

**Step 4: Commit**

```powershell
git add documents/参数规范_运行期.yaml backend/src/config/runtime_config.py documents/终端实装安装计划.md backend/tests/unit/test_config.py
git commit -m "docs: document worker queue runtime settings"
```

## Task 9: Full Test and Build Gate

**Files:** no code changes expected.

**Step 1: Run backend targeted tests**

```powershell
uv run --project backend pytest backend/tests/unit/test_sqlite_queue.py backend/tests/unit/test_task_index.py backend/tests/unit/test_worker_runtime.py backend/tests/unit/test_module7_api.py backend/tests/unit/test_terminal_deploy_builder.py backend/tests/unit/test_config.py -q
```

Expected: pass.

**Step 2: Run frontend tests**

```powershell
cd frontend
npm test
npm run build
```

Expected: pass.

**Step 3: Build deploy package**

```powershell
uv run --project backend python tools/build_terminal_deploy.py
```

Expected: package builds successfully and includes API, worker, SQLite modules, updated scripts, updated frontend.

**Step 4: Deployment hygiene scan**

Search package output for:

- development absolute paths
- stale editable install records
- missing worker files
- missing frontend assets

Expected: no blocking findings.

## Task 10: Full Task Smoke

**Files:** no code changes expected unless failures are found.

**Step 1: Start local deploy-like API + worker**

Use packaged or deploy-like runtime. Confirm:

- API ping responds while worker is idle
- worker heartbeat appears in health
- `/api/jobs/activity` returns compact state

**Step 2: Run all task classes**

Smoke:

- deliverable output
- split only
- audit check
- audit replace
- replace then deliverable
- font preflight/replacement
- downloads for package, preview, report, replaced DWG

Use existing real-DWG smoke skill/checklist when available.

**Step 3: Verify resilience behavior**

During a worker task:

- API health/ping remains responsive
- restarting API does not fail the worker task
- stopping scheduled task stops both API and worker

**Step 4: Final handoff**

Report separately:

- code implemented
- tests passed
- real sample smoke-tested
- remaining risk
