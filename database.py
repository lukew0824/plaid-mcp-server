import os
from contextlib import contextmanager
from datetime import datetime
from typing import Optional
from sqlmodel import Field, Session, SQLModel, create_engine
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///./plaid_mcp.db')
engine = create_engine(
    DATABASE_URL,
    **({"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {})
)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    google_id: str = Field(unique=True)
    email: str = Field(unique=True)


class PlaidToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key='user.id')
    access_token: str


class OAuthPendingRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(unique=True)
    client_id: str
    redirect_uri: str
    code_challenge: str
    state: str
    browser_binding_hash: str
    expires_at: datetime


class OAuthAuthCode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True)
    user_id: int = Field(foreign_key='user.id')
    client_id: str
    redirect_uri: str
    code_challenge: str
    state: str
    expires_at: datetime


class OAuthToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(unique=True)
    user_id: int = Field(foreign_key='user.id')
    expires_at: datetime


def init_db():
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_db():
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
