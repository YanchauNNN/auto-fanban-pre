from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.pipeline.executor import PipelineExecutor


def _make_executor_with_engine(engine: str) -> PipelineExecutor:
    executor = object.__new__(PipelineExecutor)
    executor.config = SimpleNamespace(module5_export=SimpleNamespace(engine=engine))
    return executor


def test_stage_split_routes_to_cad_dxf():
    executor = _make_executor_with_engine("cad_dxf")
    executor._stage_split_cad_dxf = MagicMock()

    PipelineExecutor._stage_split(executor, MagicMock(), {"frames": [], "sheet_sets": []})

    executor._stage_split_cad_dxf.assert_called_once()


def test_stage_export_routes_to_cad_dxf():
    executor = _make_executor_with_engine("cad_dxf")
    executor._stage_export_cad_dxf = MagicMock()

    PipelineExecutor._stage_export(executor, MagicMock(), {"frames": [], "sheet_sets": []})

    executor._stage_export_cad_dxf.assert_called_once()

