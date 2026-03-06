param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$distRoot = Split-Path -Parent $scriptDir
$repoRoot = Split-Path -Parent (Split-Path -Parent $distRoot)
$venvPython = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
$assetsRoot = Join-Path $distRoot "assets"
$plottersRoot = Join-Path $assetsRoot "plotters"
$plotStylesRoot = Join-Path $assetsRoot "plot_styles"
$documentsRoot = Join-Path $repoRoot "documents"
$pc3Source = Get-ChildItem -Path $documentsRoot -File -Filter *.pc3 | Where-Object { $_.Name -like "*PDF2*.pc3" } | Select-Object -First 1 -ExpandProperty FullName
$pmpSource = Join-Path $documentsRoot "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp"
$ctbCandidates = @(
    (Join-Path $env:APPDATA "Autodesk\AutoCAD 2022\R24.1\chs\Plotters\Plot Styles\monochrome.ctb"),
    (Join-Path $env:APPDATA "Autodesk\AutoCAD 2022\R24.1\enu\Plotters\Plot Styles\monochrome.ctb")
)
$ctbSource = $ctbCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

New-Item -ItemType Directory -Force -Path $plottersRoot | Out-Null
New-Item -ItemType Directory -Force -Path $plotStylesRoot | Out-Null

if (-not $pc3Source) { throw "Missing PDF2 PC3 source under documents." }
if (-not (Test-Path $pmpSource)) { throw "Missing PMP source under documents." }
if (-not $ctbSource) { throw "Missing monochrome.ctb in the current AutoCAD user profile." }

$pc3Name = Split-Path -Leaf $pc3Source
$pmpName = Split-Path -Leaf $pmpSource

Copy-Item $pc3Source (Join-Path $plottersRoot $pc3Name) -Force
Copy-Item $pmpSource (Join-Path $plottersRoot $pmpName) -Force
Copy-Item $ctbSource (Join-Path $plotStylesRoot "monochrome.ctb") -Force

& $venvPython -m pip install pyinstaller
& $venvPython -m PyInstaller (Join-Path $scriptDir "fanban_m5.spec") --noconfirm --clean --distpath $distRoot --workpath (Join-Path $distRoot "build")
