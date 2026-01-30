"""
图框检测子模块 - 候选矩形查找、锚点验证、纸张拟合

子模块：
- candidate_finder: 从DXF中查找闭合矩形候选
- anchor_calibrated_locator: 锚点校准直推定位
- anchor_first_locator: 锚点验证回退定位
- paper_fitter: 拟合标准纸张尺寸
"""

from .anchor_calibrated_locator import AnchorCalibratedLocator
from .anchor_first_locator import AnchorFirstLocator
from .candidate_finder import CandidateFinder
from .paper_fitter import PaperFitter

__all__ = [
    "AnchorCalibratedLocator",
    "AnchorFirstLocator",
    "CandidateFinder",
    "PaperFitter",
]
