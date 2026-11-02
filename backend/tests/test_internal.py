import uuid

from httpx import AsyncClient
from sqlalchemy import select, update

from app.db import Database
from app.events import RUN_FINISHED
from app.models import Run, RunEvent
from app.runs.service import RunServices
from tests.fakes import FakeSandboxProvider, RecordingEvents
from tests.test_run_lifecycle import load_run, started_run


async def _token(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> tuple[dict[str, str], str]:
    _, run_id = await started_run(client, services)
    token = sandboxes.sandboxes["sbx-1"].started[0]["envs"]["ORBIT_RUN_TOKEN"]
    return {"Authorization": f"Bearer {token}"}, run_id


async def test_runner_events_are_stored_once_per_seq(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    headers, run_id = await _token(client, services, sandboxes)
    body = {"events": [{"seq": 1, "type": "text", "payload": {"text": "hello"}}]}

    for _ in range(2):  # a retried POST
        response = await client.post(f"/internal/runs/{run_id}/events", json=body, headers=headers)
        assert response.status_code == 204, response.text

    async with db.session() as s:
        rows = list(await s.scalars(select(RunEvent).where(RunEvent.seq.is_not(None))))
    assert [(r.seq, r.type, r.payload) for r in rows] == [(1, "text", {"text": "hello"})]


async def test_a_token_cannot_write_to_another_run(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    headers, _ = await _token(client, services, sandboxes)
    other = uuid.uuid4()

    response = await client.post(
        f"/internal/runs/{other}/events",
        json={"events": [{"seq": 1, "type": "text", "payload": {}}]},
        headers=headers,
    )
    assert response.status_code == 403


async def test_completion_finishes_the_run_and_wakes_the_workflow(
    client: AsyncClient,
    services: RunServices,
    sandboxes: FakeSandboxProvider,
    events: RecordingEvents,
    db: Database,
) -> None:
    headers, run_id = await _token(client, services, sandboxes)

    response = await client.post(
        f"/internal/runs/{run_id}/complete",
        json={"status": "completed", "summary": "Done.", "session_id": "sess-1", "num_turns": 3},
        headers=headers,
    )

    assert response.status_code == 204, response.text
    run = await load_run(db, run_id)
    assert (run.status, run.final_summary, run.agent_session_id, run.num_turns) == (
        "completed",
        "Done.",
        "sess-1",
        3,
    )
    assert (RUN_FINISHED, {"run_id": run_id}) in events.sent


async def test_completion_keeps_a_more_specific_server_error(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    headers, run_id = await _token(client, services, sandboxes)
    async with db.session() as s:
        await s.execute(
            update(Run).where(Run.id == uuid.UUID(run_id)).values(error="Budget exhausted")
        )
        await s.commit()

    await client.post(
        f"/internal/runs/{run_id}/complete",
        json={"status": "failed", "error": "API status 403"},
        headers=headers,
    )

    run = await load_run(db, run_id)
    assert (run.status, run.error) == ("failed", "Budget exhausted")


async def test_completion_does_not_override_a_cancel(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    headers, run_id = await _token(client, services, sandboxes)
    async with db.session() as s:
        run = await s.get(Run, uuid.UUID(run_id))
        assert run is not None
        await services.cancel(s, run)

    response = await client.post(
        f"/internal/runs/{run_id}/complete", json={"status": "completed"}, headers=headers
    )

    assert response.status_code == 401  # cancelling revoked the token
    assert (await load_run(db, run_id)).status == "cancelled"
