from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def test_chat_client_posts_openai_compatible_payload_without_leaking_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.chat_client import ChatClientConfig, OpenAICompatibleChatClient

    captured: dict[str, Any] = {}

    class FakeResponse:
        status = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "<think>hidden reasoning</think>\n\nAI_CONNECTIVITY_OK",
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 3},
                }
            ).encode("utf-8")

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("src.ai.chat_client.urlopen", fake_urlopen)

    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="https://api.example.test/v1/",
            api_key="secret-for-test",
            authorization_scheme="bearer",
            model="MiniMax-M3",
            timeout_seconds=12,
            temperature=0.2,
            max_output_tokens=512,
        )
    )

    result = client.complete(
        [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
        ]
    )

    assert result.content == "AI_CONNECTIVITY_OK"
    assert "hidden reasoning" not in repr(result)
    assert captured["url"] == "https://api.example.test/v1/chat/completions"
    assert captured["timeout"] == 12
    assert captured["headers"]["Authorization"] == "Bearer secret-for-test"
    assert captured["body"] == {
        "model": "MiniMax-M3",
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 512,
        "messages": [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
        ],
    }
    assert "secret-for-test" not in repr(client)
    assert "secret-for-test" not in repr(result)


def test_chat_client_sends_tools_and_parses_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ai.chat_client import ChatClientConfig, OpenAICompatibleChatClient

    captured: dict[str, Any] = {}

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_text_file",
                                            "arguments": json.dumps(
                                                {"root": "documents", "path": "README.txt"},
                                            ),
                                        },
                                    },
                                ],
                            },
                        },
                    ],
                },
            ).encode("utf-8")

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("src.ai.chat_client.urlopen", fake_urlopen)
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url="https://api.example.test/v1",
            api_key=None,
            authorization_scheme="none",
            model="test-model",
            timeout_seconds=10,
            temperature=0.2,
            max_output_tokens=256,
        ),
    )
    definitions = [
        {
            "type": "function",
            "function": {
                "name": "read_text_file",
                "description": "read",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    result = client.complete([{"role": "user", "content": "读取说明"}], tools=definitions)

    assert captured["body"]["tools"] == definitions
    assert captured["body"]["tool_choice"] == "auto"
    assert result.content == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].call_id == "call-1"
    assert result.tool_calls[0].name == "read_text_file"
    assert result.tool_calls[0].arguments == {"root": "documents", "path": "README.txt"}


def test_chat_client_runtime_uses_chat_timeout_without_generation_retries(tmp_path: Path) -> None:
    from API.app.routers.ai import build_chat_client

    from src.config.ai.ai_spec import AiSpec

    spec = AiSpec.model_validate(
        {
            "ai_layer": {
                "chat": {"request_timeout_seconds": 23},
                "model_gateway": {"timeout_sec": 60, "max_retries": 2},
            }
        }
    )
    spec.source_path = tmp_path / "参数规范_AI.yaml"

    client = build_chat_client(spec)

    assert client.config.timeout_seconds == 23
    assert client.config.max_retries == 0


def test_owner_key_normalizes_proxy_resolved_ipv4_address_with_port() -> None:
    from API.app.routers.ai import _owner_key

    request = SimpleNamespace(
        client=SimpleNamespace(host="10.102.17.81:65255"),
        headers={},
    )

    assert _owner_key(request) == "ip:10.102.17.81"


def test_owner_key_normalizes_proxy_resolved_ipv6_address_with_port() -> None:
    from API.app.routers.ai import _owner_key

    request = SimpleNamespace(
        client=SimpleNamespace(host="[2001:db8:10::73]:65255"),
        headers={},
    )

    assert _owner_key(request) == "ip:2001:db8:10::73"


def test_owner_key_ignores_spoofed_forwarded_address_from_untrusted_peer() -> None:
    from API.app.routers.ai import _owner_key

    request = SimpleNamespace(
        client=SimpleNamespace(host="10.102.17.81"),
        headers={"x-forwarded-for": "10.102.17.99:65255"},
    )

    assert _owner_key(request) == "ip:10.102.17.81"


def test_chat_store_migrates_legacy_owner_keys_that_include_ports(tmp_path: Path) -> None:
    from src.ai.chat_store import AiChatStore

    db_path = tmp_path / "fanban_ai_chat.sqlite3"
    store = AiChatStore(db_path)
    store.initialize()
    conversation = store.create_conversation(
        owner_key="ip:10.102.17.81",
        title="旧会话",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE ai_conversations SET owner_key = ? WHERE conversation_id = ?",
            ("ip:10.102.17.81:65255", conversation.conversation_id),
        )

    restarted_store = AiChatStore(db_path)
    restarted_store.initialize()

    visible = restarted_store.list_conversations("ip:10.102.17.81")
    assert [item.conversation_id for item in visible] == [conversation.conversation_id]
    assert visible[0].owner_key == "ip:10.102.17.81"

    restarted_store.initialize()
    assert len(restarted_store.list_conversations("ip:10.102.17.81")) == 1


def test_chat_runtime_honors_ai_layer_master_switch(tmp_path: Path) -> None:
    from API.app.routers.ai import build_runtime

    from src.config.ai.ai_spec import AiSpec

    spec = AiSpec.model_validate(
        {
            "ai_layer": {
                "enabled": False,
                "chat": {"enabled": True},
            }
        }
    )
    spec.source_path = tmp_path / "参数规范_AI.yaml"

    assert build_runtime(spec).enabled is False


def test_chat_client_rejects_redirects_without_forwarding_authorization() -> None:
    from src.ai.chat_client import ChatClientConfig, ChatGatewayError, OpenAICompatibleChatClient

    captured_authorization: list[str | None] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            captured_authorization.append(self.headers.get("Authorization"))
            body = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "redirected"}}]}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    target_server = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    target_thread = threading.Thread(target=target_server.serve_forever, daemon=True)
    target_thread.start()
    target_url = f"http://127.0.0.1:{target_server.server_port}/capture"

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", target_url)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    redirect_server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    redirect_thread = threading.Thread(target=redirect_server.serve_forever, daemon=True)
    redirect_thread.start()
    client = OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url=f"http://127.0.0.1:{redirect_server.server_port}",
            api_key="redirect-secret",
            authorization_scheme="bearer",
            model="test-model",
            timeout_seconds=2,
            temperature=0.1,
            max_output_tokens=64,
            max_retries=0,
        )
    )

    try:
        with pytest.raises(ChatGatewayError, match="HTTP 302"):
            client.complete([{"role": "user", "content": "test"}])
    finally:
        redirect_server.shutdown()
        redirect_server.server_close()
        target_server.shutdown()
        target_server.server_close()
        redirect_thread.join(timeout=2)
        target_thread.join(timeout=2)

    assert captured_authorization == []


