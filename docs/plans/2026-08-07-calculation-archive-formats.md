# Calculation Archive Formats Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make calculation-book uploads and the packaged `D:\FanBanServer` runtime safely support ordinary single-volume, unencrypted ZIP, RAR4/RAR5, and 7z archives.

**Architecture:** Keep the existing Python `zipfile` extraction path for ZIP. Detect format from extension plus magic bytes, then use a deployment-private full 7-Zip runtime for RAR/7z, with one shared pre-extraction security policy and post-extraction verification. Business, runtime, and mechanism parameters remain YAML-backed and are consumed consistently by frontend, API, Worker, deployment builder, and target probe.

**Tech Stack:** Python 3.13, FastAPI, pytest, React/TypeScript, Vitest, YAML configuration, PowerShell deployment probes, official portable 7-Zip runtime.

---

### Task 1: Add archive format detection and runtime configuration

**Files:**
- Modify: `backend/tests/unit/calculation_book/test_archive.py`
- Modify: `backend/tests/unit/calculation_book/test_config.py`
- Modify: `backend/src/calculation_book/archive.py`
- Modify: `backend/src/config/runtime_config.py`
- Modify: `documents/参数规范_运行期.yaml`

**Step 1: Write the failing tests**

Add tests for ZIP, RAR4, RAR5, and 7z magic detection, extension/signature mismatch, and terminal-layout path resolution:

```python
@pytest.mark.parametrize(
    ("suffix", "header", "expected"),
    [
        (".zip", b"PK\x03\x04", ArchiveFormat.ZIP),
        (".rar", b"Rar!\x1a\x07\x00", ArchiveFormat.RAR),
        (".rar", b"Rar!\x1a\x07\x01\x00", ArchiveFormat.RAR),
        (".7z", b"7z\xbc\xaf\x27\x1c", ArchiveFormat.SEVEN_ZIP),
    ],
)
def test_detects_archive_format_from_suffix_and_signature(...): ...
```

Assert the runtime config resolves `bin/7-Zip/7z.exe` under a simulated
`D:\FanBanServer` root and exposes list/extract timeouts.

**Step 2: Run tests to verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_archive.py backend/tests/unit/calculation_book/test_config.py -q
```

Expected: FAIL because `ArchiveFormat`, signature validation, and extractor config do not exist.

**Step 3: Implement the minimal configuration and detector**

Add immutable models equivalent to:

```python
class ArchiveFormat(str, Enum):
    ZIP = "zip"
    RAR = "rar"
    SEVEN_ZIP = "7z"

@dataclass(frozen=True)
class ArchiveExtractorConfig:
    executable: Path
    list_timeout_seconds: int = 120
    extract_timeout_seconds: int = 300
```

Read the first eight bytes, require a supported suffix, and reject signature mismatch. Add the extractor path and timeouts under `calculation_book.archive_extractor` in the runtime YAML and loader.

**Step 4: Run tests to verify GREEN**

Run the Task 1 command again. Expected: PASS.

**Step 5: Commit**

```powershell
git add -- backend/tests/unit/calculation_book/test_archive.py backend/tests/unit/calculation_book/test_config.py backend/src/calculation_book/archive.py backend/src/config/runtime_config.py documents/参数规范_运行期.yaml
git commit -m "feat: configure calculation archive formats"
```

### Task 2: Implement safe RAR/7z listing and extraction

**Files:**
- Modify: `backend/tests/unit/calculation_book/test_archive.py`
- Modify: `backend/src/calculation_book/archive.py`

**Step 1: Write failing list-parser and policy tests**

Use a fake subprocess runner and representative `7z l -slt` output. Cover:

- Unicode and space-containing paths.
- directories versus regular files.
- encrypted and volume metadata.
- absolute, drive, UNC, `..`, ADS, control-character, reserved-device, trailing-dot/space paths.
- symbolic/hard links and reparse attributes.
- case-insensitive duplicate output targets.
- file/directory count, single size, total size, and compression-ratio limits.
- missing executable, timeout, non-zero exit, corrupted archive.

**Step 2: Run tests to verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/calculation_book/test_archive.py -q
```

Expected: new RAR/7z tests fail while existing ZIP tests remain green.

**Step 3: Implement the technical-list parser and unified member policy**

