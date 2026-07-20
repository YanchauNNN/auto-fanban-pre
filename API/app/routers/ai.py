from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.ai.chat_client import (
    ChatClientConfig,
    ChatClientTimeout,
    ChatGatewayError,
    OpenAICompatibleChatClient,
)
from src.ai.chat_service import (
    AiAgentConfig,
    AiChatBusy,
    AiChatDisabled,
    AiChatRuntimeConfig,
    AiChatService,
    AiChatValidationError,
    AiConversationBusy,
    AiConversationNotFound,
    AiMcpServerConfig,
    AiSkillConfig,
)
from src.ai.chat_store import AiChatMessage, AiChatStore, AiConversation
from src.ai.ansys_mapdl_skill import (
    ANSYS_MAPDL_SKILL_ID,
    AnsysMapdlSkill,
    AnsysMapdlSkillConfig,
    resolve_skill_root,
)
from src.ai.building_standards_skill import (
    BUILDING_STANDARDS_SKILL_ID,
    BuildingStandardsSkill,
    BuildingStandardsSkillConfig,
)
from src.ai.context_skills import ContextSkill
from src.ai.owner_identity import normalize_ip_host
from src.ai.read_only_tools import ReadOnlyHostTools
from src.config import get_config, load_ai_spec
from src.config.ai.ai_spec import AiSpec


logger = logging.getLogger(__name__)
_service_init_lock = threading.Lock()
router = APIRouter(prefix="/api/ai", tags=["ai"])


class CreateConversationPayload(BaseModel):
    title: str | None = None


class UpdateConversationPayload(BaseModel):
    title: str


class SendMessagePayload(BaseModel):
    content: str
    agent_id: str | None = None
    skill_ids: list[str] = Field(default_factory=list)
    mcp_server_ids: list[str] = Field(default_factory=list)


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    owner_key = _owner_key(request)
    service = _service(request)
    return _state_payload(service.state(owner_key))


@router.get("/conversations")
def list_conversations(request: Request) -> list[dict[str, Any]]:
    service = _service(request)
    return [_conversation_payload(item) for item in service.list_conversations(_owner_key(request))]


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: CreateConversationPayload,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    service = _service(request)
    conversation = service.create_conversation(
        _owner_key(request),
        title=payload.title or "新会话",
        account_id=_account_id(request, authorization),
    )
    return _conversation_payload(conversation)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request) -> dict[str, Any]:
    service = _service(request)
    owner_key = _owner_key(request)
    conversation = service.get_conversation(owner_key, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation_not_found")
    return {
        **_conversation_payload(conversation),
        "messages": [_message_payload(message) for message in service.list_messages(owner_key, conversation_id)],
    }


@router.patch("/conversations/{conversation_id}")
def update_conversation(
    conversation_id: str,
    payload: UpdateConversationPayload,
    request: Request,
) -> dict[str, Any]:
    try:
        conversation = _service(request).rename_conversation(
            _owner_key(request),
            conversation_id,
            title=payload.title,
        )
    except AiChatValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AiConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return _conversation_payload(conversation)


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: str,
    payload: SendMessagePayload,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    service = _service(request)
    try:
        exchange = service.send_message(
            owner_key=_owner_key(request),
            conversation_id=conversation_id,
            content=payload.content,
            agent_id=payload.agent_id,
            skill_ids=payload.skill_ids,
            mcp_server_ids=payload.mcp_server_ids,
            account_id=_account_id(request, authorization),
        )
    except AiConversationBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AiChatBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": str(exc)},
            headers={"Retry-After": "3"},
        ) from exc
    except AiChatValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AiConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AiChatDisabled as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ChatClientTimeout as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"code": "ai_timeout", "message": "model gateway timed out"},
        ) from exc
    except ChatGatewayError as exc:
        logger.warning("AI model gateway request failed (status=%s)", exc.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "ai_gateway_error", "message": "model gateway request failed"},
        ) from exc

    return {
        "conversation_id": exchange.conversation_id,
        "user_message": _message_payload(exchange.user_message),
        "assistant_message": _message_payload(exchange.assistant_message),
        "memory": exchange.memory,
    }