def test_chat_store_keeps_conversations_isolated_by_owner(tmp_path: Path) -> None:
    from src.ai.chat_store import AiChatStore

    store = AiChatStore(tmp_path / "fanban_ai_chat.sqlite3")
    store.initialize()

    first = store.create_conversation(owner_key="ip:10.0.0.1", title="A")
    second = store.create_conversation(owner_key="ip:10.0.0.2", title="B")
    store.add_message(first.conversation_id, "user", "A asks", model_profile="development")
    store.add_message(second.conversation_id, "user", "B asks", model_profile="development")

    assert [item.conversation_id for item in store.list_conversations("ip:10.0.0.1")] == [
        first.conversation_id
    ]
    assert store.get_conversation(first.conversation_id, "ip:10.0.0.1") is not None
    assert store.get_conversation(first.conversation_id, "ip:10.0.0.2") is None
    assert [message.content for message in store.list_messages(first.conversation_id)] == ["A asks"]


def test_chat_store_renames_only_owner_conversation(tmp_path: Path) -> None:
    from src.ai.chat_store import AiChatStore

    store = AiChatStore(tmp_path / "fanban_ai_chat.sqlite3")
    store.initialize()

    conversation = store.create_conversation(owner_key="ip:10.0.0.1", title="旧标题")

    assert store.rename_conversation(
        conversation.conversation_id,
        owner_key="ip:10.0.0.2",
        title="越权标题",
    ) is None

    renamed = store.rename_conversation(
        conversation.conversation_id,
        owner_key="ip:10.0.0.1",
        title="  规则提炼会话  ",
    )

    assert renamed is not None
    assert renamed.title == "规则提炼会话"
    assert store.get_conversation(conversation.conversation_id, "ip:10.0.0.1").title == "规则提炼会话"


