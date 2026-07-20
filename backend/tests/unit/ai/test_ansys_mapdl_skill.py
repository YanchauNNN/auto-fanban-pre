from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile


def _fake_skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "ansys-mapdl-18-2"
    (root / "scripts").mkdir(parents=True)
    (root / "assets" / "data").mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: ansys-mapdl-18-2\n---\n", encoding="utf-8")
    (root / "scripts" / "mapdl_query.py").write_text("print('{}')\n", encoding="utf-8")
    (root / "assets" / "data" / "mapdl_help.sqlite").write_bytes(b"sqlite")
    (root / "assets" / "data" / "mapdl_commands.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "assets" / "data" / "manifest.json").write_text("{}\n", encoding="utf-8")
    return root


def test_ansys_skill_auto_matches_explicit_questions_and_conversation_followups(
    tmp_path: Path,
) -> None:
    from src.ai.ansys_mapdl_skill import AnsysMapdlSkill, AnsysMapdlSkillConfig

    skill = AnsysMapdlSkill(
        root=_fake_skill_root(tmp_path),
        config=AnsysMapdlSkillConfig(),
        query_runner=lambda *_args, **_kwargs: {},
    )

    assert skill.matches("请解释 ANTYPE 命令", []) is True
    assert skill.matches("SOLID185 的 KEYOPT(3) 有什么作用？", []) is True
    assert skill.matches("帮我写一段 APDL 静力分析输入", []) is True
    assert skill.matches("今天天气怎么样？", []) is False

    history = [
        SimpleNamespace(
            role="assistant",
            content="上一轮是 ANSYS 回答",
            metadata={"auto_skill_ids": ["ansys_mapdl_18_2"]},
        )
    ]
    assert skill.matches("它还有哪些参数？", history) is True
    assert skill.matches("今天天气怎么样？", history) is False


def test_ansys_skill_retrieves_exact_records_and_citable_context(tmp_path: Path) -> None:
    from src.ai.ansys_mapdl_skill import AnsysMapdlSkill, AnsysMapdlSkillConfig

    calls: list[tuple[str, str, int]] = []

    def fake_query(operation: str, query: str, *, limit: int) -> dict[str, Any]:
        calls.append((operation, query, limit))
        if operation == "command":
            return {
                "exact": True,
                "results": [
                    {
                        "command": "ANTYPE",
                        "purpose": "Specifies the analysis type and restart status.",
                        "syntax": "ANTYPE,Antype,Status",
                        "source_file": "Hlp_C_ANTYPE.html",
                    }
                ],
            }
        return {
            "results": [
                {
                    "doc_id": "ans_cmd/Hlp_C_ANTYPE.html",
                    "manual": "ans_cmd",
                    "title": "ANTYPE",
                    "excerpt": "Specifies the analysis type and restart status.",
                }
            ]
        }

    skill = AnsysMapdlSkill(
        root=_fake_skill_root(tmp_path),
        config=AnsysMapdlSkillConfig(max_results=3, max_context_chars=6000),
        query_runner=fake_query,
    )

    context = skill.retrieve_if_applicable("ANSYS 中 ANTYPE 命令的作用是什么？", [])

    assert context is not None
    assert context.skill_id == "ansys_mapdl_18_2"
    assert "ANSYS Mechanical APDL 18.2" in context.content
    assert "Hlp_C_ANTYPE.html" in context.content
    assert "Specifies the analysis type" in context.content
    assert context.metadata["operations"] == ["command", "search"]
    assert calls == [("command", "ANTYPE", 3), ("search", "ANSYS 中 ANTYPE 命令的作用是什么？", 3)]


def test_chat_service_injects_auto_skill_context_without_model_tool_support(
    tmp_path: Path,
) -> None:
    from src.ai.chat_service import AiAgentConfig, AiChatRuntimeConfig, AiChatService
    from src.ai.chat_store import AiChatStore
    from src.ai.context_skills import SkillContext

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[list[dict[str, Any]]] = []

        def complete(self, messages, *, tools=None):
            self.calls.append(messages)
            return type("ChatResult", (), {"content": "根据 18.2 语料回答", "usage": {}})()

    class FakeAnsysSkill:
        skill_id = "ansys_mapdl_18_2"

        def retrieve_if_applicable(self, content, history):
            if "ANSYS" not in content and not any(
                self.skill_id in (message.metadata or {}).get("auto_skill_ids", [])
                for message in history
            ):
                return None
            return SkillContext(
                skill_id=self.skill_id,
                content="ANSYS Mechanical APDL 18.2 evidence: ANTYPE",
                metadata={"operations": ["command"], "evidence_count": 1},
            )

    store = AiChatStore(tmp_path / "chat.sqlite3")
    store.initialize()
    client = FakeClient()
    service = AiChatService(
        store=store,
        client=client,
        runtime=AiChatRuntimeConfig(
            agents=[
                AiAgentConfig(agent_id="general_assistant", name="通用对话"),
                AiAgentConfig(agent_id="business_agent", name="业务 Agent"),
            ]
        ),
        context_skills=[FakeAnsysSkill()],
    )

    conversation = service.create_conversation("ip:127.0.0.1", title="APDL")
    first = service.send_message(
        owner_key="ip:127.0.0.1",
        conversation_id=conversation.conversation_id,
        content="ANSYS 中 ANTYPE 是什么？",
        agent_id="general_assistant",
        skill_ids=[],
        account_id=None,
    )
    second = service.send_message(
        owner_key="ip:127.0.0.1",
        conversation_id=conversation.conversation_id,
        content="它还有哪些参数？",
        agent_id="business_agent",
        skill_ids=[],
        account_id=None,
    )

    assert "ANSYS Mechanical APDL 18.2 evidence" in client.calls[0][0]["content"]
    assert "ANSYS Mechanical APDL 18.2 evidence" in client.calls[1][0]["content"]
    assert first.assistant_message.metadata["auto_skill_ids"] == ["ansys_mapdl_18_2"]
    assert second.assistant_message.metadata["auto_skill_ids"] == ["ansys_mapdl_18_2"]
    assert first.user_message.metadata["skill_contexts"][0]["evidence_count"] == 1


def test_install_skill_archive_extracts_only_the_skill_payload(tmp_path: Path) -> None:
    from src.ai.ansys_mapdl_skill import install_skill_archive

    archive = tmp_path / "private.zip"
    with ZipFile(archive, "w") as bundle:
        prefix = "ansys-mapdl-private/ansys-mapdl-18-2"
        bundle.writestr(f"{prefix}/SKILL.md", "skill")
        bundle.writestr(f"{prefix}/scripts/mapdl_query.py", "print('{}')")
        bundle.writestr(f"{prefix}/assets/data/mapdl_help.sqlite", "sqlite")
        bundle.writestr(f"{prefix}/assets/data/mapdl_commands.jsonl", "{}\n")
        bundle.writestr(f"{prefix}/assets/data/manifest.json", "{}\n")
        bundle.writestr("ansys-mapdl-private/INSTALL-ZH-CN.txt", "instructions")

    destination = tmp_path / "storage" / "ai" / "skills" / "ansys-mapdl-18-2"
    installed = install_skill_archive(archive, destination)

    assert installed == destination.resolve()
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "skill"
    assert (destination / "scripts" / "mapdl_query.py").exists()
    assert not (destination / "INSTALL-ZH-CN.txt").exists()


def test_windows_powershell_installer_is_ascii_compatible() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    script = repo_root / "tools" / "ai" / "install_ansys_mapdl_skill.ps1"

    assert script.read_text(encoding="utf-8").isascii()