@router.post("/conversations/{conversation_id}/clear")
def clear_conversation(conversation_id: str, request: Request) -> dict[str, bool]:
    try:
        _service(request).clear_conversation(_owner_key(request), conversation_id)
    except AiConversationBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AiConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return {"ok": True}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request) -> dict[str, bool]:
    try:
        _service(request).delete_conversation(_owner_key(request), conversation_id)
    except AiConversationBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AiConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return {"ok": True}


def build_chat_client(spec: AiSpec) -> OpenAICompatibleChatClient:
    gateway = spec.resolve_gateway()
    models = spec.resolve_models()
    chat = spec.ai_layer.chat
    return OpenAICompatibleChatClient(
        ChatClientConfig(
            base_url=gateway.base_url,
            api_key=gateway.api_key,
            authorization_scheme=gateway.authorization_scheme,
            model=models.chat.model,
            timeout_seconds=chat.request_timeout_seconds,
            temperature=models.chat.temperature,
            max_output_tokens=models.chat.max_output_tokens,
            max_retries=0,
            retry_backoff_ms=gateway.retry_backoff_ms,
        )
    )


def build_runtime(
    spec: AiSpec,
    *,
    available_skill_ids: set[str] | None = None,
) -> AiChatRuntimeConfig:
    chat = spec.ai_layer.chat
    models = spec.resolve_models()
    return AiChatRuntimeConfig(
        enabled=bool(spec.ai_layer.enabled and chat.enabled),
        default_agent=chat.default_agent,
        max_history_messages=chat.max_history_messages,
        max_user_message_chars=chat.max_user_message_chars,
        request_timeout_seconds=chat.request_timeout_seconds,
        retention_days=chat.retention_days,
        max_global_requests=chat.concurrency.max_global_requests,
        max_per_owner_requests=chat.concurrency.max_per_owner_requests,
        max_tool_rounds=chat.read_only_host_access.max_tool_rounds,
        response_format_prompt=(
            chat.response_format.system_prompt_suffix
            if chat.response_format.enabled
            else ""
        ),
        agents=[
            AiAgentConfig(
                agent_id=agent.agent_id,
                name=agent.name,
                description=agent.description,
                system_prompt=agent.system_prompt,
            )
            for agent in chat.agents
        ],
        skills=[
            AiSkillConfig(
                skill_id=skill.skill_id,
                name=skill.name,
                description=skill.description,
                enabled=skill.enabled,
                read_only=skill.read_only,
                handler=skill.handler,
                auto_trigger=skill.auto_trigger,
                available=skill.skill_id in (available_skill_ids or set()),
            )
            for skill in chat.skills
        ],
        mcp_servers=[
            AiMcpServerConfig(
                server_id=server.server_id,
                name=server.name,
                description=server.description,
                enabled=server.enabled,
                read_only=server.read_only,
                transport=server.transport,
                endpoint=server.endpoint,
            )
            for server in chat.mcp_servers
        ],
        model_profile=spec.resolve_gateway_profile_name(),
        model_name=models.chat.model,
    )


