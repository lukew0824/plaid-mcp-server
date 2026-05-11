#!/usr/bin/env bash
set -euo pipefail

# plaid-mcp installer for Ubuntu 24.04 / Debian.
# Run from the project directory after editing .env.

if [[ $EUID -eq 0 ]]; then
    echo "Error: do not run this script as root. The service should run as a normal user."
    echo "Run as a regular user; the script will use sudo internally where needed."
    exit 1
fi

if [[ ! -f .env ]]; then
    echo "Error: .env not found. Run 'cp .env.example .env' and fill in the values first."
    exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "${BASE_URL:-}" ]]; then
    echo "Error: BASE_URL not set in .env"
    exit 1
fi

DOMAIN="${BASE_URL#https://}"
DOMAIN="${DOMAIN#http://}"
DOMAIN="${DOMAIN%%/*}"

PROJECT_DIR="$(pwd)"
RUN_USER="$(whoami)"

echo "==> Installing system packages"
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-venv python3-pip git curl \
    debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null 2>&1; then
    echo "==> Installing Caddy"
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq caddy
fi

echo "==> Setting up Python virtualenv"
if [[ ! -d .venv ]]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "==> Writing /etc/caddy/Caddyfile for $DOMAIN"
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$DOMAIN {
    reverse_proxy localhost:8080
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Frame-Options "DENY"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin"
        Content-Security-Policy "default-src 'self'; script-src 'self' https://cdn.plaid.com; connect-src 'self' https://*.plaid.com; frame-src https://*.plaid.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; object-src 'none'; base-uri 'none'"
    }
}
EOF
sudo systemctl reload caddy

echo "==> Writing /etc/systemd/system/plaid-mcp.service"
sudo tee /etc/systemd/system/plaid-mcp.service >/dev/null <<EOF
[Unit]
Description=plaid-mcp
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/.venv/bin/python app.py
Restart=on-failure
RestartSec=5

# Sandboxing
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true
RestrictRealtime=true
RestrictSUIDSGID=true
ReadWritePaths=$PROJECT_DIR
CapabilityBoundingSet=
AmbientCapabilities=
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now plaid-mcp
sudo systemctl restart plaid-mcp

echo
echo "Installed. Service status:"
sudo systemctl status plaid-mcp --no-pager -l | head -10
echo
echo "Tail logs:    sudo journalctl -u plaid-mcp -f"
echo "MCP endpoint: $BASE_URL/mcp"
