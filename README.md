<div align="center">

# Plaid MCP Server

**A self-hosted MCP server for securely querying personal financial data through Plaid.**

Connect an MCP-compatible AI assistant to bank accounts, balances, transactions, merchants, and spending data while keeping Plaid credentials and access tokens on your own server.

</div>

---

## Overview

Plaid MCP Server exposes personal financial data through the Model Context Protocol (MCP), allowing an AI assistant to answer questions about connected bank accounts and transaction history.

The server handles authentication, Plaid account linking, financial-data retrieval, and MCP tool execution behind a self-hosted API.

Example queries:

```text
"What did I spend on food last month?"

"Show me my largest purchases this week."

"How much have I spent at Trader Joe's this year?"

"What are my current account balances?"
```

## Available Tools

| Tool | Description |
| --- | --- |
| `accounts` | List all linked bank accounts |
| `balances` | Retrieve current and available balances and credit limits |
| `transactions` | Retrieve transaction history for a specified date range |
| `total_spending` | Calculate spending totals grouped by category |
| `transactions_by_category` | Filter transactions by Plaid Personal Finance Category |
| `merchants` | List merchants ranked by total spend over a date range |
| `transactions_by_merchant` | Filter transactions by merchant name |

## Architecture

```text
┌──────────────────────┐
│  MCP Client / AI     │
└──────────┬───────────┘
           │ HTTPS + MCP
           ▼
┌──────────────────────┐
│        Caddy         │
│   TLS / Reverse Proxy│
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│       FastAPI        │
│   MCP + OAuth Layer  │
└───────┬───────┬──────┘
        │       │
        │       └──────────────► Google OAuth
        │
        ▼
┌──────────────────────┐
│        Plaid         │
│ Accounts / Txns / PFC│
└──────────────────────┘
```

### Authentication and Security

- OAuth 2.1 + PKCE with Google as the identity provider
- Email allowlist controls access to the server
- Plaid access tokens remain on the self-hosted server
- MCP clients receive a time-limited bearer token
- Caddy terminates TLS and reverse-proxies traffic to FastAPI
- HTTPS certificates are automatically provisioned through Let's Encrypt

## Tech Stack

**Backend:** Python, FastAPI  
**Protocol:** Model Context Protocol (MCP)  
**Financial data:** Plaid API  
**Authentication:** Google OAuth 2.1 + PKCE  
**Storage:** SQLite  
**Infrastructure:** AWS EC2, Caddy, systemd  
**Transport:** HTTPS

## Requirements

Before deploying, you'll need:

- A Linux server with a public IP
- A domain or subdomain pointing to the server
- A Plaid developer account with Production access
- A Google Cloud project with OAuth credentials

The setup below uses an AWS EC2 `t3.micro` instance and DuckDNS, but equivalent infrastructure should work as well.

## Setup

### 1. Plaid

1. Create a Plaid developer account.
2. Request Production access through the Plaid dashboard.
3. Once approved, save your:
   - `client_id`
   - Production secret

### 2. Google OAuth

Create a Google Cloud project and configure an OAuth client.

Use the following redirect URI:

```text
https://yourdomain.com/auth/google/callback
```

Save the generated:

- Client ID
- Client secret

### 3. Server

This example uses Ubuntu on AWS EC2.

1. Launch an Ubuntu 24.04 instance.
2. Allow inbound traffic on:
   - `22` for SSH
   - `80` for HTTP
   - `443` for HTTPS
3. Associate a stable public IP with the instance.
4. Connect over SSH.

```bash
ssh -i your-key.pem ubuntu@<server-ip>
```

### 4. Domain

Point a domain or subdomain at your server's public IP.

For a free option, DuckDNS works well:

```text
plaid-yourname.duckdns.org
```

Then use:

```text
https://plaid-yourname.duckdns.org/auth/google/callback
```

as the Google OAuth redirect URI.

### 5. Install

Clone the repository:

```bash
git clone https://github.com/lukew0824/plaid-mcp-server.git
cd plaid-mcp-server
```

Create your environment file:

```bash
cp .env.example .env
nano .env
```

Fill in the required values, then run:

```bash
./install.sh
```

The installer:

- Installs Python dependencies and Caddy
- Creates a `systemd` service
- Configures the application to restart automatically
- Configures Caddy as an HTTPS reverse proxy

### 6. Connect an MCP Client

For Claude.ai:

1. Open **Settings → Connectors**
2. Add a custom connector
3. Set the URL to:

```text
https://yourdomain.com/mcp
```

4. Authenticate using the Google account configured in `ALLOWED_EMAIL`
5. Complete Plaid Link the first time you connect a financial institution

Once connected, the financial tools will be available to the MCP client.

## Configuration

| Variable | Description |
| --- | --- |
| `PLAID_ENV` | Plaid environment, typically `production` |
| `PLAID_CLIENT_ID` | Plaid client ID |
| `PLAID_PRODUCTION_SECRET` | Plaid Production secret |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `ALLOWED_EMAIL` | Google account permitted to authenticate |
| `BASE_URL` | Public HTTPS URL of the server |
| `DATABASE_URL` | Database connection string; SQLite works by default |

## Project Structure

```text
plaid-mcp-server/
├── app.py
├── crypto_utils.py
├── database.py
├── plaid_client.py
├── tools.py
├── install.sh
├── requirements.txt
├── .env.example
└── README.md
```

## License

MIT
