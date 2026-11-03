"""Dashboard routes for runs. Every query is scoped to the current user through the bot."""

import uuid
from collections.abc import AsyncIterable
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, DatabaseDep, RunServicesDep, SessionDep, SettingsDep
from app.auth.stream_tickets import StreamTicketError, issue_stream_ticket, verify_stream_ticket
from app.models import Bot, Run, RunEvent
from app.runs.service import RunStateError
from app.runs.stream import run_stream
from app.schemas.runs import RunDetail, RunEventRead, RunRead, StreamTicketRead

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> RunDetail:
    run = await get_owned_run(session, user.id, run_id)
    events = await session.scalars(
        select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.id)
    )
    return RunDetail(
        **RunRead.model_validate(run).model_dump(),
        events=[RunEventRead.model_validate(event) for event in events],
    )


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: uuid.UUID, user: CurrentUserDep, session: SessionDep, runs: RunServicesDep
) -> RunRead:
    run = await get_owned_run(session, user.id, run_id)
    try:
        run = await runs.cancel(session, run)
    except RunStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return RunRead.model_validate(run)


@router.post("/{run_id}/stream-ticket")
async def create_stream_ticket(
    run_id: uuid.UUID, user: CurrentUserDep, session: SessionDep, settings: SettingsDep
) -> StreamTicketRead:
    await get_owned_run(session, user.id, run_id)
    ticket = issue_stream_ticket(
        secret=_ticket_secret(settings.run_token_secret),
        user_id=user.id,
        run_id=run_id,
        ttl=timedelta(seconds=settings.stream_ticket_ttl_s),
    )
    return StreamTicketRead(ticket=ticket.token, expires_at=ticket.expires_at)


async def require_stream_access(
    run_id: uuid.UUID,
    ticket: Annotated[str, Query(min_length=1)],
    db: DatabaseDep,
    settings: SettingsDep,
) -> None:
    """Runs before the response starts, so a bad ticket is a plain 401/404, not a stream."""
    try:
        user_id = verify_stream_ticket(
            secret=_ticket_secret(settings.run_token_secret), token=ticket, run_id=run_id
        )
    except StreamTicketError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired ticket") from exc
    async with db.session() as session:  # not held open for the stream's lifetime
        await get_owned_run(session, user_id, run_id)


@router.get(
    "/{run_id}/stream",
    response_class=EventSourceResponse,
    dependencies=[Depends(require_stream_access)],
)
async def stream_run(
    run_id: uuid.UUID,
    db: DatabaseDep,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    async for event in run_stream(db, run_id, after_event_id=last_event_id or 0):
        yield event


async def get_owned_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = await session.scalar(
        select(Run).join(Bot, Bot.id == Run.bot_id).where(Run.id == run_id, Bot.user_id == user_id)
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run


def _ticket_secret(secret: SecretStr | None) -> str:
    if secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "RUN_TOKEN_SECRET is not set")
    return secret.get_secret_value()
