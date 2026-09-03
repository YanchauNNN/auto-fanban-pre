from __future__ import annotations

import sqlite3
from pathlib import Path

import fitz
from API.app.routers.ai import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai.building_standards_skill import (
    BuildingStandardsSkill,
    BuildingStandardsSkillConfig,
)
from src.ai.chat_service import AiChatRuntimeConfig, AiChatService
from src.ai.chat_store import AiChatStore


class _UnusedClient:
    def complete(self, _messages):
        raise AssertionError("model client must not run for document endpoints")


def _build_client(
    tmp_path: Path,
    *,
    preview_enabled: bool = True,
    download_enabled: bool = True,
) -> TestClient:
    source_root = tmp_path / "documents" / "规范下载"
    source_path = source_root / "结构" / "GB 50000-2026 测试规范.pdf"
    source_path.parent.mkdir(parents=True)
    document = fitz.open()
    page = document.new_page(width=200, height=300)
    page.insert_text((30, 40), "page one")
    page = document.new_page(width=200, height=300)
    page.insert_text((30, 40), "page two")
    document.save(source_path)
    document.close()

    skill_root = tmp_path / "skill"
    database = skill_root / "assets" / "data" / "standards.sqlite"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE sources (
                source_id INTEGER PRIMARY KEY,
                standard_code TEXT NOT NULL,
                standard_name TEXT NOT NULL,
                version TEXT NOT NULL,
                major TEXT NOT NULL,
                official_status TEXT NOT NULL,
                replacement_standard TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                official_source_url TEXT NOT NULL,
                authorization TEXT NOT NULL,
                confidentiality TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO sources VALUES (
                7, 'GB 50000-2026', '测试规范', '2026', '建筑结构', '现行', '',
                '结构/GB 50000-2026 测试规范.pdf', '', '', '内部授权', '内部'
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    skill = BuildingStandardsSkill(
        root=skill_root,
        config=BuildingStandardsSkillConfig(
            source_root=source_root,
            preview_enabled=preview_enabled,
            download_enabled=download_enabled,
            page_render_dpi=96,
        ),
    )
    store = AiChatStore(tmp_path / "chat.sqlite3")
    store.initialize()
    service = AiChatService(
        store=store,
        client=_UnusedClient(),
        runtime=AiChatRuntimeConfig(),
        context_skills=[skill],
    )
    app = FastAPI()
    app.state.ai_chat_service = service
    app.include_router(router)
    return TestClient(app, client=("10.0.0.8", 50000))


def test_standard_page_document_and_download_are_served_by_source_id(
    tmp_path: Path,
) -> None:
    with _build_client(tmp_path) as client:
        page = client.get("/api/ai/standards/7/page/2")
        document = client.get("/api/ai/standards/7/document")
        download = client.get("/api/ai/standards/7/download")

    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert page.content.startswith(b"\x89PNG")
    assert page.headers["x-standard-source-root"] == "primary"
    assert document.status_code == 200
    assert document.headers["content-type"] == "application/pdf"
    assert document.headers["content-disposition"].startswith("inline;")
    assert document.content.startswith(b"%PDF-")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")


def test_standard_document_endpoints_reject_unknown_source_and_page(
    tmp_path: Path,
) -> None:
    with _build_client(tmp_path) as client:
        missing = client.get("/api/ai/standards/999/document")
        bad_page = client.get("/api/ai/standards/7/page/3")

    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "standard_source_not_found"
    assert bad_page.status_code == 404
    assert bad_page.json()["detail"]["code"] == "standard_page_not_found"


def test_standard_document_endpoints_honor_preview_and_download_policy(
    tmp_path: Path,
) -> None:
    with _build_client(
        tmp_path,
        preview_enabled=False,
        download_enabled=False,
    ) as client:
        page = client.get("/api/ai/standards/7/page/1")
        document = client.get("/api/ai/standards/7/document")
        download = client.get("/api/ai/standards/7/download")

    assert page.status_code == 403
    assert document.status_code == 403
    assert download.status_code == 403
