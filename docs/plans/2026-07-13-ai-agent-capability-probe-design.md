# AI Agent Capability Probe Design

## Goal

Extend the existing `test_ai_model_connectivity.ps1` into a single, reusable
terminal diagnostic that distinguishes basic model connectivity from the
capabilities needed by an Agent SDK, multimodal chat, and MCP orchestration.
The probe must stay non-destructive, run on Windows PowerShell 5.1, avoid new
runtime dependencies, and write enough structured evidence to make the later
AI architecture decision without editing the script again.

## Existing Baseline

Version 0.2 already records the script/config hashes, endpoint and auth
metadata, DNS, TCP, optional `/models`, non-streaming chat, and streaming chat.
The 2026-07-13 terminal result proves the internal Qwen endpoint can complete
text chat and SSE-style streaming. It does not prove tool calling, structured
output, multimodal input, Agent SDK runtime availability, or MCP availability.

## Scope

The probe will keep the existing command-line entry point and add capability
checks in five groups:

1. Core protocol: text, UTF-8 Chinese, system instruction, multi-turn history,
   usage metadata, streaming, and latency.
2. Agent protocol: function tool selection, JSON arguments, tool-result
   round-trip, parallel tool calls, streamed tool-call reconstruction,
   `json_object`, and `json_schema` response formats.
3. Routing simulation: offer harmless synthetic specialist tools and verify
   that general conversation does not needlessly route while an explicit
   business request can produce a specialist handoff call.
4. Multimodal input: generate a temporary high-contrast PNG with a unique
   marker and send it as an OpenAI-compatible `image_url` data URL. A small
   inline text-file content part is tested separately. No project data is
   uploaded.
5. Runtime and MCP: inventory packaged Python executables and relevant Python
   packages, then probe explicitly configured MCP transports. MCP checks are
   limited to initialization, ping, and capability listing; no real tool is
   executed by default.

## Capability Semantics

Every check reports one of:

- `passed`: the expected protocol behavior was observed.
- `failed`: a required check ran and failed.
- `unsupported`: the endpoint explicitly rejected an optional feature.
- `inconclusive`: the request succeeded but its output did not prove support.
- `not_configured`: no endpoint or command was supplied for that feature.
- `not_installed`: a local SDK/runtime package is absent.
- `skipped`: the caller explicitly skipped the check or a prerequisite failed.

Only required core checks affect `status`. Optional capability failures are
reported in readiness sections and recommendations. This prevents unsupported
`/models`, JSON schema, vision, or MCP from being misreported as a total model
connectivity failure.

## Result Schema

The JSON schema version becomes `0.3`. Existing environment, profile, auth,
network, warning, and error fields remain. New sections are:

```text
checks.core
checks.agent_protocol
checks.routing
checks.multimodal
checks.runtime
checks.mcp
readiness.core_connectivity
readiness.agent_protocol
readiness.multimodal
readiness.agents_sdk_runtime
readiness.mcp
recommendations
```

Each network check keeps status code, content type, final URL, elapsed time,
bounded response previews, parsed evidence, and sanitized error text. API keys
remain excluded; only presence, length, and a short SHA-256 fingerprint are
recorded.

## Safety And Load

- Synthetic function tools perform no local or remote action.
- MCP discovery never calls a listed tool unless a future explicit safe-tool
  option and arguments are provided.
- Multimodal fixtures are generated locally and removed in `finally` blocks.
- Concurrency is a low-load sample with a small configurable count, not a
  stress test.
- Host allowlists are enforced before any network probe.
- Optional Responses-only and vendor-specific endpoints are not guessed.
- Body previews are bounded and secret-bearing request headers are never
  serialized.

## Configuration

Probe defaults and expected support stay in `documents/AI/ai_model_gateway.yaml`
so terminal and development profiles can declare required versus optional
capabilities. Command-line switches can override probe intensity and supply an
MCP HTTP URL or stdio command without creating another config file.

The current internal profile will require text chat and retain optional model
listing. Agent, structured-output, vision, and MCP checks are discovery checks
until terminal evidence establishes support.

## Verification

The existing Python fake OpenAI-compatible server will be extended to cover
successful tool calls, tool round-trips, structured output, image content,
streamed tool deltas, and explicit unsupported responses. Tests will verify:

- optional unsupported features do not fail core connectivity;
- malformed or split streaming tool arguments are reconstructed correctly;
- no secret appears in the JSON report;
- host policy blocks all probes before requests are sent;
- the terminal package still copies the updated script to
  `scripts/test_ai_model_connectivity.ps1`;
- the generated report is valid schema version 0.3 on PowerShell 5.1.

After local tests pass, the terminal operator runs the same script once with
the terminal profile and returns the generated JSON. The application Agent,
multimodal, and MCP implementation plan will be based on that evidence.
