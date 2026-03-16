"""
派生字段引擎 - 计算派生字段

职责：
1. 根据参数规范.yaml的derivations规则计算派生字段
2. 填充DocContext.derived

依赖：
- 参数规范.yaml: doc_generation.derivations

测试要点：
- test_derive_album_internal_code: 图册编号派生
- test_derive_cover_catalog_codes: 封面/目录编码派生
- test_derive_titles: 标题派生
- test_derive_catalog_revision: 目录版次派生
- test_derive_design_phase: 设计阶段派生
"""

from __future__ import annotations

from ..config import load_spec
from ..models import DerivedFields, DocContext, normalize_discipline_label


class DerivationEngine:
    """派生字段计算引擎"""

    def __init__(self, spec_path: str | None = None):
        self.spec = load_spec(spec_path) if spec_path else load_spec()
        self.rules = self.spec.get_derivation_rules()
        self.mappings = self.spec.get_mappings()

    def compute(self, ctx: DocContext) -> DerivedFields:
        """计算所有派生字段"""
        derived = DerivedFields()

        # 获取001图纸
        frame_001 = ctx.get_frame_001()

        # === 编码派生 ===
        if frame_001:
            internal_code_001 = frame_001.titleblock.internal_code
            external_code_001 = frame_001.titleblock.external_code

            derived.internal_code_001 = internal_code_001
            derived.external_code_001 = external_code_001

            if internal_code_001:
                # album_internal_code = strip_suffix(internal_code_001, '-001')
                derived.album_internal_code = self._strip_suffix(internal_code_001, "-001")

                # album_code = extract_mid5_last2(internal_code_001)
                derived.album_code = self._extract_mid5_last2(internal_code_001)

                # cover/catalog internal codes
                derived.cover_internal_code = self._replace_suffix(internal_code_001, "-001", "-FM")
                derived.catalog_internal_code = self._replace_suffix(internal_code_001, "-001", "-TM")

            if external_code_001:
                # cover/catalog external codes (第9-11位替换)
                derived.cover_external_code = self._replace_pos(external_code_001, 8, 11, "F01")
                derived.catalog_external_code = self._replace_pos(external_code_001, 8, 11, "T01")

        # === 标题派生 ===
        album_title_cn = ctx.params.album_title_cn
        album_title_en = ctx.params.album_title_en

        if album_title_cn:
            derived.cover_title_cn = album_title_cn + "封面"
            derived.catalog_title_cn = album_title_cn + "目录"

        if ctx.is_1818 and album_title_en:
            derived.cover_title_en = album_title_en + " Cover"
            derived.catalog_title_en = album_title_en + " Contents"

        # === 阶段派生 ===
        status = ctx.params.doc_status
        if status:
            derived.design_phase = self.mappings.get("status_to_design_phase", {}).get(
                status, "施工图设计"
            )

        # 1818专用：英文映射
        if ctx.is_1818:
            if derived.design_phase:
                derived.design_phase_en = self.mappings.get("design_phase_to_en", {}).get(
                    derived.design_phase
                )

            discipline = normalize_discipline_label(ctx.params.discipline, self.mappings)
            if discipline:
                derived.discipline_en = self.mappings.get("discipline_to_en", {}).get(discipline)

        # === 版次派生 ===
        # catalog_revision = coalesce_nonempty(upgrade_revision, cover_revision)
        derived.catalog_revision = (
            ctx.params.upgrade_revision or ctx.params.cover_revision or "A"
        )

        # === 固定值 ===
        derived.cover_paper_size_text = "A4图纸"
        derived.cover_page_total = 1
        derived.catalog_paper_size_text = "A4文件"
        # catalog_page_total 需要PDF计页后回填

        return derived

    def _strip_suffix(self, s: str, suffix: str) -> str:
        """去除后缀"""
        return s[:-len(suffix)] if s.endswith(suffix) else s

    def _replace_suffix(self, s: str, old_suffix: str, new_suffix: str) -> str:
        """替换后缀"""
        if s.endswith(old_suffix):
            return s[:-len(old_suffix)] + new_suffix
        return s + new_suffix

    def _extract_mid5_last2(self, internal_code: str) -> str | None:
        """从internal_code提取图册编号（中间5位的末2位）"""
        parts = internal_code.split("-")
        if len(parts) >= 2:
            mid5 = parts[1]
            if len(mid5) >= 2:
                return mid5[-2:]
        return None

    def _replace_pos(self, s: str, start: int, end: int, replacement: str) -> str:
        """替换指定位置的字符（0-based）"""
        if len(s) >= end:
            return s[:start] + replacement + s[end:]
        return s
