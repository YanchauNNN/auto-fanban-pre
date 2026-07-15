from __future__ import annotations

import threading
from dataclasses import dataclass, field
from time import perf_counter
from typing import Protocol
from weakref import WeakValueDictionary

from pydantic import BaseModel, Field

from .chat_client import ChatClientTimeout, ChatGatewayError
from .chat_store import AiChatMessage, AiChatStore, AiConversation


class AiChatError(RuntimeError):
    code = "ai_chat_error"


class AiChatDisabled(AiChatError):
    code = "ai_disabled"


class AiConversationNotFound(AiChatError):
    code = "conversation_not_found"


class AiConversationBusy(AiChatError):
    code = "conversation_busy"


class AiChatBusy(AiChatError):
    code = "ai_busy"


class AiChatValidationError(AiChatError):
    code = "ai_validation_error"


class ChatClientProtocol(Protocol):
    def complete(self, messages: list[dict[str, str]]): ...


class AiAgentConfig(BaseModel):
    agent_id: str
    name: str
    description: str = ""
    system_prompt: str = ""


class AiSkillConfig(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    enabled: bool = True
    read_only: bool = True


class AiMcpServerConfig(BaseModel):
    server_id: str
    name: str
    description: str = ""
    enabled: bool = False
    read_only: bool = True
    transport: str = "disabled"
    endpoint: str = ""


class AiChatRuntimeConfig(BaseModel):
    enabled: bool = True
    default_agent: str = "platform_assistant"
    max_history_messages: int = 20
    max_user_message_chars: int = 4000
    request_timeout_seconds: int = 60
    retention_days: int = 30
    max_global_requests: int = 4
    max_per_owner_requests: int = 1
    agents: list[AiAgentConfig] = Field(default_factory=list)
    skills: list[AiSkillConfig] = Field(default_factory=list)
    mcp_servers: list[AiMcpServerConfig] = Field(default_factory=list)
    model_profile: str = ""
    model_name: str = ""


@dataclass(frozen=True)
class AiChatExchange:
    conversation_id: str
    user_message: AiChatMessage
    assistant_message: AiChatMessage
    memory: dict[str, int]


@dataclass(frozen=True)
class AiChatState:
    enabled: bool
    profile: str
    model: str
    owner_key: str
    default_agent: str
    agents: list[AiAgentConfig] = field(default_factory=list)
    skills: list[AiSkillConfig] = field(default_factory=list)
    mcp_servers: list[AiMcpServerConfig] = field(default_factory=list)


class AiChatService:
    def __init__(
        self,
        *,
        store: AiChatStore,
        client: ChatClientProtocol,
        runtime: AiChatRuntimeConfig,
    ) -> None:
        self.store = store
        self.client = client
        self.runtime = runtime
        self._global_gate = threading.BoundedSemaphore(max(int(runtime.max_global_requests), 1))
        self._conversation_locks: WeakValueDictionary[str, threading.Lock] = WeakValueDictionary()
        self._locks_guard = threading.Lock()
        self._owner_gates: WeakValueDictionary[str, threading.BoundedSemaphore] = WeakValueDictionary()
        self._owner_gates_guard = threading.Lock()
        self.store.purge_expired(retention_days=self.runtime.retention_days)

    def state(self, owner_key: str) -> AiChatState:
        return AiChatState(
            enabled=self.runtime.enabled,
            profile=self.runtime.model_profile,
            model=self.runtime.model_name,
            owner_key=owner_key,
            default_agent=self.runtime.default_agent,
            agents=self.runtime.agents,
            skills=self.runtime.skills,
            mcp_servers=self.runtime.mcp_servers,
        )

    def create_conversation(
        self,
        owner_key: str,
        *,
        title: str = "新会话",
        account_id: str | None = None,
    ) -> AiConversation:
        self._ensure_enabled()
        return self.store.create_conversation(owner_key=owner_key, title=title, account_id=account_id)

    def list_conversations(self, owner_key: str) -> list[AiConversation]:
        self._ensure_enabled()
        self.store.purge_expired(retention_days=self.runtime.retention_days)
        return self.store.list_conversations(owner_key)

    def get_conversation(self, owner_key: str, conversation_id: str) -> AiConversation | None:
        self._ensure_enabled()
        return self.store.get_conversation(conversation_id, owner_key)

    def rename_conversation(
        self,
        owner_key: str,
        conversation_id: str,
        *,
        title: str,
    ) -> AiConversation:
        self._ensure_enabled()
        normalized_title = title.strip()
        if not normalized_title:
            raise AiChatValidationError("conversation title is required")
        renamed = self.store.rename_conversation(
            conversation_id,
            owner_key=owner_key,
            title=normalized_title[:80],
        )
        if renamed is None:
            raise AiConversationNotFound("conversation not found")
        return renamed

    def list_messages(self, owner_key: str, conversation_id: str) -> list[AiChatMessage]:
        self._ensure_enabled()
        if self.store.get_conversation(conversation_id, owner_key) is None:
            raise AiConversationNotFound("conversation not found")
        return self.store.list_messages(conversation_id)

    def clear_conversation(self, owner_key: str, conversation_id: str) -> None:
        self._ensure_enabled()
        conversation_lock = self._lock_for_conversation(conversation_id)
        if not conversation_lock.acquire(blocking=False):
            raise AiConversationBusy("conversation has an active AI request")
        try:
            if not self.store.clear_conversation(conversation_id, owner_key):
                raise AiConversationNotFound("conversation not found")
        finally:
            conversation_lock.release()

    def delete_conversation(self, owner_key: str, conversation_id: str) -> None:
        self._ensure_enabled()
        conversation_lock = self._lock_for_conversation(conversation_id)
        if not conversation_lock.acquire(blocking=False):
            raise AiConversationBusy("conversation has an active AI request")
        try:
            if not self.store.delete_conversation(conversation_id, owner_key):
                raise AiConversationNotFound("conversation not found")
        finally:
            conversation_lock.release()

    def send_message(
        self,
        *,
        owner_key: str,
        conversation_id: str,
        content: str,
        agent_id: str | None,
        skill_ids: list[str] | None,
        account_id: str | None,
        mcp_server_ids: list[str] | None = None,
    ) -> AiChatExchange:
        self._ensure_enabled()
        normalized_content = content.strip()
        if not normalized_content:
            raise AiChatValidationError("message content is required")
        if len(normalized_content) > self.runtime.max_user_message_chars:
            raise AiChatValidationError("message content is too long")
        conversation = self.store.get_conversation(conversation_id, owner_key)
        if conversation is None:
            raise AiConversationNotFound("conversation not found")

        conversation_lock = self._lock_for_conversation(conversation_id)
        if not conversation_lock.acquire(blocking=False):
            raise AiConversationBusy("conversation has an active AI request")
        owner_gate = self._gate_for_owner(owner_key)
        owner_acquired = False
        global_acquired = False
        try:
            owner_acquired = owner_gate.acquire(blocking=False)
            if not owner_acquired:
                raise AiConversationBusy("owner has an active AI request")
            global_acquired = self._global_gate.acquire(blocking=False)
            if not global_acquired:
                raise AiChatBusy("AI model gateway is busy")

            history = self.store.list_messages(
                conversation_id,
                limit=self.runtime.max_history_messages,
            )
            resolved_agent = self._resolve_agent(agent_id)
            user_metadata = {
                "agent_id": resolved_agent.agent_id,
                "skill_ids": skill_ids or [],
                "mcp_server_ids": mcp_server_ids or [],
                "account_id": account_id,
                "status": "pending",
            }
            user_message = self.store.add_message(
                conversation_id,
                "user",
                normalized_content,
                model_profile=self.runtime.model_profile,
                metadata=user_metadata,
            )
            model_messages = self._build_model_messages(
                history,
                normalized_content,
                agent_id=agent_id,
                skill_ids=skill_ids or [],
                mcp_server_ids=mcp_server_ids or [],
            )
            started_at = perf_counter()
            try:
                result = self.client.complete(model_messages)
            except Exception as exc:
                failed_metadata = {
                    **user_metadata,
                    "status": "failed",
                    "error_code": _chat_failure_code(exc),
                    "duration_ms": round((perf_counter() - started_at) * 1000),
                }
                self.store.update_message_metadata(user_message.message_id, failed_metadata)
                raise
            duration_ms = round((perf_counter() - started_at) * 1000)
            user_message, assistant_message = self.store.complete_exchange(
                conversation_id=conversation_id,
                user_message_id=user_message.message_id,
                user_metadata={
                    **user_metadata,
                    "status": "succeeded",
                    "duration_ms": duration_ms,
                },
                assistant_content=str(result.content),
                assistant_model_profile=self.runtime.model_profile,
                assistant_metadata={
                    "usage": getattr(result, "usage", {}) or {},
                    "agent_id": resolved_agent.agent_id,
                    "skill_ids": skill_ids or [],
                    "mcp_server_ids": mcp_server_ids or [],
                    "status": "succeeded",
                    "duration_ms": duration_ms,
                },
            )
            used_history = [message for message in history if _is_usable_history_message(message)]
            return AiChatExchange(
                conversation_id=conversation.conversation_id,
                user_message=user_message,
                assistant_message=assistant_message,
                memory={"used_history_messages": len(used_history)},
            )
        finally:
            if global_acquired:
                self._global_gate.release()
            if owner_acquired:
                owner_gate.release()
            conversation_lock.release()

    def _ensure_enabled(self) -> None:
        if not self.runtime.enabled:
            raise AiChatDisabled("AI chat is disabled")

    def _lock_for_conversation(self, conversation_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._conversation_locks.get(conversation_id)
            if lock is None:
                lock = threading.Lock()
                self._conversation_locks[conversation_id] = lock
            return lock

    def _gate_for_owner(self, owner_key: str) -> threading.BoundedSemaphore:
        with self._owner_gates_guard:
            gate = self._owner_gates.get(owner_key)
            if gate is None:
                gate = threading.BoundedSemaphore(max(int(self.runtime.max_per_owner_requests), 1))
                self._owner_gates[owner_key] = gate
            return gate

    def _build_model_messages(
        self,
        history: list[AiChatMessage],
        current_content: str,
        *,
        agent_id: str | None,
        skill_ids: list[str],
        mcp_server_ids: list[str],
    ) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": self._system_prompt(agent_id, skill_ids, mcp_server_ids)}]
        for message in history:
            if not _is_usable_history_message(message):
                continue
            messages.append({"role": message.role, "content": message.content})
        messages.append({"role": "user", "content": current_content})
        return messages

    def _system_prompt(
        self,
        agent_id: str | None,
        skill_ids: list[str],
        mcp_server_ids: list[str],
    ) -> str:
        agent = self._resolve_agent(agent_id)
        skills = self._resolve_skills(skill_ids)
        mcp_servers = self._resolve_mcp_servers(mcp_server_ids)
        skill_text = "\n".join(
            f"- {skill.name}: {skill.description or '只读能力'}" for skill in skills
        )
        mcp_text = "\n".join(
            f"- {server.name}: {'启用' if server.enabled else '未启用'}，只读={server.read_only}"
            for server in mcp_servers
        )
        return "\n".join(
            part
            for part in [
                agent.system_prompt or f"你是{agent.name}。",
                "你只能进行只读问答和解释，不得声称已经修改 DWG、YAML、任务、流程或文件。",
                "如果缺少证据或上下文，明确说明需要用户补充信息。",
                "回答使用中文，保持简洁、可复核。",
                f"当前智能体: {agent.name}",
                f"已选技能:\n{skill_text}" if skill_text else "已选技能: 无",
                f"MCP 注册能力:\n{mcp_text}" if mcp_text else "MCP 注册能力: 第一版未启用外部工具执行。",
            ]
            if part
        )

    def _resolve_agent(self, agent_id: str | None) -> AiAgentConfig:
        target = agent_id or self.runtime.default_agent
        for agent in self.runtime.agents:
            if agent.agent_id == target:
                return agent
        if self.runtime.agents:
            return self.runtime.agents[0]
        return AiAgentConfig(
            agent_id="platform_assistant",
            name="出图平台助手",
            system_prompt="你是出图平台的只读 AI 助手。",
        )

    def _resolve_skills(self, skill_ids: list[str]) -> list[AiSkillConfig]:
        selected = set(skill_ids)
        skills = [skill for skill in self.runtime.skills if skill.enabled and skill.skill_id in selected]
        if skills:
            return skills
        return [skill for skill in self.runtime.skills if skill.enabled and skill.read_only][:1]

    def _resolve_mcp_servers(self, mcp_server_ids: list[str]) -> list[AiMcpServerConfig]:
        selected = set(mcp_server_ids)
        return [
            server
            for server in self.runtime.mcp_servers
            if server.server_id in selected or (server.enabled and not selected)
        ]


def _is_usable_history_message(message: AiChatMessage) -> bool:
    if message.role not in {"user", "assistant"}:
        return False
    status = (message.metadata or {}).get("status")
    return status not in {"pending", "failed"}


def _chat_failure_code(exc: Exception) -> str:
    if isinstance(exc, ChatClientTimeout):
        return "ai_timeout"
    if isinstance(exc, ChatGatewayError):
        return "ai_gateway_error"
    return "ai_chat_error"
