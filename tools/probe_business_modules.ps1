param(
    [string]$PackageRoot = "",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$OutputDir = "",
    [switch]$AllowSyntheticMutation
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
    $PackageRoot = Split-Path -Parent $PSScriptRoot
}
$PackageRoot = [System.IO.Path]::GetFullPath($PackageRoot)
$python = Join-Path $PackageRoot "python-runtime\python.exe"
$backendRoot = Join-Path $PackageRoot "backend-runtime\backend"
$runtimeEnv = Join-Path $PSScriptRoot "runtime.env.ps1"
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputDir = Join-Path $PackageRoot ("logs\business-probes\account-workload-{0}" -f $stamp)
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Packaged Python is missing: $python"
}
if (-not (Test-Path -LiteralPath $backendRoot -PathType Container)) {
    throw "Packaged backend root is missing: $backendRoot"
}
if (Test-Path -LiteralPath $runtimeEnv -PathType Leaf) {
    . $runtimeEnv
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$previousPythonNoUserSite = [Environment]::GetEnvironmentVariable("PYTHONNOUSERSITE", "Process")
$previousPythonDontWriteBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")
$previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$previousPythonHome = [Environment]::GetEnvironmentVariable("PYTHONHOME", "Process")

Push-Location $backendRoot
try {
    [Environment]::SetEnvironmentVariable("PYTHONNOUSERSITE", "1", "Process")
    [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1", "Process")
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONHOME", $null, "Process")
    $pythonArgs = @(
        "-X", "utf8",
        "-m", "src.deploy.business_module_probe",
        "--api-base-url", $ApiBaseUrl,
        "--output-dir", $OutputDir
    )
    if ($AllowSyntheticMutation) {
        $pythonArgs += "--allow-synthetic-mutation"
    }
    & $python @pythonArgs
    $probeExitCode = $LASTEXITCODE
} finally {
    Pop-Location
    [Environment]::SetEnvironmentVariable("PYTHONNOUSERSITE", $previousPythonNoUserSite, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $previousPythonDontWriteBytecode, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $previousPythonPath, "Process")
    [Environment]::SetEnvironmentVariable("PYTHONHOME", $previousPythonHome, "Process")
}

$summaryPath = Join-Path $OutputDir "summary.json"
if ($probeExitCode -ne 0) {
    throw "Account/workload probe failed (exit=$probeExitCode). Summary: $summaryPath"
}
Write-Host ("Account/workload probe passed. Summary: " + $summaryPath)
