from __future__ import annotations

import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "tools/ai/building-structure-standards/scripts/standards_query.py"
)
FIRE = "GB 50016-2014"
DRAFTING = "GB/T 50001-2017"
MISSING = "NB/T 20001-2026"
TERM = "fire compartment"


@pytest.fixture
def corpus(tmp_path):
    database = tmp_path / "standards.sqlite"
    catalog = tmp_path / "audit_catalog.json"
    catalog.write_text(
        json.dumps([{"standard_code": MISSING, "included_in_corpus": True,
                     "local_file": "missing.pdf"}]), encoding="utf-8"
    )
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE sources (
                source_id INTEGER PRIMARY KEY, standard_code TEXT, standard_name TEXT,
                version TEXT, major TEXT, official_status TEXT, replacement_standard TEXT,
                official_source_url TEXT, authorization TEXT, confidentiality TEXT
            );
            CREATE TABLE pages (
                source_id INTEGER, page_number INTEGER, printed_page TEXT, text TEXT,
                anchor TEXT, native_text TEXT, ocr_text TEXT, text_source TEXT,
                ocr_confidence REAL, quality_status TEXT, quality_flags_json TEXT,
                content_role TEXT, ocr_provenance_json TEXT
            );
            CREATE TABLE clauses (
                source_id INTEGER, clause_id TEXT, heading TEXT, text TEXT,
                page_start INTEGER, page_end INTEGER, anchor TEXT, table_ids_json TEXT,
                content_role TEXT
            );
            CREATE TABLE standard_tables (
                source_id INTEGER, table_id TEXT, page_number INTEGER, rows_json TEXT,
                markdown TEXT, anchor TEXT, quality_status TEXT, table_label TEXT,
                quality_flags_json TEXT
            );
        """)
        for source_id, code in enumerate([FIRE, DRAFTING, MISSING], 1):
            db.execute(
                "INSERT INTO sources VALUES (?, ?, ?, '2026', '', ?, '', '', ?, '')",
                (source_id, code, "standard", "现行", "内部离线检索已授权"),
            )
        for source_id in [1, 2]:
            for page in [1, 2]:
                db.execute(
                    "INSERT INTO pages VALUES (?, ?, ?, 'body', ?, 'body', '', "
                    "'native', NULL, 'usable', '[]', 'normative', '{}')",
                    (source_id, page, str(page + 10), f"source.pdf#page={page}"),
                )
            text = TERM if source_id == 1 else "drawing format"
            db.execute(
                "INSERT INTO clauses VALUES (?, '3.1.1', ?, ?, 1, 2, "
                "'source.pdf#page=1', '[]', 'normative')",
                (source_id, text, text),
            )
        db.execute(
            "INSERT INTO standard_tables VALUES (1, 'p1-t1', 1, ?, 'grid', "
            "'source.pdf#page=1', 'usable', ?, '[]')",
            (json.dumps([["category", "area"], ["A", "1000"]]), "表3.2.2"),
        )
    spec = importlib.util.spec_from_file_location("standards_query_safety", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, database, catalog


def execute(corpus, sql, params=()):
    with sqlite3.connect(corpus[1]) as db:
        db.execute(sql, params)


def advice(corpus, *, codes=None, query=TERM, limit=20):
    module, database, catalog = corpus
    return module.collect_advice_evidence(
        database, catalog, query, requested_codes=codes, limit=limit
    )


@pytest.mark.parametrize("operation", ["clause", "search", "table", "visual_table"])
@pytest.mark.parametrize("has_sha_column", [True, False])
def test_evidence_rows_expose_own_source_sha256_or_legacy_null(corpus, operation, has_sha_column):
    expected_sha = {1: "a" * 64, 2: "b" * 64} if has_sha_column else {1: None, 2: None}
    if has_sha_column:
        execute(corpus, "ALTER TABLE sources ADD COLUMN source_sha256 TEXT")
        for source_id, sha in expected_sha.items():
            execute(corpus, "UPDATE sources SET source_sha256=? WHERE source_id=?", (sha, source_id))
    # Equal standard codes must not substitute one PDF's fingerprint for another's.
    execute(corpus, "UPDATE sources SET standard_code=? WHERE source_id=2", (FIRE,))
    execute(corpus, "UPDATE clauses SET text=?, heading=? WHERE source_id=2", (TERM, TERM))
    execute(corpus, "INSERT INTO standard_tables SELECT 2, 'p1-t2', page_number, rows_json, "
            "markdown, anchor, quality_status, '3.2.3', quality_flags_json FROM standard_tables")
    module, database, _ = corpus
    if operation == "clause":
        result = module.get_clause(database, FIRE, "3.1.1")
        rows = result["results"]
    elif operation == "search":
        result = module.search(database, TERM, standard_code=FIRE)
        rows = result["results"]
    else:
        if operation == "visual_table":
            execute(corpus, "UPDATE standard_tables SET quality_status='visual_required' WHERE source_id=2")
        result = module.get_table(database, FIRE, "3.2.3")
        rows = [result["table"]]
    assert result["found"] is True
    assert {row["source_id"] for row in rows} == ({1, 2} if operation in {"clause", "search"} else {2})
    for row in rows:
        assert row["source_sha256"] == expected_sha[row["source_id"]]
    if operation == "visual_table":
        assert result["evidence_insufficient"] is True
        assert result["table"]["rows"] == []


@pytest.mark.parametrize("query", ["", " \t\n\u3000", "%", "_"])
def test_empty_or_sql_wildcard_query_does_not_match_the_corpus(corpus, query):
    module, database, _ = corpus
    result = module.search(database, query)
    assert result["results"] == []
    assert result["evidence_insufficient"] is True
    result = advice(corpus, query=query, codes=[FIRE])
    assert result["evidence"] == []
    assert result["design_advice_allowed"] is False


@pytest.mark.parametrize("code", [DRAFTING, MISSING])
def test_metadata_and_other_standards_cannot_satisfy_requested_evidence(corpus, code):
    result = advice(corpus, codes=[code])
    assert result["design_advice_allowed"] is False
    assert result["evidence_level"] == "none"
    assert result["available_codes"] == []
    assert result["missing_content_codes"] == [code]
    assert result["evidence"] == []


def test_standard_name_match_is_not_relevant_body_evidence(corpus):
    execute(corpus, "UPDATE sources SET standard_name=? WHERE source_id=2", (TERM,))
    result = advice(corpus, codes=[DRAFTING])
    assert result["design_advice_allowed"] is False


def test_requested_standards_are_searched_independently_of_global_limit(corpus):
    execute(corpus, "UPDATE clauses SET text=?, heading=? WHERE source_id=2", (TERM, TERM))
    result = advice(corpus, codes=[FIRE, DRAFTING, FIRE], limit=1)
    assert result["design_advice_allowed"] is True
    assert {row["standard_code"] for row in result["evidence"]} == {FIRE, DRAFTING}
    assert result["available_codes"] == [FIRE, DRAFTING]


@pytest.mark.parametrize("status", ["review_required", "blank", "failed", "unknown", None])
def test_every_page_of_cross_page_clause_must_be_usable(corpus, status):
    execute(corpus, "UPDATE pages SET quality_status=? WHERE source_id=1 AND page_number=2", (status,))
    module, database, _ = corpus
    result = module.get_clause(database, FIRE, "3.1.1")
    assert result["found"] is True
    assert result["evidence_insufficient"] is True
    assert result["design_advice_allowed"] is False
    row = result["results"][0]
    assert len(row["page_quality"]) == 2
    assert row["page_quality"][1]["quality_status"] == (status or "unknown")
    assert advice(corpus, codes=[FIRE])["design_advice_allowed"] is False


def test_missing_continuation_page_is_not_usable(corpus):
    execute(corpus, "DELETE FROM pages WHERE source_id=1 AND page_number=2")
    assert advice(corpus, codes=[FIRE])["design_advice_allowed"] is False


def test_legacy_quality_column_preserves_review_required(corpus):
    execute(corpus, "ALTER TABLE pages RENAME COLUMN quality_status TO quality")
    execute(corpus, "UPDATE pages SET quality='review_required' WHERE source_id=1 AND page_number=2")
    result = corpus[0].get_clause(corpus[1], FIRE, "3.1.1")
    assert result["found"] is True
    assert result["evidence_insufficient"] is True
    assert result["results"][0]["page_quality"][1]["quality_status"] == "review_required"


@pytest.mark.parametrize("flags", ['["unit_suspect"]', '["formula_uncertain"]', 'invalid', '{}', 'null'])
def test_page_risk_flags_override_high_confidence_and_usable_status(corpus, flags):
    execute(corpus, "UPDATE pages SET text_source='ocr', ocr_confidence=0.999, "
            "quality_flags_json=? WHERE source_id=1 AND page_number=2", (flags,))
    result = advice(corpus, codes=[FIRE])
    assert result["design_advice_allowed"] is False
    assert result["evidence_insufficient"] is True
    assert result["warnings"]


@pytest.mark.parametrize("role", ["commentary", "toc", "announcement", "unknown"])
@pytest.mark.parametrize("table", ["pages", "clauses"])
def test_non_normative_content_is_queryable_but_cannot_support_advice(corpus, table, role):
    execute(corpus, f"UPDATE {table} SET content_role=? WHERE source_id=1", (role,))
    result = corpus[0].get_clause(corpus[1], FIRE, "3.1.1")
    assert result["found"] is True
    assert result["evidence_insufficient"] is True
    assert advice(corpus, codes=[FIRE])["design_advice_allowed"] is False


def test_exact_clause_prefers_normative_record_over_same_number_commentary(corpus):
    execute(corpus, "INSERT INTO clauses SELECT source_id, clause_id, heading, 'explanation', "
            "1, 1, anchor, table_ids_json, 'commentary' FROM clauses WHERE source_id=1")
    result = corpus[0].get_clause(corpus[1], FIRE, "3.1.1")
    assert result["results"][0]["content_role"] == "normative"
    assert result["design_advice_allowed"] is True


def test_legacy_schema_remains_queryable_but_fails_closed_for_advice(corpus):
    for table, columns in {
        "pages": ["native_text", "ocr_text", "text_source", "ocr_confidence", "quality_status",
                  "quality_flags_json", "content_role", "ocr_provenance_json"],
        "clauses": ["content_role"],
        "standard_tables": ["quality_status", "quality_flags_json", "table_label"],
    }.items():
        for column in columns:
            execute(corpus, f"ALTER TABLE {table} DROP COLUMN {column}")
    module, database, _ = corpus
    assert module.search(database, TERM)["found"] is True
    assert module.get_clause(database, FIRE, "3.1.1")["evidence_insufficient"] is True
    table = module.get_table(database, FIRE, "p1-t1")
    assert table["found"] is True
    assert table["evidence_insufficient"] is True
    assert table["table"]["rows"][1] == ["A", "1000"]
    result = advice(corpus, codes=[FIRE])
    assert result["design_advice_allowed"] is False
    assert result["evidence"]


@pytest.mark.parametrize("table_id", ["p1-t1", "3.2.2", "表 3.2.2"])
def test_visual_required_table_returns_location_not_guessed_cells(corpus, table_id):
    execute(corpus, "UPDATE standard_tables SET quality_status='visual_required'")
    result = corpus[0].get_table(corpus[1], FIRE, table_id)
    assert result["found"] is True
    assert result["evidence_insufficient"] is True
    assert result["design_advice_allowed"] is False
    assert result["table"]["rows"] == []
    assert result["table"]["quality_status"] == "visual_required"
    assert result["table"]["markdown"] == ""
    assert result["table"]["table_label"] == "表3.2.2"
    assert result["table"]["page_number"] == 1
    assert result["table"]["links"]["page"].endswith("/1/page/1")


def test_usable_table_label_returns_verified_cells(corpus):
    result = corpus[0].get_table(corpus[1], FIRE, "3.2.2")
    assert result["found"] is True
    assert result["design_advice_allowed"] is True
    assert result["table"]["rows"][1] == ["A", "1000"]


def test_table_ragged_rows_are_not_qualified(corpus):
    execute(corpus, "UPDATE standard_tables SET rows_json=?", (json.dumps([["A", "B"], ["1000"]]),))
    result = corpus[0].get_table(corpus[1], FIRE, "p1-t1")
    assert result["found"] is True
    assert result["design_advice_allowed"] is False


def test_zero_limit_does_not_force_a_result(corpus):
    assert corpus[0].search(corpus[1], TERM, limit=0)["results"] == []
    assert advice(corpus, codes=[FIRE], limit=0)["design_advice_allowed"] is False


def test_table_page_quality_and_table_flags_are_both_enforced(corpus):
    execute(corpus, "UPDATE standard_tables SET quality_flags_json='[\"unit_suspect\"]'")
    assert corpus[0].get_table(corpus[1], FIRE, "p1-t1")["evidence_insufficient"] is True
    execute(corpus, "UPDATE standard_tables SET quality_flags_json='[]'")
    execute(corpus, "UPDATE pages SET quality_status='review_required' WHERE source_id=1")
    assert corpus[0].get_table(corpus[1], FIRE, "p1-t1")["evidence_insufficient"] is True


def test_clause_with_visual_required_table_cannot_support_advice(corpus):
    execute(corpus, "UPDATE clauses SET table_ids_json='[\"p1-t1\"]' WHERE source_id=1")
    execute(corpus, "UPDATE standard_tables SET quality_status='visual_required'")
    assert advice(corpus, codes=[FIRE])["design_advice_allowed"] is False


def duplicate_code_tables(corpus, own_table_status):
    execute(corpus, "UPDATE sources SET standard_code=? WHERE source_id=2", (FIRE,))
    execute(corpus, "DELETE FROM clauses WHERE source_id=2")
    execute(corpus, "INSERT INTO standard_tables SELECT 2, table_id, page_number, rows_json, "
            "markdown, anchor, quality_status, table_label, quality_flags_json FROM standard_tables")
    execute(corpus, "UPDATE clauses SET table_ids_json='[\"p1-t1\"]' WHERE source_id=1")
    if own_table_status == "missing":
        execute(corpus, "DELETE FROM standard_tables WHERE source_id=1")
    else:
        execute(corpus, "UPDATE standard_tables SET quality_status=? WHERE source_id=1", (own_table_status,))


@pytest.mark.parametrize("own_table_status", ["visual_required", "missing", "usable"])
@pytest.mark.parametrize("operation", ["clause", "search", "advice"])
def test_clause_table_gate_never_borrows_another_source(corpus, own_table_status, operation):
    duplicate_code_tables(corpus, own_table_status)
    module, database, _ = corpus
    if operation == "clause":
        result = module.get_clause(database, FIRE, "3.1.1")
    elif operation == "search":
        result = module.search(database, TERM, standard_code=FIRE)
    else:
        result = advice(corpus, codes=[FIRE])
    rows = result["evidence"] if operation == "advice" else result["results"]
    assert len(rows) == 1
    assert rows[0]["source_id"] == 1
    allowed = own_table_status == "usable"
    assert rows[0]["design_advice_allowed"] is allowed
    assert result["design_advice_allowed"] is allowed
    assert result["evidence_insufficient"] is (not allowed)
    if not allowed:
        assert "table_evidence_insufficient:p1-t1" in rows[0]["quality_flags"]


@pytest.mark.parametrize("table_id", ["p1-t1", "3.2.2"])
@pytest.mark.parametrize(("source_id", "found", "allowed"), [
    (1, True, False), (2, True, True), (0, False, False), (3, False, False),
])
def test_get_table_source_scope_applies_to_ids_and_labels(corpus, table_id, source_id, found, allowed):
    duplicate_code_tables(corpus, "visual_required")
    module, database, _ = corpus
    unscoped = module.get_table(database, FIRE, table_id)
    assert unscoped["table"]["source_id"] == 2
    assert unscoped["design_advice_allowed"] is True
    result = module.get_table(database, FIRE, table_id, source_id=source_id)
    assert result["found"] is found
    assert result["design_advice_allowed"] is allowed
    if found:
        assert result["table"]["source_id"] == source_id
        if not allowed:
            assert result["table"]["rows"] == []
    else:
        assert result["table"] is None


def make_skill(corpus, tmp_path, **settings):
    from src.ai.building_standards_skill import BuildingStandardsSkill, BuildingStandardsSkillConfig

    root = tmp_path / "skill"
    (root / "scripts").mkdir(parents=True)
    (root / "assets/data").mkdir(parents=True)
    shutil.copyfile(SCRIPT, root / "scripts/standards_query.py")
    shutil.copyfile(corpus[1], root / "assets/data/standards.sqlite")
    shutil.copyfile(corpus[2], root / "assets/data/audit_catalog.json")
    for name in ["SKILL.md", "scripts/validate_full_corpus.py",
                 "assets/data/manifest.json", "assets/data/validation_report.json"]:
        (root / name).write_text("{}", encoding="utf-8")
    return BuildingStandardsSkill(root=root, config=BuildingStandardsSkillConfig(**settings))


def test_backend_preserves_source_sha256_in_real_query_context(corpus, tmp_path):
    execute(corpus, "ALTER TABLE sources ADD COLUMN source_sha256 TEXT")
    sha = "c" * 64
    execute(corpus, "UPDATE sources SET source_sha256=? WHERE source_id=1", (sha,))
    skill = make_skill(corpus, tmp_path)
    context = skill.retrieve_if_applicable(f"{FIRE} 第3.1.1条", [])
    payload = json.loads(context.content)
    assert payload["evidence"][0]["results"][0]["source_sha256"] == sha


def test_backend_blocks_clause_with_table_only_qualified_in_another_source(corpus, tmp_path):
    duplicate_code_tables(corpus, "visual_required")
    skill = make_skill(corpus, tmp_path)
    context = skill.retrieve_if_applicable(f"{FIRE} 第3.1.1条", [])
    payload = json.loads(context.content)
    assert payload["design_advice_allowed"] is False
    assert payload["evidence"][0]["results"][0]["evidence_insufficient"] is True
    assert context.metadata["design_advice_allowed"] is False


@pytest.mark.parametrize("unsafe", [False, True])
def test_backend_real_subprocess_context_uses_clause_quality_gate(corpus, tmp_path, unsafe):
    if unsafe:
        execute(corpus, "UPDATE pages SET quality_status='review_required' "
                "WHERE source_id=1 AND page_number=2")
    skill = make_skill(corpus, tmp_path)
    context = skill.retrieve_if_applicable(f"{FIRE} 第3.1.1条", [])
    payload = json.loads(context.content)
    assert payload["design_advice_allowed"] is (not unsafe)
    assert payload["evidence_insufficient"] is unsafe
    assert context.metadata["design_advice_allowed"] is (not unsafe)
    assert payload["evidence"][0]["results"][0]["page_quality"][1]["quality_status"] == (
        "review_required" if unsafe else "usable"
    )


def test_backend_checks_all_requested_codes_not_just_first_clause(corpus, tmp_path):
    skill = make_skill(corpus, tmp_path)
    context = skill.retrieve_if_applicable(f"{FIRE} 和 {MISSING} 第3.1.1条", [])
    payload = json.loads(context.content)
    assert payload["design_advice_allowed"] is False
    assert payload["missing_content_codes"] == [MISSING]
    assert len(payload["evidence"]) == 2


def test_backend_unspecified_scope_cannot_promote_a_bad_standard(corpus, tmp_path):
    execute(corpus, "UPDATE clauses SET text=?, heading=?", ("防火分区", "防火分区"))
    execute(corpus, "UPDATE pages SET quality_status='review_required' WHERE source_id=2")
    skill = make_skill(corpus, tmp_path)
    context = skill.retrieve_if_applicable("防火分区", [])
    payload = json.loads(context.content)
    assert payload["design_advice_allowed"] is False
    assert payload["insufficient_quality_codes"] == [DRAFTING]


def test_backend_search_removes_codes_and_keeps_each_standard_scope(corpus, tmp_path):
    skill = make_skill(corpus, tmp_path)
    context = skill.retrieve_if_applicable(f"{FIRE} {DRAFTING} {TERM}", [])
    payload = json.loads(context.content)
    assert payload["design_advice_allowed"] is False
    assert payload["available_codes"] == [FIRE]
    assert payload["missing_content_codes"] == [DRAFTING]


def test_backend_table_query_preserves_visual_required_location(corpus, tmp_path):
    execute(corpus, "UPDATE standard_tables SET quality_status='visual_required'")
    skill = make_skill(corpus, tmp_path)
    context = skill.retrieve_if_applicable(f"{FIRE} 表3.2.2", [])
    payload = json.loads(context.content)
    assert context.metadata["operations"] == ["table"]
    assert payload["design_advice_allowed"] is False
    assert payload["evidence"][0]["table"]["rows"] == []


def test_backend_truncation_keeps_valid_json_and_never_weakens_gate(corpus, tmp_path):
    execute(corpus, "UPDATE clauses SET text=? WHERE source_id=1", ("body " * 2000,))
    skill = make_skill(corpus, tmp_path, max_context_chars=1500)
    context = skill.retrieve_if_applicable(f"{FIRE} 第3.1.1条", [])
    payload = json.loads(context.content)
    assert len(context.content) <= 1500
    assert payload["design_advice_allowed"] is False
    assert payload["evidence_insufficient"] is True
    assert payload["context_truncated"] is True


def test_chat_system_prompt_contains_real_query_quality_gate(corpus, tmp_path):
    from src.ai.chat_service import AiChatRuntimeConfig, AiChatService
    from src.ai.chat_store import AiChatStore

    execute(corpus, "UPDATE pages SET quality_status='review_required' WHERE source_id=1")
    skill = make_skill(corpus, tmp_path)

    class RecordingClient:
        messages = []

        def complete(self, messages, *, tools=None):
            self.messages = messages
            return type("ChatResult", (), {"content": "Evidence needs review.", "usage": {}})()

    client = RecordingClient()
    store = AiChatStore(tmp_path / "chat.sqlite3")
    store.initialize()
    service = AiChatService(
        store=store, client=client, runtime=AiChatRuntimeConfig(), context_skills=[skill],
    )
    conversation = service.create_conversation("test-owner")
    exchange = service.send_message(
        owner_key="test-owner", conversation_id=conversation.conversation_id,
        content=f"{FIRE} 第3.1.1条", agent_id=None, skill_ids=[], account_id=None,
    )
    system = next(message["content"] for message in client.messages if message["role"] == "system")
    context = system.split('<local_skill id="building_structure_standards">', 1)[1].split("</local_skill>", 1)[0]
    payload = json.loads(context)
    assert payload["evidence_insufficient"] is True
    assert payload["design_advice_allowed"] is False
    assert payload["evidence"][0]["results"][0]["page_quality"][1]["quality_status"] == "review_required"
    assert exchange.assistant_message.metadata["skill_contexts"][0]["design_advice_allowed"] is False
