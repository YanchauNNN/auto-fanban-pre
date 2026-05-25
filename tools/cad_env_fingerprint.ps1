[CmdletBinding()]
param(
    [string]$CadExe = "",
    [string]$AccoreConsoleExe = "",
    [string]$SampleDwg = "",
    [Parameter(Mandatory = $true)]
    [string]$OutputJson,
    [string[]]$FontLibraryDir = @(),
    [string]$Pc3Name = "打印PDF2.pc3",
    [string]$PmpName = "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp",
    [string]$CtbName = "fanban_monochrome.ctb",
    [string]$PlottersDir = "",
    [string]$PlotStylesDir = "",
    [string]$RepoRoot = ""
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Resolve-FullPathOrRaw {
    param([string]$PathText)
    if ([string]::IsNullOrWhiteSpace($PathText)) {
        return ""
    }
    try {
        return [System.IO.Path]::GetFullPath($PathText)
    } catch {
        return $PathText
    }
}

function Get-Sha256Hex {
    param([string]$PathText)
    if ([string]::IsNullOrWhiteSpace($PathText) -or -not (Test-Path -LiteralPath $PathText -PathType Leaf)) {
        return ""
    }
    $hash = Get-FileHash -LiteralPath $PathText -Algorithm SHA256
    return [string]$hash.Hash.ToLowerInvariant()
}

function Get-FileFact {
    param([string]$PathText)
    $resolved = Resolve-FullPathOrRaw -PathText $PathText
    $exists = -not [string]::IsNullOrWhiteSpace($resolved) -and (Test-Path -LiteralPath $resolved -PathType Leaf)
    $size = 0
    $lastWriteUtc = ""
    if ($exists) {
        $item = Get-Item -LiteralPath $resolved
        $size = [int64]$item.Length
        $lastWriteUtc = $item.LastWriteTimeUtc.ToString("o")
    }
    return [ordered]@{
        path = $resolved
        exists = [bool]$exists
        size_bytes = $size
        sha256 = Get-Sha256Hex -PathText $resolved
        last_write_utc = $lastWriteUtc
    }
}

function Find-FirstFile {
    param(
        [string[]]$BaseDirs,
        [string[]]$RelativeNames
    )
    foreach ($baseDir in $BaseDirs) {
        if ([string]::IsNullOrWhiteSpace($baseDir)) {
            continue
        }
        foreach ($relativeName in $RelativeNames) {
            $candidate = Join-Path $baseDir $relativeName
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                return (Resolve-FullPathOrRaw -PathText $candidate)
            }
        }
    }
    return ""
}

function Get-FontLibraryInventory {
    param([string[]]$Dirs)
    $normalizedDirs = New-Object System.Collections.Generic.List[string]
    $files = New-Object System.Collections.Generic.List[object]
    $seenFiles = @{}
    foreach ($dir in $Dirs) {
        if ([string]::IsNullOrWhiteSpace($dir)) {
            continue
        }
        $resolved = Resolve-FullPathOrRaw -PathText $dir
        if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
            continue
        }
        if (-not $normalizedDirs.Contains($resolved)) {
            $normalizedDirs.Add($resolved)
        }
        Get-ChildItem -LiteralPath $resolved -File -ErrorAction SilentlyContinue |
            Where-Object { @(".shx", ".ttf", ".ttc", ".otf") -contains $_.Extension.ToLowerInvariant() } |
            Sort-Object Name |
            ForEach-Object {
                $key = $_.FullName.ToLowerInvariant()
                if ($seenFiles.ContainsKey($key)) {
                    return
                }
                $seenFiles[$key] = $true
                $files.Add([ordered]@{
                    name = $_.Name
                    path = $_.FullName
                    extension = $_.Extension.ToLowerInvariant()
                    size_bytes = [int64]$_.Length
                    sha256 = Get-Sha256Hex -PathText $_.FullName
                })
            }
    }
    return [ordered]@{
        dirs = @($normalizedDirs.ToArray())
        files = @($files.ToArray())
    }
}

function Get-LibraryCandidates {
    param(
        [string]$Name,
        [object[]]$FontFiles
    )
    $matches = New-Object System.Collections.Generic.List[object]
    foreach ($file in $FontFiles) {
        if ([string]$file.name -ieq $Name) {
            $matches.Add([ordered]@{
                path = [string]$file.path
                sha256 = [string]$file.sha256
            })
        }
    }
    return @($matches.ToArray())
}

