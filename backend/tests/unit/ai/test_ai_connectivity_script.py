from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REBAR_SUGGESTION_REQUIRED_FILES = (
    Path("SKILL.md"),
    Path("agents/openai.yaml"),
    Path("references/io-schema.md"),
    Path("references/ranking-rules.md"),
    Path("scripts/validate_fixtures.py"),
)


def _rebar_skill_bundle_sha256(skill_root: Path) -> str:
    parts = [
        ("SKILL.md", (skill_root / "SKILL.md").read_text(encoding="utf-8")),
        (
            "references/io-schema.md",
            (skill_root / "references" / "io-schema.md").read_text(
                encoding="utf-8"
            ),
        ),
        (
            "references/ranking-rules.md",
            (skill_root / "references" / "ranking-rules.md").read_text(
                encoding="utf-8"
            ),
        ),
    ]
    content = "\n\n".join(f"## {name}\n{text}" for name, text in parts)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class _OpenAiCompatibleHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    request_count = 0
    received_payloads: list[dict[str, object]] = []
    received_mcp_payloads: list[dict[str, object]] = []
    received_application_state_headers: list[dict[str, str]] = []
    application_conversations: dict[str, dict[str, object]] = {}

    def do_GET(self) -> None:
        type(self).request_count += 1
        if urlsplit(self.path).path == "/api/ai/state":
            type(self).received_application_state_headers.append(dict(self.headers.items()))
            self._send_json(
                {
                    "enabled": True,
                    "profile": "application_probe_test",
                    "model": "Qwen3.6-35A3",
                    "owner_key": self._application_owner_key(),
                }
            )
            return
        if urlsplit(self.path).path == "/api/ai/conversations":
            owner_key = self._application_owner_key()
            conversations = [
                self._application_conversation_payload(conversation)
                for conversation in type(self).application_conversations.values()
                if conversation["owner_key"] == owner_key
            ]
            self._send_json(conversations)
            return
        if urlsplit(self.path).path.startswith("/api/ai/conversations/"):
            conversation_id = urlsplit(self.path).path.rsplit("/", 1)[-1]
            conversation = type(self).application_conversations.get(conversation_id)
            if conversation is None or conversation["owner_key"] != self._application_owner_key():
                self._send_json({"detail": "conversation_not_found"}, status_code=404)
                return
            payload = self._application_conversation_payload(conversation)
            payload["messages"] = []
            self._send_json(payload)
            return
        if self.path != "/v1/models":
            self.send_error(404)
            return
        self._send_json({"data": [{"id": "Qwen3.6-35A3"}]})

    def do_POST(self) -> None:
        type(self).request_count += 1
        application_path = urlsplit(self.path).path
        if application_path == "/api/ai/conversations":
            self._read_json_body()
            conversation_id = f"application-probe-{len(type(self).application_conversations) + 1}"
            conversation = {
                "conversation_id": conversation_id,
                "owner_key": self._application_owner_key(),
                "title": "AI owner probe",
                "message_count": 0,
            }
            type(self).application_conversations[conversation_id] = conversation
            self._send_json(self._application_conversation_payload(conversation), status_code=201)
            return
        if application_path.startswith("/api/ai/conversations/") and application_path.endswith("/messages"):
            self._read_json_body()
            conversation_id = application_path.removeprefix("/api/ai/conversations/").removesuffix("/messages").rstrip("/")
            conversation = type(self).application_conversations.get(conversation_id)
            if conversation is None or conversation["owner_key"] != self._application_owner_key():
                self._send_json({"detail": "conversation_not_found"}, status_code=404)
                return
            conversation["message_count"] = 2
            self._send_json(
                {
                    "user_message": {"role": "user", "content": "AI_OWNER_PROBE"},
                    "assistant_message": {"role": "assistant", "content": "AI_OWNER_PROBE_OK"},
                    "memory": {"used_history_messages": 0},
                }
            )
            return
        if urlsplit(self.path).path == "/mcp":
            self._handle_mcp()
            return
        if self.path == "/v1/responses":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            type(self).received_payloads.append(payload)
            response_input = payload.get("input")
            input_items = response_input if isinstance(response_input, list) else []
            has_input_file = any(
                content.get("type") == "input_file"
                for item in input_items
                if isinstance(item, dict)
                for content in (
                    item.get("content") if isinstance(item.get("content"), list) else []
                )
                if isinstance(content, dict)
            )
            if has_input_file and payload.get("model") == "limited-model":
                self._send_json(
                    {"error": {"message": "responses input_file is not supported"}},
                    status_code=400,
                )
                return
            self._send_json(
                {
                    "id": "resp-probe-7319",
                    "object": "response",
                    "model": payload.get("model"),
                    "output_text": (
                        "RESPONSES_FILE_OK_7319"
                        if has_input_file
                        else "RESPONSES_API_OK_7319"
                    ),
                    "output": [],
                }
            )
            return
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).received_payloads.append(payload)
        if payload.get("stream"):
            self._send_stream(payload)
        else:
            self._send_chat(payload)

    def do_DELETE(self) -> None:
        type(self).request_count += 1
        path = urlsplit(self.path).path
        if not path.startswith("/api/ai/conversations/"):
            self.send_error(404)
            return
        conversation_id = path.rsplit("/", 1)[-1]
        conversation = type(self).application_conversations.get(conversation_id)
        if conversation is None or conversation["owner_key"] != self._application_owner_key():
            self._send_json({"detail": "conversation_not_found"}, status_code=404)
            return
        del type(self).application_conversations[conversation_id]
        self._send_json({"ok": True})

    def log_message(self, *_args: object) -> None:
        return

    def _application_owner_key(self) -> str:
        raw = (self.headers.get("X-Forwarded-For") or "127.0.0.1").split(",", 1)[0].strip()
        if raw.startswith("[") and "]" in raw:
            raw = raw[1 : raw.index("]")]
        else:
            host, separator, port = raw.rpartition(":")
            if separator and port.isdecimal():
                raw = host
        return f"ip:{ip_address(raw)}"

    @staticmethod
    def _application_conversation_payload(conversation: dict[str, object]) -> dict[str, object]:
        return {
            "conversation_id": conversation["conversation_id"],
            "title": conversation["title"],
            "message_count": conversation["message_count"],
        }

    def _read_json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        return payload if isinstance(payload, dict) else {}

    def _send_json(
        self,
        body: object,
        *,
        extra_headers: dict[str, str] | None = None,
        status_code: int = 200,
    ) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _send_chat(self, payload: dict[str, object]) -> None:
        messages = payload.get("messages")
        message_list = messages if isinstance(messages, list) else []
        last = message_list[-1] if message_list else {}
        last_role = last.get("role") if isinstance(last, dict) else None
        last_content = last.get("content") if isinstance(last, dict) else ""
        prompt = last_content if isinstance(last_content, str) else ""

        response_format = payload.get("response_format")
        if payload.get("model") == "limited-model" and (
            (isinstance(response_format, dict) and response_format.get("type") == "json_schema")
            or isinstance(last_content, list)
        ):
            self._send_json(
                {"error": {"message": "optional capability is not supported"}},
                status_code=400,
            )
            return

        if isinstance(last_content, list):
            content_types = {
                item.get("type") for item in last_content if isinstance(item, dict)
            }
            if "image_url" in content_types:
                marker = (
                    "vision_marker_7319"
                    if payload.get("model") == "concurrency-generic-model"
                    else "VISION_MARKER_7319"
                )
                self._send_completion(marker)
                return
            if "file" in content_types:
                self._send_completion("FILE_CONTENT_OK_7319")
                return

        if last_role == "tool":
            self._send_completion("TOOL_ROUNDTRIP_OK")
            return
        if "SMX_REBAR_SELECTION_PROBE_7319" in prompt:
            self._send_completion(
                json.dumps(
                    {
                        "schema_version": "smx-rebar-1",
                        "items": [
                            {
                                "item_id": "PROBE:X",
                                "status": "selected",
                                "selected_candidate_id": "linear-l1-d16-s200",
                                "reason": "minimum eligible candidate",
                                "review_reasons": [],
                            }
                        ],
                    },
                    separators=(",", ":"),
                )
            )
            return
        if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
            self._send_completion('{"marker":"JSON_SCHEMA_OK","value":7319}')
            return
        if isinstance(response_format, dict) and response_format.get("type") == "json_object":
            self._send_completion('{"marker":"JSON_OBJECT_OK"}')
            return
        if "SYSTEM_PROBE_7319" in prompt:
            system_text = " ".join(
                str(item.get("content", ""))
                for item in message_list
                if isinstance(item, dict) and item.get("role") == "system"
            )
            self._send_completion(
                "SYSTEM_INSTRUCTION_OK" if "SYSTEM_RULE_7319" in system_text else "SYSTEM_MISSING"
            )
            return
        if "MEMORY_RECALL_7319" in prompt:
            history_text = " ".join(
                str(item.get("content", "")) for item in message_list if isinstance(item, dict)
            )
            self._send_completion(
                "MEMORY_HISTORY_OK" if "MEMORY_VALUE_4826" in history_text else "MEMORY_MISSING"
            )
            return
        if "ROUTING_GENERAL_7319" in prompt:
            self._send_completion("Here is a direct general answer without a handoff.")
            return
        if "CONCURRENCY_PROBE_7319" in prompt:
            if payload.get("model") == "concurrency-generic-model":
                self._send_completion("A valid concurrent chat response without an exact marker.")
            else:
                self._send_completion("CONCURRENCY_OK_7319")
            return
        if "ROUTING_BUSINESS_7319" in prompt:
            self._send_tool_calls(
                [("route-drawing", "transfer_to_drawing_agent", {"reason": "explicit_business_request"})]
            )
            return
        if "PARALLEL_TOOL_PROBE_7319" in prompt:
            self._send_tool_calls(
                [
                    ("parallel-1", "probe_sum", {"a": 3, "b": 4}),
                    ("parallel-2", "probe_echo", {"text": "parallel"}),
                ]
            )
            return

        tool_choice = payload.get("tool_choice")
        if isinstance(tool_choice, dict):
            function = tool_choice.get("function")
            tool_name = function.get("name") if isinstance(function, dict) else None
            if tool_name == "probe_sum":
                self._send_tool_calls([("tool-sum-1", "probe_sum", {"a": 7, "b": 12})])
                return

        self._send_completion("AI_CONNECTIVITY_OK")

    def _send_completion(self, content: str) -> None:
        self._send_json(
            {
                "model": "Qwen3.6-35A3",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
            }
        )

    def _handle_mcp(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).received_mcp_payloads.append(payload)
        method = payload.get("method")
        request_id = payload.get("id")
        if method == "initialize":
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                        "serverInfo": {"name": "fanban-test-mcp", "version": "1.0"},
                    },
                },
                extra_headers={"Mcp-Session-Id": "test-session-7319"},
            )
            return
        results = {
            "ping": {},
            "tools/list": {"tools": [{"name": "read_only_probe"}]},
            "resources/list": {"resources": []},
            "prompts/list": {"prompts": []},
            "notifications/initialized": {},
        }
        self._send_json(
            {"jsonrpc": "2.0", "id": request_id, "result": results.get(str(method), {})}
        )

    def _send_tool_calls(self, calls: list[tuple[str, str, dict[str, object]]]) -> None:
        self._send_json(
            {
                "model": "Qwen3.6-35A3",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(arguments),
                                    },
                                }
                                for call_id, name, arguments in calls
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
        )

    def _send_stream(self, payload: dict[str, object]) -> None:
        messages = payload.get("messages")
        message_list = messages if isinstance(messages, list) else []
        last = message_list[-1] if message_list else {}
        prompt = last.get("content", "") if isinstance(last, dict) else ""
        if isinstance(prompt, str) and "STREAM_TOOL_PROBE_7319" in prompt:
            chunks = [
                {
                    "choices": [
                        {
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "stream-tool-1",
                                        "type": "function",
                                        "function": {"name": "probe_", "arguments": '{"a":'},
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"name": "sum", "arguments": "7,"},
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"arguments": '"b":12}'}}
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            ]
            self._send_stream_chunks(chunks)
            return

        chunks = [
            {"choices": [{"delta": {"role": "assistant", "content": ""}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "AI"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "_CONNECT"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "IVITY"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "_OK"}, "finish_reason": "stop"}]},
        ]
        self._send_stream_chunks(chunks)

    def _send_stream_chunks(self, chunks: list[dict[str, object]]) -> None:
        lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
        lines.append("data: [DONE]\n\n")
        encoded = "".join(lines).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@pytest.fixture
