from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from zipfile import ZipFile

import fitz


def fake_skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "building-structure-standards"
    required = [
        "SKILL.md",
        "scripts/standards_query.py",
        "scripts/validate_full_corpus.py",
        "assets/data/standards.sqlite",
        "assets/data/audit_catalog.json",
        "assets/data/manifest.json",
        "assets/data/validation_report.json",
    ]
    for relative in required:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    return root


def test_skill_matches_standard_questions_and_followups(tmp_path: Path) -> None:
    from src.ai.building_standards_skill import (
        BuildingStandardsSkill,
        BuildingStandardsSkillConfig,
    )

    skill = BuildingStandardsSkill(
        root=fake_skill_root(tmp_path),
        config=BuildingStandardsSkillConfig(),
        query_runner=lambda *args, **kwargs: {},
    )

    assert skill.matches("HAF 101-2023 第3.1.1条是什么？", []) is True
    assert skill.matches("GB/T 50011 的抗震要求怎么规定？", []) is True
    assert skill.matches("23J909 图集能否给出页码？", []) is True
    assert skill.matches("今天天气怎么样？", []) is False

    class Message:
        metadata = {"auto_skill_ids": ["building_structure_standards"]}

    assert skill.matches("这个条款还要注意什么？", [Message()]) is True


def test_skill_retrieves_exact_clause_and_citable_context(tmp_path: Path) -> None:
    from src.ai.building_standards_skill import (
        BuildingStandardsSkill,
        BuildingStandardsSkillConfig,
    )

    calls: list[tuple[str, str, dict[str, object]]] = []

    def runner(
        operation: str,
        query: str,
        **kwargs: object,
    ) -> dict[str, object]:
        calls.append((operation, query, kwargs))
        if operation == "clause":
            return {
                "found": True,
                "evidence_insufficient": False,
                "results": [
                    {
                        "standard_code": query,
                        "clause_id": kwargs["clause_id"],
                        "text": "厂址评价必须包括相互影响因素。",
                        "citation": ("HAF 101-2023（2023），第3.1.1条，PDF第6页（印刷页8）"),
                    }
                ],
                "warnings": [],
            }
        return {"found": False, "results": [], "warnings": []}

    skill = BuildingStandardsSkill(
        root=fake_skill_root(tmp_path),
        config=BuildingStandardsSkillConfig(max_results=4),
        query_runner=runner,
    )

    context = skill.retrieve_if_applicable(
        "请说明 HAF 101-2023 第3.1.1条",
        [],
    )

    assert context is not None
    assert context.skill_id == "building_structure_standards"
    assert calls[0] == (
        "clause",
        "HAF 101-2023",
        {"clause_id": "3.1.1", "limit": 4},
    )
    payload = json.loads(context.content)
    assert payload["policy"]["catalog_is_not_fulltext"] is True
    assert payload["evidence"][0]["results"][0]["clause_id"] == "3.1.1"
    assert context.metadata["evidence_count"] == 1
    assert payload["design_advice_allowed"] is False
    assert payload["evidence_insufficient"] is True
    assert payload["evidence"][0]["design_advice_allowed"] is False
    assert context.metadata["design_advice_allowed"] is False


def test_skill_reports_incomplete_payload_without_guessing(tmp_path: Path) -> None:
    from src.ai.building_standards_skill import (
        BuildingStandardsSkill,
        BuildingStandardsSkillConfig,
    )

    skill = BuildingStandardsSkill(
        root=tmp_path / "missing",
        config=BuildingStandardsSkillConfig(),
    )

    context = skill.retrieve_if_applicable("GB 50016 第3.1.1条", [])

    assert context is not None
    assert context.metadata["available"] is False
    assert "不得凭记忆" in context.content


def test_install_archive_extracts_only_standards_skill_payload(tmp_path: Path) -> None:
    from src.ai.building_standards_skill import install_skill_archive

    archive = tmp_path / "standards.zip"
    prefix = "private/building-structure-standards"
    with ZipFile(archive, "w") as bundle:
        for relative in [
            "SKILL.md",
            "scripts/standards_query.py",
            "scripts/validate_full_corpus.py",
            "assets/data/standards.sqlite",
            "assets/data/audit_catalog.json",
            "assets/data/manifest.json",
            "assets/data/validation_report.json",
        ]:
            bundle.writestr(f"{prefix}/{relative}", "fixture")
        bundle.writestr("private/INSTALL-ZH-CN.txt", "instructions")

    destination = tmp_path / "storage" / "ai" / "skills" / "building-structure-standards"
    installed = install_skill_archive(archive, destination)

    assert installed == destination.resolve()
    assert (installed / "SKILL.md").is_file()
    assert not (installed / "INSTALL-ZH-CN.txt").exists()


def test_router_builds_all_configured_local_context_skills(monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from API.app.routers.ai import build_context_skills

    from src.config.ai.ai_spec import AiSpecLoader

    development_root = repo_root / "tools" / "ai" / "building-structure-standards"
    monkeypatch.setenv("FANBAN_BUILDING_STANDARDS_SKILL_ROOT", str(development_root))
    AiSpecLoader.clear_cache()
    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / "参数规范_AI.yaml")

    skills = build_context_skills(spec)

    assert [skill.skill_id for skill in skills] == [
        "ansys_mapdl_18_2",
        "building_structure_standards",
        "reinforcement_table_normalizer",
    ]
    standards = skills[1]
    assert standards.root == development_root.resolve()
    assert standards.available is True
    assert standards.config.source_root == (repo_root / "documents" / "规范下载").resolve()
    assert standards.config.fallback_source_roots == (
        Path(r"\\10.102.2.7\文件服务器\建筑结构所\14-自开发软件\规范下载"),
    )
    assert standards.config.per_file_fallback is True
    assert standards.config.preview_enabled is True
    assert standards.config.download_enabled is True


