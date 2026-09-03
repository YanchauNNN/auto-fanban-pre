from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import fitz
from fastapi import (
    APIRouter,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

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
    BuildingStandardsSkillError,
)
from src.ai.chat_client import (
    ChatClientTimeout,
    ChatGatewayError,
    build_chat_client,
)
from src.ai.chat_service import (
    AiAgentConfig,
    AiAttachmentRuntimeConfig,
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
from src.ai.context_skills import ContextSkill
from src.ai.owner_identity import resolve_client_ip
from src.ai.read_only_tools import ReadOnlyHostTools
from src.ai.reinforcement_table_skill import (
    REINFORCEMENT_TABLE_SKILL_ID,
    ReinforcementTableSkill,
    ReinforcementTableSkillConfig,
)
from src.ai.standards_source_resolver import (
    StandardsSourceInvalid,
    StandardsSourceNotFound,
)
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
    content: str = ""
    agent_id: str | None = None
    skill_ids: list[str] = Field(default_factory=list)
    mcp_server_ids: list[str] = Field(default_factory=list)
    attachment_ids: list[str] = Field(default_factory=list)


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    owner_key = _owner_key(request)
    service = _service(request)
    return _state_payload(service.state(owner_key))


@router.get("/conversations")
def list_conversations(request: Request) -> list[dict[str, Any]]:
    service = _service(request)
    return [
        _conversation_payload(item)
        for item in service.list_conversations(_owner_key(request))
    ]


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation_not_found"
        )
    return {
        **_conversation_payload(conversation),
        "messages": [
            _message_payload(message)
            for message in service.list_messages(owner_key, conversation_id)
        ],
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


@router.post(
    "/conversations/{conversation_id}/attachments",
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    conversation_id: str,
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency declaration
) -> dict[str, Any]:
    service = _service(request)
    max_upload_bytes = (
        max(
            service.runtime.attachments.max_image_size_mb,
            service.runtime.attachments.max_file_size_mb,
        )
        * 1024
        * 1024
    )
    content = await file.read(max_upload_bytes + 1)
    await file.close()
    if len(content) > max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "attachment_too_large",
                "message": "attachment is too large",
            },
        )
    try:
        attachment = await run_in_threadpool(
            service.upload_attachment,
            owner_key=_owner_key(request),
            conversation_id=conversation_id,
            original_name=file.filename or "attachment",
            media_type=file.content_type or "application/octet-stream",
            content=content,
        )
    except AiConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except AiChatValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return _attachment_payload(attachment)


@router.get("/conversations/{conversation_id}/attachments")
def list_attachments(conversation_id: str, request: Request) -> list[dict[str, Any]]:
    try:
        attachments = _service(request).list_attachments(
            _owner_key(request),
            conversation_id,
        )
    except AiConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return [_attachment_payload(attachment) for attachment in attachments]


@router.delete("/conversations/{conversation_id}/attachments/{attachment_id}")
def delete_attachment(
    conversation_id: str,
    attachment_id: str,
    request: Request,
) -> dict[str, bool]:
    try:
        _service(request).delete_attachment(
            _owner_key(request),
            conversation_id,
            attachment_id,
        )
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
            attachment_ids=payload.attachment_ids,
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
            detail={
                "code": "ai_gateway_error",
                "message": "model gateway request failed",
            },
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


@router.get("/standards/{source_id}/page/{page_number}")
def get_standard_page(
    source_id: int,
    page_number: int,
    request: Request,
) -> Response:
    skill = _building_standards_skill(request)
    if not skill.config.preview_enabled:
        raise _standards_http_error(
            status.HTTP_403_FORBIDDEN,
            "standard_preview_disabled",
            "standard preview is disabled",
        )
    resolved = _resolve_standard_source(skill, source_id)
    try:
        with fitz.open(resolved.path) as document:
            if page_number < 1 or page_number > document.page_count:
                raise _standards_http_error(
                    status.HTTP_404_NOT_FOUND,
                    "standard_page_not_found",
                    "standard page was not found",
                )
            page = document.load_page(page_number - 1)
            scale = skill.config.page_render_dpi / 72.0
            pixel_count = page.rect.width * scale * page.rect.height * scale
            if pixel_count > 40_000_000:
                raise _standards_http_error(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "standard_page_too_large",
                    "standard page is too large to render",
                )
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            content = pixmap.tobytes("png")
    except HTTPException:
        raise
    except (RuntimeError, ValueError) as exc:
        logger.warning("Unable to render standard page source_id=%s", source_id)
        raise _standards_http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "standard_page_render_failed",
            "standard page could not be rendered",
        ) from exc
    return Response(
        content=content,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "X-Standard-Source-Root": resolved.root_kind,
        },
    )


@router.get("/standards/{source_id}/document")
def get_standard_document(source_id: int, request: Request) -> FileResponse:
    skill = _building_standards_skill(request)
    if not skill.config.preview_enabled:
        raise _standards_http_error(
            status.HTTP_403_FORBIDDEN,
            "standard_preview_disabled",
            "standard preview is disabled",
        )
    resolved = _resolve_standard_source(skill, source_id)
    return _standard_file_response(resolved.path, disposition="inline")


