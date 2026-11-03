"""Spec section 7: user A cannot read or act on user B's data.

Covers every user-facing table that exists so far (bots, runs, run events, threads, messages,
memory files) and the bot's workspace files. Approvals join this test in Phase 4.
"""

from typing import Any

from httpx import AsyncClient

from tests.conftest import AUTH, AUTH_B, create_bot


async def _a_has_everything(client: AsyncClient) -> dict[str, Any]:
    bot = await create_bot(client, name="A's bot")
    run = (
        await client.post(f"/api/bots/{bot['id']}/runs", json={"prompt": "x"}, headers=AUTH)
    ).json()
    thread = (
        await client.post(f"/api/bots/{bot['id']}/threads", json={"message": "hi"}, headers=AUTH)
    ).json()
    memory = await client.put(
        f"/api/bots/{bot['id']}/memory/secret.md", json={"content": "A's note"}, headers=AUTH
    )
    assert memory.status_code == 200
    return {"bot": bot, "run": run, "thread": thread}


async def test_user_b_cannot_see_user_a_data(client: AsyncClient) -> None:
    a = await _a_has_everything(client)
    bot_id, run_id, thread_id = a["bot"]["id"], a["run"]["id"], a["thread"]["id"]

    assert (await client.get("/api/bots", headers=AUTH_B)).json() == []
    for path in [
        f"/api/bots/{bot_id}",
        f"/api/bots/by-slug/{a['bot']['slug']}",
        f"/api/bots/{bot_id}/runs",
        f"/api/bots/{bot_id}/threads",
        f"/api/runs/{run_id}",
        f"/api/runs/{run_id}/stream",
        f"/api/threads/{thread_id}",
        f"/api/bots/{bot_id}/memory",
        f"/api/bots/{bot_id}/memory/secret.md",
        f"/api/bots/{bot_id}/claude-md",
        f"/api/bots/{bot_id}/files",
        f"/api/bots/{bot_id}/files?live=true",
        f"/api/bots/{bot_id}/files/content/hello.txt",
    ]:
        response = await client.get(path, headers=AUTH_B)
        assert response.status_code == 404, f"GET {path} -> {response.status_code}"


async def test_user_b_cannot_act_on_user_a_data(client: AsyncClient) -> None:
    a = await _a_has_everything(client)
    bot_id, run_id, thread_id = a["bot"]["id"], a["run"]["id"], a["thread"]["id"]

    attempts = [
        (f"/api/bots/{bot_id}/runs", {"prompt": "steal"}),
        (f"/api/bots/{bot_id}/threads", {"message": "hello"}),
        (f"/api/threads/{thread_id}/messages", {"content": "hello"}),
        (f"/api/runs/{run_id}/cancel", None),
    ]
    for path, body in attempts:
        response = await client.post(path, json=body, headers=AUTH_B)
        assert response.status_code == 404, f"POST {path} -> {response.status_code}"
    memory_path = f"/api/bots/{bot_id}/memory/secret.md"
    new_path = f"/api/bots/{bot_id}/memory/new.md"
    for response in [
        await client.put(memory_path, json={"content": "B was here"}, headers=AUTH_B),
        await client.put(new_path, json={"content": "x"}, headers=AUTH_B),
        await client.delete(memory_path, headers=AUTH_B),
        await client.patch(f"/api/bots/{bot_id}", json={"name": "Stolen"}, headers=AUTH_B),
    ]:
        assert response.status_code == 404, f"{response.request.method} {response.request.url}"

    # Nothing changed for A.
    assert (await client.get(f"/api/runs/{run_id}", headers=AUTH)).json()["status"] == "queued"
    thread = (await client.get(f"/api/threads/{thread_id}", headers=AUTH)).json()
    assert [m["content"] for m in thread["messages"]] == ["hi"]
    memory = (await client.get(f"/api/bots/{bot_id}/memory", headers=AUTH)).json()
    assert [(f["path"], f["sync_state"]) for f in memory] == [("secret.md", "push")]
    note = (await client.get(f"/api/bots/{bot_id}/memory/secret.md", headers=AUTH)).json()
    assert note["content"] == "A's note"
    assert (await client.get(f"/api/bots/{bot_id}", headers=AUTH)).json()["name"] == "A's bot"
