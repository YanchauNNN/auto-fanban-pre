param(
    [string]$OutJson = "",
    [string]$RepoRoot = "",
    [int]$Port = 8000,
    [string]$StorageRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:ProbeScriptPath = $PSCommandPath

function Get-Timestamp {
    return (Get-Date).ToString("yyyyMMdd-HHmmss")
}

function Resolve-FullPathOrRaw {
    param([string]$PathText)

    if ([string]::IsNullOrWhiteSpace($PathText)) {
        return ""
    }

    try {
        return (Resolve-Path -LiteralPath $PathText -ErrorAction Stop).Path
    } catch {
        try {
            return [System.IO.Path]::GetFullPath($PathText)
        } catch {
            return $PathText
        }
    }
}

function New-CheckResult {
    param(
        [ValidateSet("pass", "fail", "skip")]
        [string]$Status,
        [object]$Details = $null,
        [Alias("Error")]
        [string]$ErrorMessage = ""
    )

    return [ordered]@{
        status = $Status
        ok = ($Status -eq "pass")
        error = $ErrorMessage
        details = if ($null -eq $Details) { @{} } else { $Details }
    }
}

function Add-UniqueString {
    param(
        [System.Collections.Generic.List[string]]$List,
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return
    }

    foreach ($existing in $List) {
        if ($existing -eq $Value) {
            return
        }
    }

    $List.Add($Value)
}

function Invoke-ExternalCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    try {
        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) {
            $exitCode = 0
        }
        $stdout = (($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
        return [ordered]@{
            success = ($exitCode -eq 0)
            exit_code = $exitCode
            stdout = $stdout
        }
    } catch {
        return [ordered]@{
            success = $false
            exit_code = -1
            stdout = ""
            error = $_.Exception.Message
        }
    }
}

function Test-WriteProbe {
    param([string]$DirPath)

    if ([string]::IsNullOrWhiteSpace($DirPath)) {
        return New-CheckResult -Status "fail" -Error "path is empty"
    }

    $createdDir = $false
    $probePath = ""
    try {
        if (-not (Test-Path -LiteralPath $DirPath -PathType Container)) {
            New-Item -ItemType Directory -Path $DirPath -Force | Out-Null
            $createdDir = $true
        }

        $probePath = Join-Path $DirPath ("fanban_probe_" + [guid]::NewGuid().ToString("N") + ".tmp")
        "ok" | Out-File -LiteralPath $probePath -Encoding utf8 -Force
        Remove-Item -LiteralPath $probePath -Force

        return New-CheckResult -Status "pass" -Details ([ordered]@{
            path = (Resolve-FullPathOrRaw $DirPath)
            created_for_probe = $createdDir
        })
    } catch {
        return New-CheckResult -Status "fail" -Details ([ordered]@{
            path = (Resolve-FullPathOrRaw $DirPath)
            created_for_probe = $createdDir
        }) -Error $_.Exception.Message
    } finally {
        if ($probePath -and (Test-Path -LiteralPath $probePath)) {
            Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
        }
        if ($createdDir -and (Test-Path -LiteralPath $DirPath)) {
            Remove-Item -LiteralPath $DirPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-TempDirectory {
    param([string]$Prefix)

    $tempRoot = [System.IO.Path]::GetTempPath()
    $root = Join-Path $tempRoot ($Prefix + "_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    return $root
}

function Remove-ProbePath {
    param([string]$PathText)

    if ([string]::IsNullOrWhiteSpace($PathText)) {
        return
    }

    if (Test-Path -LiteralPath $PathText) {
        Remove-Item -LiteralPath $PathText -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Get-RegistrySubKeys {
    param(
        [string]$HivePrefix,
        [string]$Path
    )

    try {
        return (Get-ChildItem -Path "$HivePrefix\$Path" -ErrorAction Stop |
            Select-Object -ExpandProperty PSChildName)
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

    try {
        $item = Get-ItemProperty -Path "$HivePrefix\$Path" -ErrorAction Stop
        $value = $item.$Name
        if ($null -eq $value) {
            return ""
        }
        return [string]$value
    } catch {
        return ""
    }
}

function Add-UniquePath {
    param(
        [System.Collections.Generic.List[string]]$List,
        [string]$Candidate
    )

    if ([string]::IsNullOrWhiteSpace($Candidate)) {
        return
    }

    $trimmed = $Candidate.Trim()
    if (-not (Test-Path -LiteralPath $trimmed -PathType Container)) {
        return
    }

    $resolved = Resolve-FullPathOrRaw $trimmed
    foreach ($existing in $List) {
        if ($existing.ToLowerInvariant() -eq $resolved.ToLowerInvariant()) {
            return
        }
    }

    $List.Add($resolved)
}
function Find-AutoCADInstallDirs {
    $dirs = New-Object System.Collections.Generic.List[string]
    $uninstallRoots = @(
        "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        "SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    $autocadRoot = "SOFTWARE\Autodesk\AutoCAD"

    foreach ($hive in @("HKLM:", "HKCU:")) {
        foreach ($root in $uninstallRoots) {
            foreach ($subKey in (Get-RegistrySubKeys -HivePrefix $hive -Path $root)) {
                $fullKey = "$root\$subKey"
                $displayName = Get-RegistryStringValue -HivePrefix $hive -Path $fullKey -Name "DisplayName"
                if ([string]::IsNullOrWhiteSpace($displayName)) {
                    continue
                }
                if ($displayName.ToLowerInvariant() -notmatch "autocad") {
                    continue
                }
                $installLocation = Get-RegistryStringValue -HivePrefix $hive -Path $fullKey -Name "InstallLocation"
                Add-UniquePath -List $dirs -Candidate $installLocation
            }
        }

        foreach ($version in (Get-RegistrySubKeys -HivePrefix $hive -Path $autocadRoot)) {
            $versionPath = "$autocadRoot\$version"
            foreach ($product in (Get-RegistrySubKeys -HivePrefix $hive -Path $versionPath)) {
                $productPath = "$versionPath\$product"
                $acadLocation = Get-RegistryStringValue -HivePrefix $hive -Path $productPath -Name "AcadLocation"
                Add-UniquePath -List $dirs -Candidate $acadLocation
            }
        }
    }

    foreach ($root in @(
        "C:\Program Files\AUTOCAD",
        "D:\Program Files\AUTOCAD",
        "C:\Program Files\Autodesk",
        "D:\Program Files\Autodesk"
    )) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }

        try {
            $children = Get-ChildItem -LiteralPath $root -Directory -ErrorAction Stop |
                Where-Object { $_.Name -match "AutoCAD" } |
                Select-Object -ExpandProperty FullName
            foreach ($child in $children) {
                Add-UniquePath -List $dirs -Candidate $child
            }
        } catch {
        }
    }

    return $dirs.ToArray()
}

function Get-UserPlotterDirs {
    $result = New-Object System.Collections.Generic.List[string]
    if ([string]::IsNullOrWhiteSpace($env:APPDATA)) {
        return @()
    }

    $root = Join-Path $env:APPDATA "Autodesk"
    if (-not (Test-Path -LiteralPath $root)) {
        return @()
    }

    try {
        $dirs = Get-ChildItem -LiteralPath $root -Recurse -Directory -Filter "Plotters" -ErrorAction Stop |
            Select-Object -ExpandProperty FullName
        foreach ($dir in $dirs) {
            Add-UniquePath -List $result -Candidate $dir
        }
    } catch {
    }

    return $result.ToArray()
}

function Get-InstallFacts {
    param([string]$InstallDir)

    $plotters = Join-Path $InstallDir "Plotters"
    $styles = Join-Path $plotters "Plot Styles"
    $pc3Files = @()
    try {
        if (Test-Path -LiteralPath $plotters) {
            $pc3Files = Get-ChildItem -LiteralPath $plotters -Filter "*.pc3" -File -ErrorAction Stop |
                Select-Object -ExpandProperty Name
        }
    } catch {
    }
    $customPdf2 = @($pc3Files | Where-Object { $_ -match "(?i)pdf2.*\.pc3$" -or $_ -match "(?i)pdf2\.pc3$" })

    return [ordered]@{
        install_dir = (Resolve-FullPathOrRaw $InstallDir)
        acad_exe = (Resolve-FullPathOrRaw (Join-Path $InstallDir "acad.exe"))
        acad_exe_exists = (Test-Path -LiteralPath (Join-Path $InstallDir "acad.exe") -PathType Leaf)
        accoreconsole_exe = (Resolve-FullPathOrRaw (Join-Path $InstallDir "accoreconsole.exe"))
        accoreconsole_exe_exists = (Test-Path -LiteralPath (Join-Path $InstallDir "accoreconsole.exe") -PathType Leaf)
        fonts_dir = (Resolve-FullPathOrRaw (Join-Path $InstallDir "Fonts"))
        fonts_dir_exists = (Test-Path -LiteralPath (Join-Path $InstallDir "Fonts") -PathType Container)
        install_plotters_dir = (Resolve-FullPathOrRaw $plotters)
        install_plotters_dir_exists = (Test-Path -LiteralPath $plotters -PathType Container)
        install_plot_styles_dir = (Resolve-FullPathOrRaw $styles)
        install_plot_styles_dir_exists = (Test-Path -LiteralPath $styles -PathType Container)
        install_dwg_to_pdf_pc3_exists = (Test-Path -LiteralPath (Join-Path $plotters "DWG To PDF.pc3") -PathType Leaf)
        install_monochrome_ctb_exists = (Test-Path -LiteralPath (Join-Path $styles "monochrome.ctb") -PathType Leaf)
        install_custom_pdf2_pc3_names = $customPdf2
        install_has_custom_pdf2_pc3 = ($customPdf2.Count -gt 0)
    }
}

function Get-PlotterFacts {
    param([string]$PlotterDir)

    $styles = Join-Path $PlotterDir "Plot Styles"
    $pc3Files = @()
    $ctbFiles = @()
    try {
        if (Test-Path -LiteralPath $PlotterDir) {
            $pc3Files = Get-ChildItem -LiteralPath $PlotterDir -Filter "*.pc3" -File -ErrorAction Stop |
                Select-Object -ExpandProperty Name
        }
    } catch {
    }
    try {
        if (Test-Path -LiteralPath $styles) {
            $ctbFiles = Get-ChildItem -LiteralPath $styles -Filter "*.ctb" -File -ErrorAction Stop |
                Select-Object -ExpandProperty Name
        }
    } catch {
    }

    $customPdf2 = @($pc3Files | Where-Object { $_ -match "(?i)pdf2.*\.pc3$" -or $_ -match "(?i)pdf2\.pc3$" })
    return [ordered]@{
        plotters_dir = (Resolve-FullPathOrRaw $PlotterDir)
        plot_styles_dir = (Resolve-FullPathOrRaw $styles)
        has_custom_pdf2_pc3 = ($customPdf2.Count -gt 0)
        custom_pdf2_pc3_names = $customPdf2
        has_dwg_to_pdf_pc3 = ($pc3Files -contains "DWG To PDF.pc3")
        has_monochrome_ctb = ($ctbFiles -contains "monochrome.ctb")
        pc3_files = $pc3Files
        ctb_files = $ctbFiles
    }
}

function Select-BestAccoreconsole {
    param([array]$InstallFacts)

    $withAccore = @($InstallFacts | Where-Object { $_.accoreconsole_exe_exists -eq $true })
    if ($withAccore.Count -eq 0) {
        return ""
    }
    return [string]$withAccore[0].accoreconsole_exe
}

function Select-BestPlotterDir {
    param([array]$PlotterFacts)

    $preferred = @($PlotterFacts | Where-Object { $_.has_custom_pdf2_pc3 -and $_.has_monochrome_ctb })
    if ($preferred.Count -gt 0) {
        return $preferred[0]
    }

    $fallback = @($PlotterFacts | Where-Object { $_.has_dwg_to_pdf_pc3 -and $_.has_monochrome_ctb })
    if ($fallback.Count -gt 0) {
        return $fallback[0]
    }

    $all = @($PlotterFacts)
    if ($all.Count -gt 0) {
        return $all[0]
    }

    return $null
}

function Test-PortAvailability {
    param([int]$TargetPort)

    $listener = $null
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $TargetPort)
        $listener.Start()
        return New-CheckResult -Status "pass" -Details ([ordered]@{
            port = $TargetPort
            available = $true
        })
    } catch {
        return New-CheckResult -Status "fail" -Details ([ordered]@{
            port = $TargetPort
            available = $false
        }) -Error $_.Exception.Message
    } finally {
        if ($null -ne $listener) {
            try { $listener.Stop() } catch {}
        }
    }
}

function Get-IPv4Addresses {
    $items = New-Object System.Collections.Generic.List[string]

    try {
        $addresses = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
            Where-Object {
                $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
                -not [System.Net.IPAddress]::IsLoopback($_)
            } |
            Select-Object -ExpandProperty IPAddressToString

        foreach ($address in $addresses) {
            if ($address -notmatch "^169\.254\.") {
                Add-UniqueString -List $items -Value $address
            }
        }
    } catch {
    }

    return ,($items.ToArray())
}

function Get-FirewallFacts {
    $cmd = Get-Command Get-NetFirewallProfile -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        return New-CheckResult -Status "skip" -Error "Get-NetFirewallProfile is unavailable"
    }

    try {
        $profiles = Get-NetFirewallProfile -ErrorAction Stop | ForEach-Object {
            [ordered]@{
                name = [string]$_.Name
                enabled = [bool]$_.Enabled
                default_inbound = [string]$_.DefaultInboundAction
                default_outbound = [string]$_.DefaultOutboundAction
            }
        }
        return New-CheckResult -Status "pass" -Details ([ordered]@{
            profiles = @($profiles)
        })
    } catch {
        return New-CheckResult -Status "fail" -Error $_.Exception.Message
    }
}

function Resolve-RepoRoot {
    param([string]$RepoRootArg)

    if (-not [string]::IsNullOrWhiteSpace($RepoRootArg)) {
        return Resolve-FullPathOrRaw $RepoRootArg
    }

    $scriptPath = $script:ProbeScriptPath
    if ([string]::IsNullOrWhiteSpace($scriptPath)) {
        $scriptPath = $MyInvocation.PSCommandPath
    }
    $scriptDir = Split-Path -Parent $scriptPath
    $candidate = Resolve-FullPathOrRaw (Join-Path $scriptDir "..")
    if (-not [string]::IsNullOrWhiteSpace($candidate)) {
        $specPath = Join-Path $candidate "documents\参数规范.yaml"
        if (Test-Path -LiteralPath $specPath) {
            return $candidate
        }
    }

    return (Get-Location).Path
}
function Get-RepoFacts {
    param([string]$ActualRepoRoot)

    $paths = [ordered]@{
        repo_root = (Resolve-FullPathOrRaw $ActualRepoRoot)
        runtime_spec = (Resolve-FullPathOrRaw (Join-Path $ActualRepoRoot "documents\参数规范_运行期.yaml"))
        business_spec = (Resolve-FullPathOrRaw (Join-Path $ActualRepoRoot "documents\参数规范.yaml"))
        cad_scripts_dir = (Resolve-FullPathOrRaw (Join-Path $ActualRepoRoot "backend\src\cad\scripts"))
        dotnet_bridge_dll = (Resolve-FullPathOrRaw (Join-Path $ActualRepoRoot "backend\src\cad\dotnet\Module5CadBridge\bin\Release\net48\Module5CadBridge.dll"))
        oda_exe = (Resolve-FullPathOrRaw (Join-Path $ActualRepoRoot "bin\ODAFileConverter 25.12.0\ODAFileConverter.exe"))
        common_cover_template = (Resolve-FullPathOrRaw (Join-Path $ActualRepoRoot "documents_bin\封面模板文件.docx"))
        cover_1818_template = (Resolve-FullPathOrRaw (Join-Path $ActualRepoRoot "documents_bin\1818图册封面模板.docx"))
        common_catalog_template = (Resolve-FullPathOrRaw (Join-Path $ActualRepoRoot "documents_bin\目录模板文件.xlsx"))
        catalog_1818_template = (Resolve-FullPathOrRaw (Join-Path $ActualRepoRoot "documents_bin\1818图册目录模板.xlsx"))
    }

    $exists = [ordered]@{}
    foreach ($key in $paths.Keys) {
        if ($key -eq "repo_root") {
            continue
        }
        $pathValue = [string]$paths[$key]
        $isContainer = $key -eq "cad_scripts_dir"
        $exists[$key + "_exists"] = if ($isContainer) {
            Test-Path -LiteralPath $pathValue -PathType Container
        } else {
            Test-Path -LiteralPath $pathValue -PathType Leaf
        }
    }

    $unicodeStatus = if ($exists["business_spec_exists"] -and $exists["runtime_spec_exists"]) {
        "pass"
    } else {
        "fail"
    }

    $requiredPass = $exists["business_spec_exists"] -and
        $exists["runtime_spec_exists"] -and
        $exists["cad_scripts_dir_exists"] -and
        $exists["oda_exe_exists"]

    return [ordered]@{
        status = if ($requiredPass) { "pass" } else { "fail" }
        paths = $paths
        exists = $exists
        unicode_paths = New-CheckResult -Status $unicodeStatus -Details ([ordered]@{
            checked = @(
                "documents\参数规范.yaml",
                "documents\参数规范_运行期.yaml"
            )
        }) -Error $(if ($unicodeStatus -eq "fail") { "unicode path resolution failed" } else { "" })
    }
}

function Test-PythonCandidate {
    param(
        [string]$Label,
        [string]$Command,
        [string[]]$BaseArguments,
        [bool]$Exists,
        [string]$PathHint
    )

    if (-not $Exists) {
        return [ordered]@{
            label = $Label
            exists = $false
            command = $Command
            path_hint = $PathHint
            status = "skip"
            version = ""
            executable = ""
            meets_requirement = $false
            error = "candidate not found"
        }
    }

    $probeCode = "import json,sys; print(json.dumps({'executable': sys.executable, 'version': [sys.version_info[0], sys.version_info[1], sys.version_info[2]]}))"
    $invoke = Invoke-ExternalCommand -FilePath $Command -Arguments ($BaseArguments + @("-c", $probeCode))
    if (-not $invoke.success) {
        return [ordered]@{
            label = $Label
            exists = $true
            command = $Command
            path_hint = $PathHint
            status = "fail"
            version = ""
            executable = ""
            meets_requirement = $false
            error = if ($invoke.Contains("error")) { [string]$invoke.error } else { [string]$invoke.stdout }
        }
    }

    try {
        $json = $invoke.stdout | ConvertFrom-Json -ErrorAction Stop
        $versionText = "{0}.{1}.{2}" -f $json.version[0], $json.version[1], $json.version[2]
        $meetsRequirement = ($json.version[0] -gt 3) -or ($json.version[0] -eq 3 -and $json.version[1] -ge 13)

        return [ordered]@{
            label = $Label
            exists = $true
            command = $Command
            path_hint = $PathHint
            status = if ($meetsRequirement) { "pass" } else { "fail" }
            version = $versionText
            executable = [string]$json.executable
            meets_requirement = $meetsRequirement
            error = ""
        }
    } catch {
        return [ordered]@{
            label = $Label
            exists = $true
            command = $Command
            path_hint = $PathHint
            status = "fail"
            version = ""
            executable = ""
            meets_requirement = $false
            error = "failed to parse python introspection output"
        }
    }
}

function Test-PythonImport {
    param(
        [string]$PythonExe,
        [string]$ModuleName
    )

    if ([string]::IsNullOrWhiteSpace($PythonExe)) {
        return New-CheckResult -Status "skip" -Error "python executable is unavailable"
    }

    $code = "import importlib, sys; importlib.import_module(sys.argv[1]); print('ok')"
    $invoke = Invoke-ExternalCommand -FilePath $PythonExe -Arguments @("-c", $code, $ModuleName)
    if ($invoke.success) {
        return New-CheckResult -Status "pass"
    }

    return New-CheckResult -Status "fail" -Error $(if ($invoke.Contains("error")) { [string]$invoke.error } else { [string]$invoke.stdout })
}

function Get-PythonFacts {
    param([string]$ActualRepoRoot)

    $venvPython = Join-Path $ActualRepoRoot "backend\.venv\Scripts\python.exe"
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue

    $candidates = @(
        (Test-PythonCandidate -Label "backend_venv" -Command $venvPython -BaseArguments @() -Exists (Test-Path -LiteralPath $venvPython -PathType Leaf) -PathHint $venvPython),
        (Test-PythonCandidate -Label "python" -Command "python" -BaseArguments @() -Exists ($null -ne $pythonCommand) -PathHint $(if ($null -ne $pythonCommand) { [string]$pythonCommand.Source } else { "" })),
        (Test-PythonCandidate -Label "py_3_13" -Command "py" -BaseArguments @("-3.13") -Exists ($null -ne $pyLauncher) -PathHint $(if ($null -ne $pyLauncher) { [string]$pyLauncher.Source } else { "" }))
    )

    $selected = @($candidates | Where-Object { $_.meets_requirement }) | Select-Object -First 1
    $selectedExe = if ($null -ne $selected) { [string]$selected.executable } else { "" }

    $imports = [ordered]@{
        fastapi = (Test-PythonImport -PythonExe $selectedExe -ModuleName "fastapi")
        uvicorn = (Test-PythonImport -PythonExe $selectedExe -ModuleName "uvicorn")
        pydantic = (Test-PythonImport -PythonExe $selectedExe -ModuleName "pydantic")
        sqlite3 = (Test-PythonImport -PythonExe $selectedExe -ModuleName "sqlite3")
        python_multipart = (Test-PythonImport -PythonExe $selectedExe -ModuleName "multipart")
        win32com_client = (Test-PythonImport -PythonExe $selectedExe -ModuleName "win32com.client")
        openpyxl = (Test-PythonImport -PythonExe $selectedExe -ModuleName "openpyxl")
        python_docx = (Test-PythonImport -PythonExe $selectedExe -ModuleName "docx")
    }

    $allImportsPass = ($null -ne $selected)
    foreach ($check in $imports.Values) {
        if ($check.status -ne "pass") {
            $allImportsPass = $false
            break
        }
    }

    return [ordered]@{
        status = if (($null -ne $selected) -and $allImportsPass) { "pass" } else { "fail" }
        candidates = $candidates
        selected = [ordered]@{
            status = if ($null -ne $selected) { "pass" } else { "fail" }
            executable = $selectedExe
            version = if ($null -ne $selected) { [string]$selected.version } else { "" }
            label = if ($null -ne $selected) { [string]$selected.label } else { "" }
        }
        venv = [ordered]@{
            status = if ((Test-Path -LiteralPath $venvPython -PathType Leaf)) { "pass" } else { "skip" }
            path = (Resolve-FullPathOrRaw $venvPython)
        }
        import_checks = $imports
    }
}

function Test-SqliteProbe {
    param([string]$PythonExe)

    if ([string]::IsNullOrWhiteSpace($PythonExe)) {
        return New-CheckResult -Status "skip" -Error "python executable is unavailable"
    }

    $tempDir = New-TempDirectory -Prefix "fanban_sqlite_probe"
    $dbPath = Join-Path $tempDir "probe.db"
    $scriptPath = Join-Path $tempDir "probe_sqlite.py"
    $code = @'
import os
import sqlite3
import sys

db_path = sys.argv[1]
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("create table probe(value text)")
cur.execute("insert into probe(value) values (?)", ("ok",))
conn.commit()
row = cur.execute("select value from probe").fetchone()[0]
conn.close()
os.remove(db_path)
print(row)
'@

    try {
        $code | Out-File -LiteralPath $scriptPath -Encoding utf8
        $invoke = Invoke-ExternalCommand -FilePath $PythonExe -Arguments @($scriptPath, $dbPath)
        if ($invoke.success -and ($invoke.stdout -match "ok")) {
            return New-CheckResult -Status "pass" -Details ([ordered]@{
                probe_root = (Resolve-FullPathOrRaw $tempDir)
                db_deleted = (-not (Test-Path -LiteralPath $dbPath))
            })
        }

        return New-CheckResult -Status "fail" -Details ([ordered]@{
            probe_root = (Resolve-FullPathOrRaw $tempDir)
            db_deleted = (-not (Test-Path -LiteralPath $dbPath))
        }) -Error $(if ($invoke.Contains("error")) { [string]$invoke.error } else { [string]$invoke.stdout })
    } finally {
        Remove-ProbePath -PathText $tempDir
    }
}

function Get-StorageFacts {
    param([string]$ActualStorageRoot)

    $storageCheck = Test-WriteProbe -DirPath $ActualStorageRoot
    $jobsDir = Join-Path $ActualStorageRoot "jobs"
    $jobsCheck = Test-WriteProbe -DirPath $jobsDir

    $freeGb = 0.0
    $diskStatus = "pass"
    $diskError = ""
    try {
        $targetPath = Resolve-FullPathOrRaw $ActualStorageRoot
        if ([string]::IsNullOrWhiteSpace($targetPath)) {
            $targetPath = $ActualStorageRoot
        }
        $rootPath = [System.IO.Path]::GetPathRoot($targetPath)
        $drive = New-Object System.IO.DriveInfo($rootPath)
        $freeGb = [Math]::Round(($drive.AvailableFreeSpace / 1GB), 2)
        if ($freeGb -lt 20.0) {
            $diskStatus = "fail"
        }
    } catch {
        $diskStatus = "fail"
        $diskError = $_.Exception.Message
    }

    return [ordered]@{
        status = if (
            $storageCheck.status -eq "pass" -and
            $jobsCheck.status -eq "pass" -and
            $diskStatus -ne "fail"
        ) { "pass" } else { "fail" }
        storage_root = [ordered]@{
            path = (Resolve-FullPathOrRaw $ActualStorageRoot)
            check = $storageCheck
        }
        jobs_dir = [ordered]@{
            path = (Resolve-FullPathOrRaw $jobsDir)
            check = $jobsCheck
        }
        disk = New-CheckResult -Status $diskStatus -Details ([ordered]@{
            free_gb = $freeGb
            threshold = "pass >= 50, warn 20-50, fail < 20"
        }) -Error $diskError
    }
}

function Get-NetworkFacts {
    param([int]$TargetPort)

    $portCheck = Test-PortAvailability -TargetPort $TargetPort
    $addresses = @(Get-IPv4Addresses)
    $firewall = Get-FirewallFacts

    return [ordered]@{
        status = if ($portCheck.status -eq "pass") { "pass" } else { "fail" }
        port = $portCheck
        ipv4 = New-CheckResult -Status $(if (@($addresses).Count -gt 0) { "pass" } else { "skip" }) -Details ([ordered]@{
            addresses = $addresses
        }) -Error $(if (@($addresses).Count -eq 0) { "no non-loopback IPv4 address detected" } else { "" })
        firewall = $firewall
    }
}

function Remove-ComObjectReference {
    param([object]$ComObject)

    if ($null -eq $ComObject) {
        return
    }

    try {
        if ([System.Runtime.InteropServices.Marshal]::IsComObject($ComObject)) {
            [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($ComObject)
        }
    } catch {
    }
}

function Get-AutoCADFacts {
    $installDirs = Find-AutoCADInstallDirs
    $installFacts = @()
    foreach ($dir in $installDirs) {
        $installFacts += (Get-InstallFacts -InstallDir $dir)
    }

    $plotterDirList = New-Object System.Collections.Generic.List[string]
    foreach ($install in $installFacts) {
        if ($install.install_plotters_dir_exists) {
            Add-UniquePath -List $plotterDirList -Candidate ([string]$install.install_plotters_dir)
        }
    }

    $userPlotterDirs = Get-UserPlotterDirs
    foreach ($plotterDir in $userPlotterDirs) {
        Add-UniquePath -List $plotterDirList -Candidate $plotterDir
    }

    $plotterFacts = @()
    foreach ($plotterDir in $plotterDirList.ToArray()) {
        $plotterFacts += (Get-PlotterFacts -PlotterDir $plotterDir)
    }

    $bestAccore = Select-BestAccoreconsole -InstallFacts $installFacts
    $bestPlotter = Select-BestPlotterDir -PlotterFacts $plotterFacts

    $recommendedPc3 = ""
    $recommendedCtb = ""
    $recommendedCtbPath = ""
    $usedFallbackDwgToPdf = $false

    if ($null -ne $bestPlotter) {
        if ($bestPlotter.has_custom_pdf2_pc3 -and $bestPlotter.custom_pdf2_pc3_names.Count -gt 0) {
            $recommendedPc3 = [string]$bestPlotter.custom_pdf2_pc3_names[0]
        } elseif ($bestPlotter.has_dwg_to_pdf_pc3) {
            $recommendedPc3 = "DWG To PDF.pc3"
            $usedFallbackDwgToPdf = $true
        }

        if ($bestPlotter.has_monochrome_ctb) {
            $recommendedCtb = "monochrome.ctb"
            $recommendedCtbPath = Join-Path ([string]$bestPlotter.plot_styles_dir) $recommendedCtb
        }
    }

    $bestInstallDir = ""
    if (-not [string]::IsNullOrWhiteSpace($bestAccore)) {
        $bestInstallDir = Split-Path -Parent $bestAccore
    }

    $hasFontsDir = (@($installFacts | Where-Object { $_.fonts_dir_exists }).Count -gt 0)
    $status = if (
        -not [string]::IsNullOrWhiteSpace($bestAccore) -and
        -not [string]::IsNullOrWhiteSpace($recommendedPc3) -and
        -not [string]::IsNullOrWhiteSpace($recommendedCtb)
    ) { "pass" } else { "fail" }

    return [ordered]@{
        status = $status
        install_dirs = $installFacts
        plotter_dirs = $plotterFacts
        user_plotter_dirs = $userPlotterDirs
        candidate_counts = [ordered]@{
            install_dirs = $installFacts.Count
            plotter_dirs = $plotterFacts.Count
        }
        best_guess = [ordered]@{
            install_dir = $bestInstallDir
            accoreconsole_exe = $bestAccore
            plotters_dir = if ($null -ne $bestPlotter) { [string]$bestPlotter.plotters_dir } else { "" }
            plot_styles_dir = if ($null -ne $bestPlotter) { [string]$bestPlotter.plot_styles_dir } else { "" }
            pc3_name = $recommendedPc3
            ctb_name = $recommendedCtb
            ctb_path = $recommendedCtbPath
            used_fallback_dwg_to_pdf = $usedFallbackDwgToPdf
            has_fonts_dir = $hasFontsDir
        }
    }
}

function Test-WordCom {
    $app = $null
    try {
        $app = New-Object -ComObject Word.Application
        $app.Visible = $false
        $app.DisplayAlerts = 0
        return New-CheckResult -Status "pass" -Details ([ordered]@{
            prog_id = "Word.Application"
            version = [string]$app.Version
        })
    } catch {
        return New-CheckResult -Status "fail" -Details ([ordered]@{
            prog_id = "Word.Application"
        }) -Error $_.Exception.Message
    } finally {
        if ($null -ne $app) {
            try { $app.Quit() } catch {}
            Remove-ComObjectReference -ComObject $app
            [GC]::Collect()
            [GC]::WaitForPendingFinalizers()
        }
    }
}

function Test-ExcelCom {
    $app = $null
    try {
        $app = New-Object -ComObject Excel.Application
        $app.Visible = $false
        $app.DisplayAlerts = $false
        return New-CheckResult -Status "pass" -Details ([ordered]@{
            prog_id = "Excel.Application"
            version = [string]$app.Version
        })
    } catch {
        return New-CheckResult -Status "fail" -Details ([ordered]@{
            prog_id = "Excel.Application"
        }) -Error $_.Exception.Message
    } finally {
        if ($null -ne $app) {
            try { $app.Quit() } catch {}
            Remove-ComObjectReference -ComObject $app
            [GC]::Collect()
            [GC]::WaitForPendingFinalizers()
        }
    }
}

function Test-WordExportSmoke {
    $tempDir = New-TempDirectory -Prefix "fanban_word_export"
    $pdfPath = Join-Path $tempDir "probe.pdf"
    $app = $null
    $doc = $null

    try {
        $app = New-Object -ComObject Word.Application
        $app.Visible = $false
        $app.DisplayAlerts = 0
        $doc = $app.Documents.Add()
        $doc.Content.Text = "fanban office probe"
        $doc.ExportAsFixedFormat($pdfPath, 17)

        $pdfExists = Test-Path -LiteralPath $pdfPath -PathType Leaf
        return New-CheckResult -Status $(if ($pdfExists) { "pass" } else { "fail" }) -Details ([ordered]@{
            pdf_path = $pdfPath
            pdf_exists = $pdfExists
        }) -Error $(if ($pdfExists) { "" } else { "word export did not produce a pdf" })
    } catch {
        return New-CheckResult -Status "fail" -Details ([ordered]@{
            pdf_path = $pdfPath
            pdf_exists = (Test-Path -LiteralPath $pdfPath -PathType Leaf)
        }) -Error $_.Exception.Message
    } finally {
        if ($null -ne $doc) {
            try { $doc.Close($false) } catch {}
            Remove-ComObjectReference -ComObject $doc
        }
        if ($null -ne $app) {
            try { $app.Quit() } catch {}
            Remove-ComObjectReference -ComObject $app
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
        Remove-ProbePath -PathText $tempDir
    }
}

function Test-ExcelExportSmoke {
    $tempDir = New-TempDirectory -Prefix "fanban_excel_export"
    $pdfPath = Join-Path $tempDir "probe.pdf"
    $app = $null
    $workbook = $null
    $worksheet = $null

    try {
        $app = New-Object -ComObject Excel.Application
        $app.Visible = $false
        $app.DisplayAlerts = $false
        $workbook = $app.Workbooks.Add()
        $worksheet = $workbook.Worksheets.Item(1)
        $worksheet.Cells.Item(1, 1).Value2 = "fanban office probe"
        $workbook.ExportAsFixedFormat(0, $pdfPath)

        $pdfExists = Test-Path -LiteralPath $pdfPath -PathType Leaf
        return New-CheckResult -Status $(if ($pdfExists) { "pass" } else { "fail" }) -Details ([ordered]@{
            pdf_path = $pdfPath
            pdf_exists = $pdfExists
        }) -Error $(if ($pdfExists) { "" } else { "excel export did not produce a pdf" })
    } catch {
        return New-CheckResult -Status "fail" -Details ([ordered]@{
            pdf_path = $pdfPath
            pdf_exists = (Test-Path -LiteralPath $pdfPath -PathType Leaf)
        }) -Error $_.Exception.Message
    } finally {
        if ($null -ne $worksheet) {
            Remove-ComObjectReference -ComObject $worksheet
        }
        if ($null -ne $workbook) {
            try { $workbook.Close($false) } catch {}
            Remove-ComObjectReference -ComObject $workbook
        }
        if ($null -ne $app) {
            try { $app.Quit() } catch {}
            Remove-ComObjectReference -ComObject $app
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
        Remove-ProbePath -PathText $tempDir
    }
}

function Test-WordTemplateCopy {
    param(
        [string]$TemplatePath,
        [string]$TemplateLabel
    )

    if ([string]::IsNullOrWhiteSpace($TemplatePath) -or -not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) {
        return New-CheckResult -Status "fail" -Details ([ordered]@{
            template = $TemplateLabel
            template_path = (Resolve-FullPathOrRaw $TemplatePath)
        }) -Error "template file is missing"
    }

    $tempDir = New-TempDirectory -Prefix "fanban_word_template"
    $workingCopy = Join-Path $tempDir ([System.IO.Path]::GetFileName($TemplatePath))
    $savedCopy = Join-Path $tempDir ("saved_" + [System.IO.Path]::GetFileName($TemplatePath))
    $app = $null
    $doc = $null

    try {
        Copy-Item -LiteralPath $TemplatePath -Destination $workingCopy -Force
        $app = New-Object -ComObject Word.Application
        $app.Visible = $false
        $app.DisplayAlerts = 0
        $doc = $app.Documents.Open($workingCopy, $false, $false)
        try {
            $doc.SaveAs2($savedCopy)
        } catch {
            $doc.SaveAs([ref]$savedCopy)
        }

        $saved = Test-Path -LiteralPath $savedCopy -PathType Leaf
        return New-CheckResult -Status $(if ($saved) { "pass" } else { "fail" }) -Details ([ordered]@{
            template = $TemplateLabel
            template_path = (Resolve-FullPathOrRaw $TemplatePath)
            saved_copy = $savedCopy
            saved = $saved
        }) -Error $(if ($saved) { "" } else { "word template could not be saved" })
    } catch {
        return New-CheckResult -Status "fail" -Details ([ordered]@{
            template = $TemplateLabel
            template_path = (Resolve-FullPathOrRaw $TemplatePath)
            saved_copy = $savedCopy
            saved = (Test-Path -LiteralPath $savedCopy -PathType Leaf)
        }) -Error $_.Exception.Message
    } finally {
        if ($null -ne $doc) {
            try { $doc.Close($false) } catch {}
            Remove-ComObjectReference -ComObject $doc
        }
        if ($null -ne $app) {
            try { $app.Quit() } catch {}
            Remove-ComObjectReference -ComObject $app
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
        Remove-ProbePath -PathText $tempDir
    }
}

function Test-ExcelTemplateCopy {
    param(
        [string]$TemplatePath,
        [string]$TemplateLabel
    )

    if ([string]::IsNullOrWhiteSpace($TemplatePath) -or -not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) {
        return New-CheckResult -Status "fail" -Details ([ordered]@{
            template = $TemplateLabel
            template_path = (Resolve-FullPathOrRaw $TemplatePath)
        }) -Error "template file is missing"
    }

    $tempDir = New-TempDirectory -Prefix "fanban_excel_template"
    $workingCopy = Join-Path $tempDir ([System.IO.Path]::GetFileName($TemplatePath))
    $savedCopy = Join-Path $tempDir ("saved_" + [System.IO.Path]::GetFileName($TemplatePath))
    $app = $null
    $workbook = $null

    try {
        Copy-Item -LiteralPath $TemplatePath -Destination $workingCopy -Force
        $app = New-Object -ComObject Excel.Application
        $app.Visible = $false
        $app.DisplayAlerts = $false
        $workbook = $app.Workbooks.Open($workingCopy)
        $workbook.SaveCopyAs($savedCopy)

        $saved = Test-Path -LiteralPath $savedCopy -PathType Leaf
        return New-CheckResult -Status $(if ($saved) { "pass" } else { "fail" }) -Details ([ordered]@{
            template = $TemplateLabel
            template_path = (Resolve-FullPathOrRaw $TemplatePath)
            saved_copy = $savedCopy
            saved = $saved
        }) -Error $(if ($saved) { "" } else { "excel template could not be saved" })
    } catch {
        return New-CheckResult -Status "fail" -Details ([ordered]@{
            template = $TemplateLabel
            template_path = (Resolve-FullPathOrRaw $TemplatePath)
            saved_copy = $savedCopy
            saved = (Test-Path -LiteralPath $savedCopy -PathType Leaf)
        }) -Error $_.Exception.Message
    } finally {
        if ($null -ne $workbook) {
            try { $workbook.Close($false) } catch {}
            Remove-ComObjectReference -ComObject $workbook
        }
        if ($null -ne $app) {
            try { $app.Quit() } catch {}
            Remove-ComObjectReference -ComObject $app
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
        Remove-ProbePath -PathText $tempDir
    }
}

function Get-OfficeFacts {
    param([hashtable]$RepoFacts)

    $wordCom = Test-WordCom
    $excelCom = Test-ExcelCom
    $wordExport = if ($wordCom.status -eq "pass") {
        Test-WordExportSmoke
    } else {
        New-CheckResult -Status "skip" -Error "word com is unavailable"
    }
    $excelExport = if ($excelCom.status -eq "pass") {
        Test-ExcelExportSmoke
    } else {
        New-CheckResult -Status "skip" -Error "excel com is unavailable"
    }

    $templateChecks = [ordered]@{
        common_cover = if ($wordCom.status -eq "pass") {
            Test-WordTemplateCopy -TemplatePath ([string]$RepoFacts.paths.common_cover_template) -TemplateLabel "common_cover"
        } else {
            New-CheckResult -Status "skip" -Error "word com is unavailable"
        }
        cover_1818 = if ($wordCom.status -eq "pass") {
            Test-WordTemplateCopy -TemplatePath ([string]$RepoFacts.paths.cover_1818_template) -TemplateLabel "cover_1818"
        } else {
            New-CheckResult -Status "skip" -Error "word com is unavailable"
        }
        common_catalog = if ($excelCom.status -eq "pass") {
            Test-ExcelTemplateCopy -TemplatePath ([string]$RepoFacts.paths.common_catalog_template) -TemplateLabel "common_catalog"
        } else {
            New-CheckResult -Status "skip" -Error "excel com is unavailable"
        }
        catalog_1818 = if ($excelCom.status -eq "pass") {
            Test-ExcelTemplateCopy -TemplatePath ([string]$RepoFacts.paths.catalog_1818_template) -TemplateLabel "catalog_1818"
        } else {
            New-CheckResult -Status "skip" -Error "excel com is unavailable"
        }
    }

    $templatesPass = $true
    foreach ($check in $templateChecks.Values) {
        if ($check.status -ne "pass") {
            $templatesPass = $false
            break
        }
    }

    return [ordered]@{
        status = if (
            $wordCom.status -eq "pass" -and
            $excelCom.status -eq "pass" -and
            $wordExport.status -eq "pass" -and
            $excelExport.status -eq "pass" -and
            $templatesPass
        ) { "pass" } else { "fail" }
        word_com = $wordCom
        excel_com = $excelCom
        word_export_smoke = $wordExport
        excel_export_smoke = $excelExport
        template_checks = $templateChecks
    }
}

function Get-HostFacts {
    $os = $null
    $computer = $null
    $processors = @()
    try { $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop } catch {}
    try { $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop } catch {}
    try { $processors = @(Get-CimInstance Win32_Processor -ErrorAction Stop) } catch {}

    $logicalCores = 0
    if ($processors.Count -gt 0) {
        $sum = ($processors | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
        if ($null -ne $sum) {
            $logicalCores = [int]$sum
        }
    }
    if ($logicalCores -le 0 -and -not [string]::IsNullOrWhiteSpace($env:NUMBER_OF_PROCESSORS)) {
        $logicalCores = [int]$env:NUMBER_OF_PROCESSORS
    }

    $memoryGb = 0.0
    if ($null -ne $computer -and $computer.TotalPhysicalMemory) {
        $memoryGb = [Math]::Round(($computer.TotalPhysicalMemory / 1GB), 2)
    }

    return [ordered]@{
        status = "pass"
        computer_name = $env:COMPUTERNAME
        user = $env:USERNAME
        os_caption = if ($null -ne $os) { [string]$os.Caption } else { "" }
        os_version = if ($null -ne $os) { [string]$os.Version } else { "" }
        architecture = if ($null -ne $os) { [string]$os.OSArchitecture } else { "" }
        powershell_version = $PSVersionTable.PSVersion.ToString()
        cpu_logical_cores = $logicalCores
        physical_memory_gb = $memoryGb
        culture = (Get-Culture).Name
    }
}

function Get-ServiceHostingFacts {
    $isAdmin = $false
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
    }

    $scCommand = Get-Command sc.exe -ErrorAction SilentlyContinue
    $nssmCommand = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($null -eq $nssmCommand) {
        $nssmCommand = Get-Command nssm -ErrorAction SilentlyContinue
    }

    return [ordered]@{
        status = "pass"
        recommended_mode = "windows_service"
        admin_context = New-CheckResult -Status $(if ($isAdmin) { "pass" } else { "skip" }) -Details ([ordered]@{
            is_admin = $isAdmin
        }) -Error $(if ($isAdmin) { "" } else { "current session is not elevated" })
        sc_exe = New-CheckResult -Status $(if ($null -ne $scCommand) { "pass" } else { "fail" }) -Details ([ordered]@{
            path = if ($null -ne $scCommand) { [string]$scCommand.Source } else { "" }
        }) -Error $(if ($null -ne $scCommand) { "" } else { "sc.exe is unavailable" })
        nssm = New-CheckResult -Status $(if ($null -ne $nssmCommand) { "pass" } else { "skip" }) -Details ([ordered]@{
            path = if ($null -ne $nssmCommand) { [string]$nssmCommand.Source } else { "" }
        }) -Error $(if ($null -ne $nssmCommand) { "" } else { "nssm is not installed" })
    }
}

$actualRepoRoot = Resolve-RepoRoot -RepoRootArg $RepoRoot
if ([string]::IsNullOrWhiteSpace($StorageRoot)) {
    $StorageRoot = Join-Path $actualRepoRoot "storage"
}
$actualStorageRoot = Resolve-FullPathOrRaw $StorageRoot
if ([string]::IsNullOrWhiteSpace($actualStorageRoot)) {
    $actualStorageRoot = $StorageRoot
}

if ([string]::IsNullOrWhiteSpace($OutJson)) {
    $defaultDir = Join-Path $actualRepoRoot "tmp"
    $OutJson = Join-Path $defaultDir ("fanban_env_probe_" + $env:COMPUTERNAME + "_" + (Get-Timestamp) + ".json")
}
$actualOutJson = Resolve-FullPathOrRaw $OutJson
if ([string]::IsNullOrWhiteSpace($actualOutJson)) {
    $actualOutJson = $OutJson
}

$hostFacts = Get-HostFacts
$repoFacts = Get-RepoFacts -ActualRepoRoot $actualRepoRoot
$pythonFacts = Get-PythonFacts -ActualRepoRoot $actualRepoRoot
$sqliteFacts = Test-SqliteProbe -PythonExe ([string]$pythonFacts.selected.executable)
$storageFacts = Get-StorageFacts -ActualStorageRoot $actualStorageRoot
$networkFacts = Get-NetworkFacts -TargetPort $Port
$autocadFacts = Get-AutoCADFacts
$officeFacts = Get-OfficeFacts -RepoFacts $repoFacts
$serviceHostingFacts = Get-ServiceHostingFacts

$blockingIssues = @()
$warnings = @()

foreach ($entry in $repoFacts.exists.GetEnumerator()) {
    if (-not [bool]$entry.Value) {
        $blockingIssues += [ordered]@{
            section = "repo"
            code = [string]$entry.Key
            message = "required repository path is missing"
        }
    }
}

if ($repoFacts.unicode_paths.status -ne "pass") {
    $blockingIssues += [ordered]@{
        section = "repo"
        code = "unicode_paths"
        message = "unicode repository paths could not be resolved"
    }
}

if ($pythonFacts.selected.status -ne "pass") {
    $blockingIssues += [ordered]@{
        section = "python"
        code = "python_version"
        message = "python 3.13+ is unavailable"
    }
}
foreach ($importEntry in $pythonFacts.import_checks.GetEnumerator()) {
    if ($importEntry.Value.status -ne "pass") {
        $blockingIssues += [ordered]@{
            section = "python"
            code = [string]$importEntry.Key
            message = "required python module import failed"
        }
    }
}

if ($sqliteFacts.status -ne "pass") {
    $blockingIssues += [ordered]@{
        section = "sqlite"
        code = "sqlite_probe"
        message = if ([string]::IsNullOrWhiteSpace($sqliteFacts.error)) { "sqlite probe failed" } else { [string]$sqliteFacts.error }
    }
}

if ($storageFacts.storage_root.check.status -ne "pass") {
    $blockingIssues += [ordered]@{
        section = "storage"
        code = "storage_root_write"
        message = "storage root is not writable"
    }
}
if ($storageFacts.jobs_dir.check.status -ne "pass") {
    $blockingIssues += [ordered]@{
        section = "storage"
        code = "jobs_dir_write"
        message = "storage jobs directory is not writable"
    }
}
if ($storageFacts.disk.status -ne "pass") {
    $blockingIssues += [ordered]@{
        section = "storage"
        code = "disk_free_space"
        message = if ([string]::IsNullOrWhiteSpace($storageFacts.disk.error)) { "insufficient free disk space" } else { [string]$storageFacts.disk.error }
    }
} elseif ([double]$storageFacts.disk.details.free_gb -lt 50.0) {
    $warnings += [ordered]@{
        section = "storage"
        code = "disk_free_space_low"
        message = "free disk space is below the preferred 50 GB threshold"
    }
}

if ($networkFacts.port.status -ne "pass") {
    $blockingIssues += [ordered]@{
        section = "network"
        code = "port_unavailable"
        message = "requested port is unavailable"
    }
}
if ($networkFacts.ipv4.status -ne "pass") {
    $warnings += [ordered]@{
        section = "network"
        code = "ipv4"
        message = if ([string]::IsNullOrWhiteSpace($networkFacts.ipv4.error)) { "no LAN IPv4 address detected" } else { [string]$networkFacts.ipv4.error }
    }
}
if ($networkFacts.firewall.status -eq "fail" -or $networkFacts.firewall.status -eq "skip") {
    $warnings += [ordered]@{
        section = "network"
        code = "firewall_visibility"
        message = if ([string]::IsNullOrWhiteSpace($networkFacts.firewall.error)) { "firewall profile state could not be verified" } else { [string]$networkFacts.firewall.error }
    }
}

if ([string]::IsNullOrWhiteSpace([string]$autocadFacts.best_guess.accoreconsole_exe)) {
    $blockingIssues += [ordered]@{
        section = "autocad"
        code = "accoreconsole"
        message = "accoreconsole.exe was not detected"
    }
}
if ([string]::IsNullOrWhiteSpace([string]$autocadFacts.best_guess.pc3_name) -or [string]::IsNullOrWhiteSpace([string]$autocadFacts.best_guess.ctb_name)) {
    $blockingIssues += [ordered]@{
        section = "autocad"
        code = "plot_assets"
        message = "no usable PC3 and monochrome CTB combination was detected"
    }
}
if ([bool]$autocadFacts.best_guess.used_fallback_dwg_to_pdf) {
    $warnings += [ordered]@{
        section = "autocad"
        code = "plotter_fallback"
        message = "using DWG To PDF.pc3 fallback instead of the preferred custom PDF2 PC3"
    }
}
if (-not [bool]$autocadFacts.best_guess.has_fonts_dir) {
    $warnings += [ordered]@{
        section = "autocad"
        code = "fonts_dir"
        message = "no AutoCAD Fonts directory was detected from install candidates"
    }
}

foreach ($officeKey in @("word_com", "excel_com", "word_export_smoke", "excel_export_smoke")) {
    $check = $officeFacts[$officeKey]
    if ($check.status -ne "pass") {
        $blockingIssues += [ordered]@{
            section = "office"
            code = $officeKey
            message = if ([string]::IsNullOrWhiteSpace($check.error)) { "$officeKey failed" } else { [string]$check.error }
        }
    }
}
foreach ($templateEntry in $officeFacts.template_checks.GetEnumerator()) {
    if ($templateEntry.Value.status -ne "pass") {
        $blockingIssues += [ordered]@{
            section = "office"
            code = [string]$templateEntry.Key
            message = if ([string]::IsNullOrWhiteSpace($templateEntry.Value.error)) { "office template probe failed" } else { [string]$templateEntry.Value.error }
        }
    }
}

if ($serviceHostingFacts.admin_context.status -ne "pass") {
    $warnings += [ordered]@{
        section = "web_service"
        code = "admin_context"
        message = "current shell is not elevated; Windows service installation may require elevation"
    }
}
if ($serviceHostingFacts.sc_exe.status -ne "pass") {
    $warnings += [ordered]@{
        section = "web_service"
        code = "sc_exe"
        message = "sc.exe is unavailable in the current environment"
    }
}
if ($serviceHostingFacts.nssm.status -eq "skip") {
    $warnings += [ordered]@{
        section = "web_service"
        code = "nssm"
        message = "nssm is not installed; use built-in Windows service tooling or install nssm later"
    }
}

$readyForWebService = (
    $repoFacts.status -eq "pass" -and
    $pythonFacts.status -eq "pass" -and
    $sqliteFacts.status -eq "pass" -and
    $storageFacts.status -eq "pass" -and
    $autocadFacts.status -eq "pass" -and
    $officeFacts.status -eq "pass" -and
    $networkFacts.port.status -eq "pass"
)

$officeWarningCount = @($warnings | Where-Object { $_.section -eq "office" }).Count
$autocadWarningCount = @($warnings | Where-Object { $_.section -eq "autocad" }).Count
$recommendedMaxActiveJobs = 1
if (
    $readyForWebService -and
    [int]$hostFacts.cpu_logical_cores -ge 8 -and
    [double]$hostFacts.physical_memory_gb -ge 16.0 -and
    [double]$storageFacts.disk.details.free_gb -ge 100.0 -and
    $officeWarningCount -eq 0 -and
    $autocadWarningCount -eq 0
) {
    $recommendedMaxActiveJobs = 2
}

$recommendedRuntime = [ordered]@{
    recommended_max_active_jobs = $recommendedMaxActiveJobs
    recommended_doc_workers = 1
    recommended_port = $Port
    recommended_storage_root = $actualStorageRoot
    recommended_cleanup_hot_days = 7
    recommended_archive_keep = "package_zip_only"
    recommended_env = [ordered]@{
        FANBAN_SPEC_PATH = [string]$repoFacts.paths.business_spec
        FANBAN_RUNTIME_SPEC_PATH = [string]$repoFacts.paths.runtime_spec
        FANBAN_STORAGE_DIR = $actualStorageRoot
        FANBAN_ODA__EXE_PATH = [string]$repoFacts.paths.oda_exe
        FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR = [string]$repoFacts.paths.cad_scripts_dir
        FANBAN_MODULE5_EXPORT__DOTNET_BRIDGE__DLL_PATH = [string]$repoFacts.paths.dotnet_bridge_dll
        FANBAN_MODULE5_EXPORT__CAD_RUNNER__ACCORECONSOLE_EXE = [string]$autocadFacts.best_guess.accoreconsole_exe
        FANBAN_MODULE5_EXPORT__PLOT__PC3_NAME = [string]$autocadFacts.best_guess.pc3_name
        FANBAN_MODULE5_EXPORT__PLOT__CTB_NAME = [string]$autocadFacts.best_guess.ctb_name
        FANBAN_AUTOCAD__INSTALL_DIR = [string]$autocadFacts.best_guess.install_dir
        FANBAN_AUTOCAD__CTB_PATH = [string]$autocadFacts.best_guess.ctb_path
        FANBAN_AUTOCAD__PC3_NAME = [string]$autocadFacts.best_guess.pc3_name
        FANBAN_CONCURRENCY__MAX_JOBS = [string]$recommendedMaxActiveJobs
        FANBAN_LIFECYCLE__RETENTION_HOURS = "168"
        FANBAN_UPLOAD_LIMITS__MIN_FREE_DISK_MB = "20480"
    }
}

$recommendedUrls = @()
foreach ($address in @($networkFacts.ipv4.details.addresses)) {
    $recommendedUrls += ("http://{0}:{1}" -f $address, $Port)
}

$webServiceFacts = [ordered]@{
    status = if ($readyForWebService) { "pass" } else { "fail" }
    ready_for_web_service = $readyForWebService
    recommended_listen_host = "0.0.0.0"
    recommended_urls = $recommendedUrls
    service_hosting = $serviceHostingFacts
}

$result = [ordered]@{
    schema_version = "fanban-env-probe@2"
    probe_meta = [ordered]@{
        generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        script = (Resolve-FullPathOrRaw $script:ProbeScriptPath)
        output_json = $actualOutJson
        schema_version = "fanban-env-probe@2"
        input = [ordered]@{
            repo_root = $actualRepoRoot
            storage_root = $actualStorageRoot
            out_json = $actualOutJson
            port = $Port
        }
    }
    host = $hostFacts
    repo = $repoFacts
    python = $pythonFacts
    sqlite = $sqliteFacts
    storage = $storageFacts
    network = $networkFacts
    autocad = $autocadFacts
    office = $officeFacts
    web_service = $webServiceFacts
    recommended_runtime = $recommendedRuntime
    blocking_issues = $blockingIssues
    warnings = $warnings
    manual_checklist = @(
        "Confirm AutoCAD 2022 can start and the license is valid for unattended runs.",
        "Confirm Word and Excel have completed first-run activation under the service account.",
        "Open the chosen LAN port in Windows Firewall for inbound access from client machines."
    )
}

$outDir = Split-Path -Parent $actualOutJson
if (-not [string]::IsNullOrWhiteSpace($outDir) -and -not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$result | ConvertTo-Json -Depth 12 | Out-File -LiteralPath $actualOutJson -Encoding utf8

Write-Host "==== Fanban Environment Probe V2 ===="
Write-Host ("Output JSON: " + $actualOutJson)
Write-Host ("Repo status: " + $repoFacts.status)
Write-Host ("Python status: " + $pythonFacts.status)
Write-Host ("AutoCAD status: " + $autocadFacts.status)
Write-Host ("Office status: " + $officeFacts.status)
Write-Host ("Ready for web service: " + $readyForWebService)
Write-Host ("Blocking issues: " + $blockingIssues.Count)
Write-Host ("Warnings: " + $warnings.Count)
Write-Host "====================================="

