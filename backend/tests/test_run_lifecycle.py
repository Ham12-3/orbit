"""Queue, start, watch, finish and cancel, against a fake sandbox provider."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update

from app.db import Database
from app.events import RUN_FINISHED
from app.models import LlmUsage, Run, RunToken
from app.runs.service import RunServices
from app.sandboxes import layout
from tests.conftest import AUTH, SECRETS, create_bot, get_bot
from tests.fakes import FakeSandboxProvider, RecordingEvents


async def queue_run(client: AsyncClient, bot_id: str, prompt: str = "Do the thing") -> str:
    response = await client.post(f"/api/bots/{bot_id}/runs", json={"prompt": prompt}, headers=AUTH)
    assert response.status_code == 202, response.text
    run_id: str = response.json()["id"]
    return run_id


async def load_run(db: Database, run_id: str) -> Run:
    async with db.session() as s:
        run = await s.get(Run, uuid.UUID(run_id))
        assert run is not None
        return run


async def started_run(
    client: AsyncClient, services: RunServices, **bot_overrides: Any
) -> tuple[dict[str, Any], str]:
    bot = await create_bot(client, **bot_overrides)
    run_id = await queue_run(client, bot["id"])
    assert await services.claim(run_id, "wf-1")
    await services.start(run_id)
    return bot, run_id


async def test_one_run_at_a_time_per_bot(client: AsyncClient, services: RunServices) -> None:
    bot = await create_bot(client)
    first = await queue_run(client, bot["id"])
    second = await queue_run(client, bot["id"])

    assert await services.claim(first, "wf-1")
    assert not await services.claim(second, "wf-2")  # bot busy: stays queued
    assert await services.claim(first, "wf-1")  # a retried claim step still succeeds
    assert not await services.claim(first, "wf-3")  # a duplicate workflow does not

    assert await services.finalize(first) == second
    assert await services.claim(second, "wf-2")


async def test_start_prepares_the_sandbox_and_launches_the_runner(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    bot, run_id = await started_run(client, services, name="Writer")

    sandbox = sandboxes.sandboxes["sbx-1"]
    assert sandboxes.created_metadata == [
        {"bot_id": bot["id"], "user_id": str(services.settings.dev_user_id)}
    ]
    assert "# Writer" in sandbox.files[layout.CLAUDE_MD_PATH]
    assert sandbox.files[layout.prompt_path(uuid.UUID(run_id))] == "Do the thing"
    # The current runner is pushed every run (as root: /opt/orbit is read-only to the bot).
    runner_source = services.settings.runner_script_path.read_text(encoding="utf-8")
    assert sandbox.files[layout.RUNNER_SCRIPT] == runner_source
    assert layout.RUNNER_SCRIPT in sandbox.root_files
    [launch] = sandbox.started
    assert launch["command"].startswith(
        f"{layout.RUNNER_PYTHON} {layout.RUNNER_SCRIPT} --run-id {run_id}"
    )
    assert launch["cwd"] == layout.BOT_HOME

    run = await load_run(db, run_id)
    assert run.status == "running"
    assert run.runner_pid == launch["pid"]
    assert (await get_bot(db, bot["id"])).sandbox_id == "sbx-1"


async def test_real_secrets_never_reach_the_sandbox(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    """Spec section 7 / Phase 1: the sandbox only ever sees the short-lived run token."""
    await started_run(client, services)

    sandbox = sandboxes.sandboxes["sbx-1"]
    [launch] = sandbox.started
    everything_sent = "\n".join(
        [
            launch["command"],
            *launch["envs"].keys(),
            *launch["envs"].values(),
            *sandbox.files.values(),
        ]
    )
    for name, secret in SECRETS.items():
        assert secret not in everything_sent, f"{name} leaked into the sandbox"
    assert set(launch["envs"]) == {
        "ORBIT_RUN_ID",
        "ORBIT_API_URL",
        "ORBIT_RUN_TOKEN",
        "ORBIT_MODEL",
        "ORBIT_BACKGROUND_MODEL",
        "ORBIT_MAX_TURNS",
        "ORBIT_PROMPT_FILE",
        "ORBIT_BOT_HOME",
    }


async def test_second_run_reuses_the_bot_sandbox(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    bot, first = await started_run(client, services)
    await services.finalize(first)
    second = await queue_run(client, bot["id"])
    assert await services.claim(second, "wf-2")
    await services.start(second)

    assert list(sandboxes.sandboxes) == ["sbx-1"]
    assert sandboxes.paused == ["sbx-1"]


async def test_a_vanished_sandbox_is_replaced(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    bot, first = await started_run(client, services)
    await services.finalize(first)
    del sandboxes.sandboxes["sbx-1"]

    second = await queue_run(client, bot["id"])
    assert await services.claim(second, "wf-2")
    await services.start(second)

    assert (await get_bot(db, bot["id"])).sandbox_id == "sbx-2"


async def test_check_fails_a_run_whose_runner_died(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    _, run_id = await started_run(client, services)
    assert await services.check(run_id) == "running"

    sandboxes.sandboxes["sbx-1"].running.clear()

    assert await services.check(run_id) == "done"
    run = await load_run(db, run_id)
    assert run.status == "failed"
    assert "runner stopped" in (run.error or "")


async def test_check_times_out_a_run_past_its_deadline(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    _, run_id = await started_run(client, services)
    async with db.session() as s:
        await s.execute(
            update(Run)
            .where(Run.id == uuid.UUID(run_id))
            .values(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()

    assert await services.check(run_id) == "done"
    assert (await load_run(db, run_id)).status == "timed_out"
    assert sandboxes.sandboxes["sbx-1"].killed_runs[-1] == uuid.UUID(run_id)


async def test_finalize_revokes_the_token_pauses_and_releases_the_bot(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    bot, run_id = await started_run(client, services)

    await services.finalize(run_id)

    run = await load_run(db, run_id)
    assert run.status == "failed"  # never reported a result
    assert sandboxes.paused == ["sbx-1"]
    bot_row = await get_bot(db, bot["id"])
    assert bot_row.active_run_id is None
    assert bot_row.status == "idle"
    async with db.session() as s:
        tokens = list(await s.scalars(select(RunToken).where(RunToken.run_id == run.id)))
    assert tokens
    assert all(t.revoked_at is not None for t in tokens)


async def test_cancel_a_running_run(
    client: AsyncClient,
    services: RunServices,
    sandboxes: FakeSandboxProvider,
    events: RecordingEvents,
    db: Database,
) -> None:
    _, run_id = await started_run(client, services)

    response = await client.post(f"/api/runs/{run_id}/cancel", headers=AUTH)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    assert sandboxes.sandboxes["sbx-1"].killed_runs[-1] == uuid.UUID(run_id)
    assert (RUN_FINISHED, {"run_id": run_id}) in events.sent
    again = await client.post(f"/api/runs/{run_id}/cancel", headers=AUTH)
    assert again.status_code == 409


async def test_cancel_a_queued_run_never_starts_it(
    client: AsyncClient, services: RunServices
) -> None:
    bot = await create_bot(client)
    run_id = await queue_run(client, bot["id"])

    assert (await client.post(f"/api/runs/{run_id}/cancel", headers=AUTH)).status_code == 200
    assert not await services.claim(run_id, "wf-1")


async def test_start_refuses_when_the_daily_budget_is_spent(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    bot = await create_bot(client, daily_token_budget=1000)
    first = await queue_run(client, bot["id"])
    async with db.session() as s:
        s.add(
            LlmUsage(
                run_id=uuid.UUID(first),
                bot_id=uuid.UUID(bot["id"]),
                model="claude-sonnet-5-5",
                input_tokens=600,
                output_tokens=500,
                cache_read_tokens=0,
                cache_write_tokens=0,
                cost_usd=0,
            )
        )
        await s.commit()

    assert await services.claim(first, "wf-1")
    assert await services.start(first) == {"skipped": "budget"}
    run = await load_run(db, first)
    assert run.status == "failed"
    assert "daily token budget" in (run.error or "")
    assert sandboxes.sandboxes == {}


async def test_sweeper_dispatches_stranded_queued_runs(
    client: AsyncClient, services: RunServices, db: Database
) -> None:
    bot = await create_bot(client)
    run_id = await queue_run(client, bot["id"])
    async with db.session() as s:
        await s.execute(
            update(Run)
            .where(Run.id == uuid.UUID(run_id))
            .values(created_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await s.commit()

    assert await services.dispatchable() == [run_id]


async def test_sweeper_recovers_a_run_whose_workflow_died(
    client: AsyncClient, services: RunServices, db: Database
) -> None:
    bot, run_id = await started_run(client, services)
    waiting = await queue_run(client, bot["id"])
    async with db.session() as s:
        await s.execute(
            update(Run)
            .where(Run.id == uuid.UUID(run_id))
            .values(deadline_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await s.commit()

    assert await services.recover_stale() == [waiting]
    assert (await load_run(db, run_id)).status == "failed"