def test_chat_store_deletes_only_the_owner_conversation_and_messages(tmp_path: Path) -> None:
    from src.ai.chat_store import AiChatStore

    store = AiChatStore(tmp_path / "fanban_ai_chat.sqlite3")
    store.initialize()
    conversation = store.create_conversation(owner_key="ip:10.0.0.1", title="待删除会话")
    store.add_message(conversation.conversation_id, "user", "需要删除的消息")

    assert store.delete_conversation(conversation.conversation_id, "ip:10.0.0.2") is False
    assert store.get_conversation(conversation.conversation_id, "ip:10.0.0.1") is not None
    assert store.delete_conversation(conversation.conversation_id, "ip:10.0.0.1") is True
    assert store.get_conversation(conversation.conversation_id, "ip:10.0.0.1") is None
    assert store.list_messages(conversation.conversation_id) == []


def test_chat_store_purges_expired_conversations_and_messages(tmp_path: Path) -> None:
    from src.ai.chat_store import AiChatStore

    db_path = tmp_path / "fanban_ai_chat.sqlite3"
    store = AiChatStore(db_path)
    store.initialize()
    owner_key = "ip:10.0.0.1"
    expired = store.create_conversation(owner_key=owner_key, title="已过期")
    current = store.create_conversation(owner_key=owner_key, title="仍保留")
    store.add_message(expired.conversation_id, "user", "旧消息")
    store.add_message(current.conversation_id, "user", "新消息")

    now = datetime(2026, 7, 12, tzinfo=UTC)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE ai_conversations SET updated_at = ? WHERE conversation_id = ?",
            ((now - timedelta(days=31)).isoformat(), expired.conversation_id),
        )

    assert store.purge_expired(retention_days=30, now=now) == 1
    assert [item.conversation_id for item in store.list_conversations(owner_key)] == [
        current.conversation_id
    ]
    assert store.list_messages(expired.conversation_id) == []
    assert [message.content for message in store.list_messages(current.conversation_id)] == ["新消息"]


def test_chat_store_rejects_messages_for_missing_conversations(tmp_path: Path) -> None:
    from src.ai.chat_store import AiChatStore

    store = AiChatStore(tmp_path / "fanban_ai_chat.sqlite3")
    store.initialize()

    with pytest.raises(sqlite3.IntegrityError):
        store.add_message("missing-conversation", "user", "不能成为孤儿消息")


def test_chat_store_commits_user_success_and_assistant_atomically(tmp_path: Path) -> None:
    from src.ai.chat_store import AiChatStore

    db_path = tmp_path / "fanban_ai_chat.sqlite3"
    store = AiChatStore(db_path)
    store.initialize()
    conversation = store.create_conversation(owner_key="ip:10.0.0.8", title="原子交换")
    user_message = store.add_message(
        conversation.conversation_id,
        "user",
        "等待回复",
        metadata={"status": "pending"},
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_assistant_insert
            BEFORE INSERT ON ai_messages
            WHEN NEW.role = 'assistant'
            BEGIN
                SELECT RAISE(ABORT, 'assistant insert rejected');
            END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="assistant insert rejected"):
        store.complete_exchange(
            conversation_id=conversation.conversation_id,
            user_message_id=user_message.message_id,
            user_metadata={"status": "succeeded"},
            assistant_content="不应落库",
            assistant_model_profile="test-profile",
            assistant_metadata={"status": "succeeded"},
        )

    messages = store.list_messages(conversation.conversation_id)
    assert len(messages) == 1
    assert messages[0].metadata == {"status": "pending"}


