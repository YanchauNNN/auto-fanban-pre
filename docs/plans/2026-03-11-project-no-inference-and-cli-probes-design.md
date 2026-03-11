# Project Number Inference And Split-Only Probe Design

**Date:** 2026-03-11

## Goal

Make project number inference reusable outside the M5 GUI and remove stale filename assumptions from `tools/run_dwg_split_only.py` after the output naming rule changed to `外部编码+版次+状态 (内部编码)`.

## Scope

1. Add a backend-shared project number inference helper based on DWG filename stem.
2. Update the split-only CLI to:
   - infer `project_no` when the user does not explicitly provide one
   - stop hardcoding legacy probe filenames
3. Update the M5 GUI to auto-fill the project number from the selected DWG filename while still allowing manual override.
4. Rebuild `test\\dist\\fanban_m5` after verification.

## Rules

- Inference rule: if the DWG filename stem starts with 4 digits, use those 4 digits as `project_no`.
- Explicit user input always wins.
- GUI default `2016` counts as auto-managed and should be overwritten by inferred value.
- If the user manually edits the project number field, later DWG selections must not overwrite it.
- The CLI summary probes must not depend on a specific external-code prefix; they should resolve PDFs dynamically from actual output names.

## Architecture

### Shared backend helper

Create a small utility under `backend/src/pipeline/` so the logic is reusable by:
- the current desktop GUI
- CLI tools
- future web backend task creation

### CLI probe update

`tools/run_dwg_split_only.py` currently probes two PDFs by hardcoded legacy names. Replace this with dynamic matching based on the internal code inside the final filename parentheses, so the summary remains valid after future naming changes.

### GUI behavior

Keep the auto-fill policy in the GUI, but call the shared backend inference helper. The GUI remains a consumer of the shared rule, not the owner of it.

## Risks

- If the GUI auto-fill state is implemented sloppily, it will overwrite manual edits. Guard this with a small state flag and unit tests.
- If CLI inference treats the default `2016` as an explicit value, inference will never apply. The CLI argument default must therefore become blank/None and the fallback to `2016` should happen after inference.

## Verification

- Unit tests for the shared inference helper.
- Unit tests for launcher job construction fallback to inferred project number.
- Unit tests for GUI auto-fill policy.
- Unit tests for dynamic split-only probe selection.
- Rebuild `test\\dist\\fanban_m5` and run focused regression checks.
