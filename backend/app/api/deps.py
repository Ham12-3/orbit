"""Shared FastAPI dependencies."""

import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.run_tokens import RunPrincipal, RunTokenError, verify_run_token
from app.config import Settings
from app.db import Database
from app.events import EventSender
from app.runs.service import RunServices


def get_db(request: Request) -> Database:
    return cast(Database, request.app.state.db)


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_events(request: Request) -> EventSender:
    return cast(EventSender, request.app.state.events)


def get_run_services(request: Request) -> RunServices:
    return cast(RunServices, request.app.state.run_services)


DatabaseDep = Annotated[Database, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
EventsDep = Annotated[EventSender, Depends(get_events)]
RunServicesDep = Annotated[RunServices, Depends(get_run_services)]


async def get_session(db: DatabaseDep) -> AsyncIterator[AsyncSession]:
    async with db.session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def bearer_token(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and value:
        return value.strip()
    return request.headers.get("x-api-key") or None


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID


def get_current_user(request: Request, settings: SettingsDep) -> CurrentUser:
    """Single-user mode: one local user, behind LOCAL_API_TOKEN (see config).

    Queries still filter by user id, so real accounts can replace this one function later.
    """
    expected = settings.local_api_token
    if expected is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "LOCAL_API_TOKEN is not set (run make install)"
        )
    provided = bearer_token(request)
    if provided is None or not secrets.compare_digest(provided, expected.get_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API token")
    return CurrentUser(id=settings.local_user_id)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


async def authenticate_run(
    request: Request, session: AsyncSession, settings: Settings
) -> RunPrincipal | None:
    token = bearer_token(request)
    if token is None or settings.run_token_secret is None:
        return None
    try:
        return await verify_run_token(
            session, secret=settings.run_token_secret.get_secret_value(), token=token
        )
    except RunTokenError:
        return None


async def require_run(request: Request, session: SessionDep, settings: SettingsDep) -> RunPrincipal:
    principal = await authenticate_run(request, session, settings)
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked run token")
    return principal


RunPrincipalDep = Annotated[RunPrincipal, Depends(require_run)]
