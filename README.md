# plaid-mcp

A self-hosted [MCP](https://modelcontextprotocol.io) server that lets Claude query your bank accounts, balances, and transactions through [Plaid](https://plaid.com).

## Tools

| Tool | Description |
|------|-------------|
| `accounts` | All linked bank accounts |
| `balances` | Current/available balances and credit limits |
| `transactions` | Full transaction history for a date range |
| `total_spending` | Total spending broken down by category |
| `transactions_by_category` | Filter transactions by Plaid PFC category |
| `merchants` | All merchants for a date range, sorted by total spend |
| `transactions_by_merchant` | Filter transactions by merchant name |

## How it works

- **OAuth 2.1 + PKCE** with Google as the identity provider
- **Email allowlist** is the security boundary
- Claude.ai gets a 30-day bearer token; your Plaid access token never leaves your server
- **Caddy** sits in front of FastAPI, terminating TLS on port 443 with auto-provisioned Let's Encrypt certs and reverse-proxying to `localhost:8080`

## Requirements

- A Linux server with a public IP (this guide uses an AWS EC2 `t3.micro`)
- A domain name pointing at it (this guide uses a free DuckDNS subdomain)
- A Plaid developer account with **production access**
- A Google Cloud account for the OAuth client

## Setup

### 1. Plaid

1. Create a Plaid account at [dashboard.plaid.com](https://dashboard.plaid.com)
2. Request **Production access** in the dashboard (Plaid will review your application — this can take a few days)
3. Once approved, save your `client_id` and `Production` secret from **Team Settings → Keys**

### 2. Google OAuth

1. [console.cloud.google.com](https://console.cloud.google.com) → create a project
2. **APIs & Services → OAuth consent screen** → set up an "External" app, add yourself as a test user
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**
4. Application type: **Web application**
5. **Authorized redirect URIs**: `https://yourdomain.com/auth/google/callback` *(use your real domain from step 4 below)*
6. Save the `Client ID` and `Client secret`

### 3. Server

This guide assumes AWS EC2:

1. Launch a `t3.micro` Ubuntu 24.04 instance
2. Security group: inbound TCP **22** (SSH from your IP), **80**, **443**
3. **Allocate** an Elastic IP and **associate** it with the instance
4. SSH in: `ssh -i your-key.pem ubuntu@<elastic-ip>`

### 4. Domain

Free option using [DuckDNS](https://www.duckdns.org):

1. Sign in with Google/GitHub/Reddit
2. Reserve a subdomain (e.g. `plaid-yourname`)
3. Set the IP to your Elastic IP
4. Your domain is now `plaid-yourname.duckdns.org`

Go back to step 2.5 and set the redirect URI to `https://plaid-yourname.duckdns.org/auth/google/callback`.

### 5. Install

On the server:

```bash
git clone https://github.com/lukew0824/plaid-mcp.git
cd plaid-mcp
cp .env.example .env
nano .env   # fill in everything
./install.sh
```

The script:
- Installs Python, Caddy, and dependencies
- Sets up and starts a systemd service (`plaid-mcp`) that auto-restarts on failure and boot
- Configures Caddy as a reverse proxy with auto-HTTPS via Let's Encrypt

### 6. Connect in Claude.ai

1. Claude.ai → **Settings → Connectors → Add custom connector**
2. URL: `https://yourdomain.com/mcp`
3. Click **Connect**
4. Sign in with the Google account matching `ALLOWED_EMAIL`
5. **First time only**: a Plaid Link popup will appear — connect your bank
6. Done. Try: *"What did I spend on food last month?"*

## Configuration

The `.env` values:

| Key | Description |
|-----|-------------|
| `PLAID_ENV` | `production` |
| `PLAID_CLIENT_ID` | From Plaid dashboard |
| `PLAID_PRODUCTION_SECRET` | From Plaid dashboard |
| `GOOGLE_CLIENT_ID` | From Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | From Google Cloud Console |
| `ALLOWED_EMAIL` | The single Google email allowed to authenticate |
| `BASE_URL` | Public HTTPS URL of this server (no trailing slash) |
| `DATABASE_URL` | `sqlite:///./plaid_mcp.db` (default works for self-hosting) |

## License

MIT
