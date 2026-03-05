param(
    [string]$OutJson = ""
)

$ErrorActionPreference = "SilentlyContinue"

function Get-Timestamp {
    return (Get-Date).ToString("yyyyMMdd-HHmmss")
}

function Resolve-FullPathOrRaw {
    param([string]$PathText)
    if ([string]::IsNullOrWhiteSpace($PathText)) { return $null }
    try {
        return (Resolve-Path -LiteralPath $PathText -ErrorAction Stop).Path
    } catch {
        return $PathText
    }
}

function Test-WriteAccess {
    param([string]$DirPath)
    if ([string]::IsNullOrWhiteSpace($DirPath)) { return $false }
    if (-not (Test-Path -LiteralPath $DirPath)) { return $false }
    $probe = Join-Path $DirPath ("fanban_write_probe_" + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        "ok" | Out-File -LiteralPath $probe -Encoding utf8 -Force
        Remove-Item -LiteralPath $probe -Force
        return $true
    } catch {
        return $false
    }
}

function Get-RegistrySubKeys {
    param(
        [string]$HivePrefix,
        [string]$Path
    )
    $full = "$HivePrefix\$Path"
    try {
        return (Get-ChildItem -Path $full -ErrorAction Stop | Select-Object -ExpandProperty PSChildName)
    } catch {
        return @()
    }
}

function Get-RegistryStringValue {
    param(
        [string]$HivePrefix,
        [string]$Path,
        [string]$Name
    )
    $full = "$HivePrefix\$Path"
    try {
        $item = Get-ItemProperty -Path $full -ErrorAction Stop
        $v = $item.$Name
        if ($null -eq $v) { return $null }
        return [string]$v
    } catch {
        return $null
    }
}

function Add-UniquePath {
    param(
        [System.Collections.Generic.List[string]]$List,
        [string]$Candidate
    )
    if ([string]::IsNullOrWhiteSpace($Candidate)) { return }
    $c = $Candidate.Trim()
    if (-not (Test-Path -LiteralPath $c -PathType Container)) { return }
    foreach ($existing in $List) {
        if ($existing.ToLowerInvariant() -eq $c.ToLowerInvariant()) { return }
    }
    $List.Add((Resolve-FullPathOrRaw $c))
}

