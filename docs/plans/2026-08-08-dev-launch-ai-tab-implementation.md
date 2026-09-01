# Development Launch And AI Tab Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the calculation-book AI development commands reliable in PowerShell and enlarge the collapsed AI tab with upright stacked letters.

**Architecture:** Keep API, Worker, and Vite as three independently observable development processes. Preserve the AI drawer component structure and implement the visual change entirely in its CSS module, guarded by focused contract tests.

**Tech Stack:** PowerShell, FastAPI/Uvicorn, Python worker module, React, CSS Modules, Vitest, Pytest.

---

### Task 1: Lock the AI collapsed-tab design with a failing test

**Files:**
- Modify: `frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts`
- Test: `frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts`

**Step 1: Write the failing test**

Add a test that extracts `.collapsedTab` and `.collapsedTab span:first-child` from the CSS module and requires:

```ts
expect(collapsedTabRule).toContain("width: 3.5rem;");
expect(collapsedTabRule).toContain("min-height: 8rem;");
expect(collapsedTabRule).toContain("font-size: 1.25rem;");
expect(labelRule).toContain("text-orientation: upright;");
```

**Step 2: Run the test to verify RED**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/features/ai-chat/AiChatDrawerLayout.test.ts
```

Expected: FAIL because the current rule still contains `3rem`, `6.2rem`, `1.02rem`, and no `text-orientation`.

### Task 2: Implement the AI collapsed-tab CSS

**Files:**
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.module.css`
- Test: `frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts`

**Step 1: Write the minimal implementation**

Change only the collapsed-tab sizing and label orientation:

```css
width: 3.5rem;
min-height: 8rem;
font-size: 1.25rem;
text-orientation: upright;
```

**Step 2: Run the focused tests to verify GREEN**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/features/ai-chat/AiChatDrawerLayout.test.ts src/features/ai-chat/AiChatDrawer.test.tsx src/app/App.test.tsx
```

Expected: PASS.

### Task 3: Lock the calculation-book AI launch commands with a failing test

**Files:**
- Create: `backend/tests/unit/test_quick_start_commands.py`
- Modify: `documents/快速启动.txt`

**Step 1: Write the failing test**

Read the UTF-8 text, isolate the `codex-calculation-ai-unified` section, and assert that it contains:

- API `python -X utf8 -m uvicorn ... --port 8010`
- Worker `python -X utf8 -m API.app.worker`
- `VITE_API_PROXY_TARGET=http://127.0.0.1:8010`
- `npm.cmd run dev ... --port 5175 --strictPort`
- no plain `npm run` in this section

**Step 2: Run the test to verify RED**

Run:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_quick_start_commands.py -q
```

Expected: FAIL because the current section is unlabeled, the API lacks `-X utf8`, the proxy target is implicit, and it uses `npm run`.

**Step 3: Write the minimal command documentation**

Replace only the existing third section. Keep the first two sections unchanged and add explicit headings, three clean commands, and the frontend/health URLs.

**Step 4: Run the test to verify GREEN**

Run the same Pytest command. Expected: PASS.

**Step 5: Synchronize the user-facing main-workspace file**

Apply the identical third-section text to `E:\project\auto-fanban-pre\documents\快速启动.txt`, preserving all unrelated dirty files and the existing first two sections.

### Task 4: Verify and commit

**Files:**
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.module.css`
- Modify: `frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts`
- Modify: `documents/快速启动.txt`
- Create: `backend/tests/unit/test_quick_start_commands.py`

**Step 1: Verify process entry points without starting long-lived services**

```powershell
$env:FANBAN_AI_GATEWAY_PROFILE='development_minimax'
uv run --project backend python -X utf8 -c "from API.app.main import app; print(app.title)"
uv run --project backend python -X utf8 -c "from API.app.worker import DeliverableWorkerRuntime; print(DeliverableWorkerRuntime.__name__)"
```

Expected: `Auto Fanban API` and `DeliverableWorkerRuntime`.

**Step 2: Run frontend and command tests**

```powershell
Set-Location frontend
npm.cmd test
npm.cmd run build
Set-Location ..
backend\.venv\Scripts\python.exe -m pytest backend/tests/unit/test_quick_start_commands.py -q
```

Expected: all pass.

**Step 3: Review boundaries**

Confirm that the calculation worktree contains only the planned files and that the main workspace changes only extend its already-dirty `documents/快速启动.txt` without touching unrelated files.

**Step 4: Commit the calculation-worktree files**

```powershell
git add frontend/src/features/ai-chat/AiChatDrawer.module.css frontend/src/features/ai-chat/AiChatDrawerLayout.test.ts documents/快速启动.txt backend/tests/unit/test_quick_start_commands.py
git commit -m "fix: clarify calculation AI startup and enlarge assistant tab"
```