function ConvertTo-LispString {
    param([string]$Value)
    return ($Value.Replace("\", "/").Replace('"', '\"'))
}

function Write-CadProbeScripts {
    param(
        [string]$WorkDir,
        [string]$ProbeOut
    )
    New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
    $probeOutLisp = ConvertTo-LispString -Value $ProbeOut
    $lspPath = Join-Path $WorkDir "cad_env_probe.lsp"
    $scrPath = Join-Path $WorkDir "cad_env_probe.scr"
    $lsp = @"
(vl-load-com)
(setq *fanban-cad-env-probe-out* "$probeOutLisp")

(defun fanban-cad-env-probe-write (line / fh)
  (setq fh (open *fanban-cad-env-probe-out* "a"))
  (if fh (progn (write-line line fh) (close fh)))
  (princ)
)

(defun fanban-cad-env-probe-safe-getvar (name / value)
  (setq value (vl-catch-all-apply 'getvar (list name)))
  (if (vl-catch-all-error-p value)
    (strcat "<error:" (vl-catch-all-error-message value) ">")
    (vl-princ-to-string value)
  )
)

(defun fanban-cad-env-probe-safe-findfile (name / value)
  (setq value (vl-catch-all-apply 'findfile (list name)))
  (if (vl-catch-all-error-p value)
    (strcat "<error:" (vl-catch-all-error-message value) ">")
    (if value value "")
  )
)

(defun fanban-cad-env-probe-style (name / record font bigfont text-size xscale)
  (setq record (tblsearch "STYLE" name))
  (if record
    (progn
      (setq font (cdr (assoc 3 record)))
      (setq bigfont (cdr (assoc 4 record)))
      (setq text-size (cdr (assoc 40 record)))
      (setq xscale (cdr (assoc 41 record)))
      (fanban-cad-env-probe-write
        (strcat
          "style|" name "|"
          (if font font "") "|"
          (if bigfont bigfont "") "|"
          (vl-princ-to-string text-size) "|"
          (vl-princ-to-string xscale) "|"
          (if (and bigfont (> (strlen bigfont) 0)) "true" "false")
        )
      )
    )
    (fanban-cad-env-probe-write (strcat "style|" name "|||||false"))
  )
)

(defun fanban-cad-env-fingerprint-run (/ item)
  (foreach item '("FONTMAP" "FONTALT" "ACADPREFIX" "ROAMABLEROOTPREFIX" "LOCALROOTPREFIX" "TRUSTEDPATHS" "BACKGROUNDPLOT" "PDFSHX" "EPDFSHX")
    (fanban-cad-env-probe-write
      (strcat "getvar|" item "|" (fanban-cad-env-probe-safe-getvar item))
    )
  )
  (foreach item '("tssdeng.shx" "hztxt.shx" "tssdchn.shx" "simplex.shx" "gbcbig.shx" "simsun.ttc" "打印PDF2.pc3")
    (fanban-cad-env-probe-write
      (strcat "findfile|" item "|" (fanban-cad-env-probe-safe-findfile item))
    )
  )
  (foreach item '("TSSD_Label" "TSSD_Norm" "STANDARD")
    (fanban-cad-env-probe-style item)
  )
  (princ)
)
"@
    [System.IO.File]::WriteAllText($lspPath, $lsp, [System.Text.UTF8Encoding]::new($false))
    $scr = @(
        ('(load "{0}")' -f (ConvertTo-LispString -Value $lspPath)),
        "(fanban-cad-env-fingerprint-run)",
        "_.QUIT",
        "_N"
    ) -join "`n"
    [System.IO.File]::WriteAllText($scrPath, $scr + "`n", [System.Text.UTF8Encoding]::new($false))
    return [ordered]@{
        lsp = $lspPath
        scr = $scrPath
    }
}

function Parse-CadProbeFile {
    param([string]$ProbeOut)
    $getvars = [ordered]@{}
    $findfiles = [ordered]@{}
    $styles = New-Object System.Collections.Generic.List[object]
    if (-not (Test-Path -LiteralPath $ProbeOut -PathType Leaf)) {
        return [ordered]@{
            getvars = $getvars
            findfiles = $findfiles
            styles = @()
        }
    }
    foreach ($line in [System.IO.File]::ReadAllLines($ProbeOut, [System.Text.Encoding]::UTF8)) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        $parts = $line -split "\|", 3
        if ($parts.Count -lt 3) {
            continue
        }
        if ($parts[0] -eq "getvar") {
            $getvars[$parts[1]] = $parts[2]
            continue
        }
        if ($parts[0] -eq "findfile") {
            $findfiles[$parts[1]] = $parts[2]
            continue
        }
        if ($parts[0] -eq "style") {
            $styleParts = $line -split "\|", 7
            $styles.Add([ordered]@{
                name = if ($styleParts.Count -gt 1) { $styleParts[1] } else { "" }
                FontFile = if ($styleParts.Count -gt 2) { $styleParts[2] } else { "" }
                BigFontFile = if ($styleParts.Count -gt 3) { $styleParts[3] } else { "" }
                TextSize = if ($styleParts.Count -gt 4) { $styleParts[4] } else { "" }
                XScale = if ($styleParts.Count -gt 5) { $styleParts[5] } else { "" }
                UseBigFont = if ($styleParts.Count -gt 6) { [string]$styleParts[6] -eq "true" } else { $false }
            })
        }
    }
    return [ordered]@{
        getvars = $getvars
        findfiles = $findfiles
        styles = @($styles.ToArray())
    }
}

function Invoke-CadSessionProbe {
    param(
        [string]$AccorePath,
        [string]$DwgPath,
        [string]$WorkDir
    )
    $resolvedAccore = Resolve-FullPathOrRaw -PathText $AccorePath
    $resolvedDwg = Resolve-FullPathOrRaw -PathText $DwgPath
    $logPath = Join-Path $WorkDir "accoreconsole_probe.log"
    $stdoutPath = Join-Path $WorkDir "accoreconsole_stdout.txt"
    $stderrPath = Join-Path $WorkDir "accoreconsole_stderr.txt"
    $probeOut = Join-Path $WorkDir "cad_session_probe.txt"
    if ([string]::IsNullOrWhiteSpace($resolvedAccore) -or -not (Test-Path -LiteralPath $resolvedAccore -PathType Leaf)) {
        return [ordered]@{
            status = "not_run"
            reason = "AccoreConsoleExe is empty or missing."
            exit_code = $null
            parsed = (Parse-CadProbeFile -ProbeOut $probeOut)
            log_path = ""
            probe_path = ""
        }
    }
    if ([string]::IsNullOrWhiteSpace($resolvedDwg) -or -not (Test-Path -LiteralPath $resolvedDwg -PathType Leaf)) {
        return [ordered]@{
            status = "not_run"
            reason = "SampleDwg is empty or missing."
            exit_code = $null
            parsed = (Parse-CadProbeFile -ProbeOut $probeOut)
            log_path = ""
            probe_path = ""
        }
    }

    $scripts = Write-CadProbeScripts -WorkDir $WorkDir -ProbeOut $probeOut
    $previousProbeOut = [Environment]::GetEnvironmentVariable("FANBAN_CAD_ENV_PROBE_OUT", "Process")
    [Environment]::SetEnvironmentVariable("FANBAN_CAD_ENV_PROBE_OUT", $probeOut, "Process")
    try {
        & $resolvedAccore "/i" $resolvedDwg "/s" $scripts.scr "/l" "en-US" > $stdoutPath 2> $stderrPath
        $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    } catch {
        $exitCode = -1
        $_ | Out-String | Out-File -LiteralPath $stderrPath -Encoding utf8
    } finally {
        [Environment]::SetEnvironmentVariable("FANBAN_CAD_ENV_PROBE_OUT", $previousProbeOut, "Process")
    }

    $logLines = @(
        "exit_code=$exitCode",
        "accoreconsole_exe=$resolvedAccore",
        "sample_dwg=$resolvedDwg",
        "script=$($scripts.scr)",
        "probe_out=$probeOut",
        "----- stdout -----"
    )
    if (Test-Path -LiteralPath $stdoutPath -PathType Leaf) {
        $logLines += [System.IO.File]::ReadAllText($stdoutPath, [System.Text.Encoding]::UTF8)
    }
    $logLines += "----- stderr -----"
    if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
        $logLines += [System.IO.File]::ReadAllText($stderrPath, [System.Text.Encoding]::UTF8)
    }
    [System.IO.File]::WriteAllText($logPath, ($logLines -join "`n"), [System.Text.UTF8Encoding]::new($false))

    $parsed = Parse-CadProbeFile -ProbeOut $probeOut
    $hasData = ($parsed.getvars.Count -gt 0 -or $parsed.findfiles.Count -gt 0)
    return [ordered]@{
        status = if ($hasData) { "pass" } elseif ($exitCode -eq 0) { "empty" } else { "fail" }
        reason = if ($hasData) { "" } else { "AcCoreConsole did not write probe data." }
        exit_code = $exitCode
        parsed = $parsed
        log_path = $logPath
        probe_path = if (Test-Path -LiteralPath $probeOut -PathType Leaf) { $probeOut } else { "" }
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$defaultRepoRoot = Resolve-FullPathOrRaw -PathText (Join-Path $scriptRoot "..")
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = $defaultRepoRoot
}
$RepoRoot = Resolve-FullPathOrRaw -PathText $RepoRoot

$defaultFontDirs = @(
    (Join-Path $RepoRoot "documents_bin\font-library\ttf"),
    (Join-Path $RepoRoot "documents_bin\font-library\shx")
)
if ($FontLibraryDir.Count -eq 0) {
    $FontLibraryDir = $defaultFontDirs
}

$plotterSearchDirs = New-Object System.Collections.Generic.List[string]
if (-not [string]::IsNullOrWhiteSpace($PlottersDir)) {
    $plotterSearchDirs.Add((Resolve-FullPathOrRaw -PathText $PlottersDir))
}
$plotterSearchDirs.Add((Join-Path $RepoRoot "documents\Resources"))
$plotterSearchDirs.Add((Join-Path $RepoRoot "test\dist\assets\plotters"))
$plotterSearchDirs.Add((Join-Path $RepoRoot "test\dist\assets"))

$plotStyleSearchDirs = New-Object System.Collections.Generic.List[string]
if (-not [string]::IsNullOrWhiteSpace($PlotStylesDir)) {
    $plotStyleSearchDirs.Add((Resolve-FullPathOrRaw -PathText $PlotStylesDir))
}
if (-not [string]::IsNullOrWhiteSpace($PlottersDir)) {
    $plotStyleSearchDirs.Add((Join-Path (Resolve-FullPathOrRaw -PathText $PlottersDir) "Plot Styles"))
}
$plotStyleSearchDirs.Add((Join-Path $RepoRoot "documents\Resources"))
$plotStyleSearchDirs.Add((Join-Path $RepoRoot "test\dist\assets\plot_styles"))
$plotStyleSearchDirs.Add((Join-Path $RepoRoot "test\dist\assets"))

$pmpRelativeNames = @($PmpName, (Join-Path "PMP Files" $PmpName), (Join-Path "plotters" $PmpName))
$pc3Path = Find-FirstFile -BaseDirs @($plotterSearchDirs.ToArray()) -RelativeNames @($Pc3Name, (Join-Path "plotters" $Pc3Name))
$pmpPath = Find-FirstFile -BaseDirs @($plotterSearchDirs.ToArray()) -RelativeNames $pmpRelativeNames
$ctbPath = Find-FirstFile -BaseDirs @($plotStyleSearchDirs.ToArray()) -RelativeNames @($CtbName, (Join-Path "plot_styles" $CtbName))

$fontInventory = Get-FontLibraryInventory -Dirs $FontLibraryDir
$outputPath = Resolve-FullPathOrRaw -PathText $OutputJson
$outputDir = Split-Path -Parent $outputPath
if (-not [string]::IsNullOrWhiteSpace($outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}
$probeWorkDir = Join-Path $outputDir ("cad-session-probe-" + [DateTime]::UtcNow.ToString("yyyyMMddHHmmss"))
$cadSessionProbe = Invoke-CadSessionProbe -AccorePath $AccoreConsoleExe -DwgPath $SampleDwg -WorkDir $probeWorkDir
$cadGetVars = $cadSessionProbe.parsed.getvars
$cadFindFiles = $cadSessionProbe.parsed.findfiles

function Get-ProbeVar {
    param(
        [object]$Vars,
        [string]$Name
    )
    if ($null -eq $Vars -or -not $Vars.Contains($Name)) {
        return ""
    }
    return [string]$Vars[$Name]
}

function Get-ProbeFindFile {
    param(
        [object]$FindFiles,
        [string]$Name
    )
    if ($null -eq $FindFiles -or -not $FindFiles.Contains($Name)) {
        return ""
    }
    return [string]$FindFiles[$Name]
}

$fontFindfile = [ordered]@{}
foreach ($fontName in @("tssdeng.shx", "hztxt.shx", "tssdchn.shx", "simplex.shx", "gbcbig.shx", "simsun.ttc")) {
    $foundPath = Get-ProbeFindFile -FindFiles $cadFindFiles -Name $fontName
    $fontFindfile[$fontName] = [ordered]@{
        status = if ($cadSessionProbe.status -eq "pass") { if ([string]::IsNullOrWhiteSpace($foundPath)) { "missing" } else { "found" } } else { "not_run" }
        path = $foundPath
        sha256 = Get-Sha256Hex -PathText $foundPath
        library_candidates = @(Get-LibraryCandidates -Name $fontName -FontFiles $fontInventory.files)
    }
}

$payload = [ordered]@{
    schema_version = "fanban-cad-env-fingerprint@1"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    safety = [ordered]@{
        read_only = $true
        modifies_machine = $false
        note = "This script collects file and machine facts only; it does not change AutoCAD profile settings."
    }
    input = [ordered]@{
        repo_root = $RepoRoot
        cad_exe = Resolve-FullPathOrRaw -PathText $CadExe
        accoreconsole_exe = Resolve-FullPathOrRaw -PathText $AccoreConsoleExe
        sample_dwg = Resolve-FullPathOrRaw -PathText $SampleDwg
        pc3_name = $Pc3Name
        pmp_name = $PmpName
        ctb_name = $CtbName
        plotters_dir = Resolve-FullPathOrRaw -PathText $PlottersDir
        plot_styles_dir = Resolve-FullPathOrRaw -PathText $PlotStylesDir
        font_library_dirs = @($FontLibraryDir)
    }
    machine = [ordered]@{
        computer_name = [Environment]::MachineName
        user_name = [Environment]::UserName
        os_version = [Environment]::OSVersion.VersionString
        is_64bit_os = [Environment]::Is64BitOperatingSystem
    }
    autocad = [ordered]@{
        cad_exe = Get-FileFact -PathText $CadExe
        accoreconsole_exe = Get-FileFact -PathText $AccoreConsoleExe
        install_dir = if (-not [string]::IsNullOrWhiteSpace($AccoreConsoleExe)) { Split-Path -Parent (Resolve-FullPathOrRaw -PathText $AccoreConsoleExe) } else { "" }
    }
    cad_session = [ordered]@{
        status = $cadSessionProbe.status
        reason = $cadSessionProbe.reason
        exit_code = $cadSessionProbe.exit_code
        probe_path = $cadSessionProbe.probe_path
    }
    profile = [ordered]@{
        status = if ($cadSessionProbe.status -eq "pass") { "pass" } else { "not_run" }
        current_profile = ""
        ROAMABLEROOTPREFIX = Get-ProbeVar -Vars $cadGetVars -Name "ROAMABLEROOTPREFIX"
        LOCALROOTPREFIX = Get-ProbeVar -Vars $cadGetVars -Name "LOCALROOTPREFIX"
        TRUSTEDPATHS = Get-ProbeVar -Vars $cadGetVars -Name "TRUSTEDPATHS"
    }
    support_paths = [ordered]@{
        raw = Get-ProbeVar -Vars $cadGetVars -Name "ACADPREFIX"
        entries = @(
            (Get-ProbeVar -Vars $cadGetVars -Name "ACADPREFIX").Split(";") |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
    }
    font_vars = [ordered]@{
        FONTMAP = Get-ProbeVar -Vars $cadGetVars -Name "FONTMAP"
        FONTALT = Get-ProbeVar -Vars $cadGetVars -Name "FONTALT"
        FONTALT_resolved = Get-FileFact -PathText (Get-ProbeFindFile -FindFiles $cadFindFiles -Name (Get-ProbeVar -Vars $cadGetVars -Name "FONTALT"))
    }
    font_library = $fontInventory
    font_findfile = $fontFindfile
    text_styles = [ordered]@{
        status = if ($cadSessionProbe.status -eq "pass") { "pass" } else { "not_run" }
        styles = @($cadSessionProbe.parsed.styles)
    }
    plot_assets = [ordered]@{
        pc3 = Get-FileFact -PathText $pc3Path
        pmp = Get-FileFact -PathText $pmpPath
        ctb = Get-FileFact -PathText $ctbPath
    }
    pdf_vars = [ordered]@{
        status = if ($cadSessionProbe.status -eq "pass") { "pass" } else { "not_run" }
        BACKGROUNDPLOT = Get-ProbeVar -Vars $cadGetVars -Name "BACKGROUNDPLOT"
        PDFSHX = Get-ProbeVar -Vars $cadGetVars -Name "PDFSHX"
        EPDFSHX = Get-ProbeVar -Vars $cadGetVars -Name "EPDFSHX"
    }
    sample_plot = [ordered]@{
        status = "not_run"
        sample_dwg = Resolve-FullPathOrRaw -PathText $SampleDwg
        result = ""
        pdf_path = ""
        pdf_size_bytes = 0
    }
    logs = [ordered]@{
        accoreconsole_log = $cadSessionProbe.log_path
        module5_trace_log = ""
    }
}
$json = $payload | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($outputPath, $json, [System.Text.UTF8Encoding]::new($false))
Write-Host "CAD environment fingerprint written to $outputPath"
