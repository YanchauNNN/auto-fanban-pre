# AI Chat Attachments Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add owner-isolated AI chat attachments, image vision input, offline document/CAD parsing, frontend upload UX, and a non-blocking Responses API file capability probe.

**Architecture:** The FanBan backend owns upload storage, parsing, authorization, retention, and model-message assembly. Images are sent as Chat Completions `image_url` data URLs; PDF/TXT/DOCX/XLSX/DXF/DWG are parsed locally and inserted as bounded untrusted evidence. The existing SQLite conversation store and short POST request model remain in place.

**Tech Stack:** FastAPI, SQLite, Pydantic, `pypdf`, `python-docx`, `openpyxl`, `ezdxf`, existing `ODAConverter`, React/Vite, TanStack Query, Vitest, PowerShell diagnostics.

---

### Task 1: Resolve trusted proxy owner identity

**Files:**
- Modify: `backend/src/ai/owner_identity.py`
- Modify: `API/app/routers/ai.py`
- Test: `backend/tests/unit/ai/test_ai_chat.py`

**Step 1: Write failing tests**

Add tests proving that a loopback peer uses the first valid `X-Forwarded-For` address, IPv4/IPv6 ports are normalized, and a non-loopback peer cannot spoof the header.

**Step 2: Run the focused tests**

Run: `python -m pytest -q backend/tests/unit/ai/test_ai_chat.py -k owner_key`

Expected: the trusted-loopback test fails because `_owner_key` currently ignores forwarding headers.

**Step 3: Implement the resolver**

Add a pure `resolve_client_ip(peer_host, forwarded_for, trusted_proxy_hosts)` helper. Update `_owner_key` to trust forwarding headers only for `127.0.0.1` and `::1`.

**Step 4: Verify**

Run the same focused tests and confirm they pass.

**Step 5: Commit**

Commit only owner identity files and tests.

### Task 2: Add YAML attachment configuration

**Files:**
- Modify: `backend/src/config/ai/ai_spec.py`
- Modify: `documents/AI/参数规范_AI.yaml`
- Modify: `API/app/routers/ai.py`
- Test: `backend/tests/unit/ai/test_ai_spec.py`

**Step 1: Write failing configuration tests**

Assert the YAML loads attachment enablement, allowed suffixes, size limits, context limits, retention, and external-profile policy.

**Step 2: Run the tests and observe failure**

Run: `python -m pytest -q backend/tests/unit/ai/test_ai_spec.py -k attachment`

**Step 3: Add Pydantic models and YAML values**

Create `AiChatAttachmentsConfig` with validated defaults and attach it to `AiChatConfig`. Carry it into `AiChatRuntimeConfig` and expose non-sensitive capability fields from `/api/ai/state`.

**Step 4: Verify and commit**

Run the focused spec and state tests, then commit only configuration changes.

### Task 3: Persist and clean owner-isolated attachments

**Files:**
- Create: `backend/src/ai/attachment_store.py`
- Modify: `backend/src/ai/chat_store.py`
- Test: `backend/tests/unit/ai/test_ai_attachments.py`

**Step 1: Write failing store tests**

Cover create/list/get/bind/delete, cross-owner denial, SHA256 metadata, clear conversation cleanup, delete conversation cleanup, and retention cleanup.

**Step 2: Run and verify red**

Run: `python -m pytest -q backend/tests/unit/ai/test_ai_attachments.py -k store`

**Step 3: Implement minimal SQLite and filesystem store**

Create `ai_attachments` with foreign keys and indexes. Use an owner SHA256 directory, UUID attachment IDs, safe suffixes, atomic file writes, and path containment checks.

**Step 4: Integrate lifecycle cleanup**

Return attachment file paths from clear/delete/purge operations and remove directories after successful database transactions. Make cleanup idempotent.

**Step 5: Verify and commit**

Run attachment and existing chat-store tests, then commit.

### Task 4: Parse text, PDF, DOCX, XLSX, and images

**Files:**
- Create: `backend/src/ai/attachment_parser.py`
- Test: `backend/tests/unit/ai/test_ai_attachments.py`

**Step 1: Write fixture-based failing tests**

Generate small TXT, PDF, DOCX, XLSX and PNG fixtures containing fixed markers. Test file signature checks, encoding fallback, page/sheet/table boundaries, truncation and unsupported types.

**Step 2: Run and verify red**

Run: `python -m pytest -q backend/tests/unit/ai/test_ai_attachments.py -k parser`

**Step 3: Implement parsers**

Use `pypdf`, `python-docx`, `openpyxl` read-only mode, standard text decoders, and image header validation. Return a common result with kind, extracted text, model metadata and warnings.

**Step 4: Verify and commit**

Run parser tests and commit the parser plus fixtures generated in tests only.

### Task 5: Reuse the drawing-understanding pipeline for DXF/DWG

**Files:**
- Create: `backend/src/cad/ai/element_package_exporter.py`
- Modify: `tools/ai/export_drawing_understanding.py`
- Modify: `backend/src/ai/attachment_parser.py`
- Test: `backend/tests/unit/ai/test_ai_attachments.py`
- Test: `backend/tests/unit/ai/test_drawing_understanding.py`

**Step 1: Write failing CAD attachment tests**

Create a small DXF with text, layers and geometry. Assert structured output. Mock `ODAConverter.dwg_to_dxf` for DWG and assert the converted DXF enters the same parser.

**Step 2: Run and verify red**

