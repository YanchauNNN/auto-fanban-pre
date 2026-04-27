param(
    [int]$ApiPort = 18080,
    [int]$WebPort = 18081
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontendDir = Join-Path $repoRoot "frontend"
$backendProject = Join-Path $repoRoot "backend"
$launcherPath = Join-Path $repoRoot "desktop\launcher.py"

Push-Location $frontendDir
try {
    $env:VITE_API_BASE_URL = "http://127.0.0.1:$ApiPort"
    npm install
    npm run build
}
finally {
    Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
    Pop-Location
}

Push-Location $repoRoot
try {
    uv sync --project $backendProject --extra dev --extra desktop
    uv run --project $backendProject pyinstaller `
        --noconfirm `
        --clean `
        --name AutoFanbanFontSync `
        --paths $repoRoot `
        --paths (Join-Path $repoRoot "backend") `
        --add-data "$(Join-Path $repoRoot 'frontend\dist');frontend/dist" `
        --add-data "$(Join-Path $repoRoot 'documents');documents" `
        $launcherPath
}
finally {
    Pop-Location
}
