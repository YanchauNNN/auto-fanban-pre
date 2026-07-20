from __future__ import annotations

import json
import sys
from pathlib import Path
from zipfile import ZipFile


def fake_skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "building-structure-standards"
    required = [
        "SKILL.md",
        "scripts/standards_query.py",
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
                        "citation": (
                            "HAF 101-2023（2023），第3.1.1条，"
                            "PDF第6页（印刷页8）"
                        ),
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


def test_router_builds_both_configured_local_context_skills() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(repo_root))
    from API.app.routers.ai import build_context_skills

    from src.config.ai.ai_spec import AiSpecLoader

    AiSpecLoader.clear_cache()
    spec = AiSpecLoader.load(
        repo_root / "documents" / "AI" / "参数规范_AI.yaml"
    )

    skills = build_context_skills(spec)

    assert [skill.skill_id for skill in skills] == [
        "ansys_mapdl_18_2",
        "building_structure_standards",
    ]
