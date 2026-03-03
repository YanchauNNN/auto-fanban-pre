param(
    [string]$AutoCADInstallDir = "D:\Program Files\AUTOCAD\AutoCAD 2022"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectPath = Join-Path $scriptDir "Module5CadBridge\Module5CadBridge.csproj"

if (-not (Test-Path $projectPath)) {
    throw "Project not found: $projectPath"
}

$dotnetCmd = Get-Command dotnet -ErrorAction SilentlyContinue
if (-not $dotnetCmd) {
    throw "dotnet SDK not found. Install .NET SDK and rerun this script."
}

$sdkList = & dotnet --list-sdks
if (-not $sdkList) {
    throw "dotnet command found, but no .NET SDK is installed. Install .NET SDK and rerun this script."
}

Write-Host "[build] project: $projectPath"
Write-Host "[build] AutoCADInstallDir: $AutoCADInstallDir"

dotnet build $projectPath `
    -c Release `
    -p:AutoCADInstallDir="$AutoCADInstallDir"

if ($LASTEXITCODE -ne 0) {
    throw "dotnet build failed with exit code $LASTEXITCODE"
}

Write-Host "[build] done"
