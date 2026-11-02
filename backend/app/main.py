"""FastAPI application factory. Run with: uvicorn app.main:create_app --factory"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.config import Settings, get_settings
from app.db import Database
from app.logging_config import configure_logging
from app.workflows import mount_inngest


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    db = Database(
        settings.database_url,
        connect_timeout_s=settings.db_connect_timeout_s,
        command_timeout_s=settings.db_command_timeout_s,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await db.dispose()

    app = FastAPI(title="Orbit API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    mount_inngest(app, settings)
    return app
