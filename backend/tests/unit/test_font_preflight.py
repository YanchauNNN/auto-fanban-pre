from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from src.cad.font_inventory import InstalledFontInventory
from src.cad.font_preflight import FontPreflightService
from src.models import Job, JobType
from src.pipeline.executor import PipelineExecutor


class _FakeInventory:
    def __init__(self, options: list[dict[str, str]]) -> None:
        self._options = options
        self.requested_kinds: set[str] | None = None

    def list_options(self, *, preferred_kinds: set[str] | None = None) -> list[dict[str, str]]:
        self.requested_kinds = set(preferred_kinds or []) or None
        return list(self._options)

    def is_valid_font(self, value: str) -> bool:
        return any(option["value"] == value for option in self._options)


class _FakeBridge:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.touch_source_on_preflight = False
        self.touch_source_on_replace = False

    def preflight(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "preflight", **kwargs})
        if self.touch_source_on_preflight:
            Path(kwargs["source_dwg"]).write_bytes(b"AC1032-mutated")
        return {
            "status": "missing_fonts",
            "missing_fonts": [
                {
                    "style_name": "STYLE1",
                    "font_name": "missing.shx",
                    "bigfont_name": "",
                    "kind": "shx",
                    "used_in_block": True,
                }
            ],
            "detected_style_count": 4,
            "missing_style_count": 1,
            "font_replacement_applied": False,
            "replaced_style_count": 0,
        }

    def replace_missing(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "replace_missing", **kwargs})
        if self.touch_source_on_replace:
            Path(kwargs["source_dwg"]).write_bytes(b"AC1024-replaced")
        return {
            "status": "missing_fonts",
            "missing_fonts": [
                {
                    "style_name": "STYLE1",
                    "font_name": "missing.shx",
                    "bigfont_name": "",
                    "kind": "shx",
                    "used_in_block": True,
                }
            ],
            "detected_style_count": 4,
            "missing_style_count": 1,
            "font_replacement_applied": True,
            "replacement_font": kwargs["replacement_font"],
            "replaced_style_count": 1,
        }


def test_font_preflight_service_requires_known_replacement_font(tmp_path: Path) -> None:
    service = FontPreflightService(
        inventory=cast(
            Any,
            _FakeInventory(
                [
                    {
                        "label": "simplex.shx",
                        "value": "simplex.shx",
                        "family": "simplex",
                        "path": r"D:\AutoCAD\Fonts\simplex.shx",
                        "kind": "shx",
                    }
                ]
            ),
        ),
        bridge=cast(Any, _FakeBridge()),
    )
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    with pytest.raises(ValueError, match="font_replacement_font is unavailable"):
        service.inspect_dwg(
            source_dwg=source,
            replacement_policy="replace_missing",
            replacement_font="arial.ttf",
            workspace_dir=tmp_path / "work",
        )


def test_font_preflight_service_uses_replace_missing_when_requested(tmp_path: Path) -> None:
    bridge = _FakeBridge()
    service = FontPreflightService(
        inventory=cast(
            Any,
            _FakeInventory(
                [
                    {
                        "label": "simplex.shx",
                        "value": "simplex.shx",
                        "family": "simplex",
                        "path": r"D:\AutoCAD\Fonts\simplex.shx",
                        "kind": "shx",
                    }
                ]
            ),
        ),
        bridge=cast(Any, bridge),
    )
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    result = service.inspect_dwg(
        source_dwg=source,
        replacement_policy="replace_missing",
        replacement_font="simplex.shx",
        workspace_dir=tmp_path / "work",
    )

    assert bridge.calls[0]["method"] == "replace_missing"
    assert result["font_replacement_applied"] is True
    assert result["replacement_font"] == "simplex.shx"
    assert result["replaced_style_count"] == 1


