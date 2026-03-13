from __future__ import annotations

from pathlib import Path

from src.doc_gen.cover import CoverGenerator
from src.models import DerivedFields, DocContext, GlobalDocParams


def _build_context() -> DocContext:
    params = GlobalDocParams(
        project_no="2016",
        cover_variant="通用",
        engineering_no="1234",
        subitem_no="JG001",
        subitem_name="子项名称",
        discipline="结构",
        doc_status="CFC",
        album_title_cn="测试图册",
        cover_revision="A",
    )
    derived = DerivedFields(
        album_internal_code="1234567-JG001",
        album_code="01",
        cover_external_code="JD1NHT11F01B25C42SD",
        design_phase="施工图设计",
    )
    return DocContext(params=params, derived=derived, frames=[])


def test_cover_prefers_com_write_for_common_template_visual_refresh(
    temp_dir: Path,
    monkeypatch,
) -> None:
    gen = CoverGenerator()
    ctx = _build_context()
    bindings = gen.spec.get_cover_bindings("2016")
    data = gen._prepare_data(ctx)
    output_docx = temp_dir / "封面.docx"

    called = {"com": False, "embedded": False}

    def fake_write_cover_via_com(self, *, output_path, bindings, data):  # noqa: ANN001
        called["com"] = True

    def fake_write_cover_via_embedded_xlsx(  # noqa: ANN001
        self,
        *,
        output_path,
        embedded_xlsx_path,
        bindings,
        data,
    ):
        called["embedded"] = True

    monkeypatch.setattr(CoverGenerator, "_write_cover_via_com", fake_write_cover_via_com)
    monkeypatch.setattr(
        CoverGenerator,
        "_write_cover_via_embedded_xlsx",
        fake_write_cover_via_embedded_xlsx,
    )

    gen._write_cover(
        template_path="documents_bin/封面模板文件.docx",
        output_path=output_docx,
        bindings=bindings,
        data=data,
        ctx=ctx,
    )

    assert called["com"] is True
    assert called["embedded"] is False


def test_get_embedded_excel_sheet_activates_ole_before_reading_object() -> None:
    gen = CoverGenerator()

    class FakeSheet:
        pass

    class FakeWorkbook:
        def Worksheets(self, index: int):  # noqa: ARG002
            return FakeSheet()

    class FakeOleObject:
        def __init__(self) -> None:
            self.Parent = FakeWorkbook()

    class FakeOleFormat:
        def __init__(self) -> None:
            self.activated = False

        def Activate(self) -> None:
            self.activated = True

        @property
        def Object(self):
            if not self.activated:
                raise RuntimeError("call was rejected by callee")
            return FakeOleObject()

    class FakeShape:
        def __init__(self) -> None:
            self.OLEFormat = FakeOleFormat()

    class FakeCollection:
        Count = 1

        def Item(self, index: int):  # noqa: ARG002
            return FakeShape()

    class FakeDoc:
        InlineShapes = FakeCollection()
        Shapes = None

    sheet = gen._get_embedded_excel_sheet(FakeDoc())

    assert sheet is not None
