[CmdletBinding()]
param(
    [ValidateSet("quick", "cad", "docs", "api", "env", "all")]
    [string]$Stage = "quick",
    [switch]$VerboseOutput
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Script:ScriptPath = $PSCommandPath

function Resolve-RepoRoot {
    $scriptDir = Split-Path -Parent $Script:ScriptPath
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Get-PythonExecutable {
    param([string]$RepoRoot)

    $venvPython = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        return $venvPython
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        return @($pythonCommand.Source)
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $pyCommand) {
        return @($pyCommand.Source, "-3.13")
    }

    throw "No usable Python interpreter was found. Expected backend\.venv\Scripts\python.exe or python/py on PATH."
}

function Invoke-Pytest {
    param(
        [string]$RepoRoot,
        [string[]]$PythonExecutable,
        [string[]]$PytestArgs
    )

    $arguments = @("-m", "pytest") + $PytestArgs
    $launcherArgs = @()
    if ($PythonExecutable.Count -gt 1) {
        $launcherArgs = $PythonExecutable[1..($PythonExecutable.Count - 1)]
    }
    & $PythonExecutable[0] @launcherArgs @arguments
}

$repoRoot = Resolve-RepoRoot
$pythonExe = Get-PythonExecutable -RepoRoot $repoRoot

$commonArgs = @()
if (-not $VerboseOutput) {
    $commonArgs += "-q"
}

$stageArgs = switch ($Stage) {
    "quick" {
        @(
            "backend/tests/unit",
            "-m",
            "not slow and not integration"
        )
    }
    "cad" {
        @(
            "backend/tests/unit/test_accoreconsole_runner.py",
            "backend/tests/unit/test_autocad_path_resolver.py",
            "backend/tests/unit/test_cad_dxf_executor.py",
            "backend/tests/unit/test_frame_detector.py",
            "backend/tests/unit/test_frame_splitter.py",
            "backend/tests/unit/test_plot_resource_manager.py",
            "backend/tests/unit/test_project_no_inference.py",
            "backend/tests/unit/test_run_dwg_split_only.py",
            "backend/tests/unit/test_titleblock_extractor.py",
            "backend/tests/unit/test_fanban_m5_launcher.py"
        )
    }
    "docs" {
        @(
            "backend/tests/unit/test_cover.py",
            "backend/tests/unit/test_catalog.py",
            "backend/tests/unit/test_design.py",
            "backend/tests/unit/test_ied.py",
            "backend/tests/unit/test_pdf_engine.py",
            "backend/tests/unit/test_doc_param_validator.py",
            "backend/tests/unit/test_derivation.py"
        )
    }
    "api" {
        @(
            "backend/tests/unit/test_module7_api.py",
            "backend/tests/unit/test_job_manager.py",
            "backend/tests/unit/test_config.py",
            "backend/tests/unit/test_doc_param_validator.py",
            "backend/tests/unit/test_project_no_inference.py"
        )
    }
    "env" {
        @(
            "backend/tests/integration/test_probe_target_env.py"
        )
    }
    "all" {
        @(
            "backend/tests"
        )
    }
}

Push-Location $repoRoot
try {
    Invoke-Pytest -RepoRoot $repoRoot -PythonExecutable $pythonExe -PytestArgs ($stageArgs + $commonArgs)
} finally {
    Pop-Location
}