def openai_compatible_server() -> str:
    _OpenAiCompatibleHandler.request_count = 0
    _OpenAiCompatibleHandler.received_payloads = []
    _OpenAiCompatibleHandler.received_mcp_payloads = []
    _OpenAiCompatibleHandler.received_application_state_headers = []
    _OpenAiCompatibleHandler.application_conversations = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAiCompatibleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_ai_connectivity_script_probes_application_api_proxy_owner_behavior(
    tmp_path: Path,
    openai_compatible_server: str,
) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the connectivity script")

    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1"
    config_path = tmp_path / "ai_model_gateway.yaml"
    output_path = tmp_path / "connectivity.json"
    application_base_url = openai_compatible_server.removesuffix("/v1")
    config_path.write_text(
        f"""
schema_version: "0.1"
active_profile: "application_probe_test"
profiles:
  application_probe_test:
    provider: "local-test"
    protocol: "openai_compatible"
    network_mode: "test"
    architecture: "local_test_gateway"
    base_url: "{openai_compatible_server}"
    models_path: "/models"
    chat_completions_path: "/chat/completions"
    api_key_env_var: ""
    api_key_required: false
    authorization_scheme: "none"
    chat_model: "Qwen3.6-35A3"
    structured_model: "Qwen3.6-35A3"
    stream_enabled: true
    timeout_sec: 15
    connect_timeout_sec: 5
    model_list_required: true
    ssl_no_revoke: false
    test_prompt: "Please reply exactly: AI_CONNECTIVITY_OK"
    expected_response_contains: "AI_CONNECTIVITY_OK"
    agent_probe_enabled: false
    multimodal_probe_enabled: false
    concurrency_probe_count: 0
    application_api_base_url: "{application_base_url}"
    application_api_state_path: "/api/ai/state"
    application_api_host_header: "fanban-terminal.local"
    application_api_forwarded_for_probe: "198.18.0.73"
""".strip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ConfigPath",
            str(config_path),
            "-OutputPath",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8-sig"))
    application = result["checks"]["application_api"]
    assert application["status"] == "passed"
    assert application["direct"]["owner_key"] == "ip:127.0.0.1"
    assert application["forwarded"]["owner_key"] == "ip:198.18.0.73"
    assert application["forwarded_owner_effective"] is True
    assert "conversation" in application
    assert application["conversation"]["status"] == "passed"
    assert application["conversation"]["same_owner_after_port_change"] is True
    assert application["profile_matches_selected"] is True
    assert application["sensitive_response_fields"] == []
    assert result["readiness"]["application_api_proxy"]["status"] == "passed"
    assert _OpenAiCompatibleHandler.received_application_state_headers[-1]["Host"] == "fanban-terminal.local"
    assert _OpenAiCompatibleHandler.received_application_state_headers[-1]["X-Forwarded-For"] == "198.18.0.73:49100"


def test_ai_connectivity_script_accepts_split_stream_content(
    tmp_path: Path,
    openai_compatible_server: str,
) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the connectivity script")

    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1"
    config_path = tmp_path / "ai_model_gateway.yaml"
    output_path = tmp_path / "connectivity.json"
    config_path.write_text(
        f"""
schema_version: "0.1"
active_profile: "split_stream_test"
profiles:
  split_stream_test:
    provider: "local-test"
    protocol: "openai_compatible"
    network_mode: "test"
    architecture: "local_test_gateway"
    base_url: "{openai_compatible_server}"
    models_path: "/models"
    chat_completions_path: "/chat/completions"
    api_key_env_var: ""
    api_key_required: false
    authorization_scheme: "none"
    chat_model: "Qwen3.6-35A3"
    structured_model: "Qwen3.6-35A3"
    stream_enabled: true
    timeout_sec: 15
    connect_timeout_sec: 5
    model_list_required: true
    ssl_no_revoke: false
    test_prompt: "Please reply exactly: AI_CONNECTIVITY_OK"
    expected_response_contains: "AI_CONNECTIVITY_OK"
""".strip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ConfigPath",
            str(config_path),
            "-OutputPath",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8-sig"))
    assert result["schema_version"] == "0.6"
    assert result["status"] == "passed"
    assert result["script"]["version"] == "fanban-ai-connectivity@0.7"
    assert result["script"]["sha256"] == hashlib.sha256(script_path.read_bytes()).hexdigest().upper()
    assert result["environment"]["config_sha256"] == hashlib.sha256(
        config_path.read_bytes(),
    ).hexdigest().upper()
    assert result["checks"]["chat"]["content_type"] == "application/json"
    assert result["checks"]["ansys_mapdl_skill"]["skill_id"] == "ansys_mapdl_18_2"
    assert result["checks"]["ansys_mapdl_skill"]["local_status"] in {
        "passed",
        "failed",
        "not_installed",
    }
    assert "ansys_mapdl_skill" in result["readiness"]
    assert result["checks"]["chat"]["elapsed_ms"] >= 0
    assert result["checks"]["stream"]["content_type"] == "text/event-stream"
    assert result["checks"]["stream"]["elapsed_ms"] >= 0
    assert result["checks"]["stream"]["data_line_count"] == 6
    assert result["checks"]["stream"]["parsed_event_count"] == 5
    assert result["checks"]["stream"]["invalid_data_line_count"] == 0
    assert result["checks"]["stream"]["done_received"] is True
    assert result["checks"]["stream"]["response_contains_expected"] is True
    assert result["checks"]["stream"]["content_preview"] == "AI_CONNECTIVITY_OK"
    assert result["readiness"]["core_connectivity"]["status"] == "passed"
    assert result["readiness"]["agent_protocol"]["status"] in {
        "passed",
        "unsupported",
        "inconclusive",
        "skipped",
    }
    assert result["readiness"]["multimodal"]["status"] in {
        "passed",
        "unsupported",
        "inconclusive",
        "skipped",
    }
    assert result["readiness"]["agents_sdk_runtime"]["status"] in {
        "passed",
        "not_installed",
        "inconclusive",
    }
    assert result["readiness"]["mcp"]["status"] == "not_configured"
    assert isinstance(result["recommendations"], list)


def test_ai_connectivity_script_probes_agent_protocol_round_trip(
    tmp_path: Path,
    openai_compatible_server: str,
) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the connectivity script")

    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1"
    config_path = tmp_path / "ai_model_gateway.yaml"
    output_path = tmp_path / "connectivity.json"
    config_path.write_text(
        f"""
schema_version: "0.1"
active_profile: "agent_probe_test"
profiles:
  agent_probe_test:
    provider: "local-test"
    protocol: "openai_compatible"
    network_mode: "test"
    architecture: "local_test_gateway"
    base_url: "{openai_compatible_server}"
    models_path: "/models"
    chat_completions_path: "/chat/completions"
    responses_path: "/responses"
    api_key_env_var: ""
    api_key_required: false
    authorization_scheme: "none"
    chat_model: "Qwen3.6-35A3"
    structured_model: "Qwen3.6-35A3"
    stream_enabled: true
    timeout_sec: 15
    connect_timeout_sec: 5
    model_list_required: true
    ssl_no_revoke: false
    test_prompt: "Please reply exactly: AI_CONNECTIVITY_OK"
    expected_response_contains: "AI_CONNECTIVITY_OK"
    agent_probe_enabled: true
    multimodal_probe_enabled: false
    concurrency_probe_count: 0
""".strip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ConfigPath",
            str(config_path),
            "-OutputPath",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8-sig"))
    agent = result["checks"]["agent_protocol"]
    assert agent["system_instruction"]["status"] == "passed"
    assert agent["responses_api"]["status"] == "passed"
    assert agent["multi_turn_memory"]["status"] == "passed"
    assert agent["json_object"]["status"] == "passed"
    assert agent["json_schema"]["status"] == "passed"
    assert agent["named_tool_choice"]["status"] == "passed"
    assert agent["named_tool_choice"]["tool_calls"][0]["name"] == "probe_sum"
    assert agent["named_tool_choice"]["tool_calls"][0]["arguments"] == {"a": 7, "b": 12}
    assert agent["tool_round_trip"]["status"] == "passed"
    assert agent["parallel_tool_calls"]["status"] == "passed"
    assert agent["streamed_tool_calls"]["status"] == "passed"
    assert agent["streamed_tool_calls"]["tool_calls"][0]["name"] == "probe_sum"
    assert agent["streamed_tool_calls"]["tool_calls"][0]["arguments"] == {"a": 7, "b": 12}
    routing = result["checks"]["routing"]
    assert routing["general_conversation"]["status"] == "passed"
    assert routing["explicit_business_handoff"]["status"] == "passed"
    assert routing["explicit_business_handoff"]["selected_agent"] == "drawing_understanding"
    assert result["readiness"]["agent_protocol"]["status"] == "passed"


def test_ai_connectivity_script_probes_multimodal_runtime_concurrency_and_mcp(
    tmp_path: Path,
    openai_compatible_server: str,
) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the connectivity script")

    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1"
    config_path = tmp_path / "ai_model_gateway.yaml"
    output_path = tmp_path / "connectivity.json"
    mcp_url = openai_compatible_server.removesuffix("/v1") + "/mcp?access_token=MCP_SECRET_7319"
    config_path.write_text(
        f"""
schema_version: "0.1"
active_profile: "full_probe_test"
profiles:
  full_probe_test:
    provider: "local-test"
    protocol: "openai_compatible"
    network_mode: "test"
    architecture: "local_test_gateway"
    base_url: "{openai_compatible_server}"
    mcp_allowed_hosts: ["127.0.0.1", "localhost"]
    models_path: "/models"
    chat_completions_path: "/chat/completions"
    api_key_env_var: ""
    api_key_required: false
    authorization_scheme: "none"
    chat_model: "concurrency-generic-model"
    structured_model: "concurrency-generic-model"
    responses_path: "/responses"
    stream_enabled: true
    timeout_sec: 15
    connect_timeout_sec: 5
    model_list_required: true
    ssl_no_revoke: false
    test_prompt: "Please reply exactly: AI_CONNECTIVITY_OK"
    expected_response_contains: "AI_CONNECTIVITY_OK"
    agent_probe_enabled: false
    multimodal_probe_enabled: true
    concurrency_probe_count: 2
    mcp_streamable_http_url: "{mcp_url}"
    mcp_sse_url: ""
    mcp_stdio_command: ""
""".strip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ConfigPath",
            str(config_path),
            "-OutputPath",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8-sig"))
    multimodal = result["checks"]["multimodal"]
    assert multimodal["image_input"]["status"] == "passed"
    assert multimodal["file_input"]["status"] == "passed"
    assert multimodal["responses_file_input"]["status"] == "passed"
    assert result["readiness"]["multimodal"]["status"] == "passed"
    responses_file_payload = next(
        payload
        for payload in _OpenAiCompatibleHandler.received_payloads
        if isinstance(payload.get("input"), list)
    )
    input_content = responses_file_payload["input"][0]["content"]
    assert input_content[0] == {
        "type": "input_text",
        "text": "Read and return the exact marker stored in the attached text file.",
    }
    assert input_content[1]["type"] == "input_file"
    assert input_content[1]["filename"] == "fanban-agent-probe.txt"
    assert input_content[1]["file_data"].startswith("data:text/plain;base64,")
    concurrency = result["checks"]["concurrency"]
    assert concurrency["status"] == "passed"
    assert concurrency["requested"] == 2
    assert concurrency["succeeded"] == 2
    runtime = result["checks"]["runtime"]
    assert runtime["powershell_version"]
    assert runtime["timezone"]
    assert "python_candidates" in runtime
    assert "packages" in runtime
    assert runtime["python_version"]
    assert runtime["error"] is None
    mcp = result["checks"]["mcp"]["streamable_http"]
    assert mcp["status"] == "passed"
    assert mcp["session_id"] == "test-session-7319"
    assert mcp["server_name"] == "fanban-test-mcp"
    assert mcp["tool_count"] == 1
    assert result["readiness"]["mcp"]["status"] == "passed"
    assert result["profile"]["mcp_allowed_hosts"] == ["127.0.0.1", "localhost"]
    serialized = json.dumps(result)
    assert "Authorization: Bearer" not in serialized
    assert "MCP_SECRET_7319" not in serialized
    initialized = next(
        item
        for item in _OpenAiCompatibleHandler.received_mcp_payloads
        if item.get("method") == "notifications/initialized"
    )
    assert "id" not in initialized


def test_ai_connectivity_script_captures_full_python_runtime_error(
    tmp_path: Path,
    openai_compatible_server: str,
) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the connectivity script")

    repo_root = Path(__file__).resolve().parents[4]
    source_script = repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1"
    isolated_root = tmp_path / "isolated-probe-root"
    script_path = isolated_root / "tools" / "ai" / source_script.name
    config_path = isolated_root / "documents" / "AI" / "ai_model_gateway.yaml"
    output_path = tmp_path / "connectivity.json"
    fake_python = isolated_root / "python-runtime" / "python.exe"
    script_path.parent.mkdir(parents=True)
    config_path.parent.mkdir(parents=True)
    fake_python.parent.mkdir(parents=True)
    shutil.copy2(source_script, script_path)

    powershell_path = Path(shutil.which("powershell") or "")
    assert powershell_path.is_file()
    try:
        os.link(powershell_path, fake_python)
    except OSError:
        shutil.copy2(powershell_path, fake_python)

    config_path.write_text(
        f"""
schema_version: "0.1"
active_profile: "runtime_probe_test"
profiles:
  runtime_probe_test:
    provider: "local-test"
    protocol: "openai_compatible"
    network_mode: "test"
    architecture: "local_test_gateway"
    base_url: "{openai_compatible_server}"
    models_path: "/models"
    chat_completions_path: "/chat/completions"
    api_key_env_var: ""
    api_key_required: false
    authorization_scheme: "none"
    chat_model: "Qwen3.6-35A3"
    structured_model: "Qwen3.6-35A3"
    stream_enabled: true
    timeout_sec: 15
    connect_timeout_sec: 5
    model_list_required: true
    ssl_no_revoke: false
    test_prompt: "Please reply exactly: AI_CONNECTIVITY_OK"
    expected_response_contains: "AI_CONNECTIVITY_OK"
    agent_probe_enabled: false
    multimodal_probe_enabled: false
    concurrency_probe_count: 0
""".strip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ConfigPath",
            str(config_path),
            "-OutputPath",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8-sig"))
    runtime = result["checks"]["runtime"]
    assert runtime["python_version"] is None
    assert "MissingOpenParenthesisAfterKeyword" in runtime["error"]
    assert "\n" in runtime["error"]


def test_optional_agent_and_multimodal_rejections_do_not_fail_core_connectivity(
    tmp_path: Path,
    openai_compatible_server: str,
) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the connectivity script")

    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1"
    config_path = tmp_path / "ai_model_gateway.yaml"
    output_path = tmp_path / "connectivity.json"
    config_path.write_text(
        f"""
schema_version: "0.1"
active_profile: "limited_probe_test"
profiles:
  limited_probe_test:
    provider: "local-test"
    protocol: "openai_compatible"
    network_mode: "test"
    architecture: "local_test_gateway"
    base_url: "{openai_compatible_server}"
    models_path: "/models"
    chat_completions_path: "/chat/completions"
    api_key_env_var: ""
    api_key_required: false
    authorization_scheme: "none"
    chat_model: "limited-model"
    structured_model: "limited-model"
    responses_path: "/responses"
    stream_enabled: true
    timeout_sec: 15
    connect_timeout_sec: 5
    model_list_required: true
    ssl_no_revoke: false
    test_prompt: "Please reply exactly: AI_CONNECTIVITY_OK"
    expected_response_contains: "AI_CONNECTIVITY_OK"
    agent_probe_enabled: true
    multimodal_probe_enabled: true
    concurrency_probe_count: 0
""".strip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ConfigPath",
            str(config_path),
            "-OutputPath",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8-sig"))
    assert result["status"] == "passed"
    assert result["readiness"]["core_connectivity"]["status"] == "passed"
    assert result["checks"]["agent_protocol"]["json_schema"]["status"] == "unsupported"
    assert result["checks"]["multimodal"]["image_input"]["status"] == "unsupported"
    assert result["checks"]["multimodal"]["file_input"]["status"] == "unsupported"
    assert result["checks"]["multimodal"]["responses_file_input"]["status"] == "unsupported"
    assert result["readiness"]["agent_protocol"]["status"] == "unsupported"
    assert result["readiness"]["multimodal"]["status"] == "unsupported"
    assert result["errors"] == []


def test_ai_connectivity_script_rejects_host_outside_intranet_allowlist(
    tmp_path: Path,
    openai_compatible_server: str,
) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the connectivity script")

    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1"
    config_path = tmp_path / "ai_model_gateway.yaml"
    output_path = tmp_path / "connectivity.json"
    config_path.write_text(
        f"""
schema_version: "0.1"
active_profile: "terminal_test"
profiles:
  terminal_test:
    provider: "local-test"
    protocol: "openai_compatible"
    network_mode: "intranet_only"
    architecture: "local_test_gateway"
    base_url: "{openai_compatible_server}"
    allowed_hosts: ["models.ai.cnpe.cc"]
    models_path: "/models"
    chat_completions_path: "/chat/completions"
    api_key_env_var: ""
    api_key_required: false
    authorization_scheme: "none"
    chat_model: "Qwen3.6-35A3"
    structured_model: "Qwen3.6-35A3"
    stream_enabled: true
    timeout_sec: 15
    connect_timeout_sec: 5
    model_list_required: true
    ssl_no_revoke: false
    test_prompt: "Please reply exactly: AI_CONNECTIVITY_OK"
    expected_response_contains: "AI_CONNECTIVITY_OK"
""".strip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ConfigPath",
            str(config_path),
            "-OutputPath",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert completed.returncode == 1
    result = json.loads(output_path.read_text(encoding="utf-8-sig"))
    assert result["status"] == "failed"
    assert result["profile"]["allowed_hosts"] == ["models.ai.cnpe.cc"]
    assert any(error["stage"] == "config" for error in result["errors"])
    assert result["network"]["dns"]["attempted"] is False
    assert result["network"]["tcp"]["attempted"] is False
    assert result["checks"]["models"]["attempted"] is False
    assert result["checks"]["chat"]["attempted"] is False
    assert result["checks"]["stream"]["attempted"] is False
    assert _OpenAiCompatibleHandler.request_count == 0


def test_ai_connectivity_script_reports_ansys_mapdl_skill_readiness() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    script_text = (repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1").read_text(
        encoding="utf-8-sig"
    )

    required_probe_markers = (
        "FANBAN_ANSYS_MAPDL_SKILL_ROOT",
        "ansys_mapdl_18_2",
        "validate_mapdl_skill.py",
        "mapdl_query.py",
        "ansys_mapdl_skill",
    )
    for marker in required_probe_markers:
        assert marker in script_text


def test_terminal_profile_probes_packaged_rebar_skill_with_structured_model(
    tmp_path: Path,
    openai_compatible_server: str,
) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the connectivity script")

    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1"
    config_path = tmp_path / "ai_model_gateway.yaml"
    output_path = tmp_path / "connectivity.json"
    skill_root = tmp_path / "package" / "tools" / "ai" / "recommend-rebar-from-smx"
    shutil.copytree(
        repo_root / "tools" / "ai" / "recommend-rebar-from-smx",
        skill_root,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    assert {
        path.relative_to(skill_root) for path in skill_root.rglob("*") if path.is_file()
    } == set(REBAR_SUGGESTION_REQUIRED_FILES)
    config_path.write_text(
        f"""
schema_version: "0.1"
active_profile: "terminal_cnpe_intranet_qwen_fast"
profiles:
  terminal_cnpe_intranet_qwen_fast:
    provider: "cnpe-qwen-fast"
    protocol: "openai_compatible"
    network_mode: "intranet_only"
    architecture: "intranet_openai_compatible_gateway"
    base_url: "{openai_compatible_server}"
    allowed_hosts: ["127.0.0.1"]
    mcp_allowed_hosts: ["127.0.0.1"]
    models_path: "/models"
    chat_completions_path: "/chat/completions"
    responses_path: "/responses"
    api_key_env_var: ""
    api_key_required: false
    authorization_scheme: "none"
    chat_model: "Qwen3.6-35A3"
    structured_model: "Qwen3.6-35A3-structured"
    stream_enabled: false
    timeout_sec: 15
    connect_timeout_sec: 5
    model_list_required: false
    ssl_no_revoke: false
    test_prompt: "Please reply exactly: AI_CONNECTIVITY_OK"
    expected_response_contains: "AI_CONNECTIVITY_OK"
    agent_probe_enabled: false
    multimodal_probe_enabled: false
    concurrency_probe_count: 0
    mcp_streamable_http_url: ""
    mcp_sse_url: ""
    mcp_stdio_command: ""
    mcp_api_key_env_var: ""
    application_api_base_url: ""
""".strip(),
        encoding="utf-8",
    )

    environment = os.environ.copy()
    environment["FANBAN_REBAR_SUGGESTION_SKILL_ROOT"] = str(skill_root)
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ConfigPath",
            str(config_path),
            "-OutputPath",
            str(output_path),
            "-SkipStream",
            "-SkipAdvanced",
            "-SkipMultimodal",
            "-Concurrency",
            "0",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=90,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8-sig"))
    assert result["environment"]["profile"] == "terminal_cnpe_intranet_qwen_fast"
    assert result["profile"]["structured_model"] == "Qwen3.6-35A3-structured"
    skill = result["checks"]["calculation_book_rebar_skill"]
    assert skill["skill_id"] == "recommend-rebar-from-smx"
    assert skill["root_source"] == "environment"
    assert skill["missing_files"] == []
    assert skill["content_sha256"] == _rebar_skill_bundle_sha256(skill_root)
    assert skill["validation"]["status"] == "passed"
    assert skill["structured_selection"]["status"] == "passed"
    assert skill["structured_selection"]["model"] == "Qwen3.6-35A3-structured"
    assert skill["structured_selection"]["selected_candidate_id"] == (
        "linear-l1-d16-s200"
    )
    assert result["readiness"]["structured_model"]["status"] == "passed"
    assert result["readiness"]["calculation_book_rebar_skill"]["status"] == (
        "passed"
    )
    structured_payloads = [
        payload
        for payload in _OpenAiCompatibleHandler.received_payloads
        if payload.get("model") == "Qwen3.6-35A3-structured"
    ]
    assert len(structured_payloads) == 1
    assert structured_payloads[0]["temperature"] == 0
    assert structured_payloads[0]["response_format"] == {"type": "json_object"}
    assert "SMX_REBAR_SELECTION_PROBE_7319" in json.dumps(
        structured_payloads[0], ensure_ascii=False
    )


def test_ai_connectivity_script_records_empty_ansys_query_without_crashing(
    tmp_path: Path,
    openai_compatible_server: str,
) -> None:
    if shutil.which("powershell") is None:
        pytest.skip("PowerShell is required for the connectivity script")

    repo_root = Path(__file__).resolve().parents[4]
    script_path = repo_root / "tools" / "ai" / "test_ai_model_connectivity.ps1"
    config_path = tmp_path / "ai_model_gateway.yaml"
    output_path = tmp_path / "connectivity.json"
    skill_root = tmp_path / "ansys-mapdl-18-2"

    required_files = {
        "SKILL.md": "# Test ANSYS Skill\n",
        "scripts/validate_mapdl_skill.py": (
            "import json\n"
            "print(json.dumps({'passed': True, 'integrity': {}, 'regression': {}}))\n"
        ),
        "scripts/mapdl_query.py": (
            "import json\n"
            "print(json.dumps({'query': 'ANTYPE', 'results': [], 'result_count': 0}))\n"
        ),
        "assets/data/mapdl_help.sqlite": "test database placeholder\n",
        "assets/data/mapdl_commands.jsonl": "{}\n",
        "assets/data/manifest.json": "{}\n",
        "references/validation-cases.json": "[]\n",
    }
    for relative_path, content in required_files.items():
        path = skill_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    config_path.write_text(
        f"""
schema_version: "0.1"
active_profile: "empty_ansys_query_test"
profiles:
  empty_ansys_query_test:
    provider: "local-test"
    protocol: "openai_compatible"
    network_mode: "test"
    architecture: "local_test_gateway"
    base_url: "{openai_compatible_server}"
    models_path: "/models"
    chat_completions_path: "/chat/completions"
    api_key_env_var: ""
    api_key_required: false
    authorization_scheme: "none"
    chat_model: "Qwen3.6-35A3"
    structured_model: "Qwen3.6-35A3"
    stream_enabled: false
    timeout_sec: 15
    connect_timeout_sec: 5
    model_list_required: true
    ssl_no_revoke: false
    test_prompt: "Please reply exactly: AI_CONNECTIVITY_OK"
    expected_response_contains: "AI_CONNECTIVITY_OK"
    agent_probe_enabled: false
    multimodal_probe_enabled: false
    concurrency_probe_count: 0
""".strip(),
        encoding="utf-8",
    )

    environment = os.environ.copy()
    environment["FANBAN_ANSYS_MAPDL_SKILL_ROOT"] = str(skill_root)
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ConfigPath",
            str(config_path),
            "-OutputPath",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output_path.read_text(encoding="utf-8-sig"))
    ansys_probe = result["checks"]["ansys_mapdl_skill"]
    assert ansys_probe["query"]["result_count"] == 0
    assert ansys_probe["query"]["first_canonical"] is None
    assert ansys_probe["query"]["status"] == "failed"
    assert ansys_probe["status"] == "failed"
