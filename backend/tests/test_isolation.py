"""Spec section 7: user A cannot read or act on user B's data.

Covers every user-facing table that exists so far (bots, runs, run events, threads, messages).
Approvals and memory join this test when those tables arrive (Phases 3 and 4).
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
        f"/api/threads/{thread_id}",
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
        (f"/api/runs/{run_id}/stream-ticket", None),
    ]
    for path, body in attempts:
        response = await client.post(path, json=body, headers=AUTH_B)
        assert response.status_code == 404, f"POST {path} -> {response.status_code}"

    # Nothing changed for A.
    assert (await client.get(f"/api/runs/{run_id}", headers=AUTH)).json()["status"] == "queued"
    thread = (await client.get(f"/api/threads/{thread_id}", headers=AUTH)).json()
    assert [m["content"] for m in thread["messages"]] == ["hi"]


async def test_a_stream_ticket_only_opens_its_own_run(client: AsyncClient) -> None:
    a = await _a_has_everything(client)
    other_bot = await create_bot(client, headers=AUTH_B, name="B's bot")
    b_run = (
        await client.post(f"/api/bots/{other_bot['id']}/runs", json={"prompt": "x"}, headers=AUTH_B)
    ).json()
    ticket = (await client.post(f"/api/runs/{a['run']['id']}/stream-ticket", headers=AUTH)).json()[
        "ticket"
    ]

    response = await client.get(f"/api/runs/{b_run['id']}/stream", params={"ticket": ticket})

    assert response.status_code == 401
