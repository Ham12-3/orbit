"""Dashboard routes for runs. Every query is scoped to the current user through the bot."""

import uuid
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, DatabaseDep, RunServicesDep, SessionDep
from app.models import Bot, Run, RunEvent
from app.runs.service import RunStateError
from app.runs.stream import run_stream
from app.schemas.runs import RunDetail, RunEventRead, RunRead

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


async def require_stream_access(run_id: uuid.UUID, user: CurrentUserDep, db: DatabaseDep) -> None:
    """Runs before the response starts, so a bad request is a plain 401/404, not a stream."""
    async with db.session() as session:  # not held open for the stream's lifetime
        await get_owned_run(session, user.id, run_id)


@router.get(
    "/{run_id}/stream",
    response_class=EventSourceResponse,
    dependencies=[Depends(require_stream_access)],
)
async def stream_run(
    run_id: uuid.UUID,
    db: DatabaseDep,
    last_event_id: Annotated[int | None, Header()] = None,
    after: Annotated[int | None, Query(ge=0)] = None,
) -> AsyncIterable[ServerSentEvent]:
    # Browsers send Last-Event-ID on automatic reconnects; `after` is for manual ones (a new
    # EventSource cannot set headers).
    start = last_event_id if last_event_id is not None else (after or 0)
    async for event in run_stream(db, run_id, after_event_id=start):
        yield event


async def get_owned_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = await session.scalar(
        select(Run).join(Bot, Bot.id == Run.bot_id).where(Run.id == run_id, Bot.user_id == user_id)
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run
