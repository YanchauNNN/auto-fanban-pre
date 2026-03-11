# Module5 GUI Live Progress And AutoCAD Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Raise the M5 line rebuild limits, show live `job.json`/trace progress in the packaged GUI, and make the packaged launcher auto-detect the target machine's AutoCAD path so the same DWG can run on different Windows machines.

**Architecture:** Keep the current packaged entrypoint and pipeline. Fix the target-machine failure at the launcher/runtime-environment layer, not inside plotting logic. Add lightweight GUI polling against the existing `storage/jobs/<job_id>/job.json` and `module5_trace.log` instead of inventing a second progress channel.

**Tech Stack:** Python, Tkinter, PyInstaller onedir package, existing `PipelineExecutor`, AutoCAD path resolver.

---

### Task 1: Add Failing Tests For Launcher Path Detection And Live Snapshot Helpers

**Files:**
- Modify: `backend/tests/unit/test_fanban_m5_launcher.py`
- Modify: `test/dist/src/fanban_m5_launcher.py`

**Step 1: Write the failing tests**

- Add a test that verifies the launcher sets `FANBAN_MODULE5_EXPORT__CAD_RUNNER__ACCORECONSOLE_EXE` from an auto-detected path when frozen.
- Add a test that verifies the launcher exposes a stable `job_dir` resolver for a given `job_id`.
- Add a test that verifies reading a live snapshot returns current `job.json` plus trace excerpt content.

**Step 2: Run the tests to verify they fail**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_fanban_m5_launcher.py -q
```

Expected: failures for missing launcher behavior/helpers.

**Step 3: Write the minimal implementation**

- In `test/dist/src/fanban_m5_launcher.py`:
  - import and use `resolve_autocad_paths`
  - add `new_job_id()`
  - add `resolve_job_dir(job_id)`
  - add `read_job_live_snapshot(job_id or job_dir)`
  - make `configure_runtime_environment()` write detected AutoCAD env vars when available

**Step 4: Run the tests to verify they pass**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_fanban_m5_launcher.py -q
```

Expected: PASS.

### Task 2: Add Failing Tests For AutoCAD Resolver Candidate Coverage

**Files:**
- Modify: `backend/tests/unit/test_autocad_path_resolver.py`
- Modify: `backend/src/cad/autocad_path_resolver.py`

**Step 1: Write the failing test**

- Add a test that verifies default candidate roots also include `D:\AUTOCAD\AutoCAD <year>` style installs.

**Step 2: Run the test to verify it fails**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_autocad_path_resolver.py -q
```

Expected: FAIL because the current defaults miss `D:\AUTOCAD`.

**Step 3: Write the minimal implementation**

- Expand `_default_install_candidates()` to include `D:\AUTOCAD`, `C:\AUTOCAD`, and preserve current Autodesk roots.

**Step 4: Run the test to verify it passes**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_autocad_path_resolver.py -q
```

Expected: PASS.

### Task 3: Update GUI To Poll Live Job State

**Files:**
- Modify: `test/dist/src/fanban_m5_gui.py`
- Reuse: `test/dist/src/fanban_m5_launcher.py`

**Step 1: Write the failing test where practical**

- Prefer pure-function tests in launcher instead of Tkinter widget tests.
- GUI wiring itself can be verified with a packaged/manual smoke run after code.

**Step 2: Implement the GUI polling**

- Generate `job_id` before the worker starts.
- Pass that `job_id` into `run_split_only_job()`.
- Start a Tkinter `after()` polling loop that:
  - refreshes the jobs list
  - reads current `job.json`
  - reads recent `module5_trace.log`
  - writes both into the detail pane while the task is running
- Stop polling when status becomes terminal or when the worker raises.

**Step 3: Verify with local run**

- Launch the packaged GUI or source GUI.
- Start one job.
- Confirm the detail pane updates during execution without needing the manual refresh button.

### Task 4: Raise The Line Rebuild Limits

**Files:**
- Modify: `documents/参数规范.yaml`
- Modify: `documents/参数规范_运行期.yaml`

**Step 1: Update the effective business spec**

- Change:
  - `max_segments: 5000 -> 500000`
  - `max_coord_pairs: 50000 -> 1000000`

**Step 2: Keep runtime spec documentation in sync**

- Mirror the same values in `documents/参数规范_运行期.yaml` for documentation consistency.

**Step 3: Verify via grep**

Run:

```powershell
rg -n "max_segments|max_coord_pairs" documents -S
```

Expected: both files show the new values.

### Task 5: End-To-End Verification

**Files:**
- Verify only

**Step 1: Run focused unit tests**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\test_fanban_m5_launcher.py backend\tests\unit\test_autocad_path_resolver.py -q
```

**Step 2: Rebuild the .NET bridge**

Run:

```powershell
dotnet build backend\src\cad\dotnet\Module5CadBridge\Module5CadBridge.csproj -c Release
```

**Step 3: Rebuild the packaged GUI**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File test\dist\src\build_fanban_m5.ps1
```

**Step 4: Verify the real failure root cause is addressed**

- Confirm launcher runtime environment now resolves a real `accoreconsole.exe` path instead of the old hard-coded default on machines that install AutoCAD under `D:\AUTOCAD\...`.

**Step 5: Note performance findings without speculative claims**

- Compare packaged vs source runtime based on actual logs/timestamps.
- If not enough evidence, report that performance diagnosis remains open instead of guessing.