def test_chat_service_applies_configured_retention_when_initialized(tmp_path: Path) -> None:
    from src.ai.chat_service import AiChatRuntimeConfig, AiChatService
    from src.ai.chat_store import AiChatStore

    class FakeClient:
        def complete(self, _messages: list[dict[str, str]]):
            return type("ChatResult", (), {"content": "ok", "usage": {}})()

    db_path = tmp_path / "fanban_ai_chat.sqlite3"
    store = AiChatStore(db_path)
    store.initialize()
    owner_key = "ip:10.0.0.1"
    expired = store.create_conversation(owner_key=owner_key, title="已过期")
    store.add_message(expired.conversation_id, "user", "旧消息")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE ai_conversations SET updated_at = ? WHERE conversation_id = ?",
            ("2000-01-01T00:00:00+00:00", expired.conversation_id),
        )

    service = AiChatService(
        store=store,
        client=FakeClient(),
        runtime=AiChatRuntimeConfig(retention_days=30),
    )

    assert service.list_conversations(owner_key) == []
    assert store.list_messages(expired.conversation_id) == []


def test_chat_service_sends_recent_history_to_model(tmp_path: Path) -> None:
    from src.ai.chat_service import (
        AiAgentConfig,
        AiChatRuntimeConfig,
        AiChatService,
        AiSkillConfig,
    )
    from src.ai.chat_store import AiChatStore

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, str]]] = []

        def complete(self, messages: list[dict[str, Any]], *, tools=None):
            self.calls.append(messages)
            content = "我已记住 AI-0711" if len(self.calls) == 1 else "你的编号是 AI-0711"
            return type("ChatResult", (), {"content": content, "usage": {}})()

    store = AiChatStore(tmp_path / "fanban_ai_chat.sqlite3")
    store.initialize()
    fake_client = FakeClient()
    service = AiChatService(
        store=store,
        client=fake_client,
        runtime=AiChatRuntimeConfig(
            enabled=True,
            default_agent="platform_assistant",
            max_history_messages=20,
            max_user_message_chars=4000,
            request_timeout_seconds=60,
            retention_days=30,
            max_global_requests=4,
            max_per_owner_requests=1,
            agents=[
                AiAgentConfig(
                    agent_id="platform_assistant",
                    name="出图平台助手",
                    system_prompt="只读回答平台问题。",
                )
            ],
            skills=[
                AiSkillConfig(
                    skill_id="drawing_explain",
                    name="图纸元素解释",
                    description="解释图纸元素。",
                    enabled=True,
                    read_only=True,
                )
            ],
            mcp_servers=[],
            model_profile="development_minimax",
            model_name="MiniMax-M3",
        ),
    )

    conversation = service.create_conversation("ip:127.0.0.1", title="记忆验证")
    first = service.send_message(
        owner_key="ip:127.0.0.1",
        conversation_id=conversation.conversation_id,
        content="请记住我的测试编号是 AI-0711",
        agent_id="platform_assistant",
        skill_ids=["drawing_explain"],
        account_id=None,
    )
    second = service.send_message(
        owner_key="ip:127.0.0.1",
        conversation_id=conversation.conversation_id,
        content="我刚才的测试编号是什么？",
        agent_id="platform_assistant",
        skill_ids=["drawing_explain"],
        account_id=None,
    )

    assert first.assistant_message.content == "我已记住 AI-0711"
    assert second.assistant_message.content == "你的编号是 AI-0711"
    second_call = fake_client.calls[1]
    assert {"role": "user", "content": "请记住我的测试编号是 AI-0711"} in second_call
    assert {"role": "assistant", "content": "我已记住 AI-0711"} in second_call
    assert second.memory["used_history_messages"] == 2


