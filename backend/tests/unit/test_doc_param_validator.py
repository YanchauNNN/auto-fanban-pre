from __future__ import annotations

from src.doc_gen.param_validator import DocParamValidator
from src.models import DocContext, GlobalDocParams


def _base_ctx() -> DocContext:
    params = GlobalDocParams(
        project_no="2016",
        cover_variant="通用",
        classification="非密",
        engineering_no="1234",
        subitem_no="JG001",
        subitem_name="子项中文",
        discipline="结构",
        revision="A",
        doc_status="CFC",
        album_title_cn="测试图册",
        wbs_code="WBS-001",
        file_category="图纸",
        ied_status="发布",
        ied_doc_type="图册",
    )
    return DocContext(params=params, frames=[])


def _base_frontend_params() -> dict[str, str]:
    return {
        "project_no": "2016",
        "cover_variant": "通用",
        "classification": "非密",
        "subitem_name": "子项中文",
        "album_title_cn": "测试图册",
        "wbs_code": "WBS-001",
        "file_category": "图纸",
        "ied_status": "编制",
        "ied_doc_type": "图册",
        "is_upgrade": "false",
        "upgrade_sheet_codes": "",
    }


def test_required_when_fields_are_checked() -> None:
    validator = DocParamValidator()
    ctx = _base_ctx()

    errors = validator.validate(ctx)

    assert any("ied_prepared_by" in err for err in errors)
    assert any("ied_prepared_date" in err for err in errors)
    assert any("work_hours" in err for err in errors) is False


def test_format_validation_for_name_id_and_date() -> None:
    validator = DocParamValidator()
    ctx = _base_ctx()

    ctx.params.ied_prepared_by = "张三A001"
    ctx.params.ied_prepared_date = "2026/03/01"
    ctx.params.ied_checked_by = "李四A002"
    ctx.params.ied_checked_date = "2026-13-01"
    ctx.params.ied_discipline_office = "结构一室"
    ctx.params.ied_person_qual_category = "一般核安全物项-民用"
    ctx.params.work_hours = "100"

    errors = validator.validate(ctx)

    assert any("ied_prepared_by" in err and "格式错误" in err for err in errors)
    assert any("ied_prepared_date" in err and "格式错误" in err for err in errors)
    assert any("ied_checked_by" in err and "格式错误" in err for err in errors)
    assert any("ied_checked_date" in err and "格式错误" in err for err in errors)


def test_validate_frontend_params_accepts_upgrade_sheet_codes() -> None:
    validator = DocParamValidator()
    payload = _base_frontend_params()
    payload["is_upgrade"] = "true"
    payload["upgrade_sheet_codes"] = "001、3,5-9"

    errors = validator.validate_frontend_params(payload)

    assert errors == {}


def test_validate_frontend_params_rejects_invalid_upgrade_sheet_codes() -> None:
    validator = DocParamValidator()
    payload = _base_frontend_params()
    payload["is_upgrade"] = "true"
    payload["upgrade_sheet_codes"] = "001~000,abc"

    errors = validator.validate_frontend_params(payload)

    assert errors["upgrade_sheet_codes"] == ["format:upgrade-sheet-codes"]
