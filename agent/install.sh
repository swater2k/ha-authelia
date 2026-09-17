#!/usr/bin/env bash
# Installs or updates the Authelia HA Agent inside the Authelia host/LXC.
# Usage: bash install.sh [--port 9960] [--db /etc/authelia/db.sqlite3] [--rotate-token]
set -euo pipefail

PORT=9960
DB=/etc/authelia/db.sqlite3
ROTATE=0
REPO_RAW="https://raw.githubusercontent.com/swater2k/ha-authelia/main/agent"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --rotate-token) ROTATE=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Please run as root." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required." >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "Python >= 3.11 is required." >&2; exit 1; }
[[ -f "$DB" ]] || { echo "Authelia database not found: $DB" >&2; exit 1; }

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-/nonexistent/x}")" 2>/dev/null && pwd || echo /nonexistent)"
install -d -m 0755 /opt/authelia-ha-agent
install -d -m 0700 /etc/authelia-ha-agent

fetch() {  # fetch <file> <dest>
  if [[ -f "$SRC_DIR/$1" ]]; then
    install -m 0644 "$SRC_DIR/$1" "$2"
  else
    curl -fsSL "$REPO_RAW/$1" -o "$2"
  fi
}

fetch authelia_ha_agent.py /opt/authelia-ha-agent/authelia_ha_agent.py
fetch authelia-ha-agent.service /etc/systemd/system/authelia-ha-agent.service

ENV_FILE=/etc/authelia-ha-agent/agent.env
if [[ ! -f "$ENV_FILE" || $ROTATE -eq 1 ]]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  umask 077
  cat > "$ENV_FILE" <<ENV
AGENT_TOKEN=$TOKEN
AGENT_BIND=0.0.0.0
AGENT_PORT=$PORT
AUTHELIA_DB=$DB
AUTHELIA_BIN=$(command -v authelia || true)
ENV
  NEW_TOKEN=1
else
  NEW_TOKEN=0
fi
chmod 0600 "$ENV_FILE"

systemctl daemon-reload
systemctl enable --now authelia-ha-agent.service
systemctl restart authelia-ha-agent.service
sleep 1

if curl -fsS "http://127.0.0.1:$(grep -oP '^AGENT_PORT=\K.*' "$ENV_FILE")/health" >/dev/null; then
  echo "Authelia HA Agent is running."
else
  echo "Agent did not respond – check: journalctl -u authelia-ha-agent -n 50" >&2
  exit 1
fi

IP="$(hostname -I | awk '{print $1}')"
echo
echo "URL:   http://$IP:$(grep -oP '^AGENT_PORT=\K.*' "$ENV_FILE")"
if [[ $NEW_TOKEN -eq 1 ]]; then
  echo "Token: $(grep -oP '^AGENT_TOKEN=\K.*' "$ENV_FILE")"
  echo "Enter both in Home Assistant: Authelia → Configure."
else
  echo "Existing token kept (show it with: grep AGENT_TOKEN $ENV_FILE)."
fi
