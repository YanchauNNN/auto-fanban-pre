# OpenClaw WSL Migration

This folder contains the migration scripts for moving the current Windows
OpenClaw setup into a WSL2 Ubuntu environment stored on `D:\WSL`.

Current blockers detected on this machine:

- WSL is not installed yet.
- The current terminal is not elevated.
- Firmware virtualization is currently disabled (`Virtualization Enabled In Firmware: No`).

Script order:

1. Run `phase1_enable_wsl_admin.ps1` from an elevated PowerShell after turning on
   Intel VT-x / virtualization in BIOS or UEFI.
2. Reboot Windows.
3. Run `phase2_install_and_migrate.ps1 -LinuxPasswordPlaintext '<password>'`
   from a normal PowerShell session.

What phase 2 does:

- Installs WSL2 Ubuntu 24.04 under `D:\WSL`.
- Creates the Linux user requested by the operator.
- Installs Node 22, OpenClaw, `mcporter`, `clawhub`, Python, Playwright
  prerequisites, MarkItDown prerequisites, and a desktop stack (`xfce4` + `xrdp`).
- Copies `.openclaw` and `.mcporter` from Windows into the Linux home directory.
- Applies the minimum Linux path rewrites required for the copied configuration to
  remain runnable on Ubuntu.
- Attempts to install OpenClaw gateway and node services inside WSL.
- Exposes the Ubuntu desktop over RDP on `127.0.0.1:3390`.

Notes:

- WSL does not provide a direct user-facing knob for "maximum GPU memory". GPU
  access is exposed through the Windows host driver stack. The scripts configure
  CPU and memory aggressively, which is the main tunable resource control WSL
  supports.
- Some Windows-only helper binaries under `.openclaw/bin` are copied for fidelity,
  but they may still need Linux-native replacements if you actively use those
  specific skills inside Ubuntu.
