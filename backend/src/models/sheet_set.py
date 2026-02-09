"""
A4多页成组模型 - Sheet-Set 结构

对应参数规范.yaml 的 a4_multipage.result_structure
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .frame import BBox, FrameMeta


class PageInfo(BaseModel):
    """单页信息"""
    page_index: int
    outer_bbox: BBox
    has_titleblock: bool = False
    frame_meta: FrameMeta | None = None  # Master页有完整FrameMeta


class SheetSet(BaseModel):
    """A4多页成组结构"""
    sheet_set_type: str = "A4_MULTI_PAGE_001"
    paper: str = "A4"
    cluster_id: str

    # 页数信息
    page_total: int
    pages: list[PageInfo] = Field(default_factory=list)

    # Master页（第1页，有完整图签）
    master_page: PageInfo | None = None

    # 告警标记
    flags: list[str] = Field(default_factory=list)

    def get_inherited_titleblock(self) -> dict:
        """获取从Master继承的图签字段"""
        if self.master_page and self.master_page.frame_meta:
            return self.master_page.frame_meta.titleblock.model_dump(exclude_none=True)
        return {}

    def validate_consistency(self) -> list[str]:
        """一致性校验，返回新增的flags（不中断）

        校验项（对照 YAML ``consistency_checks``）：
        1. 簇内A4外框数 != page_total  → ``A4多页_页数不一致``
        2. 页码重复                     → ``A4多页_页码重复``
        3. 页码不连续                   → ``A4多页_页码不连续``
        4. Slave page_total 与 Master 不一致 → ``A4多页_页总数冲突``
        5. Master page_index != 1       → ``A4多页_首页页码异常``
        """
        new_flags: list[str] = []

        # 1. 校验页数
        if len(self.pages) != self.page_total:
            new_flags.append("A4多页_页数不一致")

        # 2+3. 校验页码连续性 / 重复
        indices = sorted(p.page_index for p in self.pages)
        expected = list(range(1, self.page_total + 1))
        if indices != expected:
            if len(indices) != len(set(indices)):
                new_flags.append("A4多页_页码重复")
            else:
                new_flags.append("A4多页_页码不连续")

        # 4. Slave page_total 与 Master 不一致
        #    （可能已在 _process_cluster._check_slave_page_total 中追加过，避免重复）
        if "A4多页_页总数冲突" not in self.flags:
            if self.master_page and self.master_page.frame_meta:
                master_pt = self.master_page.frame_meta.titleblock.page_total
                if master_pt is not None:
                    for page in self.pages:
                        if page.has_titleblock:
                            continue  # 跳过 Master 自身
                        if (
                            page.frame_meta
                            and page.frame_meta.titleblock.page_total is not None
                            and page.frame_meta.titleblock.page_total != master_pt
                        ):
                            new_flags.append("A4多页_页总数冲突")
                            break  # 只追加一次

        # 5. 校验Master页码
        if self.master_page and self.master_page.page_index != 1:
            new_flags.append("A4多页_首页页码异常")

        self.flags.extend(new_flags)
        return new_flags
