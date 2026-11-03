"""Threads, messages, session resume and bot replies."""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update

from app.background import drain
from app.db import Database
from app.events import RUN_REQUESTED
from app.models import Run, Thread
from app.runs.service import RunServices
from tests.conftest import AUTH, create_bot
from tests.fakes import FakeSandboxProvider, FakeTitler, RecordingEvents


async def start_thread(client: AsyncClient, message: str = "Hello bot") -> dict[str, Any]:
    bot = await create_bot(client)
    response = await client.post(
        f"/api/bots/{bot['id']}/threads", json={"message": message}, headers=AUTH
    )
    assert response.status_code == 201, response.text
    thread: dict[str, Any] = response.json()
    return thread


async def get_thread(client: AsyncClient, thread_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/threads/{thread_id}", headers=AUTH)
    assert response.status_code == 200, response.text
    thread: dict[str, Any] = response.json()
    return thread


async def runner_completes(
    client: AsyncClient, sandboxes: FakeSandboxProvider, run_id: str, **body: Any
) -> None:
    sandbox = next(iter(sandboxes.sandboxes.values()))
    token = next(s["envs"]["ORBIT_RUN_TOKEN"] for s in sandbox.started if run_id in s["command"])
    response = await client.post(
        f"/internal/runs/{run_id}/complete",
        json={"status": "completed", **body},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204, response.text


async def test_first_message_creates_a_thread_and_a_chat_run(
    client: AsyncClient, events: RecordingEvents, titler: FakeTitler
) -> None:
    thread = await start_thread(client, "Summarise the news about solar power for me")

    assert thread["title"] == "Summarise the news about solar power for me"
    [message] = thread["messages"]
    assert (message["role"], message["run_status"]) == ("user", "queued")
    assert thread["active_run_id"] == message["run_id"]
    assert events.names() == [RUN_REQUESTED]

    run = (await client.get(f"/api/runs/{message['run_id']}", headers=AUTH)).json()
    assert (run["trigger_type"], run["thread_id"]) == ("chat", thread["id"])

    await drain()  # the title is improved in the background by the cheap model
    assert titler.calls == ["Summarise the news about solar power for me"]
    assert (await get_thread(client, thread["id"]))["title"] == "A Better Title"


async def test_bot_reply_and_session_are_saved_when_the_run_ends(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    thread = await start_thread(client)
    run_id = thread["active_run_id"]
    assert await services.claim(run_id, "wf-1")
    await services.start(run_id)

    await runner_completes(client, sandboxes, run_id, summary="Hi there!", session_id="sess-1")
    await services.finalize(run_id)

    detail = await get_thread(client, thread["id"])
    assert [(m["role"], m["content"]) for m in detail["messages"]] == [
        ("user", "Hello bot"),
        ("bot", "Hi there!"),
    ]
    assert detail["messages"][1]["run_status"] == "completed"
    assert detail["active_run_id"] is None
    async with db.session() as s:
        row = await s.get(Thread, uuid.UUID(thread["id"]))
    assert row is not None
    assert row.agent_session_id == "sess-1"


async def test_follow_up_messages_resume_the_agent_session(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    thread = await start_thread(client)
    first = thread["active_run_id"]
    assert await services.claim(first, "wf-1")
    await services.start(first)
    await runner_completes(client, sandboxes, first, summary="Hi!", session_id="sess-1")
    await services.finalize(first)

    response = await client.post(
        f"/api/threads/{thread['id']}/messages", json={"content": "And again?"}, headers=AUTH
    )
    assert response.status_code == 202, response.text
    second = response.json()["active_run_id"]
    assert await services.claim(second, "wf-2")
    await services.start(second)

    launches = sandboxes.sandboxes["sbx-1"].started
    assert "ORBIT_RESUME_SESSION_ID" not in launches[0]["envs"]
    assert launches[1]["envs"]["ORBIT_RESUME_SESSION_ID"] == "sess-1"


async def test_a_failed_run_still_answers_in_the_thread(
    client: AsyncClient, services: RunServices, db: Database
) -> None:
    thread = await start_thread(client)
    run_id = thread["active_run_id"]
    assert await services.claim(run_id, "wf-1")
    await services.start(run_id)
    async with db.session() as s:
        await s.execute(update(Run).where(Run.id == uuid.UUID(run_id)).values(error="Boom."))
        await s.commit()

    await services.finalize(run_id)  # never reported a result

    bot_reply = (await get_thread(client, thread["id"]))["messages"][-1]
    assert bot_reply["role"] == "bot"
    assert bot_reply["content"].startswith("I couldn't finish this.")
    assert bot_reply["run_status"] == "failed"


async def test_cancelling_a_queued_chat_run_answers_in_the_thread(client: AsyncClient) -> None:
    thread = await start_thread(client)

    response = await client.post(f"/api/runs/{thread['active_run_id']}/cancel", headers=AUTH)

    assert response.status_code == 200
    detail = await get_thread(client, thread["id"])
    assert detail["messages"][-1]["content"] == "Cancelled before I finished."
    assert detail["active_run_id"] is None


async def test_threads_are_listed_newest_first(client: AsyncClient) -> None:
    bot = await create_bot(client)
    for text in ["first", "second"]:
        await client.post(f"/api/bots/{bot['id']}/threads", json={"message": text}, headers=AUTH)

    listed = (await client.get(f"/api/bots/{bot['id']}/threads", headers=AUTH)).json()

    assert [t["title"] for t in listed] == ["A Better Title", "A Better Title"]
    assert listed[0]["updated_at"] >= listed[1]["updated_at"]
