"""
图框元数据模型 - 单个图框的运行期与图签字段

对应参数规范.yaml 的 doc_generation.frame_meta
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class BBox(BaseModel):
    """边界框"""

    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    def intersects(self, other: BBox) -> bool:
        """判断是否相交"""
        return not (
            self.xmax < other.xmin
            or self.xmin > other.xmax
            or self.ymax < other.ymin
            or self.ymin > other.ymax
        )


class TitleblockFields(BaseModel):
    """图签字段（从DXF ROI提取）"""

    internal_code: str | None = Field(None, description="内部编码(XXXXXXX-XXXXX-XXX)")
    external_code: str | None = Field(None, description="外部编码(19位)")
    album_code: str | None = Field(None, description="图册编号(从mid提取)")
    engineering_no: str | None = Field(None, description="工程号(4位)")
    subitem_no: str | None = Field(None, description="子项号")
    paper_size_text: str | None = Field(None, description="图幅(A0/A1/A2等)")
    discipline: str | None = Field(None, description="专业")
    scale_text: str | None = Field(None, description="比例(1:X)")
    scale_denominator: float | None = Field(None, description="比例分母")
    page_total: int | None = Field(None, description="共N张")
    page_index: int | None = Field(None, description="第M张")
    title_cn: str | None = Field(None, description="中文标题")
    title_en: str | None = Field(None, description="英文标题(仅1818)")
    revision: str | None = Field(None, description="版次")
    status: str | None = Field(None, description="状态")
    date: str | None = Field(None, description="日期")

    def get_seq_no(self) -> int | None:
        """从internal_code提取尾号(如001)"""
        if self.internal_code and "-" in self.internal_code:
            suffix = self.internal_code.rsplit("-", 1)[-1]
            if suffix.isdigit():
                return int(suffix)
        return None


class FrameRuntime(BaseModel):
    """图框运行期字段（DXF流水线生成）"""

    frame_id: str = Field(..., description="图框实例唯一ID")
    source_file: Path = Field(..., description="检测/提取来源文件路径（通常为DXF）")
    cad_source_file: Path | None = Field(None, description="CAD切图来源文件路径（优先DWG）")
    outer_bbox: BBox = Field(..., description="外框边界")
    outer_vertices: list[tuple[float, float]] = Field(
        default_factory=list,
        description="图框四顶点坐标（按左下/右下/右上/左上）",
    )

    # 纸张拟合结果
    paper_variant_id: str | None = Field(None, description="匹配的标准图幅ID")
    sx: float | None = Field(None, description="X方向缩放因子")
    sy: float | None = Field(None, description="Y方向缩放因子")
    geom_scale_factor: float | None = Field(None, description="几何缩放因子")
    roi_profile_id: str | None = Field(None, description="使用的ROI配置")

    # 状态标记
    scale_mismatch: bool = False
    flags: list[str] = Field(default_factory=list)

    # 输出路径
    pdf_path: Path | None = None
    dwg_path: Path | None = None

    model_config = {"arbitrary_types_allowed": True}


class FrameMeta(BaseModel):
    """图框完整元数据（运行期+图签）"""

    runtime: FrameRuntime
    titleblock: TitleblockFields = Field(default_factory=TitleblockFields)

    # 原始提取数据（用于调试）
    raw_extracts: dict[str, Any] = Field(default_factory=dict)

    @property
    def frame_id(self) -> str:
        return self.runtime.frame_id

    @property
    def internal_code(self) -> str | None:
        return self.titleblock.internal_code

    def add_flag(self, flag: str) -> None:
        """添加告警标记"""
        if flag not in self.runtime.flags:
            self.runtime.flags.append(flag)
