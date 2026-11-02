"""Runner callbacks. Run-token auth only; a token can only write to its own run."""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import RunPrincipalDep, RunServicesDep, SessionDep
from app.auth.run_tokens import RunPrincipal
from app.runs.timeline import add_runner_events
from app.schemas.runs import RunnerCompletion, RunnerEvents

router = APIRouter(prefix="/internal", tags=["internal"])


def _own_run(principal: RunPrincipal, run_id: uuid.UUID) -> None:
    if principal.run_id != run_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token is not valid for this run")


@router.post("/runs/{run_id}/events", status_code=status.HTTP_204_NO_CONTENT)
async def post_events(
    run_id: uuid.UUID, body: RunnerEvents, principal: RunPrincipalDep, session: SessionDep
) -> None:
    _own_run(principal, run_id)
    await add_runner_events(
        session, run_id, [(event.seq, event.type, event.payload) for event in body.events]
    )
    await session.commit()


@router.post("/runs/{run_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_run(
    run_id: uuid.UUID,
    body: RunnerCompletion,
    principal: RunPrincipalDep,
    session: SessionDep,
    runs: RunServicesDep,
) -> None:
    _own_run(principal, run_id)
    await runs.complete_from_runner(
        session,
        run_id,
        succeeded=body.status == "completed",
        summary=body.summary,
        error=body.error,
        agent_session_id=body.session_id,
        num_turns=body.num_turns,
    )