function Find-AutoCADInstallDirs {
    $dirs = New-Object 'System.Collections.Generic.List[string]'

    $uninstallRoots = @(
        "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        "SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    $autocadRoot = "SOFTWARE\Autodesk\AutoCAD"

    $hives = @("HKLM:", "HKCU:")

    foreach ($h in $hives) {
        foreach ($r in $uninstallRoots) {
            $subs = Get-RegistrySubKeys -HivePrefix $h -Path $r
            foreach ($s in $subs) {
                $full = "$r\$s"
                $name = Get-RegistryStringValue -HivePrefix $h -Path $full -Name "DisplayName"
                if ([string]::IsNullOrWhiteSpace($name)) { continue }
                if ($name.ToLowerInvariant() -notmatch "autocad") { continue }
                $loc = Get-RegistryStringValue -HivePrefix $h -Path $full -Name "InstallLocation"
                Add-UniquePath -List $dirs -Candidate $loc
            }
        }

        $versions = Get-RegistrySubKeys -HivePrefix $h -Path $autocadRoot
        foreach ($v in $versions) {
            $vPath = "$autocadRoot\$v"
            $products = Get-RegistrySubKeys -HivePrefix $h -Path $vPath
            foreach ($p in $products) {
                $pPath = "$vPath\$p"
                $acadLoc = Get-RegistryStringValue -HivePrefix $h -Path $pPath -Name "AcadLocation"
                Add-UniquePath -List $dirs -Candidate $acadLoc
            }
        }
    }

    $commonRoots = @(
        "C:\Program Files\AUTOCAD",
        "D:\Program Files\AUTOCAD",
        "C:\Program Files\Autodesk",
        "D:\Program Files\Autodesk"
    )
    foreach ($root in $commonRoots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        try {
            $cands = Get-ChildItem -LiteralPath $root -Directory -ErrorAction Stop |
                Where-Object { $_.Name -match "AutoCAD" } |
                Select-Object -ExpandProperty FullName
            foreach ($c in $cands) {
                Add-UniquePath -List $dirs -Candidate $c
            }
        } catch {}
    }

    return $dirs.ToArray()
}

function Get-UserPlotterDirs {
    $res = New-Object 'System.Collections.Generic.List[string]'
    $appdata = $env:APPDATA
    if ([string]::IsNullOrWhiteSpace($appdata)) { return @() }
    $root = Join-Path $appdata "Autodesk"
    if (-not (Test-Path -LiteralPath $root)) { return @() }
    try {
        $dirs = Get-ChildItem -LiteralPath $root -Recurse -Directory -Filter "Plotters" -ErrorAction Stop |
            Select-Object -ExpandProperty FullName
        foreach ($d in $dirs) {
            Add-UniquePath -List $res -Candidate $d
        }
    } catch {}
    return $res.ToArray()
}

function Get-InstallFacts {
    param([string]$InstallDir)
    $acad = Join-Path $InstallDir "acad.exe"
    $acadlt = Join-Path $InstallDir "acadlt.exe"
    $accore = Join-Path $InstallDir "accoreconsole.exe"
    $fonts = Join-Path $InstallDir "Fonts"
    $plotters = Join-Path $InstallDir "Plotters"
    $styles = Join-Path $plotters "Plot Styles"

    $installPc3Names = @()
    try {
        if (Test-Path -LiteralPath $plotters) {
            $installPc3Names = Get-ChildItem -LiteralPath $plotters -Filter "*.pc3" -File -ErrorAction Stop |
                Select-Object -ExpandProperty Name
        }
    } catch {}
    $installCustomPdf2 = @($installPc3Names | Where-Object { $_ -match "(?i)pdf2.*\.pc3$" -or $_ -match "(?i)pdf2\.pc3$" })

    return [ordered]@{
        install_dir = $InstallDir
        acad_exe = (Resolve-FullPathOrRaw $acad)
        acad_exe_exists = (Test-Path -LiteralPath $acad -PathType Leaf)
        acadlt_exe = (Resolve-FullPathOrRaw $acadlt)
        acadlt_exe_exists = (Test-Path -LiteralPath $acadlt -PathType Leaf)
        accoreconsole_exe = (Resolve-FullPathOrRaw $accore)
        accoreconsole_exe_exists = (Test-Path -LiteralPath $accore -PathType Leaf)
        fonts_dir = (Resolve-FullPathOrRaw $fonts)
        fonts_dir_exists = (Test-Path -LiteralPath $fonts -PathType Container)
        install_plotters_dir = (Resolve-FullPathOrRaw $plotters)
        install_plotters_dir_exists = (Test-Path -LiteralPath $plotters -PathType Container)
        install_plot_styles_dir = (Resolve-FullPathOrRaw $styles)
        install_plot_styles_dir_exists = (Test-Path -LiteralPath $styles -PathType Container)
        install_monochrome_ctb = (Resolve-FullPathOrRaw (Join-Path $styles "monochrome.ctb"))
        install_monochrome_ctb_exists = (Test-Path -LiteralPath (Join-Path $styles "monochrome.ctb") -PathType Leaf)
        install_dwg_to_pdf_pc3 = (Resolve-FullPathOrRaw (Join-Path $plotters "DWG To PDF.pc3"))
        install_dwg_to_pdf_pc3_exists = (Test-Path -LiteralPath (Join-Path $plotters "DWG To PDF.pc3") -PathType Leaf)
        install_custom_pdf2_pc3_names = $installCustomPdf2
        install_has_custom_pdf2_pc3 = ($installCustomPdf2.Count -gt 0)
    }
}

function Get-PlotterFacts {
    param([string]$PlotterDir)
    $styles = Join-Path $PlotterDir "Plot Styles"
    $pc3Names = @()
    $ctbNames = @()
    try {
        if (Test-Path -LiteralPath $PlotterDir) {
            $pc3Names = Get-ChildItem -LiteralPath $PlotterDir -Filter "*.pc3" -File -ErrorAction Stop |
                Select-Object -ExpandProperty Name
        }
    } catch {}
    try {
        if (Test-Path -LiteralPath $styles) {
            $ctbNames = Get-ChildItem -LiteralPath $styles -Filter "*.ctb" -File -ErrorAction Stop |
                Select-Object -ExpandProperty Name
        }
    } catch {}
    $customPdf2 = @($pc3Names | Where-Object { $_ -match "(?i)pdf2.*\.pc3$" -or $_ -match "(?i)pdf2\.pc3$" })
    return [ordered]@{
        plotters_dir = (Resolve-FullPathOrRaw $PlotterDir)
        plot_styles_dir = (Resolve-FullPathOrRaw $styles)
        has_custom_pdf2_pc3 = ($customPdf2.Count -gt 0)
        custom_pdf2_pc3_names = $customPdf2
        has_dwg_to_pdf_pc3 = ($pc3Names -contains "DWG To PDF.pc3")
        has_monochrome_ctb = ($ctbNames -contains "monochrome.ctb")
        pc3_files = $pc3Names
        ctb_files = $ctbNames
    }
}

function Pick-BestAccoreconsole {
    param([array]$InstallFacts)
    $withAccore = $InstallFacts | Where-Object { $_.accoreconsole_exe_exists -eq $true }
    $withAccoreArr = @($withAccore)
    if (-not $withAccoreArr -or $withAccoreArr.Count -eq 0) { return $null }
    return $withAccoreArr[0].accoreconsole_exe
}

function Pick-BestPlotterDir {
    param([array]$PlotterFacts)
    $p1 = @($PlotterFacts | Where-Object { $_.has_custom_pdf2_pc3 -and $_.has_monochrome_ctb })
    if ($p1 -and $p1.Count -gt 0) { return $p1[0] }
    $p2 = @($PlotterFacts | Where-Object { $_.has_dwg_to_pdf_pc3 -and $_.has_monochrome_ctb })
    if ($p2 -and $p2.Count -gt 0) { return $p2[0] }
    $all = @($PlotterFacts)
    if ($all -and $all.Count -gt 0) { return $all[0] }
    return $null
}

function Try-GetDotnetInfo {
    $cmd = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        return [ordered]@{
            exists = $false
            path = $null
            version = $null
            info_head = @()
        }
    }
    $version = $null
    $head = @()
    try {
        $version = (& dotnet --version 2>$null | Select-Object -First 1)
    } catch {}
    try {
        $head = (& dotnet --info 2>$null | Select-Object -First 30)
    } catch {}
    return [ordered]@{
        exists = $true
        path = (Resolve-FullPathOrRaw $cmd.Source)
        version = $version
        info_head = $head
    }
}

