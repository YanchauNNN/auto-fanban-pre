# AI Agent Capability Probe Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the existing PowerShell AI connectivity diagnostic to schema 0.3 so one terminal run reports core connectivity, Agent protocol readiness, multimodal readiness, local SDK availability, and configured MCP readiness.

**Architecture:** Keep one dependency-free PowerShell 5.1 entry point and the existing OpenAI-compatible Chat Completions transport. Add a uniform capability-result model so optional unsupported features remain evidence rather than fatal errors, then exercise synthetic tools, routing, image/file content parts, low-load concurrency, runtime inventory, and explicitly configured MCP transports.

**Tech Stack:** Windows PowerShell 5.1, `curl.exe`, OpenAI-compatible Chat Completions JSON, JSON-RPC 2.0/MCP discovery, Python `pytest` fake HTTP servers, terminal package builder.

---

### Task 1: Lock The Version 0.3 Result Contract

**Files:**
- Modify: `backend/tests/unit/ai/test_ai_connectivity_script.py`
- Modify: `tools/ai/test_ai_model_connectivity.ps1`

**Step 1: Write failing assertions**

Extend the existing successful fake-server test to require schema `0.3`, script version `fanban-ai-connectivity@0.3`, readiness groups, and capability statuses. Add an unsupported fake-server mode proving an HTTP 400 on optional JSON schema or vision is reported as `unsupported` while overall core status stays `passed`.

**Step 2: Run the focused tests and verify RED**

Run: `uv run --project backend python -m pytest backend/tests/unit/ai/test_ai_connectivity_script.py -q`

Expected: FAIL because version 0.2 has no readiness or capability status model.

**Step 3: Add shared capability helpers**

Implement PowerShell helpers that create results with `passed`, `failed`, `unsupported`, `inconclusive`, `not_configured`, `not_installed`, or `skipped`; classify optional HTTP 400/404/405/422 responses without adding fatal errors; and build separate core and optional readiness summaries.

**Step 4: Preserve version 0.2 evidence fields**

Keep script/config hashes, endpoint metadata, auth fingerprint, DNS/TCP, bounded previews, elapsed time, and existing chat/stream fields so old terminal evidence remains comparable.

**Step 5: Run focused tests and verify GREEN**

Run: `uv run --project backend python -m pytest backend/tests/unit/ai/test_ai_connectivity_script.py -q`

Expected: version-contract and optional-feature classification tests pass.

### Task 2: Probe Agent Protocol And Routing

**Files:**
- Modify: `backend/tests/unit/ai/test_ai_connectivity_script.py`
- Modify: `tools/ai/test_ai_model_connectivity.ps1`
- Modify: `documents/AI/ai_model_gateway.yaml`

**Step 1: Extend the fake gateway and write failing tests**

Make the test gateway respond to system-instruction, two-turn memory, `json_object`, `json_schema`, named tool choice, automatic tool selection, multiple tool calls, tool-result continuation, and streamed tool-call deltas. Assert parsed tool names/arguments and the final handoff marker.

**Step 2: Run the focused tests and verify RED**

Run: `uv run --project backend python -m pytest backend/tests/unit/ai/test_ai_connectivity_script.py -q`

Expected: FAIL because these checks do not exist.

**Step 3: Implement non-streaming Agent checks**

Add synthetic read-only tools, deterministic named-tool selection, tool argument JSON parsing, tool-result round-trip, parallel-tool observation, JSON mode/schema checks, and general-versus-explicit-business routing simulation. Record behavior and evidence without executing any real tool.

**Step 4: Implement streamed tool-call reconstruction**

Extend the SSE parser to merge `delta.tool_calls[*].function.name` and split argument fragments by tool-call index/id. Mark malformed fragments `inconclusive` rather than crashing the whole diagnostic.

**Step 5: Add YAML probe defaults**