Create small internal helpers rather than a second entrypoint:

```python
def _list_external_archive(..., runner=subprocess.run) -> tuple[ArchiveMember, ...]: ...
def _validate_archive_members(members, limits): ...
def _extract_external_archive(..., runner=subprocess.run): ...
def _post_validate_extraction(...): ...
```

Invoke the configured absolute executable with argument arrays, `shell=False`,
`stdin=DEVNULL`, UTF-8 console switches, and YAML timeouts. Extract into a new isolated directory, then compare the actual regular-file set and sizes with the validated list.

**Step 4: Preserve and strengthen ZIP behavior**

Reuse the same normalized-target and duplicate checks for ZIP. Do not route ZIP through 7-Zip.

**Step 5: Run tests to verify GREEN**

Run the Task 2 command. Expected: all archive tests pass.

**Step 6: Commit**

```powershell
git add -- backend/tests/unit/calculation_book/test_archive.py backend/src/calculation_book/archive.py
git commit -m "feat: safely extract rar and 7z calculation archives"
```

### Task 3: Wire one archive configuration through API and Worker

**Files:**
- Modify: `backend/tests/unit/test_module7_api.py`
- Modify: `backend/tests/unit/calculation_book/test_executor.py`
- Modify: `backend/src/calculation_book/preflight.py`
- Modify: `backend/src/calculation_book/processor.py`
- Modify: `backend/src/calculation_book/executor.py`
- Modify: `API/app/runtime.py`
- Modify: `API/app/routers/jobs.py`

**Step 1: Write failing API and Worker tests**

Assert:

- `.7z` upload is accepted and cached with its suffix.
- `.7z` uses `application/x-7z-compressed` where content type is emitted.
- cache cleanup includes `.7z`.
- API preflight and Worker both pass the same resolved `ArchiveExtractorConfig`.
- missing RAR/7z runtime returns a stable Chinese error, while ZIP still works.

**Step 2: Run tests to verify RED**

Run the named API and executor tests with a short `--basetemp`. Expected: FAIL on `.7z` and missing config propagation.

**Step 3: Implement minimal wiring**

Replace `.zip/.rar` literals with the schema-derived supported set, add 7z MIME mapping, and pass the loaded extractor config into preflight and Worker calls. Change format-neutral messages from “ZIP” to “压缩包”.

**Step 4: Run tests to verify GREEN**

Run the Task 3 tests. Expected: PASS.

**Step 5: Commit**

Stage only the listed API/calculation files and commit:

```powershell
git commit -m "feat: accept 7z calculation tasks end to end"
```

### Task 4: Update business YAML and calculation-book frontend

