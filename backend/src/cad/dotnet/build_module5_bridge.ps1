param(
    [string]$AutoCADInstallDir = "D:\Program Files\AUTOCAD\AutoCAD 2022"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectPath = Join-Path $scriptDir "Module5CadBridge\Module5CadBridge.csproj"
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..\..\..")

if (-not (Test-Path $projectPath)) {
    throw "Project not found: $projectPath"
}

$dotnetExe = $null
$localDotnetCandidates = @(
    (Join-Path $repoRoot "Dependency Library\.dotnet\sdk-local\dotnet.exe"),
    (Join-Path $repoRoot "Dependency Library\.dotnet\sdk8\dotnet.exe")
)
foreach ($candidate in $localDotnetCandidates) {
    if (Test-Path $candidate) {
        $dotnetExe = $candidate
        break
    }
}

if (-not $dotnetExe) {
    $dotnetCmd = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($dotnetCmd) {
        $dotnetExe = $dotnetCmd.Source
    }
}

if (-not $dotnetExe) {
    throw "dotnet SDK not found. Ensure either system dotnet exists or repo-local dotnet exists at Dependency Library\\.dotnet\\sdk-local\\dotnet.exe."
}

$sdkList = & $dotnetExe --list-sdks
if (-not $sdkList) {
    throw "dotnet command found, but no .NET SDK is installed. Install .NET SDK and rerun this script."
}

Write-Host "[build] project: $projectPath"
Write-Host "[build] AutoCADInstallDir: $AutoCADInstallDir"
Write-Host "[build] dotnet: $dotnetExe"

& $dotnetExe build $projectPath `
    -c Release `
    -p:AutoCADInstallDir="$AutoCADInstallDir"

if ($LASTEXITCODE -ne 0) {
    throw "dotnet build failed with exit code $LASTEXITCODE"
}

Write-Host "[build] done"
