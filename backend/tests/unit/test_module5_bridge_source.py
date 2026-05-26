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
