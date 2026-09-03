from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import fitz

WORKTREE_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    WORKTREE_ROOT
    / "tools"
    / "ai"
    / "building-structure-standards"
    / "scripts"
    / "build_full_corpus.py"
)


def _load_builder():
    spec = importlib.util.spec_from_file_location("standards_incremental_for_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _write_manifest(path: Path, relative_path: str) -> None:
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "standard_code": "GB/T TEST-2026",
                        "standard_name": "测试标准",
                        "version": "2026",
                        "source_path": relative_path,
                        "official_source_url": "",
                        "authorization": "内部离线检索已授权",
                        "confidentiality": "内部",
                        "official_status": "待核验",
                        "replacement_standard": "",
                        "major": "建筑结构总图",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_incremental_builder_reuses_unchanged_source_cache(tmp_path: Path) -> None:
    builder = _load_builder()
    source_root = tmp_path / "规范下载"
    relative_path = "001-010/GB T TEST-2026 测试标准.pdf"
    _write_pdf(source_root / relative_path, "1.1.1 cached evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, relative_path)
    output = tmp_path / "standards.sqlite"
    cache = tmp_path / "cache"

    first = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=output,
        cache_dir=cache,
    )
    second = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=output,
        cache_dir=cache,
    )

    assert first["parsed_count"] == 1
    assert first["cache_hit_count"] == 0
    assert first["published"] is True
    assert first["low_text_page_count"] == 1
    assert first["ocr_queue"] == [{"source_path": relative_path, "page_numbers": [1]}]
    assert second["parsed_count"] == 0
    assert second["cache_hit_count"] == 1
    assert second["published"] is True
    assert output.is_file()


def test_incremental_builder_keeps_previous_database_on_parse_failure(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    source_root = tmp_path / "规范下载"
    relative_path = "001-010/GB T TEST-2026 测试标准.pdf"
    _write_pdf(source_root / relative_path, "1.1.1 valid evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, relative_path)
    output = tmp_path / "standards.sqlite"
    cache = tmp_path / "cache"
    initial = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=output,
        cache_dir=cache,
    )
    assert initial["published"] is True
    original = output.read_bytes()
    (source_root / relative_path).write_bytes(b"not-a-pdf")

    failed = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=output,
        cache_dir=cache,
    )

    assert failed["failed_count"] == 1
    assert failed["published"] is False
    assert output.read_bytes() == original


def test_incremental_builder_writes_validation_for_published_database(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    source_root = tmp_path / "规范下载"
    relative_path = "001-010/GB T TEST-2026 测试标准.pdf"
    _write_pdf(source_root / relative_path, "1.1.1 structural validation evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, relative_path)
    output = tmp_path / "standards.sqlite"
    validation_report = tmp_path / "validation_report.json"

    result = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=output,
        cache_dir=tmp_path / "cache",
        validation_report_path=validation_report,
    )

    validation = json.loads(validation_report.read_text(encoding="utf-8"))
    assert result["published"] is True
    assert validation["failed_count"] == 0
    assert validation["database_sha256"] == builder._sha256(output)
    assert validation["manifest_source_count"] == 1
    assert validation["database_source_count"] == 1
    assert validation["relative_source_paths_valid"] is True


def test_incremental_builder_validates_only_requested_source_subset(
    tmp_path: Path,
) -> None:
    builder = _load_builder()
    source_root = tmp_path / "规范下载"
    first_path = "001-010/GB T FIRST-2026 第一标准.pdf"
    second_path = "011-020/GB T SECOND-2026 第二标准.pdf"
    _write_pdf(source_root / first_path, "1.1.1 first evidence")
    _write_pdf(source_root / second_path, "2.1.1 second evidence")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, first_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    second = dict(payload["sources"][0])
    second.update(
        {
            "standard_code": "GB/T SECOND-2026",
            "standard_name": "第二标准",
            "source_path": second_path,
        }
    )
    payload["sources"].append(second)
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = builder.build_incremental_corpus(
        manifest_path=manifest,
        source_root=source_root,
        output_path=tmp_path / "standards.sqlite",
        cache_dir=tmp_path / "cache",
        validation_report_path=tmp_path / "validation.json",
        max_sources=1,
    )

    assert result["published"] is True
    assert result["validation"]["manifest_source_count"] == 1
    assert result["validation"]["database_source_count"] == 1
