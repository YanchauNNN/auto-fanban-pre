from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


class _OpenAiCompatibleHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    request_count = 0

    def do_GET(self) -> None:
        type(self).request_count += 1
        if self.path != "/v1/models":
            self.send_error(404)
            return
        self._send_json({"data": [{"id": "Qwen3.6-35A3"}]})

    def do_POST(self) -> None:
        type(self).request_count += 1
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if payload.get("stream"):
            self._send_stream()
        else:
            self._send_json(
                {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "AI_CONNECTIVITY_OK"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )

    def log_message(self, *_args: object) -> None:
        return

    def _send_json(self, body: object) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_stream(self) -> None:
        chunks = [
            {"choices": [{"delta": {"role": "assistant", "content": ""}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "AI"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "_CONNECT"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "IVITY"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "_OK"}, "finish_reason": "stop"}]},
        ]
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
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAiCompatibleHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


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
    assert result["schema_version"] == "0.2"
    assert result["status"] == "passed"
    assert result["script"]["version"] == "fanban-ai-connectivity@0.2"
    assert result["script"]["sha256"] == hashlib.sha256(script_path.read_bytes()).hexdigest().upper()
    assert result["environment"]["config_sha256"] == hashlib.sha256(
        config_path.read_bytes(),
    ).hexdigest().upper()
    assert result["checks"]["chat"]["content_type"] == "application/json"
    assert result["checks"]["chat"]["elapsed_ms"] >= 0
    assert result["checks"]["stream"]["content_type"] == "text/event-stream"
    assert result["checks"]["stream"]["elapsed_ms"] >= 0
    assert result["checks"]["stream"]["data_line_count"] == 6
    assert result["checks"]["stream"]["parsed_event_count"] == 5
    assert result["checks"]["stream"]["invalid_data_line_count"] == 0
    assert result["checks"]["stream"]["done_received"] is True
    assert result["checks"]["stream"]["response_contains_expected"] is True
    assert result["checks"]["stream"]["content_preview"] == "AI_CONNECTIVITY_OK"


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
