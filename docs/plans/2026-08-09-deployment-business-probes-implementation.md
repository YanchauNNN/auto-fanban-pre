# Deployment Business Probes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build fail-closed Office, account/workload, and calculation-book deployment probes with comprehensive redacted logs, then publish a full deployment package containing the latest source, probes, private archive runtime, templates, and AI Skills.

**Architecture:** Keep OS/CAD/Office inspection in the existing PowerShell environment probe, but run every Office COM operation in bounded child processes. Add small Python deployment-probe modules for common reporting, authenticated account/workload checks, and calculation-book environment/full-smoke checks. Package thin PowerShell launchers and aggregate their typed JSON results; default to read-only behavior and require an explicit mutation switch for synthetic data.

**Tech Stack:** PowerShell 5.1, Python 3.13, FastAPI, httpx, pytest, React/Vite build artifacts, YAML configuration, Office COM, private 7-Zip 26.02 runtime.

---

### Task 1: Make Office COM checks bounded and diagnostic

**Files:**
- Modify: `backend/tests/unit/test_probe_target_env.py`
- Modify: `backend/tests/integration/test_probe_target_env.py`
- Modify: `tools/probe_target_env.ps1`

**Step 1: Write the failing source-contract tests**

Add assertions that direct Word/Excel COM checks are invoked only through
`Invoke-OfficeWorkerWithTimeout`, both registry views are queried, each worker writes stdout/stderr
paths, and result payloads contain baseline/new/residual process IDs plus elapsed time and stable error
codes.

```python
def test_probe_target_env_bounds_all_office_com_operations() -> None:
    script = _probe_text()
    assert '"word_com"' in script
    assert '"excel_com"' in script
    assert "Invoke-OfficeWorkerWithTimeout" in script
    assert "office_processes_before" in script
    assert "office_processes_after" in script
    assert "office_processes_residual" in script


def test_probe_reads_both_office_registry_views() -> None:
    script = _probe_text()
    assert "Registry64" in script
    assert "Registry32" in script
    assert "WOW6432Node" in script
```

**Step 2: Run the tests and verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_probe_target_env.py -q --basetemp tmp/probe-office-red
```

Expected: FAIL because direct COM checks still run in the parent and the registration/process evidence
contract is absent.

**Step 3: Add a bounded fake-worker integration test**

Exercise the script's worker launcher with a fixture worker that blocks beyond a short test timeout.
Assert the parent returns, writes result JSON and child logs, reports `office_worker_timeout`, and never
selects a process present in the baseline PID set for cleanup.

**Step 4: Run the integration test and verify RED**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_probe_target_env.py -q --basetemp tmp/probe-office-integration-red
```

Expected: FAIL on missing bounded direct-COM behavior or missing evidence fields.

**Step 5: Implement the minimal PowerShell changes**

- Route `word_com`, `excel_com`, `word_export`, and `excel_export` through one worker launcher.
- Snapshot Word/Excel PIDs before launch and after termination.
- On timeout, stop the worker tree and only Office PIDs created after the baseline and attributable to
  the worker window.
- Capture child stdout/stderr and always write result JSON in a parent `finally` path.
- Query `Microsoft.Win32.RegistryView.Registry64` and `Registry32`, plus App Paths.
- Normalize HRESULT `-2147418111` as `office_call_rejected` while retaining the raw HRESULT.
- Do not mutate Office registration, Normal templates, add-ins, trust center, or global profiles.

**Step 6: Run focused tests and verify GREEN**

Run the Task 1 unit and integration commands. Expected: PASS.

**Step 7: Commit**

```powershell
git add -- tools/probe_target_env.ps1 backend/tests/unit/test_probe_target_env.py backend/tests/integration/test_probe_target_env.py
git commit -m "fix: bound Office COM deployment probes"
```

### Task 2: Make generic health checks fail closed on Worker and storage state

**Files:**
- Modify: `backend/tests/unit/test_terminal_deploy_builder.py`
- Modify: `backend/src/deploy/terminal_package.py`

**Step 1: Write the failing generated-script tests**

Generate `check_health.ps1` and assert it parses the JSON body and requires:

```python
assert 'ready -eq $true' in script
assert 'storage_writable -eq $true' in script
assert 'worker_alive -eq $true' in script
assert 'worker_count -gt 0' in script
assert 'code = "api_not_ready"' in script
assert 'code = "worker_not_alive"' in script
```

Also add a PowerShell execution fixture where `/api/system/health` is HTTP 200 but has
`ready=false`, and assert non-zero overall status.

**Step 2: Run and verify RED**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_terminal_deploy_builder.py -q --basetemp tmp/health-red
```

Expected: FAIL because HTTP success currently counts as health success.

**Step 3: Implement strict health-body validation**

Keep listener, IIS, proxy, and business-health results separate. Missing fields, invalid types,
`ready=false`, non-writable storage, or no live Worker must produce stable failure entries and non-zero
overall result.

**Step 4: Run and verify GREEN**

Run the Task 2 test command. Expected: PASS.

**Step 5: Commit**

```powershell
git add -- backend/src/deploy/terminal_package.py backend/tests/unit/test_terminal_deploy_builder.py
git commit -m "fix: require live worker in deployment health"
```

### Task 3: Add shared redacted probe reporting

**Files:**
- Create: `backend/src/deploy/probe_report.py`
- Create: `backend/tests/unit/test_deployment_probe_report.py`
- Modify: `documents/参数规范-3.yaml`
- Modify: `backend/src/config/mechanism_spec.py`
- Modify: `backend/tests/unit/test_mechanism_spec.py`

**Step 1: Write failing tests for the wished-for reporter API**

```python
def test_reporter_redacts_nested_credentials_and_writes_terminal_summary(tmp_path):
    reporter = ProbeReporter(tmp_path, session_id="probe-1", probe_name="account-workload")
    reporter.event("login", "pass", context={"Authorization": "Bearer secret"})
    result = reporter.finish("PASS")
    assert "secret" not in (tmp_path / "events.jsonl").read_text("utf-8")
    assert result.summary_path.exists()


def test_reporter_marks_missing_required_check_as_failure(tmp_path): ...
```

Cover password/token/API-key/cookie/secret keys, bearer text, oversized Base64, monotonic sequence,
atomic summary publication, failure to create the result directory, and `PASS/FAIL/SKIPPED` aggregation.

**Step 2: Run and verify RED**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_deployment_probe_report.py backend/tests/unit/test_mechanism_spec.py -q --basetemp tmp/probe-report-red
```

Expected: collection FAIL because `probe_report` and typed probe mechanism configuration do not exist.

**Step 3: Add typed YAML configuration and minimal reporter**

Add `deployment_mechanism.business_probes` configuration for schema version, result-root relative path,
request/Office/task timeouts, log retention, required health fields, and sensitive-key patterns. Do not
hardcode configurable thresholds in the probe modules.

**Step 4: Run and verify GREEN**

Run the Task 3 command. Expected: PASS.

**Step 5: Commit**

```powershell
git add -- backend/src/deploy/probe_report.py backend/tests/unit/test_deployment_probe_report.py backend/src/config/mechanism_spec.py backend/tests/unit/test_mechanism_spec.py documents/参数规范-3.yaml
git commit -m "feat: add redacted deployment probe reports"
```

### Task 4: Add authenticated account and workload probes

**Files:**
- Create: `backend/src/deploy/business_module_probe.py`
- Create: `backend/tests/unit/test_business_module_probe.py`
- Create: `backend/tests/integration/test_business_module_probe_api.py`

**Step 1: Write failing unit tests**

Define an HTTP client contract and test:

- login or existing bearer token, never both;
- `/api/auth/me`, accounts, invalid rows, workload and task-group/workflow reads;
- permission-aware 403 handling;
- recursive sensitive-field rejection;
- request and response timing in event logs;
- `--allow-synthetic-mutation` defaulting to false;
- no mutation request in default mode;
- mutation marked `SKIPPED` when a safe cleanup API is unavailable.

```python
def test_read_only_probe_never_calls_mutating_routes(fake_api, tmp_path):
    result = run_business_probe(config=_config(tmp_path), client=fake_api)
    assert result.status == "PASS"
    assert all(call.method == "GET" for call in fake_api.business_calls)
```