def build_context_skills(spec: AiSpec) -> list[ContextSkill]:
    source_path = spec.source_path
    if source_path is None or len(source_path.resolve().parents) < 3:
        return []
    server_root = source_path.resolve().parents[2]
    result: list[ContextSkill] = []
    ansys_defaults = AnsysMapdlSkillConfig()
    standards_defaults = BuildingStandardsSkillConfig()
    for skill in spec.ai_layer.chat.skills:
        if not skill.enabled:
            continue
        root = resolve_skill_root(server_root, skill.root, skill.root_env_var)
        if skill.handler == ANSYS_MAPDL_SKILL_ID:
            result.append(
                AnsysMapdlSkill(
                    root=root,
                    config=AnsysMapdlSkillConfig(
                        skill_id=skill.skill_id,
                        auto_trigger=skill.auto_trigger,
                        trigger_terms=(
                            tuple(skill.trigger_terms)
                            or ansys_defaults.trigger_terms
                        ),
                        max_results=skill.max_results,
                        max_context_chars=skill.max_context_chars,
                        query_timeout_seconds=skill.query_timeout_seconds,
                        history_followup_messages=skill.history_followup_messages,
                    ),
                )
            )
        elif skill.handler == BUILDING_STANDARDS_SKILL_ID:
            result.append(
                BuildingStandardsSkill(
                    root=root,
                    config=BuildingStandardsSkillConfig(
                        skill_id=skill.skill_id,
                        auto_trigger=skill.auto_trigger,
                        trigger_terms=(
                            tuple(skill.trigger_terms)
                            or standards_defaults.trigger_terms
                        ),
                        max_results=skill.max_results,
                        max_context_chars=skill.max_context_chars,
                        query_timeout_seconds=skill.query_timeout_seconds,
                        history_followup_messages=skill.history_followup_messages,
                    ),
                )
            )
    return result


def build_read_only_tools(spec: AiSpec) -> ReadOnlyHostTools | None:
    source_path = spec.source_path
    access = spec.ai_layer.chat.read_only_host_access
    if not access.enabled or source_path is None or len(source_path.resolve().parents) < 3:
        return None
    server_root = source_path.resolve().parents[2]
    tools = ReadOnlyHostTools(server_root=server_root, config=access)
    return tools if tools.definitions() else None


def _service(request: Request) -> AiChatService:
    existing = getattr(request.app.state, "ai_chat_service", None)
    if isinstance(existing, AiChatService):
        return existing

    with _service_init_lock:
        existing = getattr(request.app.state, "ai_chat_service", None)
        if isinstance(existing, AiChatService):
            return existing

        runtime_config = get_config()
        spec = load_ai_spec(runtime_config.ai_spec_path)
        store = AiChatStore(runtime_config.storage_dir / "ai" / "chat" / "fanban_ai_chat.sqlite3")
        store.initialize()
        context_skills = build_context_skills(spec)
        service = AiChatService(
            store=store,
            client=build_chat_client(spec),
            runtime=build_runtime(
                spec,
                available_skill_ids={
                    skill.skill_id
                    for skill in context_skills
                    if bool(getattr(skill, "available", False))
                },
            ),
            tools=build_read_only_tools(spec),
            context_skills=context_skills,
        )
        request.app.state.ai_chat_service = service
        return service


def _owner_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return f"ip:{normalize_ip_host(host)}"


def _account_id(request: Request, authorization: str | None) -> str | None:
    management = getattr(request.app.state, "management", None)
    if management is None or not authorization:
        return None
    account = management.session_service.resolve_account(authorization)
    return getattr(account, "account_id", None) if account is not None else None


def _state_payload(state) -> dict[str, Any]:
    return {
        "enabled": state.enabled,
        "profile": state.profile,
        "model": state.model,
        "owner_key": state.owner_key,
        "default_agent": state.default_agent,
        "agents": [
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "description": agent.description,
            }
            for agent in state.agents
        ],
        "skills": [
            {
                "skill_id": skill.skill_id,
                "name": skill.name,
                "description": skill.description,
                "enabled": skill.enabled,
                "read_only": skill.read_only,
                "auto_trigger": skill.auto_trigger,
                "available": skill.available,
            }
            for skill in state.skills
        ],
        "mcp_servers": [
            {
                "server_id": server.server_id,
                "name": server.name,
                "description": server.description,
                "enabled": server.enabled,
                "read_only": server.read_only,
                "transport": server.transport,
            }
            for server in state.mcp_servers
        ],
    }


def _conversation_payload(conversation: AiConversation) -> dict[str, Any]:
    return {
        "conversation_id": conversation.conversation_id,
        "title": conversation.title,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "message_count": conversation.message_count,
    }


def _message_payload(message: AiChatMessage) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "model_profile": message.model_profile,
        "metadata": message.metadata or {},
    }