def test_font_preflight_service_uses_staged_copy_for_preflight(tmp_path: Path) -> None:
    bridge = _FakeBridge()
    bridge.touch_source_on_preflight = True
    service = FontPreflightService(
        inventory=cast(Any, _FakeInventory([])),
        bridge=cast(Any, bridge),
    )
    source = tmp_path / "sample.dwg"
    source.write_bytes(b"AC1024-original")

    service.inspect_dwg(
        source_dwg=source,
        replacement_policy="none",
        workspace_dir=tmp_path / "work",
    )

    assert bridge.calls[0]["method"] == "preflight"
    assert Path(bridge.calls[0]["source_dwg"]).resolve() != source.resolve()
    assert source.read_bytes().startswith(b"AC1024-original")


def test_font_preflight_service_stages_unicode_filename_into_safe_workspace(tmp_path: Path) -> None:
    bridge = _FakeBridge()
    service = FontPreflightService(
        inventory=cast(Any, _FakeInventory([])),
        bridge=cast(Any, bridge),
    )
    source = tmp_path / "20162PR-JGS01 汇总B版.dwg"
    source.write_bytes(b"AC1024-original")

    service.inspect_dwg(
        source_dwg=source,
        replacement_policy="none",
        workspace_dir=tmp_path / "work",
    )

    staged = Path(bridge.calls[0]["source_dwg"])
    assert staged.resolve() != source.resolve()
    assert staged.parent.resolve().parent == (tmp_path / "work").resolve()
    assert staged.name != source.name
    assert staged.suffix.lower() == ".dwg"
    assert all(ord(ch) < 128 for ch in staged.name)


def test_font_preflight_service_copies_replaced_result_back_to_original(tmp_path: Path) -> None:
    bridge = _FakeBridge()
    bridge.touch_source_on_replace = True
    service = FontPreflightService(
        inventory=cast(
            Any,
            _FakeInventory(
                [
                    {
                        "label": "gbcbig.shx",
                        "value": "gbcbig.shx",
                        "family": "gbcbig",
                        "path": r"D:\AutoCAD\Fonts\gbcbig.shx",
                        "kind": "shx",
                    }
                ]
            ),
        ),
        bridge=cast(Any, bridge),
    )
    source = tmp_path / "sample.dwg"
    source.write_bytes(b"AC1024-original")

    service.inspect_dwg(
        source_dwg=source,
        replacement_policy="replace_missing",
        replacement_font="gbcbig.shx",
        workspace_dir=tmp_path / "work",
    )

    assert bridge.calls[0]["method"] == "replace_missing"
    assert Path(bridge.calls[0]["source_dwg"]).resolve() != source.resolve()
    assert source.read_bytes().startswith(b"AC1024-replaced")


def test_font_preflight_service_filters_replacement_options_by_missing_kinds(tmp_path: Path) -> None:
    inventory = _FakeInventory(
        [
            {
                "label": "simplex.shx",
                "value": "simplex.shx",
                "family": "simplex",
                "path": r"D:\AutoCAD\Fonts\simplex.shx",
                "kind": "shx",
            },
        ]
    )
    service = FontPreflightService(
        inventory=cast(Any, inventory),
        bridge=cast(Any, _FakeBridge()),
    )

    options = service.list_replacement_options(missing_kinds=["shx"])

    assert inventory.requested_kinds == {"shx"}
    assert options[0]["value"] == "simplex.shx"


def test_font_preflight_service_never_returns_windows_ttf_replacements(tmp_path: Path) -> None:
    inventory = _FakeInventory(
        [
            {
                "label": "simplex.shx",
                "value": "simplex.shx",
                "family": "simplex",
                "path": r"D:\AutoCAD\Fonts\simplex.shx",
                "kind": "shx",
            }
        ]
    )
    service = FontPreflightService(
        inventory=cast(Any, inventory),
        bridge=cast(Any, _FakeBridge()),
    )

    options = service.list_replacement_options(missing_kinds=["ttf"])

    assert inventory.requested_kinds == {"ttf"}
    assert options == [
        {
            "label": "simplex.shx",
            "value": "simplex.shx",
            "family": "simplex",
            "path": r"D:\AutoCAD\Fonts\simplex.shx",
            "kind": "shx",
        }
    ]
    assert service.validate_replacement_font("simsun.ttc") is False


