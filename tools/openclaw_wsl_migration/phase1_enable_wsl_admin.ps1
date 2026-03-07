param(
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-Admin {
    if (-not (Test-IsAdmin)) {
        throw "This script must be run from an elevated PowerShell window."
    }
}

function Assert-FirmwareVirtualization {
    $systemInfo = systeminfo | Out-String
    if ($systemInfo -notmatch "Virtualization Enabled In Firmware:\s+Yes") {
        throw @"
Firmware virtualization is disabled on this machine.
Enable Intel VT-x / virtualization in BIOS or UEFI first, then rerun this script.
"@
    }
}

Assert-Admin
Assert-FirmwareVirtualization

$wslRoot = "D:\WSL"
New-Item -ItemType Directory -Path $wslRoot -Force | Out-Null

$wslConfigPath = Join-Path $env:USERPROFILE ".wslconfig"
$wslConfig = @"
[wsl2]
memory=56GB
processors=32
swap=16GB
swapFile=D:\\WSL\\swap.vhdx
dnsTunneling=true
pageReporting=false
vmIdleTimeout=-1
nestedVirtualization=true
firewall=true
networkingMode=mirrored

[experimental]
autoMemoryReclaim=disabled
sparseVhd=true
hostAddressLoopback=true
"@

Set-Content -Path $wslConfigPath -Value $wslConfig -Encoding Ascii

Write-Host "Written $wslConfigPath"

dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

bcdedit /set hypervisorlaunchtype auto | Out-Null

Write-Host ""
Write-Host "WSL features have been staged."
Write-Host "A reboot is required before phase 2."

if (-not $NoRestart) {
    Restart-Computer -Force
}
