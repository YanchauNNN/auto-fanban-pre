"""
文档生成上下文 - 文档生成模块的输入结构

文档生成模块只消费这个结构化数据，与CAD模块完全解耦
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .frame import FrameMeta
from .sheet_set import SheetSet


class GlobalDocParams(BaseModel):
    """全局文档参数（前端输入+图签聚合+派生）"""

    # === 项目级 ===
    project_no: str
    cover_variant: str = "通用"
    classification: str = "非密"

    # === 图签提取的全局聚合值（来自001图纸） ===
    engineering_no: str | None = None
    subitem_no: str | None = None
    subitem_name: str | None = None        # 前端输入
    subitem_name_en: str | None = None     # 前端输入(仅1818)
    discipline: str | None = None
    revision: str | None = None
    doc_status: str | None = None

    # === 封面参数 ===
    album_title_cn: str | None = None
    album_title_en: str | None = None      # 仅1818
    cover_revision: str = "A"

    # === 目录参数 ===
    upgrade_start_seq: int | None = None
    upgrade_end_seq: int | None = None
    upgrade_revision: str | None = None
    upgrade_note_text: str = "升版"

    # === 设计文件参数 ===
    wbs_code: str | None = None
    system_code: str = "NA"
    system_name: str = "NA"
    design_status: str = "编制"
    internal_tag: str = "否"
    discipline_office: str | None = None
    file_category: str | None = None
    attachment_name: str | None = None
    qa_required: str = "否"
    qa_engineer: str | None = None
    work_hours: str = "100"

    # === IED参数（部分） ===
    ied_status: str = "发布"
    ied_doc_type: str | None = None
    ied_change_flag: str | None = None
    ied_design_type: str | None = None
    ied_responsible_unit: str | None = None
    ied_discipline_office: str | None = None
    ied_chief_designer: str | None = None
    ied_person_qual_category: str = "一般核安全物项-民用"
    ied_fu_flag: str = "N"
    ied_internal_tag: str = "否"
    ied_prepared_by: str | None = None
    ied_prepared_by_2: str | None = None
    ied_prepared_date: str | None = None
    ied_checked_by: str | None = None
    ied_checked_date: str | None = None
    ied_discipline_leader: str | None = None
    ied_discipline_leader_date: str | None = None
    ied_reviewed_by: str | None = None
    ied_reviewed_date: str | None = None
    ied_approved_by: str | None = None
    ied_approved_date: str | None = None
    ied_submitted_plan_date: str | None = None
    ied_publish_plan_date: str | None = None
    ied_external_plan_date: str | None = None
    ied_fu_plan_date: str | None = None


class DerivedFields(BaseModel):
    """派生字段（由规则计算）"""
    # 编码派生
    internal_code_001: str | None = None
    album_internal_code: str | None = None
    album_code: str | None = None
    cover_internal_code: str | None = None
    catalog_internal_code: str | None = None
    external_code_001: str | None = None
    cover_external_code: str | None = None
    catalog_external_code: str | None = None

    # 标题派生
    cover_title_cn: str | None = None
    catalog_title_cn: str | None = None
    cover_title_en: str | None = None
    catalog_title_en: str | None = None

    # 阶段派生
    design_phase: str | None = None
    design_phase_en: str | None = None     # 仅1818
    discipline_en: str | None = None       # 仅1818

    # 版次派生
    catalog_revision: str | None = None

    # 固定值
    cover_paper_size_text: str = "A4文件"
    cover_page_total: int = 1
    catalog_paper_size_text: str = "A4文件"
    catalog_page_total: int | None = None  # PDF计页后回填


class DocContext(BaseModel):
    """文档生成上下文（文档生成模块的唯一输入）"""

    # 全局参数
    params: GlobalDocParams

    # 派生字段
    derived: DerivedFields = Field(default_factory=DerivedFields)

    # 图框列表（已排序）
    frames: list[FrameMeta] = Field(default_factory=list)

    # A4多页成组（如有）
    sheet_sets: list[SheetSet] = Field(default_factory=list)

    # 规则与映射（从YAML加载）
    rules: dict[str, Any] = Field(default_factory=dict)
    mappings: dict[str, dict[str, str]] = Field(default_factory=dict)

    # 生成选项
    options: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_1818(self) -> bool:
        return self.params.project_no == "1818"

    def get_frame_001(self) -> FrameMeta | None:
        """获取001图纸"""
        for frame in self.frames:
            if frame.titleblock.internal_code and frame.titleblock.internal_code.endswith("-001"):
                return frame
        return None

    def get_sorted_frames(self) -> list[FrameMeta]:
        """按internal_code尾号排序"""
        def sort_key(f: FrameMeta) -> int:
            seq = f.titleblock.get_seq_no()
            return seq if seq is not None else 9999
        return sorted(self.frames, key=sort_key)
