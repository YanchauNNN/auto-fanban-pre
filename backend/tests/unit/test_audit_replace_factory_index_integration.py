from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import ezdxf

from src.audit_check.models import AuditLexicon, ScanTextItem
from src.audit_replace.executor import AuditReplaceExecutor
from src.audit_replace.mapping import ReplaceMapping
from src.config import SpecLoader, reload_config
from src.models import Job, JobType


def _configure_env(monkeypatch, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(repo_root / "documents" / "参数规范.yaml"))
    monkeypatch.setenv(
        "FANBAN_RUNTIME_SPEC_PATH",
        str(repo_root / "documents" / "参数规范_运行期.yaml"),
    )
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(tmp_path / "storage"))
    SpecLoader.clear_cache()
    reload_config()


def _build_source_dxf(tmp_path: Path) -> tuple[Path, str]:
    dxf_path = tmp_path / "source.dxf"
    doc = ezdxf.new("R2018")
    text = doc.modelspace().add_text("2016")
    doc.saveas(dxf_path)
    return dxf_path, text.dxf.handle


def test_executor_applies_factory_index_map_after_2016_to_2026(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)

    source_dwg = tmp_path / "20162PR-JGS01-B.dwg"
    source_dwg.write_bytes(b"original-dwg")
    dxf_path, text_handle = _build_source_dxf(tmp_path)

    executor = AuditReplaceExecutor()
    monkeypatch.setattr(executor.oda, "dwg_to_dxf", lambda src, out_dir: dxf_path)

    def _fake_dxf_to_dwg(
        src: Path,
        output_dir: Path,
        target_version_code: str | None = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "converted.dwg"
        output_path.write_bytes(b"converted-dwg")
        return output_path

    class _FakeFactoryIndexReplacement:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def replace_if_configured(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            output_dwg = Path(kwargs["output_dwg"])  # type: ignore[index]
            output_dwg.parent.mkdir(parents=True, exist_ok=True)
            output_dwg.write_bytes(b"factory-index-dwg")
            return SimpleNamespace(
                applied=True,
                output_dwg=output_dwg,
                action_count=2,
                report_json=Path(kwargs["workspace_dir"]) / "factory_index_map.json",  # type: ignore[index]
                to_progress_dict=lambda: {"applied": True, "action_count": 2},
            )

    factory_index = _FakeFactoryIndexReplacement()

    monkeypatch.setattr(executor.oda, "dxf_to_dwg", _fake_dxf_to_dwg)
    monkeypatch.setattr(executor.frame_detector, "detect_frames", lambda path: [])
    monkeypatch.setattr(executor.titleblock_extractor, "extract_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor.a4_grouper, "group_a4_pages", lambda frames: ([], []))
    monkeypatch.setattr(
        executor.lexicon_loader,
        "load",
        lambda path: AuditLexicon(
            project_options=["2016", "2026"],
            allowed_texts={"2016": {"2016"}, "2026": {"2026"}},
            foreign_texts={"2016": {"2026"}, "2026": {"2016"}},
            token_projects={"2016": {"2016"}, "2026": {"2026"}},
        ),
    )
    monkeypatch.setattr(
        executor.mapping_builder,
        "build",
        lambda workbook_path, source_project_no, target_project_no: ReplaceMapping(
            source_project_no="2016",
            target_project_no="2026",
            replacements={"2016": "2026"},
            no_op_tokens=[],
            missing_target_tokens=[],
        ),
    )
    monkeypatch.setattr(
        executor.dotnet_scanner,
        "scan",
        lambda **kwargs: [
            ScanTextItem(raw_text="2016", entity_type="DBText", entity_handle=text_handle),
        ],
    )
    executor.factory_index_maps = factory_index

    job = Job(
        job_id="job-audit-replace-factory-index",
        job_type=JobType.AUDIT_REPLACE,
        project_no="2026",
        input_files=[source_dwg],
        options={"mode": "replace"},
        params={"source_project_no": "2016", "target_project_no": "2026"},
    )

    executor.execute(job)

    assert job.artifacts.replaced_dwg and job.artifacts.replaced_dwg.read_bytes() == b"factory-index-dwg"
    assert len(factory_index.calls) == 1
    assert factory_index.calls[0]["source_project_no"] == "2016"
    assert factory_index.calls[0]["target_project_no"] == "2026"
    assert factory_index.calls[0]["source_variant"] is None
    assert factory_index.calls[0]["target_variant"] is None
    assert json.dumps(job.progress.details["factory_index_map"], sort_keys=True) == (
        '{"action_count": 2, "applied": true}'
    )


def test_executor_passes_distinct_source_and_target_factory_index_variants(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_env(monkeypatch, tmp_path)

    source_dwg = tmp_path / "20161PR-JGS01-B.dwg"
    source_dwg.write_bytes(b"original-dwg")
    dxf_path, text_handle = _build_source_dxf(tmp_path)

    executor = AuditReplaceExecutor()
    monkeypatch.setattr(executor.oda, "dwg_to_dxf", lambda src, out_dir: dxf_path)

    def _fake_dxf_to_dwg(
        src: Path,
        output_dir: Path,
        target_version_code: str | None = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "converted.dwg"
        output_path.write_bytes(b"converted-dwg")
        return output_path

    class _FakeFactoryIndexReplacement:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def replace_if_configured(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            output_dwg = Path(kwargs["output_dwg"])  # type: ignore[index]
            output_dwg.parent.mkdir(parents=True, exist_ok=True)
            output_dwg.write_bytes(b"factory-index-dwg")
            return SimpleNamespace(
                applied=True,
                output_dwg=output_dwg,
                action_count=1,
                report_json=Path(kwargs["workspace_dir"]) / "factory_index_map.json",  # type: ignore[index]
                to_progress_dict=lambda: {"applied": True, "action_count": 1},
            )

    factory_index = _FakeFactoryIndexReplacement()

    monkeypatch.setattr(executor.oda, "dxf_to_dwg", _fake_dxf_to_dwg)
    monkeypatch.setattr(executor.frame_detector, "detect_frames", lambda path: [])
    monkeypatch.setattr(executor.titleblock_extractor, "extract_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor.a4_grouper, "group_a4_pages", lambda frames: ([], []))
    monkeypatch.setattr(
        executor.lexicon_loader,
        "load",
        lambda path: AuditLexicon(
            project_options=["2016", "1916"],
            allowed_texts={"2016": {"2016"}, "1916": {"1916"}},
            foreign_texts={"2016": {"1916"}, "1916": {"2016"}},
            token_projects={"2016": {"2016"}, "1916": {"1916"}},
        ),
    )
    monkeypatch.setattr(
        executor.mapping_builder,
        "build",
        lambda workbook_path, source_project_no, target_project_no: ReplaceMapping(
            source_project_no="2016",
            target_project_no="1916",
            replacements={"2016": "1916"},
            no_op_tokens=[],
            missing_target_tokens=[],
        ),
    )
    monkeypatch.setattr(
        executor.dotnet_scanner,
        "scan",
        lambda **kwargs: [
            ScanTextItem(raw_text="2016", entity_type="DBText", entity_handle=text_handle),
        ],
    )
    executor.factory_index_maps = factory_index

    job = Job(
        job_id="job-audit-replace-source-target-variants",
        job_type=JobType.AUDIT_REPLACE,
        project_no="1916",
        input_files=[source_dwg],
        options={"mode": "replace"},
        params={
            "source_project_no": "2016",
            "target_project_no": "1916",
            "source_island_no": "1号机组",
            "target_island_no": "4号岛",
        },
    )

    executor.execute(job)

    assert len(factory_index.calls) == 1
    assert factory_index.calls[0]["source_variant"] == "1"
    assert factory_index.calls[0]["target_variant"] == "4"