def test_chat_service_runs_same_read_only_tool_loop_for_both_modes(tmp_path: Path) -> None:
    from src.ai.chat_client import ChatCompletionResult, ChatToolCall
    from src.ai.chat_service import AiAgentConfig, AiChatRuntimeConfig, AiChatService
    from src.ai.chat_store import AiChatStore
    from src.ai.read_only_tools import ReadOnlyHostTools
    from src.config.ai.ai_spec import AiReadOnlyHostAccessConfig

    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "README.txt").write_text("后端只读说明", encoding="utf-8")
    tools = ReadOnlyHostTools(
        server_root=tmp_path,
        config=AiReadOnlyHostAccessConfig(allowed_roots=["documents"]),
    )

    class ToolCallingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

        def complete(self, messages, *, tools=None):
            self.calls.append((messages, tools))
            if messages[-1]["role"] == "tool":
                return ChatCompletionResult(content="已读取允许目录中的说明。")
            return ChatCompletionResult(
                content="",
                tool_calls=[
                    ChatToolCall(
                        call_id=f"call-{len(self.calls)}",
                        name="read_text_file",
                        arguments={"root": "documents", "path": "README.txt"},
                        arguments_raw='{"root":"documents","path":"README.txt"}',
                    ),
                ],
            )

    store = AiChatStore(tmp_path / "chat.sqlite3")
    store.initialize()
    client = ToolCallingClient()
    service = AiChatService(
        store=store,
        client=client,
        tools=tools,
        runtime=AiChatRuntimeConfig(
            default_agent="general_assistant",
            agents=[
                AiAgentConfig(
                    agent_id="general_assistant",
                    name="通用对话",
                    system_prompt="可以正常聊天。",
                ),
                AiAgentConfig(
                    agent_id="business_agent",
                    name="业务 Agent",
                    system_prompt="处理全部平台业务。",
                ),
            ],
            max_tool_rounds=3,
        ),
    )

    for agent_id in ("general_assistant", "business_agent"):
        conversation = service.create_conversation("ip:127.0.0.1", title=agent_id)
        exchange = service.send_message(
            owner_key="ip:127.0.0.1",
            conversation_id=conversation.conversation_id,
            content="读取后端 README",
            agent_id=agent_id,
            skill_ids=[],
            account_id=None,
        )

        assert exchange.assistant_message.content == "已读取允许目录中的说明。"
        assert exchange.assistant_message.metadata["tool_calls"] == [
            {
                "name": "read_text_file",
                "ok": True,
                "root": "documents",
                "path": "README.txt",
            },
        ]

    first_tool_result = client.calls[1][0][-1]
    second_tool_result = client.calls[3][0][-1]
    assert first_tool_result["role"] == "tool"
    assert "后端只读说明" in first_tool_result["content"]
    assert second_tool_result["role"] == "tool"
    assert all(call_tools == tools.definitions() for _messages, call_tools in client.calls)


def test_chat_service_records_gateway_failure_without_reusing_it_as_history(
    tmp_path: Path,
) -> None:
    from src.ai.chat_client import ChatGatewayError
    from src.ai.chat_service import AiChatRuntimeConfig, AiChatService
    from src.ai.chat_store import AiChatStore

    class FailOnceClient:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, str]]] = []

        def complete(self, messages: list[dict[str, str]]):
            self.calls.append(messages)
            if len(self.calls) == 1:
                raise ChatGatewayError("temporary gateway failure", status_code=502)
            return type("ChatResult", (), {"content": "第二次成功", "usage": {}})()

    store = AiChatStore(tmp_path / "fanban_ai_chat.sqlite3")
    store.initialize()
    client = FailOnceClient()
    service = AiChatService(
        store=store,
        client=client,
        runtime=AiChatRuntimeConfig(),
    )
    owner_key = "ip:10.0.0.8"
    conversation = service.create_conversation(owner_key, title="失败记忆")

    with pytest.raises(ChatGatewayError):
        service.send_message(
            owner_key=owner_key,
            conversation_id=conversation.conversation_id,
            content="第一次失败的问题",
            agent_id=None,
            skill_ids=[],
            account_id=None,
        )

    failed_message = store.list_messages(conversation.conversation_id)[0]
    assert failed_message.metadata is not None
    assert failed_message.metadata["status"] == "failed"
    assert failed_message.metadata["error_code"] == "ai_gateway_error"

    exchange = service.send_message(
        owner_key=owner_key,
        conversation_id=conversation.conversation_id,
        content="第二次问题",
        agent_id=None,
        skill_ids=[],
        account_id=None,
    )

    assert {"role": "user", "content": "第一次失败的问题"} not in client.calls[1]
    assert exchange.memory["used_history_messages"] == 0
    assert exchange.user_message.metadata is not None
    assert exchange.user_message.metadata["status"] == "succeeded"


