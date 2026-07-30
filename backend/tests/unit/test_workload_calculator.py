from __future__ import annotations

from src.pipeline.shared_prep import SharedPrepArtifacts
from src.workload.calculator import WorkloadCalculator
from src.workload.models import WorkloadSummary


class _WorkloadSpec:
    def __init__(self, workload_cfg: dict[str, object]) -> None:
        self.workload_cfg = workload_cfg

    def get_management_features(self) -> dict[str, object]:
        return {"workload": self.workload_cfg}


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


def test_workload_calculator_uses_yaml_a_size_keys(sample_frame, tmp_path) -> None:
    frame = sample_frame.model_copy(deep=True)
    frame.runtime.paper_variant_id = "CUSTOM_A5"
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()
    artifacts = SharedPrepArtifacts(
        shared_dir=shared_dir,
        source_input_dwg=tmp_path / "input.dwg",
        source_converted_dxf=tmp_path / "input.dxf",
        font_preflight_summary={},
        frames=[frame],
        sheet_sets=[],
    )

    summary = WorkloadCalculator(
        _WorkloadSpec({"a1_equivalent": {"A5": 0.0625}, "precision": 4})
    ).build_from_shared_prep(artifacts)

    assert summary.initial_workload_a1 == 0.0625


def test_workload_calculator_uses_yaml_node_factors() -> None:
    summary = WorkloadSummary(
        initial_workload_a1=2.0,
        final_workload_a1=2.0,
        node_factors={"custom_review": 1.25},
    )

    WorkloadCalculator(_WorkloadSpec({"precision": 3})).refresh_final(summary)

    assert summary.final_workload_a1 == 2.5
