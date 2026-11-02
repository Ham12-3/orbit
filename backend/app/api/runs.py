"""Dashboard routes for runs. Every query is scoped to the current user through the bot."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, RunServicesDep, SessionDep
from app.models import Bot, Run, RunEvent
from app.runs.service import RunStateError
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


async def get_owned_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = await session.scalar(
        select(Run).join(Bot, Bot.id == Run.bot_id).where(Run.id == run_id, Bot.user_id == user_id)
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run
