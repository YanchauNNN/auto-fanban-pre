# Module5 PDF2-Only GUI Packaging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the current module5 flow PDF2-only with automatic plot resource deployment, verify it on the 2016 sample, then add a simple Tkinter GUI and PyInstaller onedir packaging scaffold under `test/dist/`.

**Architecture:** Keep the existing module1~5 execution path intact. Add a plot resource manager in the backend, remove `DWG To PDF.pc3` defaults/fallbacks across Python/LISP/.NET, then layer a thin GUI launcher in `test/dist/` that reuses the same execution and task-record pipeline.

**Tech Stack:** Python, Tkinter, PyInstaller, AutoCAD AcCoreConsole, .NET Framework 4.8 bridge, pytest

---

### Task 1: Add failing tests for AutoCAD path resolution and plot resource deployment

**Files:**
- Modify: `backend/tests/unit/test_autocad_path_resolver.py`
- Create: `backend/tests/unit/test_plot_resource_manager.py`
- Create: `backend/src/cad/plot_resource_manager.py`

**Step 1: Write the failing test**

- Add a test proving user `Plotters` should be preferred over install `Plotters`.
- Add a test proving `打印PDF2.pc3` and its `.pmp` are discovered/deployed.
- Add a test proving `monochrome.ctb` can be sourced from an existing AutoCAD user directory when not bundled in repo assets.

**Step 2: Run test to verify it fails**

Run:

```bash
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_autocad_path_resolver.py backend/tests/unit/test_plot_resource_manager.py -v
```

Expected: FAIL because the deployment manager does not exist yet and path priority is still wrong.

**Step 3: Write minimal implementation**

- Extend `autocad_path_resolver.py` so `plotters_dir` / `plot_styles_dir` prefer user profile directories.
- Implement `plot_resource_manager.py` with a small API that:
  - locates deployment targets
  - copies `打印PDF2.pc3`
  - copies the required `.pmp`
  - resolves or copies `monochrome.ctb`
  - raises a clear exception if deployment still cannot satisfy required resources

**Step 4: Run test to verify it passes**

Run the same pytest command and confirm green.

**Step 5: Commit**

```bash
git add backend/tests/unit/test_autocad_path_resolver.py backend/tests/unit/test_plot_resource_manager.py backend/src/cad/plot_resource_manager.py backend/src/cad/autocad_path_resolver.py
git commit -m "test: add plot resource deployment coverage"
```

### Task 2: Add failing tests for PDF2-only defaults and runner payloads

**Files:**
- Modify: `backend/tests/unit/test_accoreconsole_runner.py`
- Modify: `backend/tests/unit/test_cad_dxf_executor.py`
- Modify: `backend/src/cad/accoreconsole_runner.py`
- Modify: `backend/src/cad/cad_dxf_executor.py`
- Modify: `backend/src/cad/scripts/module5_cad_executor.lsp`
- Modify: `backend/src/cad/scripts/module5_bootstrap.scr`
- Modify: `backend/src/cad/dotnet/Module5CadBridge/Commands.cs`

**Step 1: Write the failing test**

- Replace `DWG To PDF.pc3` expectations with `打印PDF2.pc3`.
- Add a test proving `CADDXFExecutor` invokes deployment before building task JSON.
- Add a test proving generated runtime scripts never emit `DWG To PDF.pc3`.

**Step 2: Run test to verify it fails**

Run:

```bash
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_accoreconsole_runner.py backend/tests/unit/test_cad_dxf_executor.py -v
```

Expected: FAIL because defaults still contain `DWG To PDF.pc3`.

**Step 3: Write minimal implementation**

- Change all remaining runtime defaults from `DWG To PDF.pc3` to `打印PDF2.pc3`.
- Hook plot resource deployment into the current module5 path before task JSON is built.
- Remove any code path that silently substitutes `DWG To PDF.pc3`.

**Step 4: Run test to verify it passes**

Run the same pytest command and confirm green.

**Step 5: Commit**

```bash
git add backend/tests/unit/test_accoreconsole_runner.py backend/tests/unit/test_cad_dxf_executor.py backend/src/cad/accoreconsole_runner.py backend/src/cad/cad_dxf_executor.py backend/src/cad/scripts/module5_cad_executor.lsp backend/src/cad/scripts/module5_bootstrap.scr backend/src/cad/dotnet/Module5CadBridge/Commands.cs
git commit -m "fix: enforce PDF2-only plot device in module5"
```

### Task 3: Rebuild bridge and verify unit scope

**Files:**
- Modify if needed: `backend/src/cad/dotnet/Module5CadBridge/bin/Release/net48/Module5CadBridge.dll`

**Step 1: Write the failing test**

- No new test here; use the existing unit coverage as the failing signal after code edits.

**Step 2: Run test to verify current implementation is coherent**

Run:

```bash
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_autocad_path_resolver.py backend/tests/unit/test_plot_resource_manager.py backend/tests/unit/test_accoreconsole_runner.py backend/tests/unit/test_cad_dxf_executor.py -v
```

Expected: PASS before rebuilding the .NET bridge.

**Step 3: Write minimal implementation**

- Rebuild `Module5CadBridge.dll` so runtime behavior matches source defaults.

Suggested command:

