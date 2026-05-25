## Learned User Preferences

- The user prefers Chinese communication for project handoffs, with direct statements of what was done, what was not done, verification results, and remaining risk.
- The user expects repository code and existing project documents, especially `documents_bin`, to be read together before maintenance work.
- The user expects frontend work to be approached like a strong frontend engineer: learn the existing project patterns first, use established accessibility and interaction best practices, avoid duplicate controls, and verify behavior from the user's point of view.
- The user expects high-impact ambiguity to be surfaced before finalizing planning documents or implementation direction.
- The user prefers investigation-only requests to stop at findings and causes unless they explicitly ask for code changes.
- The user expects scan failures to be investigated as real failures, not treated as empty or successful scan results.
- The user wants mechanism parameters and configurable variables recorded in the YAML source-of-truth files instead of living only in code or architecture notes.
- The user prefers concrete handoff summaries that distinguish completed work, remaining gaps, and the next recommended action.
- The user expects deployment and environment tasks to be executed directly against the local/test context when feasible, rather than answered only as instructions.
- Keep the main workspace and feature worktrees separated; prefer a fresh worktree from latest `main` plus selective porting when an older experiment branch diverges heavily.
- Do not add duplicate top-level module entrances when the page already has module tabs; reuse the existing business, account, and workload module tabs.
- Keep the platform title/header visible at the top across modules, and avoid moving it below module tabs.
- For frontend changes, verify with relevant Vitest tests, full `npm test`, and `npm run build` before calling the work complete.
- PDF preview interaction should keep Escape-to-close behavior, use Ctrl+wheel for zooming, and expose only one horizontal drag control fixed in the preview window's top control area.
- For font replacement, trust the backend preflight result and show only the actual candidate fonts returned for the current batch; prefer multi-kind `font_replacement_fonts` over legacy single-font payloads.

## Learned Workspace Facts

- The primary workspace is `E:\project\auto-fanban-pre`.
- The project is a Windows-oriented DWG batch-processing system with a FastAPI API layer, Python backend pipeline, React/Vite frontend, ODA/AutoCAD/AcCoreConsole/.NET Bridge CAD execution, and Office COM document export.
- The backend lives under `backend`, the frontend lives under `frontend`, and the frontend uses Vite/Vitest.
- The frontend development server is commonly started from `frontend` with `npm run dev -- --host 127.0.0.1 --port 5173`.
- `documents/参数规范.yaml` is the business-parameter source of truth, and `documents/参数规范_运行期.yaml` is the runtime-parameter source of truth.
- `documents_bin` contains project/business data files that should be interpreted together with the related backend logic.
- The translation/upgrade feature is referred to as `翻版`; it converts legacy project DWG content such as 2016 project text into 2026 project text and must handle block text and nested block text.
- 翻版 matching must support whitespace-normalized project-name matching, because DWG text can contain inconsistent spaces such as `浙江金七门核电厂 1、2 号 机 组` versus `浙江金七门核电厂1、2号机组`.
- CAD audit scanning uses the .NET bridge for DWG text extraction; .NET scanner errors should propagate to Python as failures instead of returning a false zero-error result.
- CAD environment checks should include an actual AcCoreConsole session probe when available, not only file existence checks, because PDF/CAD output differences can depend on profile variables, support paths, fonts, plotter assets, and text styles.
- CAD environment synchronization should avoid mutating the global AutoCAD profile by default and prefer slot-private support directories for deploy/runtime assets.
- The known deployment-machine install root is `D:\FanBanServer`; deployment-related scripts should distinguish packaged deployment paths from the local development workspace.
- New upload deliverable tasks are intended to be unified under the `TaskGroup` concept; workflow, workload, archive state, and owner metadata belong at the task-package level.
- Account management is based on `documents_bin/姓名角色表.csv`, with the formal roles `设计人员`, `室主任`, `所领导`, and `管理员`.
- Recent-task visibility and workflow-card visibility are separate business concepts: recent tasks follow creator and office scope, while workflow cards follow process involvement except that administrators can see all workflows.
- Workload workflow submission uses the logged-in submitter as the process initiator without modifying the IED Excel or rewriting the original `ied_prepared_by` value.
- The workload approval chain has three displayed approval nodes: `一审`, `二审`, and `三审`; `校核人` and `工种负责人` are merged as `一审`.
- Automatic archive happens after `三审` approval, and archive success is the trigger for final workload settlement.
- IED plan template import should read an already-filled IED Excel file only to populate the current web IED-plan fields; drawing information must still come from the program's DWG reading flow.
- For IED plan template import, when multiple rows disagree for the same web field, use the first valid data row; imported values overwrite the current IED fields.
- The backend already has first-version modules for accounts, auth, task groups, workflow, workload, and archive under `backend/src`, plus corresponding API routers under `API/app/routers`.
- The frontend account and workload modules were last observed as placeholders in `frontend/src/app/App.tsx`, with no dedicated `account`, `auth`, `workflow`, or `workload` feature modules wired yet.
- The frontend app-shell work should continue from the sync worktree under `.worktrees`, not by directly merging the older app-shell branch into `main`.
