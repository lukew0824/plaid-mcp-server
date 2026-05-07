import os
from contextvars import ContextVar
from urllib.parse import urlparse
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from plaid_client import (
    get_accounts,
    get_balances,
    get_transactions,
    get_total_spending,
    get_transactions_by_category,
    get_merchants,
    get_transactions_by_merchant,
)

load_dotenv()

# Holds the authenticated user's Plaid access token for the current request
plaid_token_ctx: ContextVar[str] = ContextVar('plaid_token')

_base_url = os.environ.get('BASE_URL', 'http://localhost:8080')
_host = urlparse(_base_url).netloc
_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=['127.0.0.1:*', 'localhost:*', '[::1]:*', _host],
)
mcp = FastMCP('plaid-mcp', transport_security=_security)


@mcp.tool()
def accounts() -> list:
    """Get all linked bank accounts with their type, subtype, and identifying info."""
    return get_accounts(plaid_token_ctx.get())


@mcp.tool()
def balances() -> list:
    """Get current and available balances for all accounts. For credit cards, also returns the credit limit."""
    return get_balances(plaid_token_ctx.get())


@mcp.tool()
def transactions(start_date: str, end_date: str, account_id: str = None) -> list:
    """
    Get full transaction history for a date range.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_id: Optional account ID to filter to a specific account
    """
    return get_transactions(start_date, end_date, account_id, plaid_token_ctx.get())


@mcp.tool()
def total_spending(start_date: str, end_date: str, account_id: str = None) -> dict:
    """
    Get total spending for a date range, broken down by category.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_id: Optional account ID to filter to a specific account
    """
    return get_total_spending(start_date, end_date, account_id, plaid_token_ctx.get())


@mcp.tool()
def transactions_by_category(start_date: str, end_date: str, category: str, account_id: str = None) -> list:
    """
    Get transactions filtered by Plaid personal finance category (e.g. FOOD_AND_DRINK, TRAVEL, SHOPPING).

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        category: Category to filter by (case-insensitive, partial match)
        account_id: Optional account ID to filter to a specific account
    """
    return get_transactions_by_category(start_date, end_date, category, account_id, plaid_token_ctx.get())


@mcp.tool()
def merchants(start_date: str, end_date: str, account_id: str = None) -> dict:
    """
    Get all unique merchants for a date range sorted by total spend. Use this to discover merchant names before filtering.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_id: Optional account ID to filter to a specific account
    """
    return get_merchants(start_date, end_date, account_id, plaid_token_ctx.get())


@mcp.tool()
def transactions_by_merchant(start_date: str, end_date: str, merchant: str, account_id: str = None) -> list:
    """
    Get transactions for a specific merchant. Matches against both merchant_name and raw transaction name.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        merchant: Merchant name to search for (case-insensitive, partial match)
        account_id: Optional account ID to filter to a specific account
    """
    return get_transactions_by_merchant(start_date, end_date, merchant, account_id, plaid_token_ctx.get())
