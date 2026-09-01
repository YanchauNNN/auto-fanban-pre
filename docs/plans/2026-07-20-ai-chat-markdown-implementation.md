# AI Chat Markdown/GFM Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render assistant replies as safe Markdown/GFM with APDL code blocks and reliable copy behavior while preserving user messages as plain text.

**Architecture:** Add a dedicated assistant-message renderer around `react-markdown`, strict sanitization, custom links, and a custom fenced-code component. Keep user rendering in `AiChatDrawer`, add a YAML-backed response-format prompt, and verify the final behavior through component, integration, backend, build, and browser smoke tests.

**Tech Stack:** React 18, TypeScript, Vite, Vitest, Testing Library, react-markdown, remark-gfm, remark-breaks, rehype-sanitize, FastAPI/Python YAML configuration.

---

### Task 1: Install Offline-Bundled Markdown Dependencies

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

**Step 1: Install pinned dependencies**

Run:

```powershell
cd frontend
npm install react-markdown@10.1.0 remark-gfm@4.0.1 remark-breaks@4.0.0 rehype-sanitize@6.0.0
```

Expected: dependencies and lockfile are updated without CDN references.

**Step 2: Inspect dependency placement**

Run:

```powershell
npm ls react-markdown remark-gfm remark-breaks rehype-sanitize
```

Expected: all four packages resolve from local `node_modules`.

### Task 2: Build the Renderer Test-First

**Files:**
- Create: `frontend/src/features/ai-chat/AiMessageContent.test.tsx`
- Create: `frontend/src/features/ai-chat/AiMessageContent.tsx`
- Create: `frontend/src/features/ai-chat/AiMessageContent.module.css`

**Step 1: Write failing format and security tests**

Cover:

- GFM tables, lists, task lists, strikethrough, inline code, and ordinary line breaks.
- raw HTML not rendered.
- images and dangerous links not rendered as active resources.
- only explicit HTTP/HTTPS links remain clickable.

**Step 2: Run the test to verify RED**

Run:

```powershell
npm test -- --run src/features/ai-chat/AiMessageContent.test.tsx
```

Expected: FAIL because `AiMessageContent` does not exist.

**Step 3: Implement minimal safe renderer**

Use:

- `skipHtml`
- strict `allowedElements`
- `rehype-sanitize` with an explicit schema
- URL transform that permits only `http:` and `https:`
- custom anchor component with `target="_blank"` and `rel="noopener noreferrer"`

**Step 4: Run the test to verify GREEN**

Run the same targeted test. Expected: PASS.

### Task 3: Add APDL Blocks and Copy Fallback Test-First

**Files:**
- Modify: `frontend/src/features/ai-chat/AiMessageContent.test.tsx`
- Modify: `frontend/src/features/ai-chat/AiMessageContent.tsx`
- Modify: `frontend/src/features/ai-chat/AiMessageContent.module.css`

**Step 1: Write failing APDL and copy tests**

Cover:

- `apdl`, `ansys`, `ansys-apdl`, and `mapdl` labels render as `APDL`.
- code indentation and line breaks are preserved.
- Clipboard API success updates feedback and copies raw code.
- Clipboard API rejection falls back to `execCommand("copy")`.
- complete failure selects code and shows `请按 Ctrl+C`.

**Step 2: Run targeted test to verify RED**

Expected: FAIL because custom code toolbar and copy behavior do not exist.

**Step 3: Implement minimal code block component**

Use semantic `<pre><code>`, an icon-only copy button with accessible name, local
monospace font, stable toolbar dimensions, horizontal scrolling, and status text.

**Step 4: Run targeted test to verify GREEN**

Expected: PASS.

### Task 4: Integrate Assistant Markdown Without Changing User Rendering

**Files:**
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.tsx`
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.module.css`
- Modify: `frontend/src/app/App.test.tsx`

**Step 1: Write failing integration test**

Return one assistant response containing Markdown and one user message containing
literal Markdown. Assert that assistant formatting becomes semantic elements while
the user text remains literal.

**Step 2: Run focused App test to verify RED**

Run:

```powershell
npm test -- --run src/app/App.test.tsx
```

Expected: FAIL because assistant messages are still plain `<p>` elements.

**Step 3: Integrate renderer**

Render `AiMessageContent` only for `message.role === "assistant"`. Keep the existing
plain `<p>{message.content}</p>` branch for user messages and transient status rows.

**Step 4: Run focused tests to verify GREEN**

Run the component and App tests. Expected: PASS.

### Task 5: Add YAML-Backed Response Formatting

**Files:**
- Modify: `documents/AI/参数规范_AI.yaml`
- Modify: `backend/src/config/ai/ai_spec.py`
- Modify: `backend/src/ai/chat_service.py`
- Modify: `backend/tests/unit/ai/test_ai_spec.py`
- Modify: `backend/tests/unit/ai/test_ai_chat.py`

**Step 1: Write failing backend tests**

Assert that:

- YAML loads the response-format prompt.
- every agent system prompt includes the GFM/APDL instructions.

**Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/ai/test_ai_spec.py backend/tests/unit/ai/test_ai_chat.py -q
```

Expected: FAIL because the response-format configuration is missing.

**Step 3: Implement minimal configuration**

Add a typed chat response-format field and append it in `ChatService._system_prompt`.
Keep the default fallback safe when older terminal YAML lacks the field.

**Step 4: Run tests to verify GREEN**

Expected: PASS.

### Task 6: Verify and Smoke-Test the Complete Flow

**Files:**
- Modify only if a failing verification exposes a covered defect.

**Step 1: Run targeted tests**

```powershell
python -m pytest backend/tests/unit/ai/test_ai_spec.py backend/tests/unit/ai/test_ai_chat.py -q
cd frontend
npm test -- --run src/features/ai-chat/AiMessageContent.test.tsx src/app/App.test.tsx
```

**Step 2: Run full frontend verification**

```powershell
npm test -- --run
npm run build
```

Expected: all tests pass and Vite produces `frontend/dist`.

**Step 3: Inspect the production bundle**

Confirm:

- Markdown packages are bundled locally.
- production files contain no CDN imports.
- private Skill ZIPs and research JSON files remain untracked.

**Step 4: Start isolated development services**

Use ports not occupied by main or other worktrees.

**Step 5: Run browser smoke test**

Verify:

- assistant Markdown headings, lists, table, soft line breaks, inline code, and APDL block.
- APDL code copy works.
- malicious HTML/image/link payloads do not render or issue requests.
- user Markdown remains literal text.
- no console errors and drawer layout remains usable at desktop and mobile widths.

**Step 6: Review Git diff**

Run:

```powershell
git diff --check
git status --short
```

Expected: only intended source, test, YAML, lockfile, and plan changes remain.
