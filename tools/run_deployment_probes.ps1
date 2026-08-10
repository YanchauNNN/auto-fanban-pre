param(
    [string]$PackageRoot = "",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$OutputDir = "",
    [switch]$AllowSyntheticMutation,
    [switch]$RunCalculationSmoke,
    [string]$CalculationArchive = ""
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($PackageRoot)) {
    $PackageRoot = Split-Path -Parent $PSScriptRoot
}
$PackageRoot = [System.IO.Path]::GetFullPath($PackageRoot)
$python = Join-Path $PackageRoot "python-runtime\python.exe"
$backendRoot = Join-Path $PackageRoot "backend-runtime\backend"
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $OutputDir = Join-Path $PackageRoot ("logs\deployment-probes\{0}" -f $stamp)
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$transcriptPath = Join-Path $OutputDir "deployment-probes.log"
$summaryPath = Join-Path $OutputDir "summary.json"
$healthScript = Join-Path $PSScriptRoot "check_health.ps1"
$businessScript = Join-Path $PSScriptRoot "probe_business_modules.ps1"
$calculationScript = Join-Path $PSScriptRoot "probe_calculation_book.ps1"

foreach ($requiredPath in @($python, $backendRoot, $healthScript, $businessScript, $calculationScript)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Deployment probe dependency is missing: $requiredPath"
    }
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$steps = [ordered]@{}
$overallStatus = "PASS"
Start-Transcript -LiteralPath $transcriptPath -Force | Out-Null
try {
    $apiUri = [Uri]$ApiBaseUrl
    $healthArgs = @{
        Url = ($ApiBaseUrl.TrimEnd("/") + "/api/system/health")
        PingUrl = ($ApiBaseUrl.TrimEnd("/") + "/api/system/ping")
        ApiPort = $apiUri.Port
        Mode = "deep"
    }
    try {
        & $healthScript @healthArgs
        $healthSummarySource = Join-Path $PackageRoot "logs\check_health.summary.json"
        if (-not (Test-Path -LiteralPath $healthSummarySource -PathType Leaf)) {
            throw "check_health did not write its summary."
        }
        $healthSummary = Get-Content -LiteralPath $healthSummarySource -Raw | ConvertFrom-Json
        $healthStatus = ([string]$healthSummary.overall_status).ToUpperInvariant()
        if ($healthStatus -ne "PASS") {
            throw "Environment/service health status is $healthStatus."
        }
        Copy-Item -LiteralPath $healthSummarySource -Destination (Join-Path $OutputDir "environment.summary.json") -Force
        $steps.environment = [ordered]@{ status = "PASS"; summary = "environment.summary.json" }
    } catch {
        $overallStatus = "FAIL"
        $steps.environment = [ordered]@{ status = "FAIL"; error = $_.Exception.Message }
    }

    $businessOutput = Join-Path $OutputDir "account-workload"
    try {
        & $businessScript `
            -PackageRoot $PackageRoot `
            -ApiBaseUrl $ApiBaseUrl `
            -OutputDir $businessOutput `
            -AllowSyntheticMutation:$AllowSyntheticMutation
        $businessSummary = Get-Content -LiteralPath (Join-Path $businessOutput "summary.json") -Raw | ConvertFrom-Json
        if ([string]$businessSummary.status -ne "PASS") {
            throw "Account/workload summary is not PASS."
        }
        $steps.account_workload = [ordered]@{ status = "PASS"; summary = "account-workload/summary.json" }
    } catch {
        $overallStatus = "FAIL"
        $steps.account_workload = [ordered]@{ status = "FAIL"; error = $_.Exception.Message }
    }

    $calculationOutput = Join-Path $OutputDir "calculation-book"
    try {
        $calculationArgs = @{
            PackageRoot = $PackageRoot
            ApiBaseUrl = $ApiBaseUrl
            OutputDir = $calculationOutput
            RunFullSmoke = $RunCalculationSmoke
        }
        if ($RunCalculationSmoke) {
            $calculationArgs.Archive = $CalculationArchive
        }
        & $calculationScript @calculationArgs
        $calculationSummary = Get-Content -LiteralPath (Join-Path $calculationOutput "summary.json") -Raw | ConvertFrom-Json
        if ([string]$calculationSummary.status -ne "PASS") {
            throw "Calculation-book summary is not PASS."
        }
        $steps.calculation_book = [ordered]@{ status = "PASS"; summary = "calculation-book/summary.json" }
    } catch {
        $overallStatus = "FAIL"
        $steps.calculation_book = [ordered]@{ status = "FAIL"; error = $_.Exception.Message }
    }

    $summary = [ordered]@{
        schema_version = "fanban-deployment-probes@1"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        status = $overallStatus
        terminal = $true
        package_root = $PackageRoot
        log = "deployment-probes.log"
        steps = $steps
    }
    $tempSummary = Join-Path $OutputDir (".summary.{0}.tmp" -f [Guid]::NewGuid().ToString("N"))
    $summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $tempSummary -Encoding UTF8
    Move-Item -LiteralPath $tempSummary -Destination $summaryPath -Force
} finally {
    Stop-Transcript | Out-Null
}

Write-Host ("Deployment probe summary: " + $summaryPath)
if ($overallStatus -ne "PASS") {
    throw "Deployment probes failed. Return this result directory: $OutputDir"
}
