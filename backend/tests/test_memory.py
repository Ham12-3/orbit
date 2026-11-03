"""Memory sync (sandbox <-> memory_files) and the memory API."""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.db import Database
from app.models import MemoryFile, RunEvent
from app.runs.service import RunServices
from app.sandboxes import layout
from tests.conftest import AUTH
from tests.fakes import FakeSandbox, FakeSandboxProvider
from tests.test_run_lifecycle import queue_run, started_run

PREFS = f"{layout.MEMORY_DIR}/preferences.md"


async def next_run(client: AsyncClient, services: RunServices, bot_id: str) -> str:
    run_id = await queue_run(client, bot_id)
    assert await services.claim(run_id, f"wf-{run_id}")
    await services.start(run_id)
    return run_id


async def memory(client: AsyncClient, bot_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/bots/{bot_id}/memory", headers=AUTH)
    assert response.status_code == 200, response.text
    files: list[dict[str, Any]] = response.json()
    return files


async def put(client: AsyncClient, bot_id: str, path: str, content: str) -> dict[str, Any]:
    response = await client.put(
        f"/api/bots/{bot_id}/memory/{path}", json={"content": content}, headers=AUTH
    )
    assert response.status_code == 200, response.text
    file: dict[str, Any] = response.json()
    return file


async def notes(db: Database, run_id: str) -> list[str]:
    async with db.session() as s:
        events = await s.scalars(
            select(RunEvent).where(RunEvent.run_id == uuid.UUID(run_id)).order_by(RunEvent.id)
        )
        return [str(e.payload.get("message", "")) for e in events]


def sandbox_of(sandboxes: FakeSandboxProvider) -> FakeSandbox:
    return next(iter(sandboxes.sandboxes.values()))


async def test_what_the_bot_writes_is_saved_when_the_run_ends(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    bot, run_id = await started_run(client, services)
    sandbox_of(sandboxes).files[PREFS] = "- Short bullet summaries\n"
    sandbox_of(sandboxes).files[f"{layout.MEMORY_DIR}/people/alex.md"] = "Alex is my manager."

    await services.finalize(run_id)

    files = await memory(client, bot["id"])
    assert [(f["path"], f["updated_by"], f["sync_state"]) for f in files] == [
        ("people/alex.md", "bot", "synced"),
        ("preferences.md", "bot", "synced"),
    ]
    detail = (await client.get(f"/api/bots/{bot['id']}/memory/preferences.md", headers=AUTH)).json()
    assert detail["content"] == "- Short bullet summaries\n"
    assert "Memory: saved people/alex.md, preferences.md." in await notes(db, run_id)
    assert sandboxes.paused == ["sbx-1"]  # saved before the pause


async def test_unchanged_files_are_not_read_or_rewritten(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    bot, first = await started_run(client, services)
    sandbox_of(sandboxes).files[PREFS] = "v1"
    await services.finalize(first)
    [before] = await memory(client, bot["id"])

    second = await next_run(client, services, bot["id"])
    sandbox_of(sandboxes).reads.clear()
    await services.finalize(second)

    assert sandbox_of(sandboxes).reads == []
    assert await memory(client, bot["id"]) == [before]
    assert not any(note.startswith("Memory") for note in await notes(db, second))


async def test_memory_is_in_claude_md_at_the_next_start(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    bot, first = await started_run(client, services)
    sandbox_of(sandboxes).files[PREFS] = "- I prefer short bullet summaries"
    await services.finalize(first)

    await next_run(client, services, bot["id"])

    claude_md = sandbox_of(sandboxes).files[layout.CLAUDE_MD_PATH]
    assert "### memory/preferences.md\n\n- I prefer short bullet summaries" in claude_md


async def test_a_user_edit_reaches_the_sandbox_at_the_next_start(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    bot, first = await started_run(client, services)
    sandbox_of(sandboxes).files[PREFS] = "- Short bullets"
    await services.finalize(first)

    edited = await put(client, bot["id"], "preferences.md", "- One paragraph, no bullets")
    assert (edited["updated_by"], edited["sync_state"]) == ("user", "push")
    assert sandbox_of(sandboxes).files[PREFS] == "- Short bullets"  # not until the next run

    second = await next_run(client, services, bot["id"])

    sandbox = sandbox_of(sandboxes)
    assert sandbox.files[PREFS] == "- One paragraph, no bullets"
    assert "preferences.md (last edited by your owner)" in sandbox.files[layout.CLAUDE_MD_PATH]
    [file] = await memory(client, bot["id"])
    assert (file["updated_by"], file["sync_state"]) == ("user", "synced")
    assert "Memory: wrote your edits to preferences.md." in await notes(db, second)


async def test_a_user_edit_during_a_run_wins_over_the_bot(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    bot, first = await started_run(client, services)
    sandbox_of(sandboxes).files[PREFS] = "bot v1"
    await services.finalize(first)

    second = await next_run(client, services, bot["id"])
    await put(client, bot["id"], "preferences.md", "user edit")
    sandbox_of(sandboxes).files[PREFS] = "bot v2"  # the bot changes it in the same run
    await services.finalize(second)

    detail = (await client.get(f"/api/bots/{bot['id']}/memory/preferences.md", headers=AUTH)).json()
    assert (detail["content"], detail["sync_state"]) == ("user edit", "push")
    await next_run(client, services, bot["id"])
    assert sandbox_of(sandboxes).files[PREFS] == "user edit"


async def test_a_user_delete_removes_the_file_at_the_next_start(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    bot, first = await started_run(client, services)
    sandbox_of(sandboxes).files[PREFS] = "remember me"
    await services.finalize(first)

    response = await client.delete(f"/api/bots/{bot['id']}/memory/preferences.md", headers=AUTH)
    assert response.status_code == 204
    assert await memory(client, bot["id"]) == []
    assert PREFS in sandbox_of(sandboxes).files

    second = await next_run(client, services, bot["id"])
    assert PREFS not in sandbox_of(sandboxes).files
    assert "remember me" not in sandbox_of(sandboxes).files[layout.CLAUDE_MD_PATH]
    async with db.session() as s:
        assert list(await s.scalars(select(MemoryFile))) == []
    assert "Memory: removed preferences.md." in await notes(db, second)


async def test_a_file_the_bot_deletes_is_forgotten(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    bot, first = await started_run(client, services)
    sandbox_of(sandboxes).files[PREFS] = "temporary"
    await services.finalize(first)

    second = await next_run(client, services, bot["id"])
    del sandbox_of(sandboxes).files[PREFS]
    await services.finalize(second)

    assert await memory(client, bot["id"]) == []


async def test_memory_is_restored_into_a_replacement_sandbox(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    bot, first = await started_run(client, services)
    sandbox_of(sandboxes).files[PREFS] = "survives"
    await services.finalize(first)
    del sandboxes.sandboxes["sbx-1"]

    second = await next_run(client, services, bot["id"])

    assert sandboxes.sandboxes["sbx-2"].files[PREFS] == "survives"
    assert "Memory: restored preferences.md." in await notes(db, second)


async def test_a_missing_memory_folder_is_not_read_as_forgetting(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    bot, first = await started_run(client, services)
    sandbox_of(sandboxes).files[PREFS] = "keep"
    await services.finalize(first)

    second = await next_run(client, services, bot["id"])
    sandbox = sandbox_of(sandboxes)
    del sandbox.files[PREFS]
    sandbox.dirs.discard(layout.MEMORY_DIR)
    await services.finalize(second)

    assert [f["path"] for f in await memory(client, bot["id"])] == ["preferences.md"]


async def test_files_that_cannot_be_memory_are_skipped(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    bot, run_id = await started_run(client, services)
    sandbox = sandbox_of(sandboxes)
    sandbox.files[f"{layout.MEMORY_DIR}/big.md"] = "x" * (64 * 1024 + 1)
    sandbox.files[f"{layout.MEMORY_DIR}/.hidden.md"] = "secret-ish"
    sandbox.blobs[f"{layout.MEMORY_DIR}/photo.md"] = b"\xff\xd8\xff\x00"

    await services.finalize(run_id)

    assert await memory(client, bot["id"]) == []
    [note] = [n for n in await notes(db, run_id) if n.startswith("Memory")]
    assert ".hidden.md (name not allowed)" in note
    assert "big.md (over 64 KB)" in note
    assert "photo.md (not text)" in note


async def test_a_failed_save_does_not_fail_the_run_and_still_pauses(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, db: Database
) -> None:
    _, run_id = await started_run(client, services)
    sandbox = sandbox_of(sandboxes)

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("scan failed")

    sandbox.scan_tree = broken  # type: ignore[method-assign]
    await services.finalize(run_id)

    assert sandboxes.paused == ["sbx-1"]
    assert any("Could not save the bot's memory" in n for n in await notes(db, run_id))


async def test_memory_paths_and_sizes_are_checked(client: AsyncClient) -> None:
    from tests.conftest import create_bot

    bot = await create_bot(client)
    base = f"/api/bots/{bot['id']}/memory"
    for bad in [".hidden.md", "a/b/c/d/e/f.md", "x" * 201, "sp ace /x.md", "a%09b.md"]:
        response = await client.put(f"{base}/{bad}", json={"content": "x"}, headers=AUTH)
        assert response.status_code == 422, bad
    too_big = "é" * 40_000  # 40k characters, 80 KB of UTF-8
    response = await client.put(f"{base}/big.md", json={"content": too_big}, headers=AUTH)
    assert response.status_code == 413
    assert (await client.get(f"{base}/missing.md", headers=AUTH)).status_code == 404
    assert (await client.delete(f"{base}/missing.md", headers=AUTH)).status_code == 404


async def test_a_deleted_file_can_be_written_again(client: AsyncClient) -> None:
    from tests.conftest import create_bot

    bot = await create_bot(client)
    await put(client, bot["id"], "notes/today.md", "one")
    await client.delete(f"/api/bots/{bot['id']}/memory/notes/today.md", headers=AUTH)
    again = await put(client, bot["id"], "notes/today.md", "two")
    assert (again["content"], again["sync_state"]) == ("two", "push")
    assert [f["path"] for f in await memory(client, bot["id"])] == ["notes/today.md"]