```bash
msbuild backend\src\cad\dotnet\Module5CadBridge\Module5CadBridge.csproj /p:Configuration=Release
```

**Step 4: Run test to verify it passes**

- Re-run the same pytest command.
- If build output path changes, verify the configured DLL path still points to the rebuilt DLL.

**Step 5: Commit**

```bash
git add backend/src/cad/dotnet/Module5CadBridge/Commands.cs backend/src/cad/dotnet/Module5CadBridge/bin/Release/net48/Module5CadBridge.dll
git commit -m "build: refresh module5 bridge after PDF2-only defaults"
```

### Task 4: Run the 2016 regression on the current program

**Files:**
- No code file required unless debugging reveals a defect

**Step 1: Write the failing test**

- Use the real regression command as the failing acceptance test.

**Step 2: Run test to verify it fails or passes**

Run:

```bash
backend\.venv\Scripts\python.exe tools\run_dwg_split_only.py "test\dwg\2016仿真图.dwg" --project-no 2016
```

Expected: The run completes with `打印PDF2.pc3` only. If it fails, inspect `storage/jobs/<job_id>/work/cad_tasks/**/module5_trace.log`.

**Step 3: Write minimal implementation**

- Fix only the defects revealed by this regression.
- Do not start GUI work until this regression is acceptable.

**Step 4: Run test to verify it passes**

- Re-run the same command until it succeeds.

**Step 5: Commit**

```bash
git add <only the files changed by regression fixes>
git commit -m "fix: stabilize 2016 regression with PDF2-only plotting"
```

### Task 5: Add a simple GUI launcher under `test/dist`

**Files:**
- Create: `test/dist/src/fanban_m5_gui.py`
- Create: `test/dist/src/fanban_m5_launcher.py`
- Create: `backend/tests/unit/test_fanban_m5_launcher.py`

**Step 1: Write the failing test**

- Add tests for launcher helpers:
  - validating DWG input path
  - preparing output directory
  - reading recent jobs from `storage/jobs`
  - building a `Job` object with `split_only=True`

**Step 2: Run test to verify it fails**

Run:

```bash
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_fanban_m5_launcher.py -v
```

Expected: FAIL because launcher helpers do not exist yet.

**Step 3: Write minimal implementation**

- Put GUI-related source in `test/dist/src/`.
- Keep UI thin and move reusable helper logic into `fanban_m5_launcher.py`.
- The GUI must support:
  - choosing one DWG
  - choosing one output directory
  - launching the module1~5 split-only job
  - showing recent job status and key logs

**Step 4: Run test to verify it passes**

Run the same pytest command and confirm green.

**Step 5: Commit**

```bash
git add test/dist/src/fanban_m5_gui.py test/dist/src/fanban_m5_launcher.py backend/tests/unit/test_fanban_m5_launcher.py
git commit -m "feat: add module5 desktop launcher under test/dist"
```

### Task 6: Add packaging assets and build scripts under `test/dist`

**Files:**
- Create: `test/dist/src/build_fanban_m5.ps1`
- Create: `test/dist/src/fanban_m5.spec`
- Create: `test/dist/assets/plotters/打印PDF2.pc3`
- Create: `test/dist/assets/plotters/tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp`
- Create or materialize: `test/dist/assets/plot_styles/monochrome.ctb`

**Step 1: Write the failing test**

- No formal unit test required; use a packaging smoke command as the failing test.

**Step 2: Run test to verify it fails**

Run:

```bash
powershell -ExecutionPolicy Bypass -File test\dist\src\build_fanban_m5.ps1
```

Expected: FAIL initially because the build script and spec do not exist.

**Step 3: Write minimal implementation**

- Add a build script that:
  - prepares `test/dist/assets`
  - copies repo assets
  - copies `monochrome.ctb` from the current machine if not already present
  - runs `PyInstaller --noconfirm`
- Add a `.spec` file that builds into `test/dist/fanban_m5/`.

**Step 4: Run test to verify it passes**

- Re-run the build script.
- Confirm `test/dist/fanban_m5/fanban_m5.exe` exists.

**Step 5: Commit**

```bash
git add test/dist/src/build_fanban_m5.ps1 test/dist/src/fanban_m5.spec test/dist/assets
git commit -m "build: add module5 GUI packaging scaffold"
```

### Task 7: Final verification

**Files:**
- Modify only if verification reveals an issue

**Step 1: Write the failing test**

- Use the final verification set as the acceptance gate.

**Step 2: Run test to verify current state**

Run:

```bash
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_autocad_path_resolver.py backend/tests/unit/test_plot_resource_manager.py backend/tests/unit/test_accoreconsole_runner.py backend/tests/unit/test_cad_dxf_executor.py backend/tests/unit/test_fanban_m5_launcher.py -v
backend\.venv\Scripts\python.exe tools\run_dwg_split_only.py "test\dwg\2016仿真图.dwg" --project-no 2016
powershell -ExecutionPolicy Bypass -File test\dist\src\build_fanban_m5.ps1
```

Expected: all green, `2016` regression succeeds, packaged directory is produced.

**Step 3: Write minimal implementation**

- Fix only verification failures.

**Step 4: Run test to verify it passes**

- Re-run the same verification commands.

**Step 5: Commit**

```bash
git add <verification-fix-files>
git commit -m "chore: finalize module5 pdf2 gui distribution"
```
