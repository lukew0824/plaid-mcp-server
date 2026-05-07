#!/usr/bin/env bash
set -euo pipefail

# plaid-mcp installer for Ubuntu 24.04 / Debian.
# Run from the project directory after editing .env.

if [[ ! -f .env ]]; then
    echo "Error: .env not found. Run 'cp .env.example .env' and fill in the values first."
    exit 1
fi

# shellcheck disable=SC2046
export $(grep -v '^#' .env | grep -v '^$' | xargs -d '\n' -I {} echo {})

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
