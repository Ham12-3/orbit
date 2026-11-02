"""FastAPI application factory. Run with: uvicorn app.main:create_app --factory"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import bots, health, runs
from app.config import Settings, get_settings
from app.db import Database
from app.events import EventSender, InngestEventSender
from app.internal import routes as internal
from app.llm_proxy import routes as llm_proxy
from app.logging_config import configure_logging
from app.runs.service import RunServices
from app.sandboxes.e2b import E2BSandboxProvider
from app.sandboxes.provider import SandboxProvider
from app.workflows import mount_inngest
from app.workflows.client import create_inngest_client


def create_app(
    settings: Settings | None = None,
    *,
    sandboxes: SandboxProvider | None = None,
    events: EventSender | None = None,
    llm_http: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Build the app. Tests pass fakes for the sandbox provider, events and upstream LLM."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    db = Database(
        settings.database_url,
        connect_timeout_s=settings.db_connect_timeout_s,
        command_timeout_s=settings.db_command_timeout_s,
    )
    inngest_client = create_inngest_client(settings)
    llm_http = llm_http or httpx.AsyncClient(
        timeout=httpx.Timeout(
            settings.llm_upstream_read_timeout_s,
            connect=settings.llm_upstream_connect_timeout_s,
        )
    )
    run_services = RunServices(
        db=db,
        sandboxes=sandboxes or E2BSandboxProvider(settings),
        events=events or InngestEventSender(inngest_client),
        settings=settings,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await llm_http.aclose()
        await db.dispose()

    app = FastAPI(title="Orbit API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.llm_http = llm_http
    app.state.events = run_services.events
    app.state.run_services = run_services

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(bots.router)
    app.include_router(runs.router)
    app.include_router(internal.router)
    app.include_router(llm_proxy.router)
    mount_inngest(app, inngest_client, run_services)
    return app
