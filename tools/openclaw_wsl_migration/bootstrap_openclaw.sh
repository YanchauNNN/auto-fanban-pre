#!/usr/bin/env bash
set -euo pipefail

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: $name" >&2
    exit 1
  fi
}

require_env MIGRATION_LINUX_USER
require_env MIGRATION_PASSWORD_B64
require_env MIGRATION_WINDOWS_OPENCLAW
require_env MIGRATION_WINDOWS_MCPORTER
require_env MIGRATION_OPENCLAW_VERSION
require_env MIGRATION_MCPORTER_VERSION
require_env MIGRATION_CLAWHUB_VERSION
require_env MIGRATION_EDGE_CHANNEL

LINUX_USER="$MIGRATION_LINUX_USER"
LINUX_HOME="/home/$LINUX_USER"
PASSWORD="$(printf '%s' "$MIGRATION_PASSWORD_B64" | base64 -d)"
INCLUDE_CODEX="${MIGRATION_INCLUDE_CODEX:-false}"

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y \
  sudo curl wget ca-certificates gnupg2 gpg jq rsync unzip zip git \
  build-essential python3 python3-pip python3-venv python3-dev pipx \
  xfce4 xfce4-goodies xrdp dbus-x11 xorgxrdp

if ! id "$LINUX_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$LINUX_USER"
fi

echo "$LINUX_USER:$PASSWORD" | chpasswd
usermod -aG sudo "$LINUX_USER"

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
chmod a+r /etc/apt/keyrings/nodesource.gpg
cat >/etc/apt/sources.list.d/nodesource.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main
EOF

curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft-edge.gpg
chmod a+r /etc/apt/keyrings/microsoft-edge.gpg
cat >/etc/apt/sources.list.d/microsoft-edge.list <<EOF
deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft-edge.gpg] https://packages.microsoft.com/repos/edge ${MIGRATION_EDGE_CHANNEL} main
EOF

apt-get update
apt-get install -y nodejs microsoft-edge-stable

npm install -g \
  "openclaw@${MIGRATION_OPENCLAW_VERSION}" \
  "mcporter@${MIGRATION_MCPORTER_VERSION}" \
  "clawhub@${MIGRATION_CLAWHUB_VERSION}" \
  "@playwright/mcp@latest" \
  "markitdown-mcp-npx"

mkdir -p "$LINUX_HOME/.openclaw" "$LINUX_HOME/.mcporter"
rsync -a --delete "$MIGRATION_WINDOWS_OPENCLAW"/ "$LINUX_HOME/.openclaw"/
rsync -a --delete "$MIGRATION_WINDOWS_MCPORTER"/ "$LINUX_HOME/.mcporter"/

if [[ "$INCLUDE_CODEX" == "true" ]] && [[ -d "${MIGRATION_WINDOWS_CODEX:-}" ]]; then
  mkdir -p "$LINUX_HOME/.codex"
  rsync -a --delete "${MIGRATION_WINDOWS_CODEX}/" "$LINUX_HOME/.codex"/
fi

python3 - "$LINUX_HOME" <<'PY'
import json
import pathlib
import sys
from urllib.parse import urlparse

home = pathlib.Path(sys.argv[1])
backup_dir = home / ".openclaw" / ".migration-backups"
backup_dir.mkdir(parents=True, exist_ok=True)

openclaw_json = home / ".openclaw" / "openclaw.json"
if openclaw_json.exists():
    backup_path = backup_dir / "openclaw.json.windows-origin"
    if not backup_path.exists():
        backup_path.write_text(openclaw_json.read_text(encoding="utf-8"), encoding="utf-8")
    data = json.loads(openclaw_json.read_text(encoding="utf-8"))
    entries = (
        data.get("skills", {})
        .get("entries", {})
    )
    for skill_name in ("sherpa-onnx-tts",):
        entry = entries.get(skill_name)
        if not isinstance(entry, dict):
            continue
        env = entry.get("env")
        if not isinstance(env, dict):
            continue
        for key, value in list(env.items()):
            if isinstance(value, str):
                env[key] = value.replace("C:/Users/Yan/.openclaw", str(home / ".openclaw"))

    gateway = data.get("gateway")
    if isinstance(gateway, dict):
        remote = gateway.get("remote")
        remote_url = remote.get("url") if isinstance(remote, dict) else None
        if isinstance(remote_url, str):
            parsed = urlparse(remote_url)
            hostname = (parsed.hostname or "").lower()
            if gateway.get("mode") == "remote" and hostname in {"127.0.0.1", "localhost", "::1"}:
                gateway["mode"] = "local"
                gateway.pop("remote", None)

    openclaw_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

mcporter_json = home / ".mcporter" / "mcporter.json"
if mcporter_json.exists():
    backup_path = backup_dir / "mcporter.json.windows-origin"
    if not backup_path.exists():
        backup_path.write_text(mcporter_json.read_text(encoding="utf-8"), encoding="utf-8")
    data = json.loads(mcporter_json.read_text(encoding="utf-8"))
    servers = data.get("mcpServers", {})
    markitdown = servers.get("markitdown")
    if isinstance(markitdown, dict):
        markitdown["command"] = "npx"
        markitdown["args"] = ["markitdown-mcp-npx"]
        markitdown["env"] = {
            "PATH": f"/usr/local/bin:/usr/bin:/bin:{home}/.local/bin"
        }
    playwright = servers.get("playwright")
    if isinstance(playwright, dict):
        playwright["command"] = "npx"
        playwright["args"] = ["@playwright/mcp@latest", "--browser", "msedge", "--headless"]
    mcporter_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

cat >"$LINUX_HOME/.xsession" <<'EOF'
xfce4-session
EOF

mkdir -p "$LINUX_HOME/.config"
chown -R "$LINUX_USER:$LINUX_USER" "$LINUX_HOME"
chmod 700 "$LINUX_HOME" "$LINUX_HOME/.openclaw" "$LINUX_HOME/.mcporter"
chmod 600 "$LINUX_HOME/.openclaw/openclaw.json" "$LINUX_HOME/.mcporter/mcporter.json"
if [[ -d "$LINUX_HOME/.openclaw/credentials" ]]; then
  find "$LINUX_HOME/.openclaw/credentials" -type f -exec chmod 600 {} \;
fi
if [[ -d "$LINUX_HOME/.openclaw/devices" ]]; then
  find "$LINUX_HOME/.openclaw/devices" -type f -exec chmod 600 {} \;
fi

sed -i 's/^port=3389/port=3390/' /etc/xrdp/xrdp.ini
adduser xrdp ssl-cert >/dev/null 2>&1 || true

cat >/etc/wsl.conf <<EOF
[boot]
systemd=true

[user]
default=$LINUX_USER
EOF

echo "Bootstrap complete. Restart the distro before installing user services."
