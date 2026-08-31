# Terminal Qwen3.8 Model Switch Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the terminal intranet Qwen3.6 gateway configuration with Qwen3.8-27B while leaving the development MiniMax profile and deployed profile identifier stable.

**Architecture:** The YAML gateway document remains the source of truth for endpoint and model selection. Existing deployment scripts keep selecting `terminal_cnpe_intranet_qwen_fast`, but that stable profile now resolves to the `qwen_medium` endpoint and `Qwen3.8-27B`; generated operator documentation is updated to match. Both non-streaming structured calls and streaming connectivity probes are verified.

**Tech Stack:** YAML, Python/Pytest, PowerShell connectivity diagnostics, terminal deployment package generator.

---

### Task 1: Lock the new terminal gateway contract with tests

**Files:**
- Modify: `backend/tests/unit/ai/test_ai_spec.py`
- Modify: `backend/tests/unit/test_terminal_deploy_builder.py`

**Step 1: Write the failing assertions**

Change the terminal profile expectations to:

```python
assert gateway.base_url == "http://models.ai.cnpe.cc/qwen_medium/v1"
assert spec.models.chat.model == "Qwen3.8-27B"
assert spec.models.structured.model == "Qwen3.8-27B"
```

Add deployment-document assertions that the generated README contains the new endpoint and model and does not contain `qwen_fast/v1/chat/completions` or `Qwen3.6-35A3`.

**Step 2: Run tests to verify they fail**

Run: `uv run --project backend pytest backend/tests/unit/ai/test_ai_spec.py backend/tests/unit/test_terminal_deploy_builder.py -q`

Expected: FAIL because production YAML and generated deployment documentation still contain the old gateway values.

**Step 3: Do not modify unrelated dirty files**

Run: `git diff --name-only`

Expected: the pre-existing calculation-book changes remain present; this task has only added assertions in the two listed test files.

### Task 2: Switch the YAML source of truth

**Files:**
- Modify: `documents/AI/ai_model_gateway.yaml`

**Step 1: Apply the minimal configuration change**

Within the existing `terminal_cnpe_intranet_qwen_fast` mapping set:

```yaml
provider: "cnpe-qwen-medium"
base_url: "http://models.ai.cnpe.cc/qwen_medium/v1"
chat_model: "Qwen3.8-27B"
structured_model: "Qwen3.8-27B"
stream_enabled: true
```

Update the profile description and file header comment, but keep the profile key, no-auth settings, host allowlist, and intranet network policy unchanged.

**Step 2: Run the AI spec tests**

Run: `uv run --project backend pytest backend/tests/unit/ai/test_ai_spec.py -q`

Expected: PASS, including the test that rejects an internet override for the intranet profile.

### Task 3: Synchronize generated deployment documentation

**Files:**
- Modify: `backend/src/deploy/terminal_package.py`
- Modify: `documents/终端实装安装计划.md`
- Modify: `documents/AI/ANSYS_MAPDL_Skill部署说明.md`

**Step 1: Update model-facing documentation strings**

Replace only operator-facing old endpoint/model text with:

```text
http://models.ai.cnpe.cc/qwen_medium/v1/chat/completions
Qwen3.8-27B
```

Keep all occurrences of the stable profile key `terminal_cnpe_intranet_qwen_fast` unchanged.

**Step 2: Run deployment builder tests**

Run: `uv run --project backend pytest backend/tests/unit/test_terminal_deploy_builder.py -q`

Expected: PASS and generated package documentation describes the Qwen3.8 endpoint.

**Step 3: Search for stale production references**

Run: `rg -n "qwen_fast/v1|Qwen3\\.6-35A3" documents backend/src --glob '!build/**'`

Expected: no stale production/configuration references; fixture-only test data may remain where it tests generic model handling.

### Task 4: Verify response-mode compatibility

**Files:**
- Test: `backend/tests/unit/ai/test_ai_connectivity_script.py`
- Test: `backend/tests/unit/ai/test_ai_chat_client.py`

**Step 1: Run local simulated gateway tests**

Run: `uv run --project backend pytest backend/tests/unit/ai/test_ai_connectivity_script.py backend/tests/unit/ai/test_ai_chat_client.py -q`

Expected: PASS for ordinary JSON completions and SSE streaming diagnostics.

**Step 2: Run the focused regression set**

Run: `uv run --project backend pytest backend/tests/unit/ai backend/tests/unit/test_terminal_deploy_builder.py -q`

Expected: PASS.

**Step 3: Attempt the real intranet connectivity probe**

Run: `powershell -ExecutionPolicy Bypass -File backend/src/deploy/test_ai_model_connectivity.ps1 -Profile terminal_cnpe_intranet_qwen_fast`

Expected: if the development host can reach CNPE intranet DNS/network, both `chat` and `stream` checks pass against Qwen3.8. If the script is generated rather than stored at this path, generate a temporary terminal package and run its packaged diagnostic script without modifying tracked build output.

### Task 5: Final safety review

**Files:**
- Review: all files changed by this task

**Step 1: Review scoped diff**

Run: `git diff -- documents/AI/ai_model_gateway.yaml backend/src/deploy/terminal_package.py backend/tests/unit/ai/test_ai_spec.py backend/tests/unit/test_terminal_deploy_builder.py documents/终端实装安装计划.md documents/AI/ANSYS_MAPDL_Skill部署说明.md`

Expected: no calculation-book, workload, frontend, or unrelated deployment behavior changes.

**Step 2: Verify repository state**

Run: `git status --short`

Expected: pre-existing dirty files are preserved and clearly separated from this task's changes.

**Step 3: Commit only after user-directed integration**

Do not stage or commit unrelated dirty files. If a commit is requested, add only the six implementation/test/documentation files listed above.

