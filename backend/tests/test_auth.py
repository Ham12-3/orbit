"""Single-user mode: one local user, behind LOCAL_API_TOKEN."""

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from tests.conftest import AUTH, USER_A
from tests.fakes import FakeSandboxProvider, RecordingEvents


async def test_the_token_identifies_the_local_user(client: AsyncClient) -> None:
    response = await client.get("/api/me", headers=AUTH)

    assert response.status_code == 200, response.text
    assert response.json() == {"id": str(USER_A)}


async def test_requests_without_the_token_are_refused(client: AsyncClient) -> None:
    assert (await client.get("/api/bots")).status_code == 401
    wrong = {"Authorization": "Bearer not-the-token"}
    assert (await client.get("/api/bots", headers=wrong)).status_code == 401


async def test_missing_token_config_is_a_clear_503(settings: Settings) -> None:
    unconfigured = settings.model_copy(update={"local_api_token": None})
    app = create_app(unconfigured, sandboxes=FakeSandboxProvider(), events=RecordingEvents())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/me", headers=AUTH)
    await app.state.db.dispose()

    assert response.status_code == 503