@router.get("/standards/{source_id}/download")
def download_standard_document(source_id: int, request: Request) -> FileResponse:
    skill = _building_standards_skill(request)
    if not skill.config.download_enabled:
        raise _standards_http_error(
            status.HTTP_403_FORBIDDEN,
            "standard_download_disabled",
            "standard download is disabled",
        )
    resolved = _resolve_standard_source(skill, source_id)
    return _standard_file_response(resolved.path, disposition="attachment")


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
        attachments=AiAttachmentRuntimeConfig.model_validate(
            chat.attachments.model_dump()
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
    reinforcement_defaults = ReinforcementTableSkillConfig()
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
                            tuple(skill.trigger_terms) or ansys_defaults.trigger_terms
                        ),
                        max_results=skill.max_results,
                        max_context_chars=skill.max_context_chars,
                        query_timeout_seconds=skill.query_timeout_seconds,
                        history_followup_messages=skill.history_followup_messages,
                    ),
                )
            )
        elif skill.handler == BUILDING_STANDARDS_SKILL_ID:
            if not root.is_dir() and not os.environ.get(skill.root_env_var, "").strip():
                development_root = (
                    server_root / "tools" / "ai" / "building-structure-standards"
                )
                if development_root.is_dir():
                    root = development_root.resolve()
            source_access = skill.source_access
            source_root = _resolve_configured_path(
                server_root,
                source_access.primary_root,
                source_access.primary_root_env_var,
            )
            fallback_roots = _resolve_configured_paths(
                server_root,
                source_access.fallback_roots,
                source_access.fallback_roots_env_var,
            )
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
                        source_root=source_root,
                        fallback_source_roots=fallback_roots,
                        per_file_fallback=source_access.per_file_fallback,
                        preview_enabled=source_access.preview_enabled,
                        download_enabled=source_access.download_enabled,
                        model_page_images_enabled=(
                            source_access.model_page_images_enabled
                        ),
                        page_render_dpi=source_access.page_render_dpi,
                        max_model_page_images=source_access.max_model_page_images,
                        verify_source_sha256=source_access.verify_sha256,
                    ),
                )
            )
        elif skill.handler == REINFORCEMENT_TABLE_SKILL_ID:
            result.append(
                ReinforcementTableSkill(
                    root=root,
                    config=ReinforcementTableSkillConfig(
                        skill_id=skill.skill_id,
                        auto_trigger=skill.auto_trigger,
                        trigger_terms=(
                            tuple(skill.trigger_terms)
                            or reinforcement_defaults.trigger_terms
                        ),
                        max_results=skill.max_results,
                        max_context_chars=skill.max_context_chars,
                        history_followup_messages=skill.history_followup_messages,
                    ),
                )
            )
    return result


def _resolve_configured_path(
    server_root: Path,
    configured: str,
    env_var: str,
) -> Path | None:
    override = os.environ.get(env_var, "").strip() if env_var else ""
    value = override or str(configured or "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = server_root / path
    return path.resolve(strict=False)


def _resolve_configured_paths(
    server_root: Path,
    configured: list[str],
    env_var: str,
) -> tuple[Path, ...]:
    override = os.environ.get(env_var, "").strip() if env_var else ""
    values = [item.strip() for item in override.split(os.pathsep) if item.strip()]
    if not values:
        values = [str(item).strip() for item in configured if str(item).strip()]
    return tuple(
        path
        for value in values
        if (path := _resolve_configured_path(server_root, value, "")) is not None
    )


def build_read_only_tools(spec: AiSpec) -> ReadOnlyHostTools | None:
    source_path = spec.source_path
    access = spec.ai_layer.chat.read_only_host_access
    if (
        not access.enabled
        or source_path is None
        or len(source_path.resolve().parents) < 3
    ):
        return None
    server_root = source_path.resolve().parents[2]
    tools = ReadOnlyHostTools(server_root=server_root, config=access)
    return tools if tools.definitions() else None


def _building_standards_skill(request: Request) -> BuildingStandardsSkill:
    for context_skill in _service(request).context_skills:
        if isinstance(context_skill, BuildingStandardsSkill):
            return context_skill
    raise _standards_http_error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "standards_skill_unavailable",
        "building standards skill is unavailable",
    )


def _resolve_standard_source(
    skill: BuildingStandardsSkill,
    source_id: int,
):
    try:
        resolved = skill.resolve_source(source_id)
    except StandardsSourceNotFound as exc:
        raise _standards_http_error(
            status.HTTP_404_NOT_FOUND,
            "standard_source_not_found",
            "standard source file was not found",
        ) from exc
    except (StandardsSourceInvalid, BuildingStandardsSkillError) as exc:
        raise _standards_http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "standard_source_invalid",
            "standard source file is invalid or unavailable",
        ) from exc
    if resolved is None:
        raise _standards_http_error(
            status.HTTP_404_NOT_FOUND,
            "standard_source_not_found",
            "standard source record was not found",
        )
    return resolved


def _standard_file_response(path: Path, *, disposition: str) -> FileResponse:
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type=disposition,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
        },
    )


def _standards_http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


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
        store = AiChatStore(
            runtime_config.storage_dir / "ai" / "chat" / "fanban_ai_chat.sqlite3"
        )
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
    forwarded_for = request.headers.get("x-forwarded-for")
    return f"ip:{resolve_client_ip(host, forwarded_for)}"


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
        "attachments": {
            "enabled": state.attachments.enabled,
            "allowed_extensions": state.attachments.allowed_extensions,
            "max_files_per_message": state.attachments.max_files_per_message,
            "max_image_size_mb": state.attachments.max_image_size_mb,
            "max_file_size_mb": state.attachments.max_file_size_mb,
            "max_total_size_mb_per_message": (
                state.attachments.max_total_size_mb_per_message
            ),
        },
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


def _attachment_payload(attachment) -> dict[str, Any]:
    return {
        "attachment_id": attachment.attachment_id,
        "conversation_id": attachment.conversation_id,
        "message_id": attachment.message_id,
        "original_name": attachment.original_name,
        "media_type": attachment.media_type,
        "kind": attachment.kind,
        "size_bytes": attachment.size_bytes,
        "sha256": attachment.sha256,
        "status": attachment.status,
        "metadata": attachment.metadata,
        "error_code": attachment.error_code,
        "created_at": attachment.created_at,
    }
