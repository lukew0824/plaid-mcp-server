import hashlib
import os
import secrets
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import plaid
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from sqlmodel import select
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv

from database import (
    init_db, get_db,
    User, PlaidToken, OAuthPendingRequest, OAuthAuthCode, OAuthToken,
)

load_dotenv()

ALLOWED_EMAIL = os.environ['ALLOWED_EMAIL']
GOOGLE_CLIENT_ID = os.environ['GOOGLE_CLIENT_ID']
GOOGLE_CLIENT_SECRET = os.environ['GOOGLE_CLIENT_SECRET']
BASE_URL = os.environ.get('BASE_URL', 'http://localhost:8080')

_ENV = os.environ.get('PLAID_ENV', 'production').lower()
_plaid_config = plaid.Configuration(
    host=plaid.Environment.Sandbox if _ENV == 'sandbox' else plaid.Environment.Production,
    api_key={
        'clientId': os.environ['PLAID_CLIENT_ID'],
        'secret': os.environ.get('PLAID_SANDBOX_SECRET') if _ENV == 'sandbox' else os.environ.get('PLAID_PRODUCTION_SECRET'),
    }
)
_plaid_client = plaid_api.PlaidApi(plaid.ApiClient(_plaid_config))


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


from tools import mcp, plaid_token_ctx


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    async with mcp.session_manager.run():
        yield

app = FastAPI(lifespan=lifespan)


# ── OAuth 2.1 discovery ────────────────────────────────────────────────────

@app.get('/.well-known/oauth-protected-resource')
@app.get('/.well-known/oauth-protected-resource/mcp')
async def oauth_protected_resource():
    return {
        'resource': f'{BASE_URL}/mcp',
        'authorization_servers': [BASE_URL],
        'bearer_methods_supported': ['header'],
        'scopes_supported': ['mcp'],
    }


@app.get('/.well-known/oauth-authorization-server')
async def oauth_metadata():
    return {
        'issuer': BASE_URL,
        'authorization_endpoint': f'{BASE_URL}/oauth/authorize',
        'token_endpoint': f'{BASE_URL}/oauth/token',
        'registration_endpoint': f'{BASE_URL}/oauth/register',
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code'],
        'code_challenge_methods_supported': ['S256'],
        'token_endpoint_auth_methods_supported': ['none'],
        'scopes_supported': ['mcp'],
    }


@app.post('/oauth/register')
async def oauth_register(request: Request):
    body = await request.json()
    return JSONResponse({
        'client_id': secrets.token_urlsafe(16),
        'client_id_issued_at': int(utcnow().timestamp()),
        'redirect_uris': body.get('redirect_uris', []),
        'token_endpoint_auth_method': 'none',
        'grant_types': ['authorization_code'],
        'response_types': ['code'],
    }, status_code=201)


# ── Step 1: Claude.ai sends user here ─────────────────────────────────────

@app.get('/oauth/authorize')
async def oauth_authorize(
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str = 'S256',
):
    if response_type != 'code':
        raise HTTPException(400, 'Only authorization_code flow supported')
    if code_challenge_method != 'S256':
        raise HTTPException(400, 'Only S256 PKCE supported')

    session_id = secrets.token_urlsafe(32)
    with get_db() as db:
        db.add(OAuthPendingRequest(
            session_id=session_id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            state=state,
            expires_at=utcnow() + timedelta(minutes=10),
        ))
        db.commit()

    google_params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': f'{BASE_URL}/auth/google/callback',
        'response_type': 'code',
        'scope': 'openid email',
        'state': session_id,
    }
    return RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(google_params))


# ── Step 2: Google redirects back here ────────────────────────────────────

@app.get('/auth/google/callback')
async def google_callback(code: str, state: str):
    with get_db() as db:
        pending = db.exec(
            select(OAuthPendingRequest).where(
                OAuthPendingRequest.session_id == state,
                OAuthPendingRequest.expires_at > utcnow(),
            )
        ).first()

        if not pending:
            raise HTTPException(400, 'Invalid or expired session')

        async with httpx.AsyncClient() as http:
            token_res = await http.post('https://oauth2.googleapis.com/token', data={
                'code': code,
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
                'redirect_uri': f'{BASE_URL}/auth/google/callback',
                'grant_type': 'authorization_code',
            })
            google_token = token_res.json()

            userinfo_res = await http.get(
                'https://www.googleapis.com/oauth2/v3/userinfo',
                headers={'Authorization': f"Bearer {google_token['access_token']}"},
            )
            userinfo = userinfo_res.json()

        email = userinfo.get('email')
        google_id = userinfo.get('sub')

        if email != ALLOWED_EMAIL:
            raise HTTPException(403, 'Not authorized')

        user = db.exec(select(User).where(User.google_id == google_id)).first()
        if not user:
            user = User(google_id=google_id, email=email)
            db.add(user)
            db.commit()
            db.refresh(user)

        plaid_token = db.exec(select(PlaidToken).where(PlaidToken.user_id == user.id)).first()
        if not plaid_token:
            return RedirectResponse(f'/plaid/link?session={pending.session_id}')

        return _issue_auth_code(db, user, pending)


# ── Plaid Link onboarding ──────────────────────────────────────────────────