function Detect-RepoRoot {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    $cand = Resolve-FullPathOrRaw (Join-Path $here "..")
    if (-not [string]::IsNullOrWhiteSpace($cand)) {
        $spec = Join-Path $cand "documents\参数规范.yaml"
        if (Test-Path -LiteralPath $spec) {
            return $cand
        }
    }
    return (Get-Location).Path
}

function Get-RepoFacts {
    param([string]$RepoRoot)
    $paths = [ordered]@{
        repo_root = $RepoRoot
        runtime_spec = Join-Path $RepoRoot "documents\参数规范_运行期.yaml"
        business_spec = Join-Path $RepoRoot "documents\参数规范.yaml"
        cad_scripts_dir = Join-Path $RepoRoot "backend\src\cad\scripts"
        dotnet_bridge_dll = Join-Path $RepoRoot "backend\src\cad\dotnet\Module5CadBridge\bin\Release\net48\Module5CadBridge.dll"
        oda_exe = Join-Path $RepoRoot "bin\ODAFileConverter 25.12.0\ODAFileConverter.exe"
    }
    $exists = [ordered]@{}
    foreach ($k in $paths.Keys) {
        if ($k -eq "repo_root") { continue }
        $exists[$k + "_exists"] = (Test-Path -LiteralPath $paths[$k])
    }
    return [ordered]@{
        paths = $paths
        exists = $exists
    }
}

if ([string]::IsNullOrWhiteSpace($OutJson)) {
    $OutJson = Join-Path (Get-Location).Path ("fanban_env_probe_" + $env:COMPUTERNAME + "_" + (Get-Timestamp) + ".json")
}

$installDirs = Find-AutoCADInstallDirs
$installFacts = @()
foreach ($d in $installDirs) {
    $installFacts += (Get-InstallFacts -InstallDir $d)
}

$userPlotterDirs = Get-UserPlotterDirs
$plotterFacts = @()
foreach ($p in $userPlotterDirs) {
    $plotterFacts += (Get-PlotterFacts -PlotterDir $p)
}