def test_router_honors_standards_source_environment_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from API.app.routers.ai import build_context_skills

    from src.config.ai.ai_spec import AiSpecLoader

    primary = tmp_path / "primary"
    fallback_one = tmp_path / "fallback-one"
    fallback_two = tmp_path / "fallback-two"
    monkeypatch.setenv("FANBAN_BUILDING_STANDARDS_SOURCE_ROOT", str(primary))
    monkeypatch.setenv(
        "FANBAN_BUILDING_STANDARDS_FALLBACK_ROOTS",
        f"{fallback_one};{fallback_two}",
    )
    AiSpecLoader.clear_cache()
    spec = AiSpecLoader.load(repo_root / "documents" / "AI" / "参数规范_AI.yaml")

    standards = build_context_skills(spec)[1]

    assert standards.config.source_root == primary.resolve()
    assert standards.config.fallback_source_roots == (
        fallback_one.resolve(),
        fallback_two.resolve(),
    )


def test_skill_attaches_bounded_pdf_page_images_to_matching_evidence(
    tmp_path: Path,
) -> None:
    from src.ai.building_standards_skill import (
        BuildingStandardsSkill,
        BuildingStandardsSkillConfig,
    )

    root = fake_skill_root(tmp_path)
    database = root / "assets" / "data" / "standards.sqlite"
    database.unlink()
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE sources (
                source_id INTEGER PRIMARY KEY,
                standard_code TEXT NOT NULL,
                standard_name TEXT NOT NULL,
                version TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_sha256 TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO sources VALUES (3, 'GB 50000-2026', '测试', '2026', 'test.pdf', '')"
        )
        connection.commit()
    finally:
        connection.close()

    source_root = tmp_path / "sources"
    source_root.mkdir()
    document = fitz.open()
    page = document.new_page(width=200, height=300)
    page.insert_text((30, 40), "figure evidence")
    document.save(source_root / "test.pdf")
    document.close()

    def runner(*_args, **_kwargs):
        return {
            "found": True,
            "results": [
                {
                    "source_id": 3,
                    "standard_code": "GB 50000-2026",
                    "page_start": 1,
                    "text": "图示要求",
                },
                {
                    "source_id": 3,
                    "standard_code": "GB 50000-2026",
                    "page_start": 1,
                    "text": "同页另一条",
                },
            ],
            "warnings": [],
        }

    skill = BuildingStandardsSkill(
        root=root,
        config=BuildingStandardsSkillConfig(
            source_root=source_root,
            model_page_images_enabled=True,
            max_model_page_images=2,
            page_render_dpi=96,
        ),
        query_runner=runner,
    )

    context = skill.retrieve_if_applicable("GB 50000-2026 图示要求", [])

    assert context is not None
    assert len(context.images) == 1
    assert context.images[0].media_type == "image/png"
    assert context.images[0].content.startswith(b"\x89PNG")
    assert context.images[0].label == "GB 50000-2026 PDF第1页"
    assert context.metadata["page_image_count"] == 1


def test_chat_service_retries_without_auto_skill_page_images_when_rejected(
    tmp_path: Path,
) -> None:
    from src.ai.chat_client import ChatGatewayError
    from src.ai.chat_service import AiChatRuntimeConfig, AiChatService
    from src.ai.chat_store import AiChatStore
    from src.ai.context_skills import SkillContext, SkillImageEvidence

    class PageImageSkill:
        skill_id = "building_structure_standards"

        def retrieve_if_applicable(self, _content, _history):
            return SkillContext(
                skill_id=self.skill_id,
                content="规范文字证据",
                metadata={"evidence_count": 1, "page_image_count": 1},
                images=(
                    SkillImageEvidence(
                        content=b"\x89PNG\r\nfixture",
                        media_type="image/png",
                        label="GB 50000-2026 PDF第1页",
                    ),
                ),
            )

    class RejectImagesClient:
        def __init__(self) -> None:
            self.calls = []

        def complete(self, messages, *, tools=None):
            self.calls.append(messages)
            if len(self.calls) == 1:
                raise ChatGatewayError("image input unsupported", status_code=400)
            return type("ChatResult", (), {"content": "已按文字证据回答", "usage": {}})()

    store = AiChatStore(tmp_path / "chat.sqlite3")
    store.initialize()
    client = RejectImagesClient()
    service = AiChatService(
        store=store,
        client=client,
        runtime=AiChatRuntimeConfig(),
        context_skills=[PageImageSkill()],
    )
    conversation = service.create_conversation("ip:127.0.0.1")

    exchange = service.send_message(
        owner_key="ip:127.0.0.1",
        conversation_id=conversation.conversation_id,
        content="请解释规范图示",
        agent_id=None,
        skill_ids=[],
        account_id=None,
    )

    first_content = client.calls[0][-1]["content"]
    assert isinstance(first_content, list)
    assert any(block.get("type") == "image_url" for block in first_content)
    assert client.calls[1][-1]["content"] == "请解释规范图示"
    assert exchange.assistant_message.content == "已按文字证据回答"
    assert exchange.assistant_message.metadata["page_images_downgraded"] is True