**Files:**
- Modify: `documents/参数规范.yaml`
- Modify: `frontend/src/features/schema/schema.ts`
- Modify: `frontend/src/features/schema/schema.test.ts`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.tsx`
- Modify: `frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx`

**Step 1: Write failing frontend tests**

Assert the normalized schema and input `accept` include `.zip,.rar,.7z`, and the user-facing upload copy says `ZIP / RAR / 7z` without adding a duplicate control.

**Step 2: Run test to verify RED**

```powershell
frontend\node_modules\.bin\vitest.cmd run frontend/src/features/schema/schema.test.ts frontend/src/features/calculation-book/CalculationBookWorkspace.test.tsx
```

Expected: FAIL because `.7z` is absent.

**Step 3: Implement minimal YAML/schema/UI changes**

Add `.7z` to the business YAML, fallback schema, file input, examples, and help copy. Preserve the internal-code placeholder `例如：20161NH-JGS01` and all compact review behavior.

**Step 4: Run tests and build**

Run the Task 4 tests, then `npm.cmd run build` from `frontend`. Expected: PASS.

**Step 5: Commit**

Stage only the five listed files and commit:

```powershell
git commit -m "feat: expose 7z calculation uploads"
```

### Task 5: Add portable 7-Zip runtime to deployment construction

**Files:**
- Modify: `documents/参数规范-3.yaml`
- Modify: `backend/src/config/mechanism_spec.py`
- Modify: `backend/tests/unit/test_terminal_deploy_builder.py`
- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `tools/build_terminal_deploy.py`
- Add: `tools/prepare_archive_runtime.py`
- Add at build time: `bin/7-Zip/7z.exe`
- Add at build time: `bin/7-Zip/7z.dll`
- Add at build time: `bin/7-Zip/License.txt`
- Add at build time: `bin/7-Zip/PROVENANCE.txt`

**Step 1: Record the supply-chain contract in mechanism YAML**

Add version, official source URL, expected SHA256, required runtime filenames, destination, and license/source URLs. Treat these as configuration data, not Python constants.

**Step 2: Write failing builder tests**

Assert:

- a complete verified runtime is copied to `bin/7-Zip`.
- missing, extra, or hash-mismatched required files fail the build.
- full and delta manifests include each runtime file and component metadata.
- no installer is copied into the target package.

**Step 3: Run tests to verify RED**

Run `test_terminal_deploy_builder.py` with a short repository-local basetemp. Expected: new assertions fail.

**Step 4: Implement the runtime preparation and copy plan**

The preparation tool may download only the small official artifact during an explicit build step, verifies the YAML SHA256 before extraction, materializes only the four approved files, writes provenance, and never installs software. Normal deployment construction consumes the verified local cache and fails closed if it is absent.

**Step 5: Run tests to verify GREEN**

Run the Task 5 tests. Expected: PASS.

**Step 6: Commit source/config/tests**

Do not commit generated binaries unless repository policy explicitly tracks deployment runtime assets. Commit the YAML, preparation tool, builder and tests:

```powershell
git commit -m "feat: package a verified private 7zip runtime"
```

### Task 6: Add target probe, startup validation, and deployment documentation

**Files:**
- Modify: `tools/probe_target_env.ps1`
- Modify: `backend/tests/unit/test_probe_target_env.py`
- Modify: `backend/tests/unit/test_terminal_deploy_builder.py`
- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `documents/终端实装安装计划.md`

**Step 1: Write failing probe/script tests**

Assert the generated probe and startup scripts use the fixed runtime path, do not search PATH, report the version, detect ZIP/RAR/7z handlers, and put failures in `blocking_issues`.

**Step 2: Run tests to verify RED**

Run the probe and deployment-builder tests. Expected: FAIL because archive facts are absent.

**Step 3: Implement probe and generated-script checks**

Add `Get-ArchiveToolFacts`, execute the packaged tiny probe archives, and write the verified absolute path to `runtime.env.ps1`. Add license and diagnostic instructions to generated deployment README and installation plan.

**Step 4: Run tests to verify GREEN**

Run the Task 6 tests and PowerShell parser checks. Expected: PASS.

**Step 5: Commit**

```powershell
git commit -m "feat: probe packaged archive capabilities"
```

### Task 7: Regression, real archives, and packaged-layout smoke

**Files:**
- Modify as needed: `tools/smoke_calculation_book_ai_suggestion.py`
- Add generated test fixtures only if licensing permits: `backend/tests/fixtures/calculation_book/archives/*`
- Generated and ignored: `build/*`

**Step 1: Run focused regressions**

Run archive/config/API/deployment tests, the calculation-book frontend suite, full frontend `npm test`, and frontend build.

**Step 2: Create equivalent minimal ZIP/RAR5/7z fixtures**

Use the verified private runtime to create the three formats from the same minimal calculation payload. Assert preflight wall/image/slab counts and extracted relative paths are identical.

**Step 3: Run the user-provided real RAR through formal API/Worker**

Source:

```text
E:\project\auto-fanban-pre\test\文档\6层11.45~15\6层11.45~15.95m 结果云图 - 副本.rar
```

Record SHA256, task ID, output directory, generated DOCX, archive format, and exact 7-Zip path/version from the task log.

**Step 4: Build and inspect the isolated deployment output**

Generate full/delta artifacts only from this clean worktree. Verify manifest hashes and package contents. Do not overwrite or merge another agent's build output.

**Step 5: Run packaged-layout smoke**

Stage the package in an isolated `D:\FanBanServer`-equivalent directory or the approved test machine, run the target probe, then submit equivalent ZIP/RAR5/7z tasks through API/Worker.

**Step 6: Final review and commit**

Run `git diff --check`, inspect every changed file, request code review, and commit any final smoke/test adjustments. Do not merge the branch.
