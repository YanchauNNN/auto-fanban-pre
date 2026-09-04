from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    WORKTREE_ROOT
    / "tools"
    / "ai"
    / "building-structure-standards"
    / "scripts"
    / "inventory_sources.py"
)


def _load_inventory_module():
    spec = importlib.util.spec_from_file_location("standards_inventory_for_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_inventory_matches_audit_metadata_and_preserves_relative_paths(
    tmp_path: Path,
) -> None:
    inventory = _load_inventory_module()
    source_root = tmp_path / "规范下载"
    first = source_root / "001-010" / "GB T 50010-2010 混凝土结构设计规范.pdf"
    second = source_root / "废止规范" / "JGJ 999-2001 演示规范（废止）.pdf"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"%PDF-audit")
    second.write_bytes(b"%PDF-inferred")
    audit = tmp_path / "audit.json"
    audit.write_text(
        json.dumps(
            [
                {
                    "standard_code": "GB/T 50010-2010",
                    "standard_name": "混凝土结构设计规范",
                    "official_status": "现行",
                    "replacement_standard": "",
                    "official_source_url": "https://official.example/50010",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = inventory.build_inventory(source_root, audit)

    assert result["summary"] == {
        "pdf_count": 2,
        "audit_matched_count": 1,
        "inferred_count": 1,
        "unidentified_count": 0,
        "duplicate_standard_code_count": 0,
    }
    records = {item["source_path"]: item for item in result["sources"]}
    audited = records["001-010/GB T 50010-2010 混凝土结构设计规范.pdf"]
    assert audited["standard_code"] == "GB/T 50010-2010"
    assert audited["official_status"] == "现行"
    assert audited["metadata_source"] == "audit_catalog"
    inferred = records["废止规范/JGJ 999-2001 演示规范（废止）.pdf"]
    assert inferred["standard_code"] == "JGJ 999-2001"
    assert inferred["official_status"] == "废止"
    assert inferred["metadata_source"] == "filename"
    assert "已授权" in inferred["authorization"]


def test_inventory_keeps_unidentified_pdf_explicit(tmp_path: Path) -> None:
    inventory = _load_inventory_module()
    source_root = tmp_path / "规范下载"
    source_root.mkdir()
    (source_root / "无法识别的扫描资料.pdf").write_bytes(b"%PDF-fixture")
    audit = tmp_path / "audit.json"
    audit.write_text("[]", encoding="utf-8")

    result = inventory.build_inventory(source_root, audit)

    assert result["summary"]["unidentified_count"] == 1
    source = result["sources"][0]
    assert source["standard_code"].startswith("UNIDENTIFIED-")
    assert source["official_status"] == "待核验"
    assert source["metadata_source"] == "unidentified"
