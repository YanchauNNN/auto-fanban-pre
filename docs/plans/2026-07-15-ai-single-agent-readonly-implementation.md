# AI Single-Agent And Read-Only Host Access Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a two-mode single-agent chat UI with controlled read-only host filesystem tools available from both modes.

**Architecture:** Keep one `AiChatService` and represent the two user choices as prompt profiles. Add a small allowlisted filesystem tool registry and a bounded OpenAI-compatible tool-call loop in the backend. Remove placeholder capabilities from the UI and make the drawer default to the full viewport height.

**Tech Stack:** FastAPI, Pydantic, Python standard library, SQLite metadata, React, TanStack Query, CSS Modules, Vitest.

---

### Task 1: Runtime Configuration

**Files:**
- Modify: `documents/AI/参数规范_AI.yaml`
- Modify: `backend/src/config/ai/ai_spec.py`
- Modify: `backend/tests/unit/ai/test_ai_spec.py`

**Steps:**

1. Write failing tests for `general_assistant` default mode, `business_agent`, empty skill/MCP registries, and read-only host access parameters.
2. Run the targeted tests and confirm they fail on the old three-agent schema.
3. Implement the new Pydantic configuration and YAML defaults.
4. Run the targeted tests and confirm they pass.

### Task 2: Read-Only Host Tool Registry

**Files:**
- Create: `backend/src/ai/read_only_tools.py`
- Create: `backend/tests/unit/ai/test_read_only_tools.py`

**Steps:**

1. Write failing tests for allowed listing, metadata, search and bounded text reading.
2. Add failing security tests for traversal, absolute paths outside roots, symlink/reparse escape, `.env`, keys, executables and SQLite files.
3. Run the tests and confirm the expected failures.
4. Implement canonical path validation, denial rules and bounded tool results.
5. Run the tool tests and confirm they pass.

### Task 3: OpenAI-Compatible Tool Loop

**Files:**
- Modify: `backend/src/ai/chat_client.py`
- Modify: `backend/src/ai/chat_service.py`
- Modify: `API/app/routers/ai.py`
- Modify: `backend/tests/unit/ai/test_ai_chat.py`

**Steps:**

1. Write failing tests for outbound `tools`, parsed tool calls, execution results and a final assistant answer.
2. Write a failing test proving both modes receive the same read-only tool registry.
3. Run the targeted tests and confirm they fail on the current content-only client.
4. Implement tool-call parsing and a bounded service loop.
5. Include tool-call summaries in assistant metadata without persisting file contents.
6. Run the targeted AI chat tests and confirm they pass.

### Task 4: Two-Mode Full-Height Drawer

**Files:**
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.tsx`
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.module.css`
- Modify: `frontend/src/app/App.test.tsx`

**Steps:**

1. Write failing tests that expect exactly `通用对话` and `业务 Agent` and reject skill/MCP chips.
2. Add a failing test for the new drawer size version and viewport-height default.
3. Run the targeted Vitest test and confirm it fails.
4. Remove skill/MCP selection state and send only the selected mode identifier.
5. Make desktop default height equal to the viewport and preserve later resizing.
6. Run the targeted Vitest test and confirm it passes.

### Task 5: Regression And Visual Verification

**Files:**
- Verify only unless failures require focused fixes.

**Steps:**

1. Run `python -m pytest backend/tests/unit/ai -q` with the worktree backend environment.
2. Run `npm test -- --run` from `frontend`.
3. Run `npm run build` from `frontend`.
4. Start the isolated worktree frontend/backend servers.
5. Verify desktop and mobile screenshots: full-height drawer, transcript-dominant layout, two modes only, no skill/MCP placeholders.
6. Verify one general conversation and one allowlisted read-only file query through a fake or development model gateway.
7. Run `git diff --check` and report unrelated pre-existing worktree changes separately.

