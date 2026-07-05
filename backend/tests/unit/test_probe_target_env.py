from __future__ import annotations

import subprocess
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


def test_probe_target_env_python_commands_disable_user_site_and_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert '[Environment]::SetEnvironmentVariable("PYTHONNOUSERSITE", "1", "Process")' in script_text
    assert '[Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process")' in script_text
    assert '[Environment]::SetEnvironmentVariable("PYTHONHOME", $null, "Process")' in script_text


def test_probe_target_env_deep_pdf_export_uses_backend_pdf_exporter() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "from src.doc_gen.pdf_engine import PDFExporter" in script_text
    assert "backend-runtime" in script_text
    assert "python_traceback.txt" in script_text
    assert "preserved_temp_dir" in script_text


def test_probe_target_env_prefers_package_python_runtime() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "python-runtime\\python.exe" in script_text
    assert 'Label "package_runtime"' in script_text


def test_probe_target_env_prefers_terminal_backend_runtime_layout() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    runtime_scripts = 'backend-runtime\\backend\\src\\cad\\scripts'
    dev_scripts = 'backend\\src\\cad\\scripts'
    runtime_bridge = (
        'backend-runtime\\backend\\src\\cad\\dotnet\\Module5CadBridge\\bin\\Release\\net48\\Module5CadBridge.dll'
    )
    dev_bridge = 'backend\\src\\cad\\dotnet\\Module5CadBridge\\bin\\Release\\net48\\Module5CadBridge.dll'

    assert script_text.index(runtime_scripts) < script_text.index(dev_scripts)
    assert script_text.index(runtime_bridge) < script_text.index(dev_bridge)


def test_probe_target_env_downgrades_windows_store_python_alias() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "Test-WindowsStorePythonAliasFailure" in script_text
    assert "windows app execution alias is not an installed Python runtime" in script_text


def test_probe_target_env_keeps_excel_failure_evidence_and_checks_logon_task_support() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "excel_probe_failure.txt" in script_text
    assert "exception_hresult" in script_text
    assert "diagnostics_path" in script_text
    assert "register_backend_task.ps1" in script_text
    assert "unregister_backend_task.ps1" in script_text
    assert "recommended_mode = \"logon_task\"" in script_text


def test_probe_target_env_can_reuse_quick_probe_baseline_for_deep_checks() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert '[string]$ReuseQuickProbeJson = ""' in script_text
    assert "Import-ProbeBaseline" in script_text
    assert "reused_quick_probe_json" in script_text
    assert "复用 quick 探针结果" in script_text


def test_probe_target_env_uses_safer_excel_template_open_strategy() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "function Get-ExcelWorkbooksWithRetry" in script_text
    assert "function Wait-ExcelApplicationReady" in script_text
    assert "function Invoke-ExcelOpenWithRetry" in script_text
    assert "function Set-ExcelHeadlessState" in script_text
    assert 'fanban_excel_' in script_text
    assert "Unblock-File -LiteralPath $workingCopy" in script_text
    assert 'Name = "AskToUpdateLinks"; Value = $false' in script_text
    assert 'Name = "EnableEvents"; Value = $false' in script_text
    assert "GetFileName($TemplatePath)" not in script_text
    assert "[switch]$TreatNullAsFailure" in script_text
    assert '-Description "Excel.Workbooks" -Retries $Retries -TreatNullAsFailure' in script_text
    assert 'if ($null -eq $workbooks) {' in script_text
    assert 'throw "Excel.Workbooks unavailable"' in script_text


def test_probe_target_env_collects_office_com_registration_diagnostics() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "function Get-ComRegistrationFacts" in script_text
    assert "function Get-ExecutablePathFromCommandText" in script_text
    assert "local_server32_raw" in script_text
    assert "local_server_path" in script_text
    assert "local_server_exists" in script_text
    assert "Get-ComRegistrationFacts -ProgId \"Excel.Application\"" in script_text


def test_probe_target_env_can_bootstrap_excel_from_executable_candidates() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "function Get-ExcelExecutableCandidates" in script_text
    assert "function Start-ExcelAutomationCandidate" in script_text
    assert "function Get-ExcelComObjectWithBootstrap" in script_text
    assert "function Test-IsRecoverableExcelBootstrapError" in script_text
    assert 'GetActiveObject("Excel.Application")' in script_text
    assert "/automation" in script_text
    assert "Test-IsRecoverableExcelBootstrapError -Message $message -HResult $hresult" in script_text


def test_probe_target_env_requires_managed_pdf2_pc3_and_does_not_use_dwg_fallback() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert 'recommendedPc3 = "DWG To PDF.pc3"' not in script_text
    assert "used_fallback_dwg_to_pdf" not in script_text
    assert "documents\\Resources\\打印PDF2.pc3" in script_text


def test_probe_target_env_prefers_managed_ctb_when_packaged_asset_exists() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert 'recommendedCtb = "fanban_monochrome.ctb"' in script_text
    assert "documents\\Resources\\fanban_monochrome.ctb" in script_text


def test_probe_target_env_checks_required_cad_fonts() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "function Get-RequiredAutoCADFontFacts" in script_text
    assert "tssdeng.shx" in script_text
    assert "tssdchn.shx" in script_text
    assert "hztxt.shx" in script_text
    assert "tssdeng2.shx" in script_text
    assert "simsun.ttc" in script_text
    assert "simsun.ttf" in script_text
    assert "windows_fonts_dir" in script_text
    assert "missing_required_fonts" in script_text
    assert 'code = "required_fonts"' in script_text


def test_probe_target_env_prefers_highest_autocad_version_with_accoreconsole(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8-sig",
    )
    start = script_text.index("function Select-BestAccoreconsole")
    end = script_text.index("function Select-BestPlotterDir")
    function_text = script_text[start:end]
    probe_script = tmp_path / "select_best_accore.ps1"
    probe_script.write_text(
        function_text
        + r'''
$facts = @(
    [pscustomobject]@{
        install_dir = "D:\Program Files\Autodesk\AutoCAD 2014"
        acad_exe = "D:\Program Files\Autodesk\AutoCAD 2014\acad.exe"
        accoreconsole_exe = "D:\Program Files\Autodesk\AutoCAD 2014\accoreconsole.exe"
        accoreconsole_exe_exists = $true
    },
    [pscustomobject]@{
        install_dir = "D:\AUTOCAD\AutoCAD 2022"
        acad_exe = "D:\AUTOCAD\AutoCAD 2022\acad.exe"
        accoreconsole_exe = "D:\AUTOCAD\AutoCAD 2022\accoreconsole.exe"
        accoreconsole_exe_exists = $true
    }
)
$actual = Select-BestAccoreconsole -InstallFacts $facts
$expected = "D:\AUTOCAD\AutoCAD 2022\accoreconsole.exe"
if ($actual -ne $expected) {
    throw "expected $expected but got $actual"
}
''',
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(probe_script),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr


def test_probe_target_env_uses_openpyxl_for_excel_template_validation() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_text = (repo_root / "tools" / "probe_target_env.ps1").read_text(
        encoding="utf-8",
    )

    assert "excel_template_probe.py" in script_text
    assert "from openpyxl import load_workbook" in script_text
    assert 'validation_mode = "python_openpyxl"' in script_text
    assert "traceback_path = $tracebackPath" in script_text
