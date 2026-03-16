"""
纸张尺寸拟合器 - 将图框尺寸拟合到标准图幅

拟合策略：
1. 遍历所有标准图幅（从spec读取）
2. 计算缩放因子 sx = W_obs / W_std, sy = H_obs / H_std
3. 检查是否为均匀缩放（|sx - sy| < tolerance）
4. 选择拟合误差最小的图幅
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...models import BBox


class PaperFitter:
    """纸张尺寸拟合器"""

    def __init__(
        self,
        allow_rotation: bool = False,
        uniform_scale_required: bool = True,
        uniform_scale_tol: float = 0.02,
        error_metric: str = "max_rel_error(W,H)",
    ) -> None:
        self.allow_rotation = allow_rotation
        self.uniform_scale_required = uniform_scale_required
        self.uniform_scale_tol = uniform_scale_tol
        self.error_metric = error_metric

    def fit(
        self,
        bbox: BBox,
        paper_variants: Mapping[str, object],
    ) -> tuple[str, float, float, str] | None:
        """
        拟合标准纸张尺寸

        Args:
            bbox: 观测到的外框BBox
            paper_variants: 标准图幅字典 {id: {W, H, profile}} 或 PaperVariant

        Returns:
            (paper_variant_id, sx, sy, roi_profile_id) or None
        """
        best_match = None
        best_error = float("inf")

        for variant_id, sx, sy, profile, error in self.fit_all(bbox, paper_variants):
            if error < best_error:
                best_error = error
                best_match = (variant_id, sx, sy, profile)

        return best_match

    def fit_all(
        self,
        bbox: BBox,
        paper_variants: Mapping[str, object],
    ) -> list[tuple[str, float, float, str, float]]:
        """返回所有满足拟合条件的候选"""
        W_obs = bbox.width
        H_obs = bbox.height
        results: list[tuple[str, float, float, str, float]] = []

        for variant_id, variant in paper_variants.items():
            # 统一处理：优先尝试属性访问，失败则尝试字典访问
            try:
                W_std = variant.W  # type: ignore[union-attr]
                H_std = variant.H  # type: ignore[union-attr]
                profile = variant.profile  # type: ignore[union-attr]
            except AttributeError:
                mapping_variant = variant if isinstance(variant, Mapping) else {}
                W_std = mapping_variant.get("W")
                H_std = mapping_variant.get("H")
                profile = mapping_variant.get("profile")

            if not W_std or not H_std or not profile:
                continue

            if not isinstance(W_std, (int, float)) or not isinstance(H_std, (int, float)):
                continue
            if not isinstance(profile, str):
                continue

            candidate = self._evaluate_variant(W_obs, H_obs, W_std, H_std)
            if candidate:
                sx, sy, error = candidate
                results.append((variant_id, sx, sy, profile, error))

            if self.allow_rotation:
                candidate = self._evaluate_variant(W_obs, H_obs, H_std, W_std)
                if candidate:
                    sx, sy, error = candidate
                    results.append((variant_id, sx, sy, profile, error))

        return results

    def _evaluate_variant(
        self, W_obs: float, H_obs: float, W_std: float, H_std: float
    ) -> tuple[float, float, float] | None:
        sx = W_obs / W_std
        sy = H_obs / H_std

        if self.uniform_scale_required:
            scale_diff = abs(sx - sy)
            if scale_diff / max(sx, sy, 1e-9) > self.uniform_scale_tol:
                return None

        error = self._compute_error(W_obs, H_obs, W_std, H_std, sx, sy)
        return sx, sy, error

    def _compute_error(
        self,
        W_obs: float,
        H_obs: float,
        W_std: float,
        H_std: float,
        sx: float,
        sy: float,
    ) -> float:
        if self.error_metric == "max_rel_error(W,H)":
            scale = (sx + sy) / 2.0
            return max(
                abs(W_std * scale - W_obs) / max(W_obs, 1e-9),
                abs(H_std * scale - H_obs) / max(H_obs, 1e-9),
            )
        return abs(sx - sy) / max(sx, sy, 1e-9)
