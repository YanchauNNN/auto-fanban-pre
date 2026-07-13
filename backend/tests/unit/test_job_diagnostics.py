from __future__ import annotations

from src.job_diagnostics import build_job_diagnostics


def test_build_job_diagnostics_expands_duplicate_external_codes_to_drawings() -> None:
    flags = [
        "CAD结果错误:18185NP-JGS44.consistency.dwg:检测到重复编码: internal=[], external=['PC5NPM12004B25C42MD', 'PC5NPM12004B25C42SD']",
        "[PC5NPM12004B25C42SDACFC (18185NP-JGS44-024)] DXF执行失败",
        "[PC5NPM12004B25C42SDACFC (18185NP-JGS44-026)] PDF缺失",
        "[PC5NPM12004B25C42MDACFC (18185NP-JGS44-025)] DWG缺失",
        "[PC5NPM12004B25C42MDACFC (18185NP-JGS44-027)] DXF执行失败",
    ]

    diagnostics = build_job_diagnostics(flags=flags, errors=[])

    duplicate = next(item for item in diagnostics if item["kind"] == "duplicate_code")
    assert duplicate["title"] == "检测到重复编码"
    assert duplicate["severity"] == "error"
    assert duplicate["details"] == [
        {
            "label": "外部编码 PC5NPM12004B25C42MD",
            "items": ["18185NP-JGS44-025", "18185NP-JGS44-027"],
        },
        {
            "label": "外部编码 PC5NPM12004B25C42SD",
            "items": ["18185NP-JGS44-024", "18185NP-JGS44-026"],
        },
    ]


def test_build_job_diagnostics_groups_output_missing_and_office_errors() -> None:
    diagnostics = build_job_diagnostics(
        flags=[
            "[PC5NPL12001B25C42SDACFC (18185NP-JGS44-006)] PDF缺失",
            "[PC5NPL12001B25C42SDACFC (18185NP-JGS44-006)] DWG缺失",
            "PREVIEW_PDF_GENERATE_FAILED",
        ],
        errors=[
            "目录PDF导出失败: Excel导出PDF失败: 无法创建 Excel.Application",
        ],
    )

    kinds = [item["kind"] for item in diagnostics]
    assert "cad_output" in kinds
    assert "office_export" in kinds
    assert "preview" in kinds

    output = next(item for item in diagnostics if item["kind"] == "cad_output")
    assert output["summary"] == "1 张图纸存在 CAD 导出、PDF 或 DWG 产物缺失问题。"
    assert output["details"] == [
        {
            "label": "18185NP-JGS44-006",
            "items": ["PDF缺失", "DWG缺失"],
        },
    ]


def test_build_job_diagnostics_categorizes_paper_font_and_param_issues() -> None:
    diagnostics = build_job_diagnostics(
        flags=[
            "[PC5NPK12002B25C42MDBCFC (18185NP-JGS44-003)] PAPER_SIZE_AUTO_FIXED",
            "FONT_REPLACEMENT_INCOMPLETE",
        ],
        errors=[
            "文档参数缺失: engineering_no",
        ],
        font_preflight_summary={
            "files": [
                {
                    "missing_fonts": [
                        {"style_name": "汉字", "font_name": "missing.shx"},
                    ],
                },
            ],
        },
    )

    kinds = [item["kind"] for item in diagnostics]
    assert "paper_size" in kinds
    assert "font" in kinds
    assert "param" in kinds
    assert "other" not in kinds
