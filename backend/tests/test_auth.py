"""Supabase access-token verification and the development-only dev token."""

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import AUTH, DEV_TOKEN, USER_A, JwksServer, supabase_token
from tests.fakes import FakeSandboxProvider, RecordingEvents


async def test_valid_token_identifies_the_user(client: AsyncClient) -> None:
    response = await client.get("/api/me", headers=AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(USER_A)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"exp": 1}, id="expired"),
        pytest.param({"iss": "https://other-project.supabase.co/auth/v1"}, id="wrong-issuer"),
        pytest.param({"aud": "someone-else"}, id="wrong-audience"),
        pytest.param({"role": "anon"}, id="not-signed-in"),
        pytest.param({"kid": "unknown-key"}, id="unknown-key"),
        pytest.param({"key": ec.generate_private_key(ec.SECP256R1())}, id="forged-signature"),
        pytest.param(
            {"key": "a-shared-secret-of-at-least-32-bytes!!", "algorithm": "HS256"},
            id="legacy-hs256",
        ),
    ],
)
async def test_bad_tokens_are_rejected(client: AsyncClient, overrides: dict[str, object]) -> None:
    token = supabase_token(USER_A, **overrides)
    response = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_signing_keys_are_cached(client: AsyncClient, jwks: JwksServer) -> None:
    for _ in range(3):
        assert (await client.get("/api/me", headers=AUTH)).status_code == 200
    assert jwks.calls == 1


async def test_dev_token_is_refused_outside_development(client: AsyncClient) -> None:
    response = await client.get("/api/me", headers={"Authorization": f"Bearer {DEV_TOKEN}"})
    assert response.status_code == 401


async def test_dev_token_works_in_development(settings: Settings) -> None:
    dev = settings.model_copy(update={"orbit_env": "development"})
    app = create_app(
        dev,
        sandboxes=FakeSandboxProvider(),
        events=RecordingEvents(),
        auth_http=httpx.AsyncClient(transport=httpx.MockTransport(JwksServer())),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/me", headers={"Authorization": f"Bearer {DEV_TOKEN}"})
    await app.state.db.dispose()

    assert response.status_code == 200
    assert response.json()["id"] == str(dev.dev_user_id)


async def test_missing_supabase_config_is_a_clear_503(settings: Settings) -> None:
    unconfigured = settings.model_copy(update={"supabase_url": ""})
    app = create_app(unconfigured, sandboxes=FakeSandboxProvider(), events=RecordingEvents())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/me", headers=AUTH)
    await app.state.db.dispose()

    assert response.status_code == 503
