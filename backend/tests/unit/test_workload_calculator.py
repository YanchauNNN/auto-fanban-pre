from __future__ import annotations

from src.pipeline.shared_prep import SharedPrepArtifacts
from src.workload.calculator import WorkloadCalculator


def test_workload_calculator_uses_frames_and_a4_sheet_sets(sample_frame, tmp_path) -> None:
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()
    artifacts = SharedPrepArtifacts(
        shared_dir=shared_dir,
        source_input_dwg=tmp_path / "input.dwg",
        source_converted_dxf=tmp_path / "input.dxf",
        font_preflight_summary={},
        frames=[sample_frame],
        sheet_sets=[],
    )

    summary = WorkloadCalculator().build_from_shared_prep(artifacts)

    assert summary.initial_workload_a1 == 1.0
    assert summary.final_workload_a1 == 1.0
