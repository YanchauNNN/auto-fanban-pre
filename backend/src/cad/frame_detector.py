"""
图框检测器 - 识别DXF中的图框

职责：
1. 解析DXF找到候选矩形（闭合polyline优先，LINE重建兜底）
2. 锚点验证（CNPE/中国核电工程有限公司）
3. 纸张尺寸拟合（确定paper_variant/sx/sy/roi_profile）

依赖：
- ezdxf: DXF解析
- 参数规范.yaml: paper_variants/roi_profiles/anchor配置

测试要点：
- test_detect_single_frame: 单图框检测
- test_detect_multiple_frames: 多图框检测（同一DXF内）
- test_paper_fitting: 纸张尺寸拟合（各种图幅）
- test_anchor_verification: 锚点验证
- test_scale_mismatch_flag: 比例不一致标记
"""

from __future__ import annotations

from pathlib import Path

import ezdxf

from ..config import load_spec
from ..interfaces import DetectionError, IFrameDetector
from ..models import BBox, FrameMeta
from .detection import (
    AnchorCalibratedLocator,
    AnchorFirstLocator,
    CandidateFinder,
    PaperFitter,
)


class FrameDetector(IFrameDetector):
    """图框检测器实现"""

    def __init__(
        self,
        spec_path: str | None = None,
        min_frame_dim: float = 100.0,
        project_no: str | None = None,
        frame_detect_mode: str | None = None,
    ):
        self.spec = load_spec(spec_path) if spec_path else load_spec()
        self.paper_variants = self.spec.get_paper_variants()
        principles = self.spec.titleblock_extract.get("principles", {})
        self.frame_detect_mode = str(
            frame_detect_mode or principles.get("detection_mode", "geometry_first")
        )
        outer_frame_cfg = self.spec.titleblock_extract.get("outer_frame", {})
        layer_priority = outer_frame_cfg.get("layer_priority", {})
        layers = layer_priority.get("layers")
        if not layers:
            primary = layer_priority.get("primary_layer", "_TSZ-PLOT_MARK")
            secondary = layer_priority.get("secondary_layer", "0")
            layers = [primary, secondary]
        entity_order = layer_priority.get("entity_order", ["LWPOLYLINE", "POLYLINE", "LINE"])
        line_rebuild_limits = outer_frame_cfg.get("line_rebuild_limits", {})
        acceptance_cfg = outer_frame_cfg.get("acceptance", {})
        orthogonality_tol_deg = float(acceptance_cfg.get("orthogonality_tol_deg", 1.0))
        self.max_candidates = (
            acceptance_cfg.get("min_area_rank")
            if isinstance(acceptance_cfg.get("min_area_rank"), int)
            else None
        )
        base_profile = self.spec.get_roi_profile("BASE10")
        coord_tol = base_profile.tolerance if base_profile else 0.5

        scale_fit_cfg = self.spec.titleblock_extract.get("scale_fit", {})
        self.paper_fitter = PaperFitter(
            allow_rotation=bool(scale_fit_cfg.get("allow_rotation", True)),
            uniform_scale_required=bool(scale_fit_cfg.get("uniform_scale_required", True)),
            uniform_scale_tol=float(scale_fit_cfg.get("uniform_scale_tol", 0.02)),
            error_metric=str(scale_fit_cfg.get("fit_error_metric", "max_rel_error(W,H)")),
        )
        anchor_cfg = self.spec.titleblock_extract.get("anchor", {})
        scale_candidates = anchor_cfg.get("scale_candidates", [])
        scale_candidate_set: set[int] = set()
        for c in scale_candidates:
            try:
                scale_candidate_set.add(int(float(c)))
            except (TypeError, ValueError):
                continue
        scale_candidate_match_tol = float(scale_fit_cfg.get("scale_candidate_match_tol", 0.015))

        def bbox_scale_validator(bbox: BBox) -> bool:
            if not scale_candidate_set:
                return True
            fits = self.paper_fitter.fit_all(bbox, self.paper_variants)
            if not fits:
                return False
            _paper_id, sx, sy, _profile_id, _error = min(fits, key=lambda f: f[4])
            scale = (sx + sy) / 2.0
            nearest = round(scale)
            if nearest < 1 or nearest not in scale_candidate_set:
                return False
            rel_err = abs(scale - nearest) / nearest
            return rel_err <= scale_candidate_match_tol

        self.candidate_finder = CandidateFinder(
            min_dim=min_frame_dim,
            coord_tol=coord_tol,
            orthogonality_tol_deg=orthogonality_tol_deg,
            layer_order=layers,
            entity_order=entity_order,
            line_rebuild_limits=line_rebuild_limits,
            bbox_scale_validator=bbox_scale_validator,
        )
        self.anchor_locator = AnchorFirstLocator(
            self.spec,
            self.candidate_finder,
            self.paper_fitter,
            max_candidates=self.max_candidates,
            project_no=project_no,
        )
        self.anchor_calibrated_locator = AnchorCalibratedLocator(
            self.spec,
            self.candidate_finder,
            self.paper_fitter,
            max_candidates=self.max_candidates,
            project_no=project_no,
        )

    def detect_frames(self, dxf_path: Path) -> list[FrameMeta]:
        """检测DXF中的所有图框"""
        if not dxf_path.exists():
            raise DetectionError(f"DXF文件不存在: {dxf_path}")

        try:
            doc = ezdxf.readfile(str(dxf_path))
        except Exception as e:
            raise DetectionError(f"DXF解析失败: {e}") from e

        msp = doc.modelspace()

        if self.frame_detect_mode == "rb_anchor":
            return self.anchor_calibrated_locator.locate_frames(msp, dxf_path)
        return self.anchor_locator.locate_frames(msp, dxf_path)
