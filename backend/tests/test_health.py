from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_returns_ok_when_database_is_up(client: AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_ready_returns_503_when_database_is_down(settings: Settings) -> None:
    unreachable = settings.model_copy(
        update={
            "database_url": "postgresql+asyncpg://orbit:orbit@127.0.0.1:1/orbit",
            "db_connect_timeout_s": 1.0,
        }
    )
    app = create_app(unreachable)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