def test_chat_service_limits_concurrent_requests_per_owner_across_conversations(
    tmp_path: Path,
) -> None:
    from src.ai.chat_service import (
        AiChatRuntimeConfig,
        AiChatService,
        AiConversationBusy,
    )
    from src.ai.chat_store import AiChatStore

    first_call_started = threading.Event()
    release_first_call = threading.Event()
    call_guard = threading.Lock()
    call_count = 0

    class BlockingFirstClient:
        def complete(self, _messages: list[dict[str, str]]):
            nonlocal call_count
            with call_guard:
                call_count += 1
                current_call = call_count
            if current_call == 1:
                first_call_started.set()
                assert release_first_call.wait(timeout=5)
            return type("ChatResult", (), {"content": "ok", "usage": {}})()

    store = AiChatStore(tmp_path / "fanban_ai_chat.sqlite3")
    store.initialize()
    service = AiChatService(
        store=store,
        client=BlockingFirstClient(),
        runtime=AiChatRuntimeConfig(max_global_requests=4, max_per_owner_requests=1),
    )
    owner_key = "ip:10.0.0.8"
    first = service.create_conversation(owner_key, title="会话一")
    second = service.create_conversation(owner_key, title="会话二")

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            service.send_message,
            owner_key=owner_key,
            conversation_id=first.conversation_id,
            content="第一个请求",
            agent_id=None,
            skill_ids=[],
            account_id=None,
        )
        assert first_call_started.wait(timeout=5)
        try:
            with pytest.raises(AiConversationBusy):
                service.send_message(
                    owner_key=owner_key,
                    conversation_id=second.conversation_id,
                    content="第二个请求",
                    agent_id=None,
                    skill_ids=[],
                    account_id=None,
                )
        finally:
            release_first_call.set()
            pending.result(timeout=5)


def test_chat_service_rejects_clear_while_conversation_is_generating(tmp_path: Path) -> None:
    from src.ai.chat_service import AiChatRuntimeConfig, AiChatService, AiConversationBusy
    from src.ai.chat_store import AiChatStore

    call_started = threading.Event()
    release_call = threading.Event()

    class BlockingClient:
        def complete(self, _messages: list[dict[str, str]]):
            call_started.set()
            assert release_call.wait(timeout=5)
            return type("ChatResult", (), {"content": "完成回复", "usage": {}})()

    store = AiChatStore(tmp_path / "fanban_ai_chat.sqlite3")
    store.initialize()
    owner_key = "ip:10.0.0.8"
    service = AiChatService(
        store=store,
        client=BlockingClient(),
        runtime=AiChatRuntimeConfig(),
    )
    conversation = service.create_conversation(owner_key, title="清空竞态")

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            service.send_message,
            owner_key=owner_key,
            conversation_id=conversation.conversation_id,
            content="正在生成",
            agent_id=None,
            skill_ids=[],
            account_id=None,
        )
        assert call_started.wait(timeout=5)
        try:
            with pytest.raises(AiConversationBusy):
                service.clear_conversation(owner_key, conversation.conversation_id)
        finally:
            release_call.set()
            pending.result(timeout=5)

    assert [message.role for message in store.list_messages(conversation.conversation_id)] == [
        "user",
        "assistant",
    ]


