# Project Number Inference And Split-Only Probe Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add shared DWG filename project-number inference, update split-only probing to the new naming rule, and keep the M5 packaged GUI aligned with the latest backend behavior.

**Architecture:** Put the inference rule in a backend-shared helper under `backend/src/pipeline/`, let both the launcher and the CLI call it, and keep GUI auto-fill as a thin consumer with explicit manual-override protection. Replace the split-only hardcoded filename probes with dynamic filename parsing based on the final output naming contract.

**Tech Stack:** Python, pytest, Tkinter, PyInstaller onedir packaging.

---

### Task 1: Shared Project Number Inference

**Files:**
- Create: `backend/src/pipeline/project_no_inference.py`
- Test: `backend/tests/unit/test_project_no_inference.py`

**Step 1: Write the failing test**
- Add tests for:
  - `20261RS-JGS65.dwg -> 2026`
  - `19076NH-JGS45 -> 1907`
  - non-matching names return `None`

**Step 2: Run test to verify it fails**
- Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_project_no_inference.py -q`

**Step 3: Write minimal implementation**
- Add a small helper that reads the filename stem and returns the first 4 digits if present.

**Step 4: Run test to verify it passes**
- Re-run the same pytest command.

### Task 2: Launcher Uses Shared Inference

**Files:**
- Modify: `test/dist/src/fanban_m5_launcher.py`
- Test: `backend/tests/unit/test_fanban_m5_launcher.py`

**Step 1: Write the failing test**
- Add tests showing:
  - explicit `project_no` wins
  - blank `project_no` falls back to inferred value
  - blank `project_no` with no inferable filename falls back to `2016`

**Step 2: Run test to verify it fails**
- Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_fanban_m5_launcher.py -q`

**Step 3: Write minimal implementation**
- Import the shared helper.
- Add a small resolver function and use it in `build_split_only_job()`.

**Step 4: Run test to verify it passes**
- Re-run the same pytest command.

### Task 3: GUI Auto-Fill Without Overwriting Manual Input

**Files:**
- Modify: `test/dist/src/fanban_m5_gui.py`
- Create: `backend/tests/unit/test_fanban_m5_gui.py`

**Step 1: Write the failing test**
- Add tests for pure helper behavior:
  - auto-managed/default value gets replaced by inferred project number
  - manual value is preserved
  - no inferred value leaves the current value unchanged

**Step 2: Run test to verify it fails**
- Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_fanban_m5_gui.py -q`

**Step 3: Write minimal implementation**
- Add pure helper functions for project number auto-fill policy.
- Wire them into `pick_dwg()` with an auto-managed state flag.

**Step 4: Run test to verify it passes**
- Re-run the same pytest command.

### Task 4: Split-Only Dynamic Probes

**Files:**
- Modify: `tools/run_dwg_split_only.py`
- Create: `backend/tests/unit/test_run_dwg_split_only.py`

**Step 1: Write the failing test**
- Add tests showing:
  - the script can resolve `001/002` PDFs from filenames using the new naming rule
  - project number resolution prefers explicit input, then inferred filename, then `2016`

**Step 2: Run test to verify it fails**
- Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_run_dwg_split_only.py -q`

**Step 3: Write minimal implementation**
- Refactor the script into small helpers for project number resolution and probe selection.
- Replace hardcoded legacy filenames with dynamic matching.

**Step 4: Run test to verify it passes**
- Re-run the same pytest command.

### Task 5: Full Verification And Rebuild

**Files:**
- Modify if needed: `test/dist/src/build_fanban_m5.ps1`

**Step 1: Run focused verification**
- Run:
  - `backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_project_no_inference.py backend/tests/unit/test_fanban_m5_launcher.py backend/tests/unit/test_fanban_m5_gui.py backend/tests/unit/test_run_dwg_split_only.py backend/tests/unit/test_frame_splitter.py backend/tests/unit/test_cad_dxf_executor.py -q`
  - `backend\.venv\Scripts\python.exe -m py_compile backend/src/pipeline/project_no_inference.py test/dist/src/fanban_m5_launcher.py test/dist/src/fanban_m5_gui.py tools/run_dwg_split_only.py`

**Step 2: Rebuild packaged app**
- Run: `powershell -ExecutionPolicy Bypass -File test\dist\src\build_fanban_m5.ps1`

**Step 3: Smoke-check outputs**
- Confirm the rebuilt package exists under `test\dist\fanban_m5` and the old summary probe issue is gone on at least one sample run.
