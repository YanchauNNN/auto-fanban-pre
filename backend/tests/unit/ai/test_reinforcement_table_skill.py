from __future__ import annotations

import json
import math
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openpyxl import Workbook


def _skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "reinforcement-table-normalizer"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: reinforcement-table-normalizer\n"
        "description: Normalize wall reinforcement workbooks.\n---\n",
        encoding="utf-8",
    )
    (root / "references" / "normalization-rules.md").write_text(
        "deterministic rules",
        encoding="utf-8",
    )
    return root


def _workbook_bytes(*, duplicate: bool = True) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "墙体单侧实配钢筋"
    sheet.append(["墙号", "水平筋(X)", "竖向筋(Y)", "拉筋(Z)"])
    sheet.append(
        [
            "墙N5007",
            "1 40@200",
            "1D36间距200（1 40@200）",
            "1A14间距400*400#",
        ]
    )
    if duplicate:
        sheet.append(["N5007", "1D32间距200", "1D28间距200", "2C12间距200*400"])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _workbook_with_issue_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "墙体单侧实配钢筋"
    sheet.append(["墙号", "水平筋(X)", "竖向筋(Y)", "拉筋(Z)"])
    sheet.append(["N5007", "1D40间距200", "1D36间距200", "1C14间距400*400"])
    sheet.append(["待确认墙", "1D32间距200", "1D32间距200", "1C14间距400*400"])
    sheet.append(["N5008", "未知写法", "1D28间距200", "1C12间距400*400"])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_skill_normalizes_attached_workbook_with_exact_formula_and_review_flags(
    tmp_path: Path,
) -> None:
    from src.ai.reinforcement_table_skill import (
        ReinforcementTableSkill,
        ReinforcementTableSkillConfig,
    )

    attachment = SimpleNamespace(
        attachment_id="attachment-1",
        original_name="墙体配筋结果.xlsx",
        kind="document",
        status="ready",
    )
    payload = _workbook_bytes()
    skill = ReinforcementTableSkill(
        root=_skill_root(tmp_path),
        config=ReinforcementTableSkillConfig(max_results=100),
    )

    context = skill.retrieve_from_attachments(
        "请把附件中的墙体配筋表统一成标准格式",
        [],
        [attachment],
        lambda item: payload if item is attachment else b"",
    )

    assert context is not None
    result = json.loads(context.content)
    workbook_result = result["workbooks"][0]
    assert workbook_result["source_name"] == "墙体配筋结果.xlsx"
    assert workbook_result["requires_completion_review"] is True
    assert workbook_result["duplicate_wall_ids"] == ["N5007"]
    assert len(workbook_result["rows"]) == 2

    first = workbook_result["rows"][0]
    assert first["wall_id"] == "N5007"
    assert first["source_sheet"] == "墙体单侧实配钢筋"
    assert first["source_row"] == 2
    assert first["directions"]["X"]["canonical_specification"] == "1D40间距200"
    assert first["directions"]["Y"]["canonical_specification"] == "1D40间距200"
    assert first["directions"]["Y"]["selected_parenthetical"] is True
    assert first["directions"]["Z"]["canonical_specification"] == "1C14间距400*400"
    assert first["directions"]["X"]["actual_area"] == math.pi * 20**2 * 5
    assert (
        first["directions"]["Z"]["actual_area"]
        == math.pi * 7**2 * 2.5 * 2.5
    )
    assert context.metadata["evidence_count"] == 2
    assert context.metadata["requires_completion_review"] is True


def test_skill_reconciles_source_rows_without_dropping_normalization_issues(
    tmp_path: Path,
) -> None:
    from src.ai.reinforcement_table_skill import (
        ReinforcementTableSkill,
        ReinforcementTableSkillConfig,
    )

    attachment = SimpleNamespace(
        attachment_id="attachment-issues",
        original_name="非标准墙体配筋结果.xlsx",
        kind="document",
        status="ready",
    )
    skill = ReinforcementTableSkill(
        root=_skill_root(tmp_path),
        config=ReinforcementTableSkillConfig(max_results=100),
    )

    context = skill.retrieve_from_attachments(
        "创建计算书并规范化附件配筋表",
        [],
        [attachment],
        lambda _item: _workbook_with_issue_bytes(),
    )

    assert context is not None
    result = json.loads(context.content)
    workbook_result = result["workbooks"][0]
    assert workbook_result["source_row_count"] == 3
    assert workbook_result["normalized_row_count"] == 1
    assert workbook_result["issue_row_count"] == 2
    assert workbook_result["source_row_count"] == (
        workbook_result["normalized_row_count"]
        + workbook_result["issue_row_count"]
    )
    assert len(workbook_result["output_rows"]) == 3
    assert [row["status"] for row in workbook_result["output_rows"]] == [
        "normalized",
        "needs_review",
        "needs_review",
    ]
    assert [issue["source_row"] for issue in workbook_result["issues"]] == [3, 4]
    assert workbook_result["normalization_triggered"] is True
    assert workbook_result["requires_completion_review"] is True
    assert context.metadata["source_row_count"] == 3
    assert context.metadata["requires_completion_review"] is True