**Step 2: Run unit tests and verify RED**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_business_module_probe.py -q --basetemp tmp/business-probe-red
```

Expected: collection FAIL because the probe module does not exist.

**Step 3: Write the FastAPI integration tests**

Start the real temporary application with controlled account/workload storage. Verify a valid session
passes read-only checks, a dead Worker health body fails, role-limited endpoints are classified, and a
password injected anywhere in a public response fails with a safe path-only diagnostic.

**Step 4: Run integration tests and verify RED**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/integration/test_business_module_probe_api.py -q --basetemp tmp/business-probe-api-red
```

Expected: FAIL because orchestration and response validation are missing.

**Step 5: Implement the minimal CLI and probe flow**

Expose:

```powershell
python -m src.deploy.business_module_probe `
  --api-base-url http://127.0.0.1:8000 `
  --output-dir probe-results `
  --token-env FANBAN_PROBE_TOKEN
```

Add `--allow-synthetic-mutation`, but never bypass API cleanup. If a reversible delete endpoint is not
available, record the mutation capability as `SKIPPED` rather than editing CSV/JSON/SQLite directly.

**Step 6: Run focused tests and verify GREEN**

Run the Task 4 unit and integration commands. Expected: PASS.

**Step 7: Commit**

```powershell
git add -- backend/src/deploy/business_module_probe.py backend/tests/unit/test_business_module_probe.py backend/tests/integration/test_business_module_probe_api.py
git commit -m "feat: probe account and workload health"
```

### Task 5: Add calculation-book environment and full-smoke probes

**Files:**
- Create: `backend/src/deploy/calculation_book_probe.py`
- Create: `backend/tests/unit/test_calculation_book_probe.py`
- Modify: `tools/smoke_calculation_book_ai_suggestion.py`
- Modify: `backend/tests/unit/calculation_book/test_config.py`

**Step 1: Write failing environment-probe tests**

Test required YAML, template and Skill files, archive runtime result, API/Worker health, preflight
contract, and clear `probe_level=environment`. Missing any required template, Skill file, RAR handler,
Worker, or writable storage must fail.

**Step 2: Run and verify RED**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_calculation_book_probe.py -q --basetemp tmp/calculation-probe-red
```

Expected: collection FAIL because the module does not exist.

**Step 3: Add failing full-smoke tests**

Use `httpx.MockTransport` for deterministic polling and downloads. Cover failed terminal state, timeout,
corrupt DOCX, missing diagnostic log, missing `task_completed`, count mismatch, and success. Assert every
failure retains task ID, last stage/status and safe response excerpts.

**Step 4: Implement the minimal calculation probe**

Move reusable approved-smoke validation from `tools/smoke_calculation_book_ai_suggestion.py` into the
deploy module and keep the tool as a thin compatible entry point. Add explicit `--run-full-smoke`,
`--archive`, and credential options. Full smoke must use formal API plus independent Worker; no direct
processor invocation.

**Step 5: Run and verify GREEN**

Run the Task 5 test command and the existing calculation smoke unit coverage. Expected: PASS.

**Step 6: Commit**

```powershell
git add -- backend/src/deploy/calculation_book_probe.py backend/tests/unit/test_calculation_book_probe.py tools/smoke_calculation_book_ai_suggestion.py backend/tests/unit/calculation_book/test_config.py
git commit -m "feat: add calculation book deployment probe"
```

### Task 6: Package probe launchers, Skills, runtime and manifests

**Files:**
- Create: `tools/probe_business_modules.ps1`
- Create: `tools/probe_calculation_book.ps1`
- Create: `tools/run_deployment_probes.ps1`
- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `backend/tests/unit/test_terminal_deploy_builder.py`
- Modify: `README_部署说明.md` or generated deployment README source in `terminal_package.py`

**Step 1: Write failing package-layout tests**

Assert the generated package contains the three launchers, Python probe modules, Office environment
probe, archive runtime probe, private 7-Zip files, four Skills, calculation templates and manifest
metadata for Git SHA/probe schema/Skill IDs/archive runtime version.

Also assert generated PowerShell parses under Windows PowerShell 5.1 and forwards
`-AllowSyntheticMutation` only when explicitly supplied.

**Step 2: Run and verify RED**

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_terminal_deploy_builder.py -q --basetemp tmp/package-probe-red
```

