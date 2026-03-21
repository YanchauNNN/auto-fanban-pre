"""
派生字段单元测试

每个模块完成后必须运行：pytest tests/unit/test_derivation.py -v
"""

import pytest

from src.doc_gen.derivation import DerivationEngine
from src.models import DerivedFields, DocContext, GlobalDocParams


class TestDerivationEngine:
    """派生字段引擎测试"""

    @pytest.fixture
    def engine(self) -> DerivationEngine:
        return DerivationEngine()

    @pytest.fixture
    def derived_2016(
        self, engine: DerivationEngine, sample_doc_context: DocContext,
    ) -> DerivedFields:
        """标准 2016 场景的派生结果（函数级，每个 test 独立计算）"""
        return engine.compute(sample_doc_context)

    # ------------------------------------------------------------------
    # 标准 2016 场景派生（共用 derived_2016 fixture）
    # ------------------------------------------------------------------

    def test_derive_album_internal_code(self, derived_2016: DerivedFields):
        """测试图册编号派生"""
        # internal_code_001 = "1234567-JG001-001"
        # album_internal_code = "1234567-JG001"
        assert derived_2016.album_internal_code == "1234567-JG001"

    def test_derive_cover_catalog_codes(self, derived_2016: DerivedFields):
        """测试封面/目录编码派生"""
        assert derived_2016.cover_internal_code == "1234567-JG001-FM"
        assert derived_2016.catalog_internal_code == "1234567-JG001-TM"

    def test_derive_external_codes(self, derived_2016: DerivedFields):
        """测试外部编码派生"""
        # external_code_001 = "JD1NHT11001B25C42SD"
        # cover: 第9-11位(001)替换为F01
        # catalog: 第9-11位(001)替换为T01
        assert derived_2016.cover_external_code == "JD1NHT11F01B25C42SD"
        assert derived_2016.catalog_external_code == "JD1NHT11T01B25C42SD"

    def test_derive_titles(self, derived_2016: DerivedFields):
        """测试标题派生"""
        # album_title_cn = "测试图册"
        assert derived_2016.cover_title_cn == "测试图册封面"
        assert derived_2016.catalog_title_cn == "测试图册目录"

    def test_derive_design_phase(self, derived_2016: DerivedFields):
        """测试设计阶段派生"""
        # doc_status = "CFC" -> design_phase = "施工图设计"
        assert derived_2016.design_phase == "施工图设计"

    # ------------------------------------------------------------------
    # 特殊场景（各自构造专用上下文）
    # ------------------------------------------------------------------

    def test_derive_1818_english(self, engine: DerivationEngine):
        """测试1818项目英文派生"""
        params = GlobalDocParams(
            project_no="1818",
            discipline="结构",
            doc_status="CFC",
            album_title_cn="测试图册",
            album_title_en="Test Album",
        )
        ctx = DocContext(params=params, frames=[])
        derived = engine.compute(ctx)

        assert derived.discipline_en == "Structural Engineering"
        assert derived.design_phase_en == "Constructing Design"
        assert derived.cover_title_en == "Test Album Cover"
        assert derived.catalog_title_en == "Test Album Contents"

    def test_derive_1818_english_from_structure_hint(self, engine: DerivationEngine):
        """1818 专业值即使带损坏文本/英文提示，也应派生成标准英文专业名。"""
        params = GlobalDocParams(
            project_no="1818",
            discipline="\uc368\ubbd0\nStructure",
            doc_status="CFC",
            album_title_cn="娴嬭瘯鍥惧唽",
            album_title_en="Test Album",
        )
        ctx = DocContext(params=params, frames=[])
        derived = engine.compute(ctx)

        assert derived.discipline_en == "Structural Engineering"

    def test_derive_catalog_revision_uses_highest_drawing_revision(
        self,
        engine: DerivationEngine,
        sample_frame,
    ):
        """目录/封面版次应与图纸最高版次保持一致。"""
        params = GlobalDocParams(
            project_no="2016",
            cover_revision="A",
        )
        frame_a = sample_frame.model_copy(deep=True)
        frame_a.titleblock.revision = "A"
        frame_b = sample_frame.model_copy(deep=True)
        frame_b.titleblock.internal_code = "1234567-JG001-002"
        frame_b.titleblock.external_code = "JD1NHT11002B25C42SD"
        frame_b.titleblock.revision = "C"
        ctx = DocContext(params=params, frames=[frame_a, frame_b])
        derived = engine.compute(ctx)
        assert derived.document_revision == "C"
        assert derived.catalog_revision == "C"

    def test_derive_catalog_revision_falls_back_to_cover_without_drawing_revisions(
        self,
        engine: DerivationEngine,
    ):
        params = GlobalDocParams(
            project_no="2016",
            cover_revision="A",
        )
        ctx = DocContext(params=params, frames=[])
        derived = engine.compute(ctx)
        assert derived.document_revision == "A"
        assert derived.catalog_revision == "A"

        params2 = GlobalDocParams(
            project_no="2016",
            cover_revision="C",
        )
        ctx2 = DocContext(params=params2, frames=[])
        derived2 = engine.compute(ctx2)
        assert derived2.document_revision == "C"
        assert derived2.catalog_revision == "C"

    def test_upgrade_toggle_does_not_affect_document_revision(
        self,
        engine: DerivationEngine,
    ):
        params = GlobalDocParams(
            project_no="2016",
            cover_revision="B",
            is_upgrade=True,
            upgrade_sheet_codes="001~099",
        )
        ctx = DocContext(params=params, frames=[])

        derived = engine.compute(ctx)

        assert derived.document_revision == "B"
        assert derived.catalog_revision == "B"

    def test_derive_fixed_cover_and_catalog_paper_labels(self, engine: DerivationEngine):
        """封面与目录固定图幅值应符合设计文件业务口径"""
        params = GlobalDocParams(project_no="2016")
        ctx = DocContext(params=params, frames=[])

        derived = engine.compute(ctx)

        assert derived.cover_paper_size_text == "A4图纸"
        assert derived.catalog_paper_size_text == "A4文件"