def test_ai_api_exposes_state_and_ip_owned_chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from src.config import SpecLoader, reload_config
    from src.config.ai.ai_spec import AiSpecLoader

    repo_root = Path(__file__).resolve().parents[4]
    ai_spec = tmp_path / "documents" / "AI" / "参数规范_AI.yaml"
    ai_spec.parent.mkdir(parents=True)
    ai_spec.write_text(
        """
schema_version: "0.1"
ai_layer:
  enabled:
    type: bool
    default: true
  chat:
    enabled:
      type: bool
      default: true
    default_agent:
      type: str
      default: "platform_assistant"
    max_history_messages:
      type: int
      default: 20
    max_user_message_chars:
      type: int
      default: 4000
    request_timeout_seconds:
      type: int
      default: 60
    retention_days:
      type: int
      default: 30
    concurrency:
      max_global_requests:
        type: int
        default: 4
      max_per_owner_requests:
        type: int
        default: 1
    agents:
      - agent_id: "platform_assistant"
        name: "出图平台助手"
        system_prompt: "只读回答平台问题。"
    skills:
      - skill_id: "drawing_explain"
        name: "图纸元素解释"
        description: "解释图纸元素。"
        enabled: true
        read_only: true
    mcp_servers: []
  model_gateway:
    base_url:
      type: str
      default: "https://api.example.test/v1"
  models:
    chat:
      model:
        type: str
        default: "MiniMax-M3"
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("FANBAN_SPEC_PATH", str(repo_root / "documents" / "参数规范.yaml"))
    monkeypatch.setenv(
        "FANBAN_RUNTIME_SPEC_PATH",
        str(repo_root / "documents" / "参数规范_运行期.yaml"),
    )
    monkeypatch.setenv("FANBAN_AI_SPEC_PATH", str(ai_spec))
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    SpecLoader.clear_cache()
    AiSpecLoader.clear_cache()
    reload_config()

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, str]]] = []

        def complete(self, messages: list[dict[str, str]], *, tools=None):
            self.calls.append(messages)
            content = "记住了 AI-0711" if len(self.calls) == 1 else "AI-0711"
            return type(
                "ChatResult",
                (),
                {"content": content, "usage": {}, "tool_calls": ()},
            )()

    fake_client = FakeClient()
    monkeypatch.setattr("API.app.routers.ai.build_chat_client", lambda *_args, **_kwargs: fake_client)

    from API.app.main import create_app

    with TestClient(create_app(), client=("10.0.0.8", 50000)) as client:
        state = client.get("/api/ai/state")
        assert state.status_code == 200
        assert state.json()["model"] == "MiniMax-M3"
        assert state.json()["agents"][0]["agent_id"] == "platform_assistant"

        created = client.post("/api/ai/conversations", json={"title": "记忆验证"})
        assert created.status_code == 201
        conversation_id = created.json()["conversation_id"]

        renamed = client.patch(
            f"/api/ai/conversations/{conversation_id}",
            json={"title": "规则提炼会话"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "规则提炼会话"

        first = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "请记住我的测试编号是 AI-0711"},
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/ai/conversations/{conversation_id}/messages",
            json={"content": "我刚才的测试编号是什么？"},
        )
        assert second.status_code == 200
        assert second.json()["assistant_message"]["content"] == "AI-0711"
        assert second.json()["memory"]["used_history_messages"] == 2

    with TestClient(create_app(), client=("10.0.0.9", 50001)) as other_client:
        blocked = other_client.get(f"/api/ai/conversations/{conversation_id}")
        assert blocked.status_code == 404
        blocked_rename = other_client.patch(
            f"/api/ai/conversations/{conversation_id}",
            json={"title": "越权修改"},
        )
        assert blocked_rename.status_code == 404
        blocked_delete = other_client.delete(f"/api/ai/conversations/{conversation_id}")
        assert blocked_delete.status_code == 404

    with TestClient(create_app(), client=("10.0.0.8", 50000)) as owner_client:
        deleted = owner_client.delete(f"/api/ai/conversations/{conversation_id}")
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True}
        assert owner_client.get(f"/api/ai/conversations/{conversation_id}").status_code == 404

    with TestClient(create_app(), client=("10.0.0.10:61001", 50000)) as first_proxy_connection:
        created = first_proxy_connection.post("/api/ai/conversations", json={"title": "端口归一化"})
        assert created.status_code == 201
        proxy_conversation_id = created.json()["conversation_id"]

    with TestClient(create_app(), client=("10.0.0.10:61002", 50000)) as second_proxy_connection:
        listed = second_proxy_connection.get("/api/ai/conversations")
        assert listed.status_code == 200
        assert [item["conversation_id"] for item in listed.json()] == [proxy_conversation_id]
        assert second_proxy_connection.get(f"/api/ai/conversations/{proxy_conversation_id}").status_code == 200


def test_ai_api_busy_response_includes_retry_after_header(tmp_path: Path) -> None:
    from API.app.routers.ai import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.ai.chat_service import AiChatRuntimeConfig, AiChatService
    from src.ai.chat_store import AiChatStore

    class UnusedClient:
        def complete(self, _messages: list[dict[str, str]]):
            raise AssertionError("model client should not run while the global gate is full")

    store = AiChatStore(tmp_path / "fanban_ai_chat.sqlite3")
    store.initialize()
    owner_key = "ip:10.0.0.8"
    conversation = store.create_conversation(owner_key=owner_key, title="繁忙测试")
    service = AiChatService(
        store=store,
        client=UnusedClient(),
        runtime=AiChatRuntimeConfig(max_global_requests=1, max_per_owner_requests=1),
    )
    assert service._global_gate.acquire(blocking=False)
    app = FastAPI()
    app.state.ai_chat_service = service
    app.include_router(router)

    try:
        with TestClient(app, client=("10.0.0.8", 50000)) as client:
            response = client.post(
                f"/api/ai/conversations/{conversation.conversation_id}/messages",
                json={"content": "测试繁忙响应"},
            )
    finally:
        service._global_gate.release()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ai_busy"
    assert response.headers["retry-after"] == "3"


def test_ai_api_does_not_expose_model_gateway_error_details(tmp_path: Path) -> None:
    from API.app.routers.ai import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.ai.chat_client import ChatGatewayError
    from src.ai.chat_service import AiChatRuntimeConfig, AiChatService
    from src.ai.chat_store import AiChatStore

    class FailingClient:
        def complete(self, _messages: list[dict[str, str]]):
            raise ChatGatewayError("upstream echoed api_key=secret-for-test", status_code=502)

    store = AiChatStore(tmp_path / "fanban_ai_chat.sqlite3")
    store.initialize()
    owner_key = "ip:10.0.0.8"
    conversation = store.create_conversation(owner_key=owner_key, title="网关错误测试")
    service = AiChatService(
        store=store,
        client=FailingClient(),
        runtime=AiChatRuntimeConfig(),
    )
    app = FastAPI()
    app.state.ai_chat_service = service
    app.include_router(router)

    with TestClient(app, client=("10.0.0.8", 50000)) as client:
        response = client.post(
            f"/api/ai/conversations/{conversation.conversation_id}/messages",
            json={"content": "触发网关错误"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == {
        "code": "ai_gateway_error",
        "message": "model gateway request failed",
    }
    assert "secret-for-test" not in response.text


def test_ai_service_lazy_initialization_is_singleton_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import API.app.routers.ai as ai_router

    from src.ai.chat_service import AiChatRuntimeConfig

    original_service_type = ai_router.AiChatService
    construction_count = 0
    construction_guard = threading.Lock()
    start_barrier = threading.Barrier(2)

    class FakeClient:
        def complete(self, _messages: list[dict[str, str]]):
            return type("ChatResult", (), {"content": "ok", "usage": {}})()

    class CountingService(original_service_type):
        def __init__(self, **kwargs: Any) -> None:
            nonlocal construction_count
            with construction_guard:
                construction_count += 1
            super().__init__(**kwargs)

    def slow_load_ai_spec(_path: Path) -> object:
        time.sleep(0.08)
        return object()

    monkeypatch.setattr(ai_router, "AiChatService", CountingService)
    monkeypatch.setattr(ai_router, "get_config", lambda: SimpleNamespace(
        ai_spec_path=tmp_path / "参数规范_AI.yaml",
        storage_dir=tmp_path / "storage",
    ))
    monkeypatch.setattr(ai_router, "load_ai_spec", slow_load_ai_spec)
    monkeypatch.setattr(ai_router, "build_chat_client", lambda _spec: FakeClient())
    monkeypatch.setattr(ai_router, "build_runtime", lambda _spec, **_kwargs: AiChatRuntimeConfig())
    monkeypatch.setattr(ai_router, "build_read_only_tools", lambda _spec: None)
    monkeypatch.setattr(ai_router, "build_context_skills", lambda _spec: [])
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    def resolve_service():
        start_barrier.wait(timeout=5)
        return ai_router._service(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        services = list(executor.map(lambda _index: resolve_service(), range(2)))

    assert services[0] is services[1]
    assert construction_count == 1
