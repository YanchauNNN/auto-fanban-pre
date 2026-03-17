from __future__ import annotations

from pathlib import Path


def test_probe_target_env_avoids_psscriptanalyzer_naming_issues() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert '[string]$Error = ""' not in script_text
    assert "function Try-RemovePath" not in script_text
    assert "function Pick-BestAccoreconsole" not in script_text
    assert "function Pick-BestPlotterDir" not in script_text
    assert "function Detect-RepoRoot" not in script_text
    assert "function Release-ComObject" not in script_text


def test_probe_target_env_avoids_scalar_count_on_ipv4_addresses() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "$addresses.Count" not in script_text


def test_probe_target_env_word_deep_checks_follow_runtime_style() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert ".Documents.Add()" not in script_text
    assert ".SaveAs2(" not in script_text
    assert '.Options.SaveNormalPrompt = $false' in script_text
    assert "NormalTemplate" in script_text
    assert "Documents.Open(" in script_text


def test_probe_target_env_deep_checks_run_with_timeout_worker() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "OfficeWorkerTask" in script_text
    assert "Start-Process" in script_text
    assert "WaitForExit" in script_text
    assert "Stop-Process" in script_text


def test_probe_target_env_python_import_uses_temp_script_not_dash_c() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "fanban_import_probe" in script_text
    assert 'Arguments @("-c"' not in script_text


def test_probe_target_env_deep_pdf_export_uses_backend_pdf_exporter() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "from src.doc_gen.pdf_engine import PDFExporter" in script_text
    assert "backend-runtime" in script_text
