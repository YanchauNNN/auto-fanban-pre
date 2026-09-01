[CmdletBinding()]
param(
    [string]$ArchivePath = "",
    [string]$Destination = "",
    [switch]$SkipValidation
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if ([string]::IsNullOrWhiteSpace($ArchivePath)) {
    $archive = Get-ChildItem -LiteralPath (Join-Path $repoRoot "documents\AI") `
        -Filter "ansys-mapdl-18-2-private-offline-*.zip" -File |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $archive) {
        throw "ANSYS MAPDL 18.2 private offline archive was not found."
    }
    $ArchivePath = $archive.FullName
}
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $repoRoot "storage\ai\skills\ansys-mapdl-18-2"
}

$python = Get-Command python -ErrorAction SilentlyContinue
$pythonArgs = @()
if ($null -eq $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    $pythonArgs = @("-3")
}
if ($null -eq $python) {
    throw "Python 3.10 or later was not found."
}

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $repoRoot "backend"
    & $python.Source @pythonArgs -m src.ai.ansys_mapdl_skill $ArchivePath $Destination
    if ($LASTEXITCODE -ne 0) {
        throw "ANSYS MAPDL Skill extraction failed with exit code $LASTEXITCODE"
    }

    if (-not $SkipValidation) {
        $validator = Join-Path $Destination "scripts\validate_mapdl_skill.py"
        & $python.Source @pythonArgs $validator
        if ($LASTEXITCODE -ne 0) {
            throw "ANSYS MAPDL Skill validation failed with exit code $LASTEXITCODE"
        }
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host ("ANSYS MAPDL Skill installed: " + (Resolve-Path -LiteralPath $Destination).Path)
