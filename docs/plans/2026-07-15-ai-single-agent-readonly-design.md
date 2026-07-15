# AI Single-Agent And Read-Only Host Access Design

## Goal

Simplify the AI drawer to two user-facing modes, `通用对话` and `业务 Agent`, while keeping one backend chat service and giving both modes controlled read-only access to approved deployment-host directories.

## Product Model

- The application runs one `AiChatService`; there is no multi-agent handoff, parallel agent, or autonomous worker loop.
- The two UI modes select prompt profiles on the same service.
- `通用对话` supports unrestricted normal conversation subject to safety policy.
- `业务 Agent` combines drawing understanding, task explanation, template rules, and future business tools.
- Skills and MCP placeholder chips are removed. A capability is shown only after a real backend tool is available.

## Read-Only Host Access

The model never receives operating-system credentials or direct filesystem access. It may request a small set of backend functions:

- `list_directory`: list a directory under an approved root.
- `search_files`: find file names under an approved root with bounded depth and result count.
- `read_text_file`: read a bounded UTF-8 or text-compatible file.
- `get_file_info`: return metadata without reading content.

Approved terminal roots are resolved relative to the packaged server root:

- `storage`
- `documents`
- `documents_bin`
- `backend-runtime/backend/src/cad`

The development equivalent `backend/src/cad` is also allowed when present. Path traversal, symlink/reparse escape, executable content, SQLite databases, secrets, keys, certificates, environment files, and configured sensitive names are denied. Tool calls are capped per model turn and recorded in message metadata without storing file contents in audit metadata.

## Model Protocol

The existing OpenAI-compatible client sends Chat Completions `tools` with `tool_choice: auto`. If the model returns tool calls, the service executes only registered read-only functions, appends tool results to the in-memory model context, and requests the final answer. The loop has a small fixed round limit. The probe already establishes that the terminal Qwen gateway supports named tool calls; unsupported gateways fail with a mapped gateway error rather than silently granting broader access.

## UI

Visual thesis: a quiet, full-height work surface where the transcript is the dominant area and configuration remains secondary.

- Desktop drawer opens at the full dynamic viewport height and remains resizable from the top-left handle.
- Existing stored 820px dimensions are invalidated once through a size schema version bump; later user resizing remains persistent.
- The mode selector contains exactly `通用对话` and `业务 Agent`.
- Skill chips and the disabled local MCP registry row are removed.
- The conversation strip remains compact; transcript receives all remaining vertical space.
- Mobile keeps a full-screen drawer and does not expose the desktop resize handle.

## Security And Errors

- All paths are canonicalized and must remain inside an allowed root.
- Missing roots are omitted from the available tool context.
- Files over the configured byte limit return a bounded error.
- Binary or denied files are never read.
- Tool errors are returned to the model as structured, non-sensitive results.
- The user receives a normal answer explaining unavailable access; raw server paths are not exposed unless they are inside an approved root and relevant to the request.

## Verification

- Unit tests cover mode configuration, general-chat prompt behavior, business prompt behavior, path traversal, denied files, bounded reads, listing/searching, and tool-call loops.
- Frontend tests cover two modes only, absence of skill/MCP chips, and full-height default sizing.
- Full AI backend tests, frontend tests, frontend build, and browser screenshots at desktop/mobile sizes are required before handoff.

