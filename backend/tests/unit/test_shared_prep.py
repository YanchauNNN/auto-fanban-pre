from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from src.models import BBox, FrameMeta, FrameRuntime
from src.pipeline.shared_prep import SharedPrepService


class _FakeFontPreflightService:
    def __init__(self, summary: dict[str, Any]) -> None:
        self.summary = summary
        self.calls: list[dict[str, Any]] = []

    def validate_replacement_font(self, font_name: str) -> bool:
        return font_name == "simsun.ttc"

    def inspect_dwg(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        return dict(self.summary)


class _FakeODA:
    def dwg_to_dxf(self, source_dwg: Path, shared_dir: Path) -> Path:
        dxf_path = shared_dir / f"{source_dwg.stem}.dxf"
        dxf_path.write_text("0\nEOF\n", encoding="utf-8")
        return dxf_path


class _FakeFrameDetector:
    def __init__(self, frames: list[Any] | None = None) -> None:
        self.project_no: str | None = None
        self.frames = list(frames or [])

    def set_project_no(self, project_no: str | None) -> None:
        self.project_no = project_no

    def detect_frames(self, dxf_path: Path) -> list[Any]:
        return list(self.frames)


class _FakeTitleblockExtractor:
    def __init__(self) -> None:
        self.project_no: str | None = None

    def set_project_no(self, project_no: str | None) -> None:
        self.project_no = project_no

    def extract_fields(self, dxf_path: Path, frame: Any) -> None:
        return None


class _FakeA4Grouper:
    def group_a4_pages(self, frames: list[Any]) -> tuple[list[Any], list[Any]]:
        return frames, []


def _make_service(summary: dict[str, Any]) -> SharedPrepService:
    service = SharedPrepService(font_preflight_service=cast(Any, _FakeFontPreflightService(summary)))
    service.oda = cast(Any, _FakeODA())
    service.frame_detector = cast(Any, _FakeFrameDetector())
    service.titleblock_extractor = cast(Any, _FakeTitleblockExtractor())
    service.a4_grouper = cast(Any, _FakeA4Grouper())
    return service


def _make_frame(frame_id: str) -> FrameMeta:
    return FrameMeta(
        runtime=FrameRuntime(
            frame_id=frame_id,
            source_file=Path("sample.dxf"),
            outer_bbox=BBox(xmin=0, ymin=0, xmax=100, ymax=100),
            sx=1.0,
            sy=1.0,
            roi_profile_id="BASE10",
        ),
    )


def test_shared_prep_blocks_when_missing_fonts_are_unconfirmed(tmp_path: Path) -> None:
    service = _make_service(
        {
            "status": "missing_fonts",
            "missing_fonts": [{"style_name": "STYLE1"}],
            "detected_style_count": 3,
            "missing_style_count": 1,
            "font_replacement_applied": False,
            "replacement_font": None,
            "replaced_style_count": 0,
        }
    )
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing fonts detected"):
        service.prepare(group_id="g1", source_dwg=source, shared_dir=tmp_path / "shared")

def test_shared_prep_allows_replace_missing_and_records_summary(tmp_path: Path) -> None:
    service = _make_service(
        {
            "status": "missing_fonts",
            "missing_fonts": [{"style_name": "STYLE1"}],
            "detected_style_count": 3,
            "missing_style_count": 1,
            "font_replacement_applied": True,
            "replacement_font": "simsun.ttc",
            "replaced_style_count": 1,
        }
    )
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    prep = service.prepare(
        group_id="g1",
        source_dwg=source,
        shared_dir=tmp_path / "shared",
        font_replace_policy="replace_missing",
        font_replacement_font="simsun.ttc",
    )

    assert prep.font_preflight_summary["replacement_font"] == "simsun.ttc"
    assert prep.font_preflight_summary["font_replacement_applied"] is True


def test_shared_prep_passes_font_compatibility_mode_to_preflight(tmp_path: Path) -> None:
    service = _make_service(
        {
            "status": "ok",
            "missing_fonts": [],
            "detected_style_count": 3,
            "missing_style_count": 0,
            "font_replacement_applied": True,
            "replacement_font": None,
            "font_compatibility_mode": True,
            "replaced_style_count": 1,
        }
    )
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    service.prepare(
        group_id="g1",
        source_dwg=source,
        shared_dir=tmp_path / "shared",
        font_compatibility_mode=True,
    )

    assert service.font_preflight_service.calls[0]["font_compatibility_mode"] is True


def test_shared_prep_passes_detected_frames_to_font_preflight(tmp_path: Path) -> None:
    service = _make_service(
        {
            "status": "ok",
            "missing_fonts": [],
            "detected_style_count": 3,
            "missing_style_count": 0,
            "font_replacement_applied": True,
            "replacement_font": None,
            "font_compatibility_mode": True,
            "replaced_style_count": 1,
        }
    )
    frame = _make_frame("frame-font-target")
    service.frame_detector = cast(Any, _FakeFrameDetector([frame]))
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    service.prepare(
        group_id="g1",
        source_dwg=source,
        shared_dir=tmp_path / "shared",
        font_compatibility_mode=True,
    )

    assert service.font_preflight_service.calls[0]["frames"] == [frame]


def test_shared_prep_sets_project_no_before_detection(tmp_path: Path) -> None:
    service = _make_service(
        {
            "status": "ok",
            "missing_fonts": [],
            "detected_style_count": 0,
            "missing_style_count": 0,
            "font_replacement_applied": False,
            "replacement_font": None,
            "replaced_style_count": 0,
        }
    )
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    service.prepare(
        group_id="g1",
        project_no="1818",
        source_dwg=source,
        shared_dir=tmp_path / "shared",
    )

    assert service.frame_detector.project_no == "1818"


def test_shared_prep_sets_project_no_on_titleblock_extractor(tmp_path: Path) -> None:
    service = _make_service(
        {
            "status": "ok",
            "missing_fonts": [],
            "detected_style_count": 0,
            "missing_style_count": 0,
            "font_replacement_applied": False,
            "replacement_font": None,
            "replaced_style_count": 0,
        }
    )
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    service.prepare(
        group_id="g1",
        project_no="1818",
        source_dwg=source,
        shared_dir=tmp_path / "shared",
    )

    assert service.titleblock_extractor.project_no == "1818"


def test_shared_prep_filters_out_frames_that_failed_anchor_validation(tmp_path: Path) -> None:
    service = _make_service(
        {
            "status": "ok",
            "missing_fonts": [],
            "detected_style_count": 0,
            "missing_style_count": 0,
            "font_replacement_applied": False,
            "replacement_font": None,
            "replaced_style_count": 0,
        }
    )
    valid_frame = _make_frame("valid-frame")
    invalid_frame = _make_frame("invalid-frame")
    service.frame_detector = cast(Any, _FakeFrameDetector([valid_frame, invalid_frame]))

    class _FlaggingExtractor(_FakeTitleblockExtractor):
        def extract_fields(self, dxf_path: Path, frame: Any) -> None:
            if frame.frame_id == "invalid-frame":
                frame.add_flag("未命中锚点文本")

    service.titleblock_extractor = cast(Any, _FlaggingExtractor())

    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")

    prep = service.prepare(
        group_id="g1",
        project_no="1818",
        source_dwg=source,
        shared_dir=tmp_path / "shared",
    )

    assert [frame.frame_id for frame in prep.frames] == ["valid-frame"]
    assert (prep.shared_dir / "excluded_frames.json").exists()
