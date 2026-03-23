from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from src.audit_replace.mapping import ReplaceMappingBuilder


def _build_replace_lexicon_workbook(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Sheet1"
    ws.append(["project", "1418", "2016", "2026", "note"])
    ws.append(["lexicon", "CHANGJIANG", "JINQIMEN", "XUWEI", "note"])
    ws.append([None, "1418YNI-JGS01", "20161NH-JGS01-002", "20261NH-JGS01-002", None])
    ws.append([None, "SHARED", "SHARED", "OTHER", None])
    ws.append([None, "HL", "JD", "XZ", None])
    ws.append([None, "SOURCE_ONLY", None, "TARGET2026", None])
    wb.save(path)
    return path


def test_replace_mapping_builder_includes_rows_1_2_and_3_plus(tmp_path: Path) -> None:
    workbook = _build_replace_lexicon_workbook(tmp_path / "replace-lexicon.xlsx")

    mapping = ReplaceMappingBuilder().build(
        workbook_path=workbook,
        source_project_no="1418",
        target_project_no="2016",
    )

    assert mapping.replacements["1418"] == "2016"
    assert mapping.replacements["CHANGJIANG"] == "JINQIMEN"
    assert mapping.replacements["1418YNI-JGS01"] == "20161NH-JGS01-002"
    assert mapping.replacements["HL"] == "JD"


def test_replace_mapping_builder_skips_shared_text_and_tracks_missing_target(tmp_path: Path) -> None:
    workbook = _build_replace_lexicon_workbook(tmp_path / "replace-lexicon.xlsx")

    mapping = ReplaceMappingBuilder().build(
        workbook_path=workbook,
        source_project_no="1418",
        target_project_no="2016",
    )

    assert "SHARED" not in mapping.replacements
    assert mapping.no_op_tokens == ["SHARED"]
    assert mapping.missing_target_tokens == ["SOURCE_ONLY"]
