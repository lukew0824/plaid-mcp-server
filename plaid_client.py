import os
from datetime import date, datetime, timezone
from dotenv import load_dotenv
import plaid
from plaid.api import plaid_api
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.accounts_balance_get_request_options import AccountsBalanceGetRequestOptions
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

load_dotenv()

_ENV = os.environ.get('PLAID_ENV', 'sandbox').lower()
_PLAID_HOSTS = {
    'sandbox': plaid.Environment.Sandbox,
    'production': plaid.Environment.Production,
}
_SECRETS = {
    'sandbox': os.environ.get('PLAID_SANDBOX_SECRET'),
    'production': os.environ.get('PLAID_PRODUCTION_SECRET'),
}

_configuration = plaid.Configuration(
    host=_PLAID_HOSTS[_ENV],
    api_key={
        'clientId': os.environ['PLAID_CLIENT_ID'],
        'secret': _SECRETS[_ENV],
    }
)
_api_client = plaid.ApiClient(_configuration)
_client = plaid_api.PlaidApi(_api_client)


def _fetch_all(start_date: str, end_date: str, account_id: str, access_token: str):
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    transactions = []
    offset = 0

    while True:
        opts_kwargs = {'count': 500, 'offset': offset}
        if account_id:
            opts_kwargs['account_ids'] = [account_id]

        response = _client.transactions_get(
            TransactionsGetRequest(
                access_token=access_token,
                start_date=start,
                end_date=end,
                options=TransactionsGetRequestOptions(**opts_kwargs),
            )
        )
        transactions.extend(response.transactions)

        if len(transactions) >= response.total_transactions:
            break
        offset += len(response.transactions)

    return transactions


def _format(t) -> dict:
    loc = t.location
    pm = t.payment_meta
    pfc = t.personal_finance_category
    return {
        'transaction_id': t.transaction_id,
        'account_id': t.account_id,
        'date': str(t.date),
        'authorized_date': str(t.authorized_date) if t.authorized_date else None,
        'name': t.name,
        'merchant_name': t.merchant_name,
        'amount': t.amount,
        'currency': t.iso_currency_code,
        'payment_channel': t.payment_channel if t.payment_channel else None,
        'category': t.category,
        'category_id': t.category_id,
        'pending': t.pending,
        'pending_transaction_id': t.pending_transaction_id,
        'transaction_type': t.transaction_type if t.transaction_type else None,
        'transaction_code': t.transaction_code,
        'website': t.website,
        'logo_url': t.logo_url,
        'location': {
            'address': loc.address,
            'city': loc.city,
            'region': loc.region,
            'postal_code': loc.postal_code,
            'country': loc.country,
            'lat': loc.lat,
            'lon': loc.lon,
        } if loc else None,
        'payment_meta': {
            'reference_number': pm.reference_number,
            'ppd_id': pm.ppd_id,
            'payee': pm.payee,
            'payer': pm.payer,
            'payment_method': pm.payment_method,
            'payment_processor': pm.payment_processor,
            'reason': pm.reason,
            'by_order_of': pm.by_order_of,
        } if pm else None,
        'personal_finance_category': {
            'primary': pfc.primary,
            'detailed': pfc.detailed,
        } if pfc else None,
    }


def get_accounts(access_token: str):
    response = _client.accounts_get(AccountsGetRequest(access_token=access_token))
    return [
        {
            'account_id': a.account_id,
            'name': a.name,
            'official_name': a.official_name,
            'type': a.type,
            'subtype': a.subtype if a.subtype else None,
            'mask': a.mask,
        }
        for a in response.accounts
    ]


def get_balances(access_token: str):
    response = _client.accounts_balance_get(AccountsBalanceGetRequest(
        access_token=access_token,
        options=AccountsBalanceGetRequestOptions(
            min_last_updated_datetime=datetime(2020, 1, 1, tzinfo=timezone.utc),
        ),
    ))
    return [
        {
            'account_id': a.account_id,
            'name': a.name,
            'type': a.type,
            'subtype': a.subtype if a.subtype else None,
            'available': a.balances.available,
            'current': a.balances.current,
            'limit': a.balances.limit,
            'currency': a.balances.iso_currency_code,
        }
        for a in response.accounts
    ]


def get_transactions(start_date: str, end_date: str, account_id: str, access_token: str):
    return [_format(t) for t in _fetch_all(start_date, end_date, account_id, access_token)]


def get_total_spending(start_date: str, end_date: str, account_id: str, access_token: str):
    transactions = _fetch_all(start_date, end_date, account_id, access_token)
    # Positive amounts in Plaid = money out (debits). Exclude pending and credits.
    debits = [t for t in transactions if t.amount > 0 and not t.pending]

    total = round(sum(t.amount for t in debits), 2)

    by_category = {}
    for t in debits:
        category = t.personal_finance_category.primary if t.personal_finance_category else 'UNCATEGORIZED'
        by_category[category] = round(by_category.get(category, 0) + t.amount, 2)

    by_category = dict(sorted(by_category.items(), key=lambda x: x[1], reverse=True))

    return {
        'total': total,
        'transaction_count': len(debits),
        'by_category': by_category,
    }


def get_transactions_by_category(start_date: str, end_date: str, category: str, account_id: str, access_token: str):
    transactions = _fetch_all(start_date, end_date, account_id, access_token)
    category_upper = category.upper()
    filtered = [
        t for t in transactions
        if t.personal_finance_category and category_upper in t.personal_finance_category.primary.upper()
    ]
    return [_format(t) for t in filtered]


def get_merchants(start_date: str, end_date: str, account_id: str, access_token: str):
    transactions = _fetch_all(start_date, end_date, account_id, access_token)
    merchants = {}
    for t in transactions:
        name = t.merchant_name or t.name
        if name:
            if name not in merchants:
                merchants[name] = {'transaction_count': 0, 'total_spent': 0.0}
            merchants[name]['transaction_count'] += 1
            if t.amount > 0:
                merchants[name]['total_spent'] = round(merchants[name]['total_spent'] + t.amount, 2)

    return dict(sorted(merchants.items(), key=lambda x: x[1]['total_spent'], reverse=True))


def get_transactions_by_merchant(start_date: str, end_date: str, merchant: str, account_id: str, access_token: str):
    transactions = _fetch_all(start_date, end_date, account_id, access_token)
    merchant_lower = merchant.lower()
    filtered = [
        t for t in transactions
        if (t.merchant_name and merchant_lower in t.merchant_name.lower())
        or (t.name and merchant_lower in t.name.lower())
    ]
    return [_format(t) for t in filtered]
