import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text

from app.config import Settings
from app.db import Database
from app.llm_proxy import routes as llm_routes
from app.main import create_app
from app.models import Bot
from app.runs.service import RunServices
from tests.fakes import FakeSandboxProvider, RecordingEvents

DEV_TOKEN = "dev-token-for-tests"
AUTH = {"Authorization": f"Bearer {DEV_TOKEN}"}
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


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def sandboxes() -> FakeSandboxProvider:
    return FakeSandboxProvider()


@pytest.fixture
def events() -> RecordingEvents:
    return RecordingEvents()


@pytest.fixture
async def app(
    settings: Settings, upstream: Upstream, sandboxes: FakeSandboxProvider, events: RecordingEvents
) -> AsyncIterator[FastAPI]:
    application = create_app(
        settings,
        sandboxes=sandboxes,
        events=events,
        llm_http=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )
    db: Database = application.state.db
    async with db.engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE bots, runs, run_events, run_tokens, llm_usage RESTART IDENTITY CASCADE")
        )
    yield application
    await application.state.llm_http.aclose()
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


async def create_bot(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {"name": "Researcher", "job_description": "Research things.", **overrides}
    response = await client.post("/api/bots", json=body, headers=AUTH)
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
    await asyncio.gather(*list(llm_routes._background_tasks))
