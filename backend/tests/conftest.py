from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Test settings: never read the developer's .env, always use the test database."""
    base = Settings(_env_file=None)
    return base.model_copy(
        update={
            "orbit_env": "test",
            "database_url": base.test_database_url,
            "inngest_dev": True,
        }
    )


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await app.state.db.dispose()
