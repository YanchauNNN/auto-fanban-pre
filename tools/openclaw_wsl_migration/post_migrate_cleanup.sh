#!/usr/bin/env bash
set -euo pipefail

WINDOWS_CODEX_DIR="${POST_MIGRATE_WINDOWS_CODEX:-/mnt/c/Users/Yan/.codex}"
CODEX_VERSION="${POST_MIGRATE_CODEX_VERSION:-0.107.0}"
GITHUB_ENV_VAR="${POST_MIGRATE_GITHUB_ENV_VAR:-GITHUB_PAT_TOKEN}"
TARGET_USER="${POST_MIGRATE_TARGET_USER:-yanchuan}"
HOME_DIR="${POST_MIGRATE_HOME_DIR:-/home/$TARGET_USER}"
INCLUDE_CODEX="${POST_MIGRATE_INCLUDE_CODEX:-false}"

backup_dir="$HOME_DIR/.openclaw/.migration-backups"
sessions_dir="$HOME_DIR/.openclaw/agents/main/sessions"
mkdir -p "$backup_dir" "$sessions_dir"

run_as_target_user() {
  local command="$1"
  if [[ "$(id -u)" -eq 0 ]]; then
    local target_uid
    target_uid="$(id -u "$TARGET_USER")"
    runuser -u "$TARGET_USER" -- env HOME="$HOME_DIR" XDG_RUNTIME_DIR="/run/user/$target_uid" bash -lc "$command"
  else
    env HOME="$HOME_DIR" bash -lc "$command"
  fi
}

install_root_tools() {
  if [[ "$INCLUDE_CODEX" != "true" ]]; then
    return 0
  fi

  if [[ "$(id -u)" -eq 0 ]]; then
    apt-get update >/dev/null
    apt-get install -y ripgrep >/dev/null
    npm install -g "@openai/codex@$CODEX_VERSION" >/dev/null
  else
    sudo apt-get update >/dev/null
    sudo apt-get install -y ripgrep >/dev/null
    sudo npm install -g "@openai/codex@$CODEX_VERSION" >/dev/null
  fi
}

python3 - "$HOME_DIR" <<'PY'
import json
import pathlib
import shutil
import sys

home = pathlib.Path(sys.argv[1])
backup_dir = home / ".openclaw" / ".migration-backups"
sessions_dir = home / ".openclaw" / "agents" / "main" / "sessions"
store_path = sessions_dir / "sessions.json"

if store_path.exists():
    shutil.copy2(store_path, backup_dir / "sessions.json.pre-rewrite")
    store = json.loads(store_path.read_text(encoding="utf-8"))
    keep = set()

    for value in store.values():
        if not isinstance(value, dict):
            continue
        session_id = value.get("sessionId")
        if not session_id:
            continue
        keep.add(f"{session_id}.jsonl")
        value["sessionFile"] = str(sessions_dir / f"{session_id}.jsonl")

    store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    orphan_dir = sessions_dir / "orphaned"
    orphan_dir.mkdir(exist_ok=True)
    for transcript in sessions_dir.glob("*.jsonl"):
        if transcript.name not in keep:
            shutil.move(str(transcript), str(orphan_dir / transcript.name))

config_path = home / ".openclaw" / "openclaw.json"
if config_path.exists():
    backup_path = backup_dir / "openclaw.json.pre-memory-provider-fix"
    if not backup_path.exists():
        shutil.copy2(config_path, backup_path)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    memory_search = config.setdefault("agents", {}).setdefault("defaults", {}).setdefault("memorySearch", {})
    memory_search["enabled"] = True
    if memory_search.get("provider") not in {"openai", "gemini", "voyage", "mistral", "local"}:
        memory_search["provider"] = "local"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

(home / ".openclaw" / "workspace" / "memory").mkdir(parents=True, exist_ok=True)
PY

install_root_tools

if [[ "$INCLUDE_CODEX" == "true" ]] && [[ -d "$WINDOWS_CODEX_DIR" ]]; then
  mkdir -p "$HOME_DIR/.codex"
  rsync -a --delete "$WINDOWS_CODEX_DIR"/ "$HOME_DIR/.codex"/
fi

if [[ "$INCLUDE_CODEX" == "true" ]]; then
python3 - "$HOME_DIR" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1]) / ".codex" / "config.toml"
if not config_path.exists():
    raise SystemExit(0)

