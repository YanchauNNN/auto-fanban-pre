from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

from src.cad.cad_dxf_executor import CADDXFExecutor
from src.config import RuntimeConfig
from src.models import BBox, FrameMeta, FrameRuntime, TitleblockFields


class _SpecStub:
    doc_generation = {
        "options": {
            "pdf_margin_mm": {"top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0},
        },
    }

    class _Variant:
        def __init__(self, w: float, h: float) -> None:
            self.W = w
            self.H = h

    def get_paper_variants(self):
        return {"A1": self._Variant(841.0, 594.0)}


def _make_frame() -> FrameMeta:
    return FrameMeta(
        runtime=FrameRuntime(
            frame_id="f-001",
            source_file=Path("sample.dxf"),
            outer_bbox=BBox(xmin=0.0, ymin=0.0, xmax=100.0, ymax=50.0),
            outer_vertices=[],
            paper_variant_id="A1",
            sx=1.0,
            sy=1.0,
        ),
        titleblock=TitleblockFields(
            internal_code="18185PE-JZS02-001",
            external_code="PC5PEX11001B25C42SD",
            revision="A",
            status="CFC",
        ),
    )


def test_build_window_plot_frame_entry_keeps_bbox_when_mismatch_small() -> None:
    cfg = RuntimeConfig()
    executor = CADDXFExecutor(config=cfg, runner=cast(Any, MagicMock()), spec=_SpecStub())

    entry, flags = executor._build_window_plot_frame_entry(
        frame=_make_frame(),
        split_item={
            "selection_extents": {"xmin": -0.5, "ymin": 0.0, "xmax": 100.4, "ymax": 50.4},
        },
    )

    assert "plot_window_bbox" not in entry
    assert flags == []


def test_build_window_plot_frame_entry_switches_when_mismatch_large() -> None:
    cfg = RuntimeConfig()
    executor = CADDXFExecutor(config=cfg, runner=cast(Any, MagicMock()), spec=_SpecStub())

    entry, flags = executor._build_window_plot_frame_entry(
        frame=_make_frame(),
        split_item={
            "selection_extents": {"xmin": -3.0, "ymin": -1.0, "xmax": 100.0, "ymax": 50.0},
        },
    )

    assert entry["plot_window_bbox"] == {"xmin": -3.0, "ymin": -1.0, "xmax": 100.0, "ymax": 50.0}
    assert "PLOT_WINDOW_SELECTION_EXTENTS_USED" in flags
