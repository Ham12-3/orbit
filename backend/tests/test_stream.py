"""Live run timeline over SSE, with stream tickets."""

import json
import logging
import uuid

from httpx import AsyncClient
from sqlalchemy import update

from app.db import Database
from app.logging_config import _RedactStreamTickets
from app.models import Run
from app.models.enums import RunEventType, RunStatus
from app.runs.timeline import add_runner_events
from tests.conftest import AUTH, create_bot


def parse_sse(body: str) -> list[dict[str, str]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            name, _, value = line.partition(":")
            fields[name] = value.removeprefix(" ")
        if fields:
            events.append(fields)
    return events


async def finished_run_with_events(client: AsyncClient, db: Database) -> str:
    bot = await create_bot(client)
    run_id: str = (
        await client.post(f"/api/bots/{bot['id']}/runs", json={"prompt": "x"}, headers=AUTH)
    ).json()["id"]
    async with db.session() as s:
        await add_runner_events(
            s,
            uuid.UUID(run_id),
            [
                (1, RunEventType.TEXT, {"text": "Working on it"}),
                (2, RunEventType.TOOL_USE, {"id": "t1", "name": "Bash", "input": {}}),
            ],
        )
        await s.execute(
            update(Run).where(Run.id == uuid.UUID(run_id)).values(status=RunStatus.COMPLETED)
        )
        await s.commit()
    return run_id


async def ticket_for(client: AsyncClient, run_id: str) -> str:
    response = await client.post(f"/api/runs/{run_id}/stream-ticket", headers=AUTH)
    assert response.status_code == 200, response.text
    ticket: str = response.json()["ticket"]
    return ticket


async def test_stream_sends_events_then_the_run_then_end(client: AsyncClient, db: Database) -> None:
    run_id = await finished_run_with_events(client, db)

    response = await client.get(
        f"/api/runs/{run_id}/stream", params={"ticket": await ticket_for(client, run_id)}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [e["event"] for e in events] == ["run_event", "run_event", "run", "end"]
    assert [e.get("id") for e in events[:2]] == ["1", "2"]
    assert json.loads(events[0]["data"])["payload"] == {"text": "Working on it"}
    assert json.loads(events[2]["data"])["status"] == "completed"


async def test_reconnect_resumes_after_last_event_id(client: AsyncClient, db: Database) -> None:
    run_id = await finished_run_with_events(client, db)

    response = await client.get(
        f"/api/runs/{run_id}/stream",
        params={"ticket": await ticket_for(client, run_id)},
        headers={"Last-Event-ID": "1"},
    )

    events = parse_sse(response.text)
    assert [e.get("id") for e in events if e["event"] == "run_event"] == ["2"]


async def test_manual_reconnect_resumes_with_after(client: AsyncClient, db: Database) -> None:
    run_id = await finished_run_with_events(client, db)

    response = await client.get(
        f"/api/runs/{run_id}/stream",
        params={"ticket": await ticket_for(client, run_id), "after": 1},
    )

    events = parse_sse(response.text)
    assert [e.get("id") for e in events if e["event"] == "run_event"] == ["2"]


async def test_stream_requires_a_valid_ticket(client: AsyncClient, db: Database) -> None:
    run_id = await finished_run_with_events(client, db)

    assert (await client.get(f"/api/runs/{run_id}/stream")).status_code == 422
    bad = await client.get(f"/api/runs/{run_id}/stream", params={"ticket": "not-a-ticket"})
    assert bad.status_code == 401
    # A dashboard bearer token is not a ticket.
    bearer = AUTH["Authorization"].removeprefix("Bearer ")
    assert (
        await client.get(f"/api/runs/{run_id}/stream", params={"ticket": bearer})
    ).status_code == 401


def test_tickets_never_reach_the_access_log() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/api/runs/abc/stream?ticket=eyJsecret.part", "1.1", 200),
        None,
    )

    _RedactStreamTickets().filter(record)

    assert "eyJsecret" not in record.getMessage()
    assert "ticket=***" in record.getMessage()