@app.get('/plaid/link')
async def plaid_link_page(session: str):
    link_token_res = _plaid_client.link_token_create(LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id='local-user'),
        client_name='plaid-mcp',
        products=[Products('transactions')],
        country_codes=[CountryCode('US')],
        language='en',
    ))
    link_token = link_token_res.link_token

    return HTMLResponse(f'''
<!DOCTYPE html>
<html>
<head><title>Connect your bank</title></head>
<body>
  <h2>One more step — connect your bank</h2>
  <button id="link-btn">Connect with Plaid</button>
  <p id="status"></p>
  <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
  <script>
    const handler = Plaid.create({{
      token: '{link_token}',
      onSuccess: async (public_token) => {{
        document.getElementById('status').textContent = 'Connecting...';
        const res = await fetch('/plaid/exchange', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{ public_token, session: '{session}' }})
        }});
        const data = await res.json();
        if (data.redirect) window.location.href = data.redirect;
      }},
      onExit: (err) => {{
        if (err) document.getElementById('status').textContent = 'Error: ' + err.display_message;
      }}
    }});
    document.getElementById('link-btn').onclick = () => handler.open();
  </script>
</body>
</html>
''')


@app.post('/plaid/exchange')
async def plaid_exchange(request: Request):
    body = await request.json()
    public_token = body['public_token']
    session_id = body['session']

    with get_db() as db:
        pending = db.exec(
            select(OAuthPendingRequest).where(
                OAuthPendingRequest.session_id == session_id,
                OAuthPendingRequest.expires_at > utcnow(),
            )
        ).first()

        if not pending:
            raise HTTPException(400, 'Invalid or expired session')

        exchange_res = _plaid_client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )

        user = db.exec(select(User).where(User.email == ALLOWED_EMAIL)).first()
        existing = db.exec(select(PlaidToken).where(PlaidToken.user_id == user.id)).first()
        if existing:
            existing.access_token = exchange_res.access_token
            db.add(existing)
        else:
            db.add(PlaidToken(user_id=user.id, access_token=exchange_res.access_token))
        db.commit()

        redirect_url = _issue_auth_code(db, user, pending, return_url=True)
        return JSONResponse({'redirect': redirect_url})


# ── Step 3: Claude.ai exchanges auth code for token ───────────────────────

@app.post('/oauth/token')
async def oauth_token(
    grant_type: str = Form(),
    code: str = Form(),
    redirect_uri: str = Form(),
    client_id: str = Form(),
    code_verifier: str = Form(),
):
    if grant_type != 'authorization_code':
        raise HTTPException(400, 'Unsupported grant type')

    with get_db() as db:
        auth_code = db.exec(
            select(OAuthAuthCode).where(
                OAuthAuthCode.code == code,
                OAuthAuthCode.expires_at > utcnow(),
            )
        ).first()

        if not auth_code:
            raise HTTPException(400, 'Invalid or expired code')

        if auth_code.redirect_uri != redirect_uri:
            raise HTTPException(400, 'redirect_uri mismatch')

        computed = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b'=').decode()

        if computed != auth_code.code_challenge:
            raise HTTPException(400, 'PKCE verification failed')

        access_token = secrets.token_urlsafe(32)
        db.add(OAuthToken(
            token=access_token,
            user_id=auth_code.user_id,
            expires_at=utcnow() + timedelta(days=30),
        ))
        db.delete(auth_code)
        db.commit()

        return {
            'access_token': access_token,
            'token_type': 'bearer',
            'expires_in': 30 * 24 * 3600,
        }


# ── Helpers ────────────────────────────────────────────────────────────────

def _issue_auth_code(db, user, pending: OAuthPendingRequest, return_url: bool = False):
    code = secrets.token_urlsafe(32)
    db.add(OAuthAuthCode(
        code=code,
        user_id=user.id,
        client_id=pending.client_id,
        redirect_uri=pending.redirect_uri,
        code_challenge=pending.code_challenge,
        state=pending.state,
        expires_at=utcnow() + timedelta(minutes=5),
    ))
    db.delete(pending)
    db.commit()

    url = f'{pending.redirect_uri}?code={code}&state={pending.state}'
    return url if return_url else RedirectResponse(url)


# ── MCP mounting + auth middleware ─────────────────────────────────────────


class MCPAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith('/mcp'):
            resource_metadata = f'{BASE_URL}/.well-known/oauth-protected-resource'
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return JSONResponse(
                    {'error': 'unauthorized'},
                    status_code=401,
                    headers={'WWW-Authenticate': f'Bearer realm="{BASE_URL}", resource_metadata="{resource_metadata}"'},
                )

            token = auth_header[7:]
            with get_db() as db:
                oauth_token = db.exec(
                    select(OAuthToken).where(
                        OAuthToken.token == token,
                        OAuthToken.expires_at > utcnow(),
                    )
                ).first()

                if not oauth_token:
                    return JSONResponse(
                        {'error': 'invalid_token'},
                        status_code=401,
                        headers={'WWW-Authenticate': f'Bearer error="invalid_token", resource_metadata="{resource_metadata}"'},
                    )

                plaid_token = db.exec(
                    select(PlaidToken).where(PlaidToken.user_id == oauth_token.user_id)
                ).first()

                if not plaid_token:
                    return JSONResponse({'error': 'no_plaid_token'}, status_code=403)

                plaid_token_ctx.set(plaid_token.access_token)

        return await call_next(request)


app.add_middleware(MCPAuthMiddleware)
app.mount('/', mcp.streamable_http_app())


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8080)