Add profile-level discovery defaults for Agent checks, image/file checks, and low-load concurrency. Keep terminal advanced capabilities optional until proven by real evidence.

**Step 6: Run focused tests and verify GREEN**

Run: `uv run --project backend python -m pytest backend/tests/unit/ai/test_ai_connectivity_script.py -q`

Expected: Agent protocol and routing tests pass.

### Task 3: Probe Multimodal, Runtime, Concurrency, And MCP

**Files:**
- Modify: `backend/tests/unit/ai/test_ai_connectivity_script.py`
- Modify: `tools/ai/test_ai_model_connectivity.ps1`

**Step 1: Write failing tests for remaining readiness groups**

Add fake image/file content handling, a low-load concurrent response test, runtime inventory assertions, an MCP Streamable HTTP fake server, and no-MCP configuration behavior. Assert no temporary fixture or secret is retained in the report.

**Step 2: Run the focused tests and verify RED**

Run: `uv run --project backend python -m pytest backend/tests/unit/ai/test_ai_connectivity_script.py -q`

Expected: FAIL because multimodal/runtime/MCP checks do not exist.

**Step 3: Implement generated multimodal fixtures**

Generate a temporary PNG containing a high-contrast marker and a tiny UTF-8 text fixture. Send standard content-part payloads, classify explicit protocol rejection as `unsupported`, marker-free success as `inconclusive`, and always remove temporary files.

**Step 4: Implement runtime and low-load concurrency inventory**

Discover packaged/system Python executables, query versions/importability of `openai`, `agents`, and `mcp`, and issue a small configurable number of concurrent harmless chats. Record success counts, response codes, latency, and throttling evidence without stress testing.

**Step 5: Implement MCP discovery**

Accept optional MCP Streamable HTTP URL, SSE URL, or stdio executable/arguments. Probe only configured transports. Perform initialize, initialized notification, ping, `tools/list`, `resources/list`, and `prompts/list`; do not call discovered tools. When transport support cannot be completed without an installed MCP SDK, report `not_installed` or `inconclusive` with the missing prerequisite.

**Step 6: Run focused tests and verify GREEN**

Run: `uv run --project backend python -m pytest backend/tests/unit/ai/test_ai_connectivity_script.py -q`

Expected: all probe tests pass.

### Task 4: Verify Terminal Packaging And Operator Workflow

**Files:**
- Modify if required: `backend/tests/unit/test_terminal_deploy_builder.py`
- Verify: `backend/src/deploy/terminal_package.py`
- Verify: `tools/ai/test_ai_model_connectivity.ps1`

**Step 1: Add packaging assertions if missing**

Assert the terminal package contains the version 0.3 script at `scripts/test_ai_model_connectivity.ps1` and the updated gateway YAML with capability defaults.

**Step 2: Run targeted packaging tests**

Run: `uv run --project backend python -m pytest backend/tests/unit/test_terminal_deploy_builder.py -q`

Expected: PASS and packaged script content/hash match the source.

**Step 3: Run syntax and focused regression checks**

Run:

```powershell
powershell -NoProfile -Command "[void][scriptblock]::Create((Get-Content -Raw 'tools/ai/test_ai_model_connectivity.ps1'))"
uv run --project backend python -m pytest backend/tests/unit/ai/test_ai_connectivity_script.py backend/tests/unit/ai/test_ai_spec.py backend/tests/unit/test_terminal_deploy_builder.py -q
```

Expected: PowerShell parses and all targeted tests pass.

**Step 4: Run a local fake-gateway report and inspect it**

Use the test fixture or an equivalent local server to produce a complete version 0.3 JSON. Validate JSON parsing, secret absence, readiness summaries, bounded previews, and cleanup.

**Step 5: Review and commit implementation**

Run `git diff --check`, inspect the complete diff, then commit only the probe, YAML, tests, and plan changes. Provide the terminal command and request the resulting JSON before designing the production Agent/MCP implementation.
