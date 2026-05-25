[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$GoldenJson,
    [Parameter(Mandatory = $true)]
    [string]$TargetJson,
    [Parameter(Mandatory = $true)]
    [string]$OutputJson,
    [string]$TargetPlottersDir = "",
    [string]$TargetPlotStylesDir = "",
    [object]$Apply = $false
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

function Read-JsonFile {
    param([string]$PathText)
    $resolved = Resolve-FullPathOrRaw -PathText $PathText
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "JSON file not found: $resolved"
    }
    $text = [System.IO.File]::ReadAllText($resolved, [System.Text.Encoding]::UTF8)
    return $text | ConvertFrom-Json
}

function Get-JsonValue {
    param(
        [object]$ObjectValue,
        [string]$PathText,
        [object]$DefaultValue = $null
    )
    $cursor = $ObjectValue
    foreach ($token in $PathText.Split(".")) {
        if ($null -eq $cursor) {
            return $DefaultValue
        }
        if ($cursor -is [System.Collections.IDictionary]) {
            if (-not $cursor.Contains($token)) {
                return $DefaultValue
            }
            $cursor = $cursor[$token]
            continue
        }
        $property = $cursor.PSObject.Properties[$token]
        if ($null -eq $property) {
            return $DefaultValue
        }
        $cursor = $property.Value
    }
    if ($null -eq $cursor) {
        return $DefaultValue
    }
    return $cursor
}

function Convert-ToStringArray {
    param([object]$Value)
    $result = New-Object System.Collections.Generic.List[string]
    if ($null -eq $Value) {
        return @()
    }
    if ($Value -is [string]) {
        if (-not [string]::IsNullOrWhiteSpace($Value)) {
            $result.Add($Value)
        }
        return @($result.ToArray())
    }
    foreach ($item in @($Value)) {
        $text = [string]$item
        if (-not [string]::IsNullOrWhiteSpace($text)) {
            $result.Add($text)
        }
    }
    return @($result.ToArray())
}

function Add-Difference {
    param(
        [System.Collections.Generic.List[object]]$List,
        [string]$Code,
        [string]$PathText,
        [object]$GoldenValue,
        [object]$TargetValue
    )
    $goldenText = [string]$GoldenValue
    $targetText = [string]$TargetValue
    if ($goldenText -eq $targetText) {
        return
    }
    $List.Add([ordered]@{
        code = $Code
        path = $PathText
        golden = $GoldenValue
        target = $TargetValue
    })
}

function Add-PlannedAction {
    param(
        [System.Collections.Generic.List[object]]$List,
        [string]$Kind,
        [string]$Source,
        [string]$Target,
        [string]$Reason,
        [string]$Status
    )
    $List.Add([ordered]@{
        kind = $Kind
        source = $Source
        target = $Target
        reason = $Reason
        status = $Status
    })
}

function Get-ObjectPropertyNames {
    param([object]$ObjectValue)
    if ($null -eq $ObjectValue) {
        return @()
    }
    $names = New-Object System.Collections.Generic.List[string]
    foreach ($property in $ObjectValue.PSObject.Properties) {
        $names.Add($property.Name)
    }
    return @($names.ToArray())
}

function Get-ObjectPropertyValue {
    param(
        [object]$ObjectValue,
        [string]$Name,
        [object]$DefaultValue = $null
    )
    if ($null -eq $ObjectValue) {
        return $DefaultValue
    }
    $property = $ObjectValue.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $DefaultValue
    }
    if ($null -eq $property.Value) {
        return $DefaultValue
    }
    return $property.Value
}

function Convert-ApplyFlag {
    param([object]$Value)
    if ($Value -is [System.Management.Automation.SwitchParameter]) {
        return [bool]$Value.IsPresent
    }
    if ($Value -is [bool]) {
        return [bool]$Value
    }
    $text = ([string]$Value).Trim()
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $false
    }
    if ($text.StartsWith(":")) {
        $text = $text.Substring(1)
    }
    if ($text.StartsWith("$")) {
        $text = $text.Substring(1)
    }
    return @("true", "1", "yes", "y") -contains $text.ToLowerInvariant()
}

