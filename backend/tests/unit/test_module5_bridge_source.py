from __future__ import annotations

from pathlib import Path


def test_plot_engine_regenerates_active_document_before_pdf_plotting() -> None:
    source = Path("backend/src/cad/dotnet/Module5CadBridge/PlotEngine.cs").read_text(
        encoding="utf-8",
    )

    assert "RunRegenBeforePlot();" in source
    assert ".Editor.Regen()" in source


def test_lisp_plot_fallback_regenerates_before_pdf_plotting() -> None:
    source = Path("backend/src/cad/scripts/module5_cad_executor.lsp").read_text(
        encoding="utf-8",
    )

    assert "(m5-regen-before-plot)" in source
    assert "\"_.REGENALL\"" in source


def test_font_preflight_bridge_honors_exempt_style_names() -> None:
    commands_source = Path(
        "backend/src/cad/dotnet/Module5CadBridge/Commands.cs"
    ).read_text(encoding="utf-8")
    processor_source = Path(
        "backend/src/cad/dotnet/Module5CadBridge/FontPreflightProcessor.cs"
    ).read_text(encoding="utf-8")

    assert "font_compatibility_exempt_style_names" in commands_source
    assert "FontCompatibilityExemptStyleNames" in commands_source
    assert "IsFontCompatibilityExemptStyle(styleName)" in processor_source
    assert "IsFontCompatibilityExemptStyle(usage.StyleName)" in processor_source
    titleblock_method = processor_source.split(
        "private int ApplyTitleblockPrintStyleReplacements",
        maxsplit=1,
    )[1].split(
        "private void CollectTitleblockPrintUsageInRecord",
        maxsplit=1,
    )[0]
    assert "IsFontCompatibilityExemptStyle(styleName)" in titleblock_method


def test_release_bridge_build_disables_debug_symbols() -> None:
    project_source = Path(
        "backend/src/cad/dotnet/Module5CadBridge/Module5CadBridge.csproj"
    ).read_text(encoding="utf-8")

    assert 'Condition="\'$(Configuration)\' == \'Release\'"' in project_source
    assert "<DebugType>none</DebugType>" in project_source
    assert "<DebugSymbols>false</DebugSymbols>" in project_source
