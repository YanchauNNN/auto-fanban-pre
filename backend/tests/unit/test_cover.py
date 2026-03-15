from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from src.doc_gen.cover import CoverGenerator
from src.models import DerivedFields, DocContext, GlobalDocParams


class DummyPDFExporter:
    def export_docx_to_pdf(self, docx_path: Path, pdf_path: Path) -> None:
        pdf_path.write_bytes(b"%PDF-1.4\n%dummy\n")


def _build_context(project_no: str = "2016") -> DocContext:
    params = GlobalDocParams(
        project_no=project_no,
        cover_variant="通用",
        engineering_no="1234",
        subitem_no="JG001",
        subitem_name="这是一个很长的子项名称用于测试",
        subitem_name_en="Secondary Steel Shop",
        discipline="结构",
        doc_status="CFC",
        album_title_cn="这是一个很长的中文图册标题用于分割测试",
        album_title_en="Secondary steel shop drawings at elevation -8.800m",
        cover_revision="B",
    )
    derived = DerivedFields(
        album_internal_code="1234567-JG001",
        album_code="01",
        cover_external_code="JD1NHT11F01B25C42SD",
        design_phase="施工图设计",
        design_phase_en="Constructing Design",
        discipline_en="Structural",
    )
    return DocContext(params=params, derived=derived, frames=[])


def _read_cover_embedded_wb(docx_path: Path):
    with zipfile.ZipFile(docx_path, "r") as zf:
        payload = zf.read("word/embeddings/Microsoft_Excel_Worksheet.xlsx")
    wb = load_workbook(BytesIO(payload))
    return wb["封面"] if "封面" in wb.sheetnames else wb.active


def test_cover_variant_template_mapping() -> None:
    gen = CoverGenerator(pdf_exporter=DummyPDFExporter())
    ctx = _build_context()

    ctx.params.cover_variant = "压力容器"
    assert gen._get_template_path(ctx).endswith("封面模板文件压力容器版.docx")

    ctx.params.cover_variant = "核安全设备"
    assert gen._get_template_path(ctx).endswith("封面模板文件核安全设备版.docx")

    ctx.params.project_no = "1818"
    ctx.params.cover_variant = "通用"
    assert gen._get_template_path(ctx).endswith("1818图册封面模板.docx")

    ctx.params.cover_variant = "压力容器"
    assert gen._get_template_path(ctx).endswith("1818图册压力容器封面模板.docx")

    ctx.params.cover_variant = "核安全设备"
    assert gen._get_template_path(ctx).endswith("1818图册核安全设备封面模板.docx")


def test_write_cover_with_embedded_xlsx(temp_dir: Path) -> None:
    gen = CoverGenerator(pdf_exporter=DummyPDFExporter())
    ctx = _build_context(project_no="2016")
    bindings = gen.spec.get_cover_bindings(ctx.params.project_no)
    data = gen._prepare_data(ctx)

    output_docx = temp_dir / "封面.docx"
    def force_embedded_fallback(*, output_path, bindings, data):  # noqa: ANN001
        raise RuntimeError("force embedded fallback")

    gen._write_cover_via_com = force_embedded_fallback  # type: ignore[method-assign]

    gen._write_cover(
        template_path="documents_bin/封面模板文件.docx",
        output_path=output_docx,
        bindings=bindings,
        data=data,
        ctx=ctx,
    )

    ws = _read_cover_embedded_wb(output_docx)
    assert ws["I11"].value == "1234"
    assert ws["I13"].value == "JG001"
    assert ws["I21"].value
    assert ws["I22"].value
    assert str(ws["N5"].value).strip().endswith("：B")

    chars = [str(ws[f"{col}29"].value or "") for col in "BCDEFGHIJKLMNOPQRST"]
    assert "".join(chars) == "JD1NHT11F01B25C42SD"


def test_write_cover_1818_uses_com_when_no_embedded_xlsx(
    temp_dir: Path,
    monkeypatch,
) -> None:
    gen = CoverGenerator(pdf_exporter=DummyPDFExporter())
    ctx = _build_context(project_no="1818")
    bindings = gen.spec.get_cover_bindings("1818")
    data = gen._prepare_data(ctx)
    output_docx = temp_dir / "封面1818.docx"

    called = {"hit": False}

    def fake_write_cover_via_com(self, *, output_path, bindings, data):  # noqa: ANN001
        called["hit"] = True

    monkeypatch.setattr(CoverGenerator, "_write_cover_via_com", fake_write_cover_via_com)

    gen._write_cover(
        template_path="documents_bin/1818图册封面模板.docx",
        output_path=output_docx,
        bindings=bindings,
        data=data,
        ctx=ctx,
    )

    assert called["hit"] is True


def test_1818_cover_binding_writes_external_code_on_row_30() -> None:
    gen = CoverGenerator(pdf_exporter=DummyPDFExporter())
    bindings = gen.spec.get_cover_bindings("1818")

    assert "cover_external_code" in bindings
    assert bindings["cover_external_code"].cell == "B30:T30"
