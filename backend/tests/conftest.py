import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import inngest
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text

from app.background import drain
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import Bot
from app.runs.service import RunServices
from app.workflows.client import create_inngest_client
from tests.fakes import FakeSandboxProvider, FakeTitler, RecordingEvents

# --- A fake Supabase project: a real ES256 key pair whose public half is served as JWKS.
SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())
KEY_ID = "test-signing-key"
JWKS = {
    "keys": [
        {
            **jwt.algorithms.ECAlgorithm.to_jwk(SIGNING_KEY.public_key(), as_dict=True),
            "kid": KEY_ID,
            "alg": "ES256",
            "use": "sig",
        }
    ]
}

USER_A = uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a")
USER_B = uuid.UUID("bbbbbbbb-0000-4000-8000-00000000000b")


def supabase_token(user_id: uuid.UUID, **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "sub": str(user_id),
        "iss": ISSUER,
        "aud": "authenticated",
        "role": "authenticated",
        "email": f"{str(user_id)[:4]}@example.com",
        "iat": now,
        "exp": now + 3600,
    }
    key: Any = overrides.pop("key", SIGNING_KEY)
    algorithm: str = overrides.pop("algorithm", "ES256")
    kid: str = overrides.pop("kid", KEY_ID)
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


AUTH = {"Authorization": f"Bearer {supabase_token(USER_A)}"}
AUTH_B = {"Authorization": f"Bearer {supabase_token(USER_B)}"}

DEV_TOKEN = "dev-token-for-tests"
SECRETS = {
    "anthropic_api_key": "sk-ant-REAL-KEY-must-never-reach-a-sandbox",
    "e2b_api_key": "e2b_REAL_KEY_must_never_reach_a_sandbox",
    "run_token_secret": "run-token-signing-secret-for-tests-0123456789",
    "dev_api_token": DEV_TOKEN,
}


@pytest.fixture
def settings() -> Settings:
    """Test settings: never read the developer's .env, always use the test database."""
    base = Settings(_env_file=None)
    return base.model_copy(
        update={
            "orbit_env": "test",
            "database_url": base.test_database_url,
            "inngest_dev": True,
            "public_base_url": "https://orbit.example.test",
            "supabase_url": SUPABASE_URL,
            **{name: SecretStr(value) for name, value in SECRETS.items()},
        }
    )


@dataclass
class Upstream:
    """The fake Anthropic API. Tests set `handler` and inspect `requests`."""

    requests: list[httpx.Request] = field(default_factory=list)
    handler: Callable[[httpx.Request], httpx.Response] = lambda _: httpx.Response(500)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


@dataclass
class JwksServer:
    """The fake Supabase JWKS endpoint."""

    calls: int = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url == f"{ISSUER}/.well-known/jwks.json"
        self.calls += 1
        return httpx.Response(200, json=JWKS)


@pytest.fixture(scope="session")
def inngest_client() -> inngest.Inngest:
    """Built once: each Inngest client creates HTTP clients, and SSL setup is slow on Windows."""
    return create_inngest_client(Settings(_env_file=None, inngest_dev=True))


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def jwks() -> JwksServer:
    return JwksServer()


@pytest.fixture
def sandboxes() -> FakeSandboxProvider:
    return FakeSandboxProvider()


@pytest.fixture
def events() -> RecordingEvents:
    return RecordingEvents()


@pytest.fixture
def titler() -> FakeTitler:
    return FakeTitler()


@pytest.fixture
async def app(
    settings: Settings,
    upstream: Upstream,
    jwks: JwksServer,
    sandboxes: FakeSandboxProvider,
    events: RecordingEvents,
    titler: FakeTitler,
    inngest_client: inngest.Inngest,
) -> AsyncIterator[FastAPI]:
    application = create_app(
        settings,
        sandboxes=sandboxes,
        events=events,
        llm_http=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        auth_http=httpx.AsyncClient(transport=httpx.MockTransport(jwks)),
        titler=titler,
        inngest_client=inngest_client,
    )
    db: Database = application.state.db
    async with db.engine.begin() as conn:
        # Every table hangs off bots with ON DELETE CASCADE; DELETE is far faster than
        # TRUNCATE on these tiny tables.
        await conn.execute(text("DELETE FROM bots"))
        await conn.execute(text("ALTER TABLE run_events ALTER COLUMN id RESTART WITH 1"))
    yield application
    await drain()
    await db.dispose()


@pytest.fixture
def db(app: FastAPI) -> Database:
    database: Database = app.state.db
    return database


@pytest.fixture
def services(app: FastAPI) -> RunServices:
    run_services: RunServices = app.state.run_services
    return run_services


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def create_bot(
    client: AsyncClient, *, headers: dict[str, str] | None = None, **overrides: Any
) -> dict[str, Any]:
    body = {"name": "Researcher", "job_description": "Research things.", **overrides}
    response = await client.post("/api/bots", json=body, headers=headers or AUTH)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def get_bot(db: Database, bot_id: Any) -> Bot:
    async with db.session() as session:
        bot = await session.get(Bot, bot_id)
        assert bot is not None
        return bot


async def flush_usage_writes() -> None:
    """The proxy records usage in background tasks; wait for them."""
    await drain()
