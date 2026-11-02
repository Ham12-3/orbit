import uuid

from httpx import AsyncClient

from app.db import Database
from app.events import RUN_REQUESTED
from app.models import Bot
from tests.conftest import AUTH, create_bot
from tests.fakes import RecordingEvents


async def test_dashboard_routes_require_the_dev_token(client: AsyncClient) -> None:
    assert (await client.get("/api/bots")).status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert (await client.get("/api/bots", headers=wrong)).status_code == 401


async def test_create_bot_applies_defaults_and_unique_slugs(client: AsyncClient) -> None:
    first = await create_bot(client, name="Research Bot")
    second = await create_bot(client, name="Research Bot")

    assert first["slug"] == "research-bot"
    assert second["slug"] == "research-bot-2"
    assert first["model"] == "claude-sonnet-5-5"
    assert first["max_turns_per_run"] == 50
    assert first["status"] == "idle"


async def test_unknown_model_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/bots",
        json={"name": "X", "job_description": "j", "model": "gpt-5"},
        headers=AUTH,
    )
    assert response.status_code == 422


async def test_starting_a_run_queues_it_and_requests_the_workflow(
    client: AsyncClient, events: RecordingEvents
) -> None:
    bot = await create_bot(client)

    response = await client.post(
        f"/api/bots/{bot['id']}/runs", json={"prompt": "Say hi"}, headers=AUTH
    )

    assert response.status_code == 202, response.text
    run = response.json()
    assert run["status"] == "queued"
    assert events.sent == [(RUN_REQUESTED, {"run_id": run["id"]})]

    detail = (await client.get(f"/api/runs/{run['id']}", headers=AUTH)).json()
    assert detail["input_prompt"] == "Say hi"
    assert detail["events"] == []


async def test_other_users_bots_and_runs_are_invisible(client: AsyncClient, db: Database) -> None:
    async with db.session() as s:
        foreign = Bot(
            user_id=uuid.uuid4(),
            name="Not yours",
            slug="not-yours",
            avatar_emoji="🤖",
            job_description="j",
            model="claude-sonnet-5-5",
            daily_token_budget=1000,
            max_turns_per_run=5,
        )
        s.add(foreign)
        await s.commit()

    assert (await client.get("/api/bots", headers=AUTH)).json() == []
    assert (await client.get(f"/api/bots/{foreign.id}", headers=AUTH)).status_code == 404
    start = await client.post(f"/api/bots/{foreign.id}/runs", json={"prompt": "x"}, headers=AUTH)
    assert start.status_code == 404