$bestAccore = Pick-BestAccoreconsole -InstallFacts $installFacts
$bestPlotter = Pick-BestPlotterDir -PlotterFacts $plotterFacts

$repoRoot = Detect-RepoRoot
$repoFacts = Get-RepoFacts -RepoRoot $repoRoot

$recommendedPc3 = $null
$recommendedCtb = $null
if ($bestPlotter -ne $null) {
    if ($bestPlotter.has_custom_pdf2_pc3 -and $bestPlotter.custom_pdf2_pc3_names.Count -gt 0) {
        $recommendedPc3 = $bestPlotter.custom_pdf2_pc3_names[0]
    }
    elseif ($bestPlotter.has_dwg_to_pdf_pc3) { $recommendedPc3 = "DWG To PDF.pc3" }
    if ($bestPlotter.has_monochrome_ctb) { $recommendedCtb = "monochrome.ctb" }
}

$result = [ordered]@{
    probe_meta = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        script = (Resolve-FullPathOrRaw $MyInvocation.MyCommand.Path)
        output_json = (Resolve-FullPathOrRaw $OutJson)
    }
    host = [ordered]@{
        computer_name = $env:COMPUTERNAME
        user = $env:USERNAME
        os_caption = (Get-CimInstance Win32_OperatingSystem).Caption
        os_version = (Get-CimInstance Win32_OperatingSystem).Version
        architecture = (Get-CimInstance Win32_OperatingSystem).OSArchitecture
        powershell_version = $PSVersionTable.PSVersion.ToString()
        culture = (Get-Culture).Name
    }
    write_access = [ordered]@{
        temp = [ordered]@{
            path = $env:TEMP
            writable = (Test-WriteAccess -DirPath $env:TEMP)
        }
        current_dir = [ordered]@{
            path = (Get-Location).Path
            writable = (Test-WriteAccess -DirPath (Get-Location).Path)
        }
    }
    dotnet = (Try-GetDotnetInfo)
    autocad = [ordered]@{
        install_dirs = $installFacts
        user_plotters = $plotterFacts
        best_guess = [ordered]@{
            accoreconsole_exe = $bestAccore
            plotters_dir = if ($bestPlotter -ne $null) { $bestPlotter.plotters_dir } else { $null }
            plot_styles_dir = if ($bestPlotter -ne $null) { $bestPlotter.plot_styles_dir } else { $null }
            pc3_name = $recommendedPc3
            ctb_name = $recommendedCtb
        }
    }
    repo = $repoFacts
    recommended_env = [ordered]@{
        FANBAN_MODULE5_EXPORT__CAD_RUNNER__ACCORECONSOLE_EXE = $bestAccore
        FANBAN_MODULE5_EXPORT__PLOT__PC3_NAME = $recommendedPc3
        FANBAN_MODULE5_EXPORT__PLOT__CTB_NAME = $recommendedCtb
        FANBAN_AUTOCAD__PC3_NAME = $recommendedPc3
        FANBAN_AUTOCAD__CTB_PATH = if ($bestPlotter -ne $null) {
            Join-Path $bestPlotter.plot_styles_dir "monochrome.ctb"
        } else {
            $null
        }
    }
    manual_checklist = @(
        "Confirm AutoCAD can start and license is valid.",
        "In AutoCAD plot dialog, verify target PC3 is visible (prefer printPDF2.pc3).",
        "Verify monochrome.ctb is available in Plot Styles.",
        "If only English profile exists, verify DWG To PDF.pc3 is available.",
        "Confirm write permission to the output directory."
    )
}

$json = $result | ConvertTo-Json -Depth 8
$outDir = Split-Path -Parent $OutJson
if (-not [string]::IsNullOrWhiteSpace($outDir) -and -not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}
$json | Out-File -LiteralPath $OutJson -Encoding utf8

Write-Host "==== Fanban Environment Probe ===="
Write-Host ("Output JSON: " + (Resolve-FullPathOrRaw $OutJson))
Write-Host ("AutoCAD install candidates: " + $installFacts.Count)
Write-Host ("User plotter dirs: " + $plotterFacts.Count)
Write-Host ("Best accoreconsole: " + $bestAccore)
Write-Host ("Best PC3 name: " + $recommendedPc3)
Write-Host ("Best CTB name: " + $recommendedCtb)
Write-Host "=================================="
