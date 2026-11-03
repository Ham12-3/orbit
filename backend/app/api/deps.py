"""Shared FastAPI dependencies."""

import secrets
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.run_tokens import RunPrincipal, RunTokenError, verify_run_token
from app.auth.supabase import SupabaseAuthError, SupabaseUnavailableError, SupabaseVerifier
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
    email: str | None = None


def _is_dev_token(token: str, settings: Settings) -> bool:
    expected = settings.dev_api_token
    return (
        settings.orbit_env == "development"
        and expected is not None
        and secrets.compare_digest(token, expected.get_secret_value())
    )


async def get_current_user(request: Request, settings: SettingsDep) -> CurrentUser:
    """Dashboard auth: a Supabase access token, or the dev token in development only."""
    token = bearer_token(request)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    if _is_dev_token(token, settings):
        return CurrentUser(id=settings.dev_user_id)

    verifier = cast(SupabaseVerifier | None, request.app.state.supabase_verifier)
    if verifier is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SUPABASE_URL is not set")
    try:
        claims = await verifier.verify(token)
    except SupabaseUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth is unavailable") from exc
    except SupabaseAuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    return CurrentUser(id=claims.user_id, email=claims.email)


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