def test_installed_font_inventory_only_returns_autocad_fonts(tmp_path: Path) -> None:
    autocad_fonts_dir = tmp_path / "Fonts"
    autocad_fonts_dir.mkdir()
    (autocad_fonts_dir / "simplex.shx").write_text("", encoding="utf-8")
    windows_fonts_dir = tmp_path / "WindowsFonts"
    windows_fonts_dir.mkdir()
    (windows_fonts_dir / "simsun.ttc").write_text("", encoding="utf-8")

    inventory = InstalledFontInventory(
        autocad_fonts_dirs=[autocad_fonts_dir],
        windows_fonts_dir=windows_fonts_dir,
        include_registry=False,
        include_windows_fonts=True,
    )

    options = inventory.list_options(preferred_kinds={"ttf"})

    assert options == [
        {
            "label": "simplex.shx (AutoCAD SHX)",
            "value": "simplex.shx",
            "family": "simplex",
            "path": str(autocad_fonts_dir / "simplex.shx"),
            "kind": "shx",
            "source": "autocad_fonts",
        }
    ]
    assert inventory.is_valid_font("simplex.shx") is True
    assert inventory.is_valid_font("simsun.ttc") is False


def test_stage_font_preflight_blocks_when_missing_fonts_are_unconfirmed(tmp_path: Path) -> None:
    executor = object.__new__(PipelineExecutor)
    executor._update_progress = MagicMock()
    executor.font_preflight_service = MagicMock()
    executor.font_preflight_service.inspect_dwg.return_value = {
        "filename": "sample.dwg",
        "status": "missing_fonts",
        "missing_fonts": [{"style_name": "STYLE1"}],
        "detected_style_count": 2,
        "missing_style_count": 1,
        "font_replacement_applied": False,
        "replacement_font": None,
        "replaced_style_count": 0,
    }

    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "sample.dwg").write_text("dwg", encoding="utf-8")

    job = Job(
        job_id="job-font-stage-missing",
        job_type=JobType.DELIVERABLE,
        project_no="2016",
        work_dir=tmp_path,
        params={"font_replace_policy": "none"},
    )

    with pytest.raises(RuntimeError, match="missing fonts detected"):
        PipelineExecutor._stage_font_preflight_and_replace(executor, job, {})

    assert job.missing_fonts_detected is True
    assert job.font_replacement_applied is False


def test_stage_font_preflight_updates_job_summary_after_replacement(tmp_path: Path) -> None:
    executor = object.__new__(PipelineExecutor)
    executor._update_progress = MagicMock()
    executor.font_preflight_service = MagicMock()
    executor.font_preflight_service.validate_replacement_font.return_value = True
    executor.font_preflight_service.inspect_dwg.return_value = {
        "filename": "sample.dwg",
        "status": "missing_fonts",
        "missing_fonts": [{"style_name": "STYLE1"}],
        "detected_style_count": 2,
        "missing_style_count": 1,
        "font_replacement_applied": True,
        "replacement_font": "simplex.shx",
        "replaced_style_count": 1,
    }

    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "sample.dwg").write_text("dwg", encoding="utf-8")

    job = Job(
        job_id="job-font-stage-replaced",
        job_type=JobType.DELIVERABLE,
        project_no="2016",
        work_dir=tmp_path,
        params={"font_replace_policy": "replace_missing", "font_replacement_font": "simplex.shx"},
    )

    PipelineExecutor._stage_font_preflight_and_replace(executor, job, {})

    assert job.font_preflight_summary["policy"] == "replace_missing"
    assert job.missing_fonts_detected is True
    assert job.font_replacement_applied is True
    assert job.replacement_font == "simplex.shx"
    assert job.replaced_style_count == 1
