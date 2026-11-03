import uuid
from decimal import Decimal

from httpx import AsyncClient

from app.db import Database
from app.events import RUN_REQUESTED
from app.models import Bot, LlmUsage
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


async def test_bot_list_shows_last_run_and_todays_cost(client: AsyncClient, db: Database) -> None:
    bot = await create_bot(client)
    run = (
        await client.post(f"/api/bots/{bot['id']}/runs", json={"prompt": "x"}, headers=AUTH)
    ).json()
    async with db.session() as s:
        s.add(
            LlmUsage(
                run_id=uuid.UUID(run["id"]),
                bot_id=uuid.UUID(bot["id"]),
                model="claude-sonnet-5-5",
                input_tokens=1,
                output_tokens=1,
                cache_read_tokens=0,
                cache_write_tokens=0,
                cost_usd=Decimal("0.25"),
            )
        )
        await s.commit()

    [listed] = (await client.get("/api/bots", headers=AUTH)).json()
    by_slug = (await client.get(f"/api/bots/by-slug/{bot['slug']}", headers=AUTH)).json()

    assert listed["last_run_status"] == "queued"
    assert listed["cost_today_usd"] == 0.25
    assert by_slug["id"] == bot["id"]
    runs = (await client.get(f"/api/bots/{bot['id']}/runs", headers=AUTH)).json()
    assert [r["id"] for r in runs] == [run["id"]]
