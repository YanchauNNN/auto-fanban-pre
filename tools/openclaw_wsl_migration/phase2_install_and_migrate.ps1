param(
    [Parameter(Mandatory = $true)]
    [string]$LinuxPasswordPlaintext,

    [string]$DistroName = "ubuntu-openclaw",
    [string]$InstallRoot = "D:\WSL\ubuntu-openclaw",
    [string]$RootFsPath = "D:\WSL\images\ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz",
    [string]$RootFsUrl = "https://cloud-images.ubuntu.com/wsl/releases/noble/current/ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz",
    [string]$LinuxUser = "yanchuan",
    [switch]$MigrateCodex
)

$ErrorActionPreference = "Stop"

function Convert-ToWslPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)

    $resolved = [System.IO.Path]::GetFullPath($WindowsPath)
    $drive = $resolved.Substring(0, 1).ToLowerInvariant()
    $rest = $resolved.Substring(2).Replace("\", "/")
    return "/mnt/$drive$rest"
}

function Invoke-Wsl {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string]$User = "root"
    )

    & wsl.exe -d $DistroName --user $User -- bash -lc $Command
    if ($LASTEXITCODE -ne 0) {
        throw "WSL command failed for user '$User': $Command"
    }
}

function Get-ExistingDistros {
    $raw = & wsl.exe -l -q 2>$null
    if ($LASTEXITCODE -ne 0) {
        return @()
    }

    return ($raw | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "wsl.exe was not found. Run phase 1 first and reboot."
}

$distros = Get-ExistingDistros
if ($distros -contains $DistroName) {
    throw "WSL distro '$DistroName' already exists. Refusing to overwrite it."
}

New-Item -ItemType Directory -Path (Split-Path -Parent $RootFsPath) -Force | Out-Null
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null

if (-not (Test-Path $RootFsPath)) {
    Write-Host "Downloading Ubuntu rootfs to $RootFsPath"
    Invoke-WebRequest -Uri $RootFsUrl -OutFile $RootFsPath
}

Write-Host "Updating WSL runtime"
& wsl.exe --update
& wsl.exe --set-default-version 2

Write-Host "Importing Ubuntu into $InstallRoot"
& wsl.exe --import $DistroName $InstallRoot $RootFsPath --version 2
if ($LASTEXITCODE -ne 0) {
    throw "WSL import failed."
}

$bootstrapScriptWindows = Join-Path $PSScriptRoot "bootstrap_openclaw.sh"
if (-not (Test-Path $bootstrapScriptWindows)) {
    throw "Bootstrap script not found: $bootstrapScriptWindows"
}

$postCleanupScriptWindows = Join-Path $PSScriptRoot "post_migrate_cleanup.sh"
if (-not (Test-Path $postCleanupScriptWindows)) {
    throw "Post-migrate cleanup script not found: $postCleanupScriptWindows"
}

$bootstrapScriptWsl = Convert-ToWslPath -WindowsPath $bootstrapScriptWindows
$postCleanupScriptWsl = Convert-ToWslPath -WindowsPath $postCleanupScriptWindows
$passwordBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($LinuxPasswordPlaintext))
$codexFlag = if ($MigrateCodex) { "true" } else { "false" }

$windowsOpenClaw = "/mnt/c/Users/Yan/.openclaw"
$windowsMcporter = "/mnt/c/Users/Yan/.mcporter"
$windowsCodex = "/mnt/c/Users/Yan/.codex"

$envBlock = @"
export MIGRATION_LINUX_USER='$LinuxUser'
export MIGRATION_PASSWORD_B64='$passwordBase64'
export MIGRATION_WINDOWS_OPENCLAW='$windowsOpenClaw'
export MIGRATION_WINDOWS_MCPORTER='$windowsMcporter'
export MIGRATION_WINDOWS_CODEX='$windowsCodex'
export MIGRATION_INCLUDE_CODEX='$codexFlag'
export MIGRATION_OPENCLAW_VERSION='2026.3.1'
export MIGRATION_MCPORTER_VERSION='0.7.3'
export MIGRATION_CLAWHUB_VERSION='0.7.0'
export MIGRATION_EDGE_CHANNEL='stable'
bash '$bootstrapScriptWsl'
"@

Invoke-Wsl -Command $envBlock -User "root"

Write-Host "Restarting distro to apply /etc/wsl.conf and systemd"
& wsl.exe --terminate $DistroName
Start-Sleep -Seconds 3

Invoke-Wsl -Command "loginctl enable-linger $LinuxUser" -User "root"
Invoke-Wsl -Command "systemctl enable --now xrdp" -User "root"

$installServices = @'
set -euo pipefail
openclaw gateway install || true
openclaw node install --host 127.0.0.1 --port 18789 --display-name DESKTOP-LQJC0UJ-openclaw-node || true
systemctl --user daemon-reload || true
systemctl --user enable --now openclaw-gateway.service || true
systemctl --user enable --now openclaw-node.service || true
timeout 180s npx markitdown-mcp-npx >/tmp/markitdown-mcp-warmup.log 2>&1 || true
openclaw doctor --non-interactive || true
mcporter list || true
'@

Invoke-Wsl -Command $installServices -User $LinuxUser

$postMigrate = @"
export POST_MIGRATE_WINDOWS_CODEX='$windowsCodex'
export POST_MIGRATE_CODEX_VERSION='0.107.0'
export POST_MIGRATE_GITHUB_ENV_VAR='GITHUB_PAT_TOKEN'
export POST_MIGRATE_TARGET_USER='$LinuxUser'
export POST_MIGRATE_HOME_DIR='/home/$LinuxUser'
export POST_MIGRATE_INCLUDE_CODEX='$codexFlag'
bash '$postCleanupScriptWsl'
"@

Invoke-Wsl -Command $postMigrate -User "root"

$validation = @'
set -euo pipefail
printf 'openclaw=%s\n' "$(openclaw --version)"
printf 'node=%s\n' "$(node --version)"
printf 'npm=%s\n' "$(npm --version)"
printf 'python=%s\n' "$(python3 --version)"
printf 'xrdp=%s\n' "$(systemctl is-enabled xrdp)"
printf 'gateway=%s\n' "$(systemctl --user is-enabled openclaw-gateway.service || true)"
printf 'node_service=%s\n' "$(systemctl --user is-enabled openclaw-node.service || true)"
printf 'gateway_mode=%s\n' "$(python3 - <<'PY'
import json, pathlib
data = json.loads(pathlib.Path('/home/yanchuan/.openclaw/openclaw.json').read_text())
print(data.get('gateway', {}).get('mode', 'unknown'))
PY
)"
printf 'memory_provider=%s\n' "$(python3 - <<'PY'
import json, pathlib
data = json.loads(pathlib.Path('/home/yanchuan/.openclaw/openclaw.json').read_text())
print(data.get('agents', {}).get('defaults', {}).get('memorySearch', {}).get('provider', 'unknown'))
PY
)"
printf 'memory_enabled=%s\n' "$(python3 - <<'PY'
import json, pathlib
data = json.loads(pathlib.Path('/home/yanchuan/.openclaw/openclaw.json').read_text())
print(data.get('agents', {}).get('defaults', {}).get('memorySearch', {}).get('enabled', 'unknown'))
PY
)"
'@

Invoke-Wsl -Command $validation -User $LinuxUser

Write-Host ""
Write-Host "Migration phase 2 completed."
Write-Host "RDP target: 127.0.0.1:3390"
