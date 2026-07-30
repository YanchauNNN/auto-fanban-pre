from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from zipfile import ZipFile

WORKTREE_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = WORKTREE_ROOT / "tools" / "ai" / "package_building_standards_skill.py"


def load_packager() -> object:
    spec = importlib.util.spec_from_file_location("standards_packager", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_private_package_contains_manifest_hashes_reports_and_skill(tmp_path: Path) -> None:
    packager = load_packager()
    skill = tmp_path / "building-structure-standards"
    files = {
        "SKILL.md": "skill",
        "scripts/standards_query.py": "query",
        "assets/data/standards.sqlite": "database",
        "assets/data/audit_catalog.json": json.dumps([{"source_id": 1}]),
        "assets/data/source_manifest.json": json.dumps({"sources": []}),
        "assets/data/parse_report.json": json.dumps({"source_count": 1}),
        "assets/data/validation_report.json": json.dumps(
            {"case_count": 72, "passed_count": 72, "failed_count": 0}
        ),
        "references/gold_cases.json": json.dumps({"case_count": 72}),
    }
    for relative, content in files.items():
        path = skill / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (skill / "__pycache__").mkdir()
    (skill / "__pycache__" / "bad.pyc").write_bytes(b"bad")
    audit_workbook = tmp_path / "audit.xlsx"
    audit_workbook.write_bytes(b"audit workbook")
    validation_set = tmp_path / "validation.yaml"
    validation_set.write_text("items: []\n", encoding="utf-8")
    output = tmp_path / "private.zip"

    result = packager.build_package(
        skill_root=skill,
        output_zip=output,
        audit_workbook=audit_workbook,
        validation_set=validation_set,
    )

    assert result["file_count"] >= len(files) + 2
    assert result["validation"]["failed_count"] == 0
    manifest = json.loads(
        (skill / "assets" / "data" / "manifest.json").read_text(encoding="utf-8")
    )
    names = {item["path"] for item in manifest["files"]}
    assert "assets/reports/建筑结构总图规范语料获取审计表.xlsx" in names
    assert "references/validation_set.yaml" in names
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
    with ZipFile(output) as archive:
        archive_names = set(archive.namelist())
        prefix = "private/building-structure-standards/"
        assert f"{prefix}SKILL.md" in archive_names
        assert f"{prefix}assets/data/manifest.json" in archive_names
        assert "private/INSTALL-ZH-CN.txt" in archive_names
        database_bytes = archive.read(f"{prefix}assets/data/standards.sqlite")
    database_entry = next(
        item
        for item in manifest["files"]
        if item["path"] == "assets/data/standards.sqlite"
    )
    assert hashlib.sha256(database_bytes).hexdigest() == database_entry["sha256"]