Expected: FAIL because the launchers and manifest fields are absent.

**Step 3: Implement the minimal package integration**

Copy physical launcher scripts rather than adding more large embedded script bodies. Make
`run_deployment_probes.ps1` create one session directory and aggregate child summaries. Preserve the
current full-package name `build/AI测试终端部署包.zip`.

**Step 4: Run and verify GREEN**

Run Task 6 tests and `git diff --check`. Expected: PASS.

**Step 5: Commit**

```powershell
git add -- tools/probe_business_modules.ps1 tools/probe_calculation_book.ps1 tools/run_deployment_probes.ps1 backend/src/deploy/terminal_package.py backend/tests/unit/test_terminal_deploy_builder.py
git commit -m "feat: package deployment business probes"
```

### Task 7: Run regression tests and rebuild the complete deployment package

**Files:**
- Generated: `frontend/dist/**`
- Generated: `build/runtime-cache/7-Zip/**`
- Generated: `build/fanban-terminal-deploy/**`
- Generated: `build/AI测试终端部署包.zip`

**Step 1: Run backend focused and adjacent regression tests**

```powershell
backend\.venv\Scripts\python.exe -m pytest `
  backend/tests/unit/test_probe_target_env.py `
  backend/tests/integration/test_probe_target_env.py `
  backend/tests/unit/test_deployment_probe_report.py `
  backend/tests/unit/test_business_module_probe.py `
  backend/tests/integration/test_business_module_probe_api.py `
  backend/tests/unit/test_calculation_book_probe.py `
  backend/tests/unit/test_archive_runtime_probe.py `
  backend/tests/unit/test_archive_runtime_deploy.py `
  backend/tests/unit/test_terminal_deploy_builder.py `
  backend/tests/integration/test_account_public_api.py `
  backend/tests/unit/test_workload_queries.py `
  backend/tests/integration/test_workload_queries.py `
  -q --basetemp tmp/probes-final
```

Expected: PASS with no business failures. Use a short basetemp to avoid Windows MAX_PATH artifacts.

**Step 2: Run lint, frontend tests and build**

```powershell
backend\.venv\Scripts\python.exe -m ruff check backend/src/deploy backend/tests/unit backend/tests/integration
Set-Location frontend
npm.cmd test
npm.cmd run build
Set-Location ..
```

Expected: all tests and build PASS.

**Step 3: Prepare the private archive runtime**

```powershell
backend\.venv\Scripts\python.exe tools\prepare_archive_runtime.py
```

Expected: official 7-Zip payload downloaded to the configured cache and every size/SHA/version/handler
check passes. If network is unavailable, stop and report the missing cache; never fall back to PATH.

**Step 4: Build the complete package**

```powershell
backend\.venv\Scripts\python.exe tools\build_terminal_deploy.py `
  --output-root build\fanban-terminal-deploy
```

Expected: a fresh full deployment root and `build/AI测试终端部署包.zip`; do not publish the current
metadata-only delta as a deployment artifact.

**Step 5: Verify the package from inside its own layout**

Run the archive runtime probe and read-only aggregate probe using packaged Python and scripts. Confirm
manifest hashes, probe files, all four Skills, templates and frontend assets. The development machine's
known Word COM failure may make the Office section fail; retain the generated evidence and do not report
an overall PASS in that case.

**Step 6: Inspect Git boundaries and package manifest**

```powershell
git status --short
git diff --check
```

Confirm the pre-existing quick-start and AI-rail changes are untouched and excluded from probe commits.
Record package timestamp, Git SHA, ZIP SHA256, probe results and any remaining environment-only risk.

**Step 7: Commit any final source-only documentation corrections**

Do not commit generated deployment contents unless repository policy already tracks them. If source
documentation needs correction, stage only the exact source paths and commit:

```powershell
git commit -m "docs: document deployment probe workflow"
```
