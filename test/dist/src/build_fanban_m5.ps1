param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$distRoot = Split-Path -Parent $scriptDir
$repoRoot = Split-Path -Parent (Split-Path -Parent $distRoot)
$venvPython = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$assetsRoot = Join-Path $distRoot "assets"
$plottersRoot = Join-Path $assetsRoot "plotters"
$plotStylesRoot = Join-Path $assetsRoot "plot_styles"
$appDistRoot = Join-Path $distRoot "fanban_m5"
$buildRoot = Join-Path $distRoot "build"
$resourcesRoot = Join-Path $repoRoot "documents\Resources"
$pc3Source = Get-ChildItem -Path $resourcesRoot -File -Filter *.pc3 | Where-Object { $_.Name -like "*PDF2*.pc3" } | Select-Object -First 1 -ExpandProperty FullName
$pmpSource = Join-Path $resourcesRoot "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp"
$ctbSources = @(
    (Join-Path $resourcesRoot "fanban_monochrome.ctb"),
    (Join-Path $resourcesRoot "fanban_monochrome-same width.ctb"),
    (Join-Path $resourcesRoot "打白图.ctb")
)

if (Test-Path $assetsRoot) { Remove-Item $assetsRoot -Recurse -Force }
if (Test-Path $appDistRoot) { Remove-Item $appDistRoot -Recurse -Force }
if (Test-Path $buildRoot) { Remove-Item $buildRoot -Recurse -Force }

New-Item -ItemType Directory -Force -Path $plottersRoot | Out-Null
New-Item -ItemType Directory -Force -Path $plotStylesRoot | Out-Null

if (-not $pc3Source) { throw "Missing PDF2 PC3 source under documents\\Resources." }
if (-not (Test-Path $pmpSource)) { throw "Missing PMP source under documents\\Resources." }
foreach ($ctbSource in $ctbSources) {
    if (-not (Test-Path $ctbSource)) {
        throw "Missing managed CTB source under documents\\Resources: $ctbSource"
    }
}

$pc3Name = Split-Path -Leaf $pc3Source
$pmpName = Split-Path -Leaf $pmpSource

try {
    Copy-Item $pc3Source (Join-Path $plottersRoot $pc3Name) -Force
    Copy-Item $pmpSource (Join-Path $plottersRoot $pmpName) -Force
    foreach ($ctbSource in $ctbSources) {
        Copy-Item $ctbSource (Join-Path $plotStylesRoot (Split-Path -Leaf $ctbSource)) -Force
    }

    & $venvPython -m pip install pyinstaller
    & $venvPython -m PyInstaller (Join-Path $scriptDir "fanban_m5.spec") --noconfirm --clean --distpath $distRoot --workpath $buildRoot
}
finally {
    if (Test-Path $assetsRoot) { Remove-Item $assetsRoot -Recurse -Force }
    if (Test-Path $buildRoot) { Remove-Item $buildRoot -Recurse -Force }
}
