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

import re

from ..config import load_spec
from ..models import DerivedFields, DocContext, normalize_discipline_label
from .upgrade_marking import (
    UpgradeEntryParseError,
    parse_upgrade_entries,
    resolve_highest_upgrade_revision,
)


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
                derived.album_internal_code = self._album_base_internal_code(internal_code_001)

                # album_code = extract_mid5_last2(internal_code_001)
                derived.album_code = self._extract_mid5_last2(internal_code_001)

                # cover/catalog internal codes
                derived.cover_internal_code = f"{derived.album_internal_code}-FM"
                derived.catalog_internal_code = f"{derived.album_internal_code}-TM"

            derived.steel_liner_mode = ctx.is_steel_liner_mode()

            if external_code_001:
                # cover/catalog external codes (第9-11位替换)
                code_suffix = self._cover_catalog_external_suffix(derived)
                derived.cover_external_code = self._replace_pos(
                    external_code_001,
                    8,
                    11,
                    f"F{code_suffix}",
                )
                derived.catalog_external_code = self._replace_pos(
                    external_code_001,
                    8,
                    11,
                    f"T{code_suffix}",
                )

        # === 标题派生 ===
        album_title_cn = ctx.params.album_title_cn
        album_title_en = ctx.params.album_title_en

        if album_title_cn:
            derived.cover_title_cn = self._append_cn_title_suffix(
                album_title_cn,
                self._append_suffix_from_rule("cover_title_cn", "图册封面"),
            )
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
        derived.document_revision = self._resolve_document_revision(ctx)
        derived.cover_catalog_revision = self._resolve_cover_catalog_revision(ctx)
        derived.catalog_revision = derived.cover_catalog_revision

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

    def _append_suffix_from_rule(self, field_name: str, default: str) -> str:
        rule = self.rules.get(field_name, {})
        transform = str(rule.get("transform") or "") if isinstance(rule, dict) else ""
        match = re.fullmatch(r"""append\((?P<quote>['"])(?P<suffix>.*?)(?P=quote)\)""", transform.strip())
        if match:
            return match.group("suffix")
        return default

    @staticmethod
    def _append_cn_title_suffix(title: str, suffix: str) -> str:
        base = str(title or "").strip()
        normalized_suffix = str(suffix or "").strip()
        if not base or not normalized_suffix:
            return base
        if base.endswith(normalized_suffix):
            return base
        if normalized_suffix.startswith("图册") and base.endswith("图册"):
            return base + normalized_suffix[len("图册"):]
        return base + normalized_suffix

    @staticmethod
    def _album_base_internal_code(internal_code: str) -> str:
        """Resolve the album-level internal code from a drawing-level internal code."""
        match = re.match(r"^(.*)-\d{3}$", internal_code)
        if match:
            return match.group(1)
        return internal_code

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

    @staticmethod
    def _cover_catalog_external_suffix(derived: DerivedFields) -> str:
        if derived.steel_liner_mode and derived.album_code:
            return str(derived.album_code).strip().zfill(2)
        return "01"

    @staticmethod
    def _normalize_revision(value: str | None) -> str:
        return str(value or "").strip().upper()

    def _resolve_document_revision(self, ctx: DocContext) -> str:
        drawing_revisions = [
            revision
            for revision in (
                self._normalize_revision(frame.titleblock.revision)
                for frame in ctx.get_sorted_document_frames()
            )
            if revision
        ]
        if drawing_revisions:
            return max(drawing_revisions, key=self._revision_sort_key)

        return self._normalize_revision(ctx.params.revision) or "A"

    def _resolve_cover_catalog_revision(self, ctx: DocContext) -> str:
        cover_revision = self._normalize_revision(ctx.params.cover_revision)
        if cover_revision:
            return cover_revision
        if ctx.params.is_upgrade:
            upgrade_entries_revision = self._resolve_upgrade_entries_revision(ctx.params.upgrade_entries)
            if upgrade_entries_revision:
                return upgrade_entries_revision
            return "B"
        return "A"

    def _resolve_upgrade_entries_revision(self, raw_entries) -> str:
        try:
            return resolve_highest_upgrade_revision(parse_upgrade_entries(raw_entries))
        except UpgradeEntryParseError:
            return ""

    @staticmethod
    def _revision_sort_key(revision: str) -> tuple[tuple[int, int | str], ...]:
        parts = re.findall(r"[A-Z]+|\d+", revision.upper())
        if not parts:
            return ((0, revision.upper()),)

        key: list[tuple[int, int | str]] = []
        for part in parts:
            if part.isdigit():
                key.append((1, int(part)))
            else:
                key.append((0, part))
        return tuple(key)