Run: `python -m pytest -q backend/tests/unit/ai/test_ai_attachments.py -k cad`

**Step 3: Extract reusable service**

Move reusable `_process_source`, DXF normalization and element summarization from the tool script into `src.cad.ai.element_package_exporter`. Keep the command-line script as a thin adapter.

**Step 4: Connect attachment parser**

Convert DWG with existing ODA configuration, parse DXF with the shared service, and serialize a bounded structured summary for the model.

**Step 5: Verify and commit**

Run CAD attachment, existing drawing-understanding and ODA-related unit tests, then commit.

### Task 6: Add attachment API and model context assembly

**Files:**
- Modify: `backend/src/ai/chat_service.py`
- Modify: `backend/src/ai/chat_client.py`
- Modify: `API/app/routers/ai.py`
- Modify: `backend/src/ai/chat_store.py`
- Test: `backend/tests/unit/ai/test_ai_attachments.py`
- Test: `backend/tests/unit/ai/test_ai_chat.py`

**Step 1: Write failing service/API tests**

Cover multipart upload, owner isolation, validation errors, attachment-only messages, binding ready attachments, rejecting failed/deleted/cross-owner IDs, image content blocks, parsed-document evidence, history follow-up and cleanup endpoints.

**Step 2: Run and verify red**

Run: `python -m pytest -q backend/tests/unit/ai/test_ai_attachments.py backend/tests/unit/ai/test_ai_chat.py`

**Step 3: Implement attachment service and routes**

Add upload/list/delete routes. Save the file, parse it, update status, and return sanitized metadata. Add `attachment_ids` to `SendMessagePayload`.

**Step 4: Build model messages**

For the current message, use a content list containing `text` and image `image_url` blocks. Insert parsed file evidence in bounded `<attachment>` sections with prompt-injection warnings. Keep stored user content unchanged and persist attachment metadata.

**Step 5: Verify and commit**

Run the focused backend tests and commit.

### Task 7: Add frontend attachment controls

**Files:**
- Modify: `frontend/src/platform/api/types.ts`
- Modify: `frontend/src/platform/api/httpAdapter.ts`
- Modify: `frontend/src/features/ai-chat/types.ts`
- Modify: `frontend/src/features/ai-chat/useAiChat.ts`
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.tsx`
- Modify: `frontend/src/features/ai-chat/AiChatDrawer.module.css`
- Create: `frontend/src/features/ai-chat/AiChatDrawer.test.tsx`
- Modify: `frontend/src/platform/api/httpAdapter.test.ts`

**Step 1: Write failing adapter and UI tests**

Assert multipart upload, attachment ID message payload, `+` button behavior, allowed file types, upload status, image preview, remove action, attachment-only send, disabled send while parsing, and historical attachment labels.

**Step 2: Run and verify red**

Run: `cd frontend; npm test -- --run src/platform/api/httpAdapter.test.ts src/features/ai-chat/AiChatDrawer.test.tsx`

**Step 3: Implement adapter and hook mutations**

Add upload/list/delete methods and normalized attachment types. Upload selected files before send and include ready IDs.

**Step 4: Implement accessible UI**

Use the existing icon library for add/remove/file/image controls, include tooltips and screen-reader labels, keep the message list as the dominant area, and avoid blocking the entire drawer during upload.

**Step 5: Verify and commit**

Run focused tests, full frontend tests and build, then commit.

### Task 8: Probe Responses API input_file without making it a dependency

**Files:**
- Modify: `tools/ai/test_ai_model_connectivity.ps1`
- Modify: `backend/tests/unit/ai/test_ai_connectivity_script.py`

**Step 1: Extend the fake gateway and write failing tests**

Accept a Responses API payload with `input_text` and `input_file`, return a marker, and assert `checks.multimodal.responses_file_input` is recorded. Add unsupported and missing Responses endpoint cases.

**Step 2: Run and verify red**

Run: `python -m pytest -q backend/tests/unit/ai/test_ai_connectivity_script.py -k responses_file`

**Step 3: Implement the probe**

Send a small base64 text file to `/responses`. Record passed, unsupported, inconclusive or skipped independently from Chat Completions `file_input`. Do not include it in core connectivity failure calculation.

**Step 4: Verify and commit**

Run the complete connectivity script test file and commit the probe changes, including the prior empty-result fix if still uncommitted.

### Task 9: Full verification and deployment synchronization

**Files:**
- Modify only if generated by official packaging: `build/fanban-terminal-deploy/**`

**Step 1: Backend verification**

Run: `python -m pytest -q backend/tests/unit/ai`

Run relevant CAD unit tests and a real local DXF smoke sample. Run DWG smoke only when ODA is available and report the exact source/output paths.

**Step 2: Frontend verification**

Run: `cd frontend; npm test -- --run`

Run: `cd frontend; npm run build`

**Step 3: Browser smoke**

Start isolated frontend/backend ports. Use Playwright to upload a generated image, TXT and DXF; verify preview, send, assistant response, history reload, deletion and cross-owner API rejection.

**Step 4: Package verification**

Generate the terminal deployment tree through the official builder. Confirm the packaged probe hash matches source and attachment parser dependencies are present. The full ZIP name remains `build/AI测试终端部署包.zip`.

**Step 5: Final report**

Separate code implemented, tests passed, real sample smoke-tested, terminal-only checks, and remaining risks. Do not claim Responses file support unless the terminal probe returns passed.