def test_skill_refuses_to_guess_invalid_or_missing_workbook(tmp_path: Path) -> None:
    from src.ai.reinforcement_table_skill import (
        ReinforcementTableSkill,
        ReinforcementTableSkillConfig,
    )

    skill = ReinforcementTableSkill(
        root=_skill_root(tmp_path),
        config=ReinforcementTableSkillConfig(),
    )

    missing = skill.retrieve_if_applicable("请规范化墙体配筋表", [])
    assert missing is not None
    assert missing.metadata["available"] is True
    assert missing.metadata["error"] == "xlsx_attachment_required"
    assert "不得猜测" in missing.content

    attachment = SimpleNamespace(
        attachment_id="attachment-bad",
        original_name="错误.xlsx",
        kind="document",
        status="ready",
    )
    invalid = skill.retrieve_from_attachments(
        "规范化配筋表",
        [],
        [attachment],
        lambda _item: b"not-an-xlsx",
    )
    assert invalid is not None
    result = json.loads(invalid.content)
    assert result["workbooks"] == []
    assert result["errors"][0]["source_name"] == "错误.xlsx"
    assert result["policy"]["guessing_forbidden"] is True


def test_skill_compacts_large_context_without_dropping_rows(tmp_path: Path) -> None:
    from src.ai.reinforcement_table_skill import (
        ReinforcementTableSkill,
        ReinforcementTableSkillConfig,
    )

    attachment = SimpleNamespace(
        attachment_id="attachment-compact",
        original_name="墙体配筋结果.xlsx",
        kind="document",
        status="ready",
    )
    skill = ReinforcementTableSkill(
        root=_skill_root(tmp_path),
        config=ReinforcementTableSkillConfig(max_context_chars=5_000),
    )

    context = skill.retrieve_from_attachments(
        "规范化配筋表",
        [],
        [attachment],
        lambda _item: _workbook_bytes(),
    )

    assert context is not None
    result = json.loads(context.content)
    assert result["encoding"] == "compact_rows_v1"
    assert len(result["workbooks"][0]["row_records"]) == 2
    assert context.metadata["context_format"] == "compact_rows_v1"
    assert context.metadata["context_error"] is None
    assert len(context.content) <= 5_000


def test_chat_service_passes_current_attachments_to_attachment_aware_skills(
    tmp_path: Path,
) -> None:
    from src.ai.chat_service import AiChatRuntimeConfig, AiChatService
    from src.ai.chat_store import AiChatStore
    from src.ai.context_skills import SkillContext

    calls: list[tuple[str, list[Any], bytes]] = []

    class FakeClient:
        def complete(self, messages, *, tools=None):
            return SimpleNamespace(content="ok", usage={})

    class AttachmentAwareSkill:
        skill_id = "reinforcement_table_normalizer"

        def retrieve_if_applicable(self, content, history):
            raise AssertionError("attachment-aware retrieval should be preferred")

        def retrieve_from_attachments(
            self,
            content,
            history,
            attachments,
            attachment_reader,
        ):
            calls.append(
                (content, list(attachments), attachment_reader(attachments[0]))
            )
            return SkillContext(
                skill_id=self.skill_id,
                content="normalized",
                metadata={"evidence_count": 1},
            )

    store = AiChatStore(tmp_path / "chat.sqlite3")
    store.initialize()
    service = AiChatService(
        store=store,
        client=FakeClient(),
        runtime=AiChatRuntimeConfig(),
        context_skills=[AttachmentAwareSkill()],
    )
    service.attachment_store.read_bytes = lambda _attachment: b"xlsx-bytes"
    attachment = SimpleNamespace(original_name="配筋表.xlsx")

    contexts = service._retrieve_skill_contexts(
        "请规范化",
        [],
        [attachment],
    )

    assert [context.skill_id for context in contexts] == [
        "reinforcement_table_normalizer"
    ]
    assert calls == [("请规范化", [attachment], b"xlsx-bytes")]