function Copy-AssetAction {
    param(
        [System.Collections.Generic.List[object]]$ActionList,
        [string]$Kind,
        [object]$Golden,
        [string]$TargetDir,
        [bool]$ShouldApply
    )
    $source = [string](Get-JsonValue -ObjectValue $Golden -PathText "plot_assets.$Kind.path" -DefaultValue "")
    if ([string]::IsNullOrWhiteSpace($source)) {
        return
    }
    $sourcePath = Resolve-FullPathOrRaw -PathText $source
    $target = ""
    $status = "planned"
    if (-not [string]::IsNullOrWhiteSpace($TargetDir)) {
        $target = Join-Path (Resolve-FullPathOrRaw -PathText $TargetDir) ([System.IO.Path]::GetFileName($sourcePath))
    }
    if ($ShouldApply) {
        if ([string]::IsNullOrWhiteSpace($target)) {
            $status = "blocked"
        } elseif (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            $status = "blocked"
        } else {
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            Copy-Item -LiteralPath $sourcePath -Destination $target -Force
            $status = "applied"
        }
    }
    Add-PlannedAction `
        -List $ActionList `
        -Kind "copy_plot_asset:$Kind" `
        -Source $sourcePath `
        -Target $target `
        -Reason "Golden and target plot asset differ or target asset is missing." `
        -Status $status
}

$applyFlag = Convert-ApplyFlag -Value $Apply
$golden = Read-JsonFile -PathText $GoldenJson
$target = Read-JsonFile -PathText $TargetJson
$differences = New-Object System.Collections.Generic.List[object]
$actions = New-Object System.Collections.Generic.List[object]

$goldenSupport = (Convert-ToStringArray -Value (Get-JsonValue -ObjectValue $golden -PathText "support_paths.entries" -DefaultValue @())) -join ";"
$targetSupport = (Convert-ToStringArray -Value (Get-JsonValue -ObjectValue $target -PathText "support_paths.entries" -DefaultValue @())) -join ";"
Add-Difference -List $differences -Code "support_path" -PathText "support_paths.entries" -GoldenValue $goldenSupport -TargetValue $targetSupport
if ($goldenSupport -ne $targetSupport) {
    Add-PlannedAction -List $actions -Kind "prepend_support_path" -Source $goldenSupport -Target "runtime SupportPath" -Reason "Team support/font path order differs." -Status "planned"
}

foreach ($varName in @("FONTMAP", "FONTALT")) {
    $goldenValue = [string](Get-JsonValue -ObjectValue $golden -PathText "font_vars.$varName" -DefaultValue "")
    $targetValue = [string](Get-JsonValue -ObjectValue $target -PathText "font_vars.$varName" -DefaultValue "")
    Add-Difference -List $differences -Code $varName -PathText "font_vars.$varName" -GoldenValue $goldenValue -TargetValue $targetValue
    if ($goldenValue -ne $targetValue) {
        Add-PlannedAction -List $actions -Kind "set_runtime_var:$varName" -Source $goldenValue -Target "runtime $varName" -Reason "$varName differs from golden fingerprint." -Status "planned"
    }
}

