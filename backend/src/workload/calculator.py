from __future__ import annotations

import re

from ..config import BusinessSpec, load_spec
from ..pipeline.shared_prep import SharedPrepArtifacts
from .models import WorkloadSummary


class WorkloadCalculator:
    def __init__(self, spec: BusinessSpec | None = None) -> None:
        self.spec = spec or load_spec()
        workload_cfg = dict(self.spec.get_management_features().get("workload") or {})
        self.a1_map = {str(key).upper(): float(value) for key, value in dict(workload_cfg.get('a1_equivalent') or {}).items()}
        self.precision = int(workload_cfg['precision'])
        self._paper_variant_pattern = self._build_paper_variant_pattern()

    def build_from_shared_prep(self, prep: SharedPrepArtifacts) -> WorkloadSummary:
        return self.build_from_frame_sets(prep.frames, prep.sheet_sets)

    def build_from_frame_sets(self, frames: list, sheet_sets: list) -> WorkloadSummary:
        initial = 0.0
        for frame in frames:
            initial += self._value_for_variant(frame.runtime.paper_variant_id)
        for sheet_set in sheet_sets:
            initial += float(sheet_set.page_total) * self._value_for_variant(sheet_set.paper)
        initial = round(initial, self.precision)
        return WorkloadSummary(initial_workload_a1=initial, final_workload_a1=initial)

    def refresh_final(self, summary: WorkloadSummary) -> WorkloadSummary:
        node_factors = list(summary.node_factors.values())
        if node_factors:
            factor_product = 1.0
            for factor in node_factors:
                factor_product *= float(factor)
        else:
            factor_product = (
                summary.one_review_factor
                * summary.two_review_factor
                * summary.three_review_factor
            )
        summary.final_workload_a1 = round(
            summary.initial_workload_a1 * factor_product,
            self.precision,
        )
        return summary

    def _value_for_variant(self, value: str | None) -> float:
        text = str(value or '').upper()
        match = self._paper_variant_pattern.search(text) if self._paper_variant_pattern else None
        if match is None:
            return 0.0
        return float(self.a1_map.get(match.group(0), 0.0))

    def _build_paper_variant_pattern(self) -> re.Pattern[str] | None:
        keys = sorted((re.escape(key) for key in self.a1_map), key=len, reverse=True)
        if not keys:
            return None
        return re.compile("|".join(keys))
