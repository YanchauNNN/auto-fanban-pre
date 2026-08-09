from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.config.mechanism_spec import MechanismSpecLoader
from src.deploy.archive_runtime import validate_archive_runtime_cache


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _powershell_executable() -> str:
    executable = shutil.which("powershell") or shutil.which("powershell.exe")
    if not executable:
        pytest.skip("Windows PowerShell is unavailable")
    return executable


@pytest.mark.integration
def test_bounded_child_process_times_out_and_keeps_logs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    probe_script = repo_root / "tools" / "probe_target_env.ps1"
    stdout_path = tmp_path / "child.stdout.log"
    stderr_path = tmp_path / "child.stderr.log"
    harness = tmp_path / "invoke-bounded-child.ps1"
    harness.write_text(
        f'''$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    {_ps_quote(str(probe_script))},
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {{ throw "probe_target_env.ps1 parse failed" }}
$functionAst = @($ast.FindAll({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-BoundedChildProcess"
}}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) {{ throw "missing Invoke-BoundedChildProcess" }}
Invoke-Expression $functionAst.Extent.Text
$result = Invoke-BoundedChildProcess `
    -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-Command", "Write-Output before-timeout; Start-Sleep -Seconds 5") `
    -TimeoutSec 1 `
    -StdoutPath {_ps_quote(str(stdout_path))} `
    -StderrPath {_ps_quote(str(stderr_path))}
$result | ConvertTo-Json -Depth 8 -Compress
if (-not $result.timed_out) {{ exit 4 }}
''',
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            _powershell_executable(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip())
    assert payload["timed_out"] is True
    assert payload["elapsed_ms"] >= 900
    assert stdout_path.exists()
    assert stderr_path.exists()


def _build_real_archive_probe_package(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[3]
    config = MechanismSpecLoader.load(
        repo_root / "documents" / "参数规范-3.yaml"
    ).deployment_mechanism.archive_runtime
    assert config is not None
    configured_cache = repo_root / config.cache_dir
    try:
        configured_cache.lstat()
    except FileNotFoundError:
        pytest.skip("portable 7-Zip cache is not provisioned")
    cache_dir = validate_archive_runtime_cache(repo_root, config)

    package_root = tmp_path / "deployed-package"
    backend_root = package_root / "backend-runtime" / "backend"
    shutil.copytree(
        repo_root / "backend" / "src",
        backend_root / "src",
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            ".build_packages",
            "bin",
            "obj",
        ),
    )
    documents = package_root / "documents"
    documents.mkdir(parents=True)
    shutil.copy2(
        repo_root / "documents" / "参数规范-3.yaml",
        documents / "参数规范-3.yaml",
    )
    runtime = package_root / config.destination_dir
    runtime.mkdir(parents=True)
    for filename in (
        *(item.filename for item in config.required_files),
        config.provenance_filename,
    ):
        shutil.copy2(cache_dir / filename, runtime / filename)
    return package_root, backend_root


@pytest.mark.integration
@pytest.mark.slow
def test_private_archive_runtime_passes_real_deployed_module_and_powershell_probe(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    package_root, backend_root = _build_real_archive_probe_package(tmp_path)
    clean_env = dict(os.environ)
    clean_env.pop("PYTHONHOME", None)
    clean_env.pop("PYTHONPATH", None)
    clean_env["PATH"] = ""
    clean_env["PYTHONNOUSERSITE"] = "1"

    direct = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "src.deploy.archive_runtime_probe",
            "--package-root",
            str(package_root),
        ],
        cwd=backend_root,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert direct.returncode == 0, direct.stderr
    direct_payload = json.loads(direct.stdout)
    assert direct_payload["status"] == "pass"
    assert set(direct_payload["formats"]) == {"zip", "7z", "rar5"}
    assert all(
        item == {"status": "pass", "listed": True, "extracted": True}
        for item in direct_payload["formats"].values()
    )

    powershell = shutil.which("powershell") or shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    probe_script = repo_root / "tools" / "probe_target_env.ps1"
    harness = tmp_path / "invoke-archive-runtime-facts.ps1"
    harness.write_text(
        f'''$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    {_ps_quote(str(probe_script))},
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {{ throw "probe_target_env.ps1 parse failed" }}
$functionAsts = @($ast.FindAll({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}}, $true))
foreach ($name in @("New-CheckResult", "ConvertTo-PlainValue", "Invoke-ExternalCommand", "Get-ArchiveRuntimeFacts")) {{
    $functionAst = @($functionAsts | Where-Object {{ $_.Name -eq $name }}) | Select-Object -First 1
    if ($null -eq $functionAst) {{ throw ("missing function: " + $name) }}
    Invoke-Expression $functionAst.Extent.Text
}}
$pythonFacts = [ordered]@{{ selected = [ordered]@{{ executable = {_ps_quote(sys.executable)} }} }}
$facts = Get-ArchiveRuntimeFacts -ActualRepoRoot {_ps_quote(str(package_root))} -PythonFacts $pythonFacts
$facts | ConvertTo-Json -Depth 12 -Compress
if ($facts.status -ne "pass") {{ exit 3 }}
''',
        encoding="utf-8",
    )
    powershell_result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
        ],
        cwd=repo_root,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert powershell_result.returncode == 0, powershell_result.stderr
    powershell_payload = json.loads(powershell_result.stdout.strip())
    assert powershell_payload["status"] == "pass"
    assert set(powershell_payload["formats"]) == {"zip", "7z", "rar5"}


@pytest.mark.integration
@pytest.mark.slow
def test_probe_target_env_v2_schema_and_repo_paths(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "tools" / "probe_target_env.ps1"
    out_json = tmp_path / "probe.json"
    storage_root = tmp_path / "storage"
    port = _pick_free_port()

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-OutJson",
            str(out_json),
            "-RepoRoot",
            str(repo_root),
            "-Port",
            str(port),
            "-StorageRoot",
            str(storage_root),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.returncode == 0
    assert out_json.exists()

    payload = json.loads(out_json.read_text(encoding="utf-8-sig"))

    assert payload["schema_version"] == "fanban-env-probe@2"
    assert payload["probe_meta"]["input"]["repo_root"] == str(repo_root)
    assert payload["repo"]["exists"]["business_spec_exists"] is True
    assert payload["repo"]["exists"]["runtime_spec_exists"] is True
    assert payload["repo"]["unicode_paths"]["status"] == "pass"
    assert "archive_runtime" in payload
    assert any(
        issue["section"] == "archive_runtime" and issue["code"] == "archive_runtime_probe"
        for issue in payload["blocking_issues"]
    ) == (payload["archive_runtime"]["status"] != "pass")

    office = payload["office"]
    assert office["word_com"]["status"] in {"pass", "fail", "skip"}
    assert office["excel_com"]["status"] in {"pass", "fail", "skip"}
    assert office["word_export_smoke"]["status"] in {"pass", "fail", "skip"}
    assert office["excel_export_smoke"]["status"] in {"pass", "fail", "skip"}

    recommended = payload["recommended_runtime"]
    assert recommended["recommended_doc_workers"] == 1
    assert recommended["recommended_port"] == port
    assert recommended["recommended_storage_root"] == str(storage_root)
    assert recommended["recommended_archive_keep"] == "package_zip_only"
    expected_7z = repo_root / "bin" / "7-Zip" / "7z.exe"
    assert recommended["recommended_env"][
        "FANBAN_CALCULATION_BOOK__ARCHIVE_EXTRACTOR__EXECUTABLE"
    ] == str(expected_7z)