text = config_path.read_text(encoding="utf-8")
text = text.replace(
    'command = "C:/Users/Yan/AppData/Local/Programs/Python/Python313/Scripts/markitdown-mcp-server.exe"',
    'command = "npx"\nargs = ["markitdown-mcp-npx"]\nenv = { SSL_CERT_FILE = "/etc/ssl/certs/ca-certificates.crt", REQUESTS_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt" }',
)
text = text.replace(
    'args = ["markitdown-mcp-npx"]',
    'args = ["markitdown-mcp-npx"]\nenv = { SSL_CERT_FILE = "/etc/ssl/certs/ca-certificates.crt", REQUESTS_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt" }',
)
text = text.replace(
    'args = ["markitdown-mcp-npx"]\nenv = { SSL_CERT_FILE = "/etc/ssl/certs/ca-certificates.crt", REQUESTS_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt" }\nenv = { SSL_CERT_FILE = "/etc/ssl/certs/ca-certificates.crt", REQUESTS_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt" }',
    'args = ["markitdown-mcp-npx"]\nenv = { SSL_CERT_FILE = "/etc/ssl/certs/ca-certificates.crt", REQUESTS_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt" }',
)
text = text.replace(
    'args = ["@playwright/mcp@latest"]',
    'args = ["@playwright/mcp@latest", "--browser", "msedge", "--headless"]',
)
text = text.replace('[windows]\nsandbox = "elevated"\n', "")
config_path.write_text(text, encoding="utf-8")
PY
fi

profile_snippet=$(cat <<EOF
# CODEX_GITHUB_PAT_IMPORT
if [ -z "\${$GITHUB_ENV_VAR:-}" ] && command -v powershell.exe >/dev/null 2>&1; then
  export $GITHUB_ENV_VAR="\$(powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('$GITHUB_ENV_VAR','User')" | tr -d '\r')"
fi
EOF
)

if [[ "$INCLUDE_CODEX" == "true" ]]; then
  for file in "$HOME_DIR/.profile" "$HOME_DIR/.bashrc"; do
    touch "$file"
    if ! grep -q "CODEX_GITHUB_PAT_IMPORT" "$file"; then
      printf '\n%s\n' "$profile_snippet" >>"$file"
    fi
  done
fi

mkdir -p "$HOME_DIR/.config/systemd/user/openclaw-gateway.service.d"
mkdir -p "$HOME_DIR/.config/systemd/user/openclaw-node.service.d"
cat >"$HOME_DIR/.config/systemd/user/openclaw-gateway.service.d/override.conf" <<'EOF'
[Service]
Environment="NODE_OPTIONS=--use-openssl-ca --dns-result-order=ipv4first"
EOF
cat >"$HOME_DIR/.config/systemd/user/openclaw-node.service.d/override.conf" <<'EOF'
[Service]
Environment="NODE_OPTIONS=--use-openssl-ca --dns-result-order=ipv4first"
EOF

if [[ "$INCLUDE_CODEX" == "true" ]] && [[ -d "$HOME_DIR/.codex" ]]; then
  chmod 700 "$HOME_DIR/.codex"
fi

chown -R "$TARGET_USER:$TARGET_USER" "$backup_dir" "$HOME_DIR/.openclaw" "$HOME_DIR/.config"
if [[ -d "$HOME_DIR/.codex" ]]; then
  chown -R "$TARGET_USER:$TARGET_USER" "$HOME_DIR/.codex"
fi
if [[ -d "$sessions_dir/orphaned" ]]; then
  chown -R "$TARGET_USER:$TARGET_USER" "$sessions_dir/orphaned"
fi
if [[ "$INCLUDE_CODEX" == "true" ]]; then
  chown "$TARGET_USER:$TARGET_USER" "$HOME_DIR/.profile" "$HOME_DIR/.bashrc"
fi

run_as_target_user "systemctl --user daemon-reload"
run_as_target_user "systemctl --user restart openclaw-gateway.service"
run_as_target_user "systemctl --user restart openclaw-node.service"
run_as_target_user "openclaw memory status --deep --index --json >/tmp/openclaw-memory-status.json"
python3 - "$HOME_DIR" <<'PY'
import json
import pathlib
import sys

home = pathlib.Path(sys.argv[1])
config_path = home / ".openclaw" / "openclaw.json"
model_path = home / ".node-llama-cpp" / "models" / "hf_ggml-org_embeddinggemma-300m-qat-Q8_0.gguf"
if not config_path.exists() or not model_path.exists():
    raise SystemExit(0)

config = json.loads(config_path.read_text(encoding="utf-8"))
memory_search = config.setdefault("agents", {}).setdefault("defaults", {}).setdefault("memorySearch", {})
if memory_search.get("provider") == "local":
    local = memory_search.setdefault("local", {})
    local["modelPath"] = str(model_path)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
if [[ "$INCLUDE_CODEX" == "true" ]]; then
  run_as_target_user "codex --version >/tmp/codex-version.txt"
  run_as_target_user "codex mcp list >/tmp/codex-mcp-list.txt"
fi

echo "post_migrate_cleanup_complete"