$fontNames = New-Object System.Collections.Generic.HashSet[string]
foreach ($name in (Get-ObjectPropertyNames -ObjectValue (Get-JsonValue -ObjectValue $golden -PathText "font_findfile" -DefaultValue $null))) {
    [void]$fontNames.Add($name)
}
foreach ($name in (Get-ObjectPropertyNames -ObjectValue (Get-JsonValue -ObjectValue $target -PathText "font_findfile" -DefaultValue $null))) {
    [void]$fontNames.Add($name)
}
foreach ($fontName in ($fontNames | Sort-Object)) {
    $goldenFontFindfile = Get-JsonValue -ObjectValue $golden -PathText "font_findfile" -DefaultValue $null
    $targetFontFindfile = Get-JsonValue -ObjectValue $target -PathText "font_findfile" -DefaultValue $null
    $goldenFont = Get-ObjectPropertyValue -ObjectValue $goldenFontFindfile -Name $fontName -DefaultValue $null
    $targetFont = Get-ObjectPropertyValue -ObjectValue $targetFontFindfile -Name $fontName -DefaultValue $null
    $goldenPath = [string](Get-JsonValue -ObjectValue $goldenFont -PathText "path" -DefaultValue "")
    $targetPath = [string](Get-JsonValue -ObjectValue $targetFont -PathText "path" -DefaultValue "")
    $goldenHash = [string](Get-JsonValue -ObjectValue $goldenFont -PathText "sha256" -DefaultValue "")
    $targetHash = [string](Get-JsonValue -ObjectValue $targetFont -PathText "sha256" -DefaultValue "")
    if ($goldenPath -ne $targetPath -or $goldenHash -ne $targetHash) {
        $differences.Add([ordered]@{
            code = "font_findfile:$fontName"
            path = "font_findfile.$fontName"
            golden = [ordered]@{ path = $goldenPath; sha256 = $goldenHash }
            target = [ordered]@{ path = $targetPath; sha256 = $targetHash }
        })
        Add-PlannedAction -List $actions -Kind "inspect_font_hit:$fontName" -Source $goldenPath -Target $targetPath -Reason "AutoCAD findfile result differs." -Status "planned"
    }
}

foreach ($assetKind in @("pc3", "pmp", "ctb")) {
    $goldenHash = [string](Get-JsonValue -ObjectValue $golden -PathText "plot_assets.$assetKind.sha256" -DefaultValue "")
    $targetHash = [string](Get-JsonValue -ObjectValue $target -PathText "plot_assets.$assetKind.sha256" -DefaultValue "")
    $goldenPath = [string](Get-JsonValue -ObjectValue $golden -PathText "plot_assets.$assetKind.path" -DefaultValue "")
    $targetPath = [string](Get-JsonValue -ObjectValue $target -PathText "plot_assets.$assetKind.path" -DefaultValue "")
    if ($goldenHash -ne $targetHash -or $goldenPath -ne $targetPath) {
        $differences.Add([ordered]@{
            code = "plot_asset:$assetKind"
            path = "plot_assets.$assetKind"
            golden = [ordered]@{ path = $goldenPath; sha256 = $goldenHash }
            target = [ordered]@{ path = $targetPath; sha256 = $targetHash }
        })
        if ($assetKind -eq "ctb") {
            Copy-AssetAction -ActionList $actions -Kind $assetKind -Golden $golden -TargetDir $TargetPlotStylesDir -ShouldApply $applyFlag
        } else {
            Copy-AssetAction -ActionList $actions -Kind $assetKind -Golden $golden -TargetDir $TargetPlottersDir -ShouldApply $applyFlag
        }
    }
}

$payload = [ordered]@{
    schema_version = "fanban-cad-env-sync-plan@1"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    mode = if ($applyFlag) { "apply" } else { "dry-run" }
    safety = [ordered]@{
        apply = [bool]$applyFlag
        modifies_global_autocad_profile = $false
        deletes_user_files = $false
        target_plotters_dir = Resolve-FullPathOrRaw -PathText $TargetPlottersDir
        target_plot_styles_dir = Resolve-FullPathOrRaw -PathText $TargetPlotStylesDir
    }
    input = [ordered]@{
        golden_json = Resolve-FullPathOrRaw -PathText $GoldenJson
        target_json = Resolve-FullPathOrRaw -PathText $TargetJson
    }
    differences = @($differences.ToArray())
    actions = @($actions.ToArray())
}

$outputPath = Resolve-FullPathOrRaw -PathText $OutputJson
$outputDir = Split-Path -Parent $outputPath
if (-not [string]::IsNullOrWhiteSpace($outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}
$json = $payload | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($outputPath, $json, [System.Text.UTF8Encoding]::new($false))
Write-Host "CAD environment sync plan written to $outputPath"
