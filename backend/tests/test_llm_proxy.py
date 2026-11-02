import json
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
from httpx import AsyncClient
from sqlalchemy import select

from app.db import Database
from app.models import LlmUsage, Run
from app.runs.service import RunServices
from tests.conftest import SECRETS, Upstream, flush_usage_writes
from tests.fakes import FakeSandboxProvider
from tests.test_run_lifecycle import started_run

SSE_BODY = (
    b"event: message_start\n"
    b'data: {"type":"message_start","message":{"id":"msg_1","model":"claude-sonnet-5-5",'
    b'"usage":{"input_tokens":10,"cache_creation_input_tokens":100,'
    b'"cache_read_input_tokens":1000,"output_tokens":1,'
    b'"cache_creation":{"ephemeral_5m_input_tokens":100,"ephemeral_1h_input_tokens":0}}}}\n\n'
    b"event: ping\n"
    b'data: {"type":"ping"}\n\n'
    b"event: content_block_delta\n"
    b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hi"}}\n\n'
    b"event: message_delta\n"
    b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
    b'"usage":{"output_tokens":42}}\n\n'
    b"event: message_stop\n"
    b'data: {"type":"message_stop"}\n\n'
)
REQUEST_BODY = json.dumps(
    {"model": "claude-sonnet-5-5", "max_tokens": 100, "stream": True, "messages": []}
).encode()


async def _token(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> tuple[str, str]:
    _, run_id = await started_run(client, services)
    token: str = sandboxes.sandboxes["sbx-1"].started[0]["envs"]["ORBIT_RUN_TOKEN"]
    return token, run_id


async def _chunked(body: bytes, size: int = 37) -> AsyncIterator[bytes]:
    for i in range(0, len(body), size):  # odd chunk size splits SSE lines mid-way
        yield body[i : i + size]


async def test_requests_without_a_valid_run_token_are_rejected(client: AsyncClient) -> None:
    response = await client.post("/llm/v1/messages", content=REQUEST_BODY)
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"

    response = await client.post(
        "/llm/v1/messages", content=REQUEST_BODY, headers={"Authorization": "Bearer junk"}
    )
    assert response.status_code == 401


async def test_streaming_is_relayed_byte_for_byte_and_metered(
    client: AsyncClient,
    services: RunServices,
    sandboxes: FakeSandboxProvider,
    upstream: Upstream,
    db: Database,
) -> None:
    token, run_id = await _token(client, services, sandboxes)
    upstream.handler = lambda _: httpx.Response(
        200,
        headers={"content-type": "text/event-stream", "request-id": "req_1"},
        content=_chunked(SSE_BODY),
    )

    response = await client.post(
        "/llm/v1/messages?beta=true",
        content=REQUEST_BODY,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "some-beta-2026-01-01",
            "content-type": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.content == SSE_BODY
    assert response.headers["request-id"] == "req_1"

    [sent] = upstream.requests
    assert sent.url == "https://api.anthropic.com/v1/messages?beta=true"
    assert sent.content == REQUEST_BODY
    assert sent.headers["x-api-key"] == SECRETS["anthropic_api_key"]
    assert sent.headers["anthropic-beta"] == "some-beta-2026-01-01"
    assert "authorization" not in sent.headers  # the run token never goes upstream

    await flush_usage_writes()
    async with db.session() as s:
        usage = await s.scalar(select(LlmUsage))
        run = await s.get(Run, uuid.UUID(run_id))
    assert usage is not None
    assert run is not None
    assert (usage.input_tokens, usage.output_tokens) == (10, 42)
    assert (usage.cache_read_tokens, usage.cache_write_tokens) == (1000, 100)
    # 10*$2 + 100*$2.50 + 1000*$0.10 + 42*$10, per million tokens
    assert usage.cost_usd == Decimal("0.000790")
    assert (run.input_tokens, run.output_tokens, run.cost_usd) == (10, 42, Decimal("0.000790"))


async def test_non_streaming_response_is_metered(
    client: AsyncClient,
    services: RunServices,
    sandboxes: FakeSandboxProvider,
    upstream: Upstream,
    db: Database,
) -> None:
    token, _ = await _token(client, services, sandboxes)
    upstream.handler = lambda _: httpx.Response(
        200,
        json={"id": "msg_1", "content": [], "usage": {"input_tokens": 7, "output_tokens": 3}},
    )

    response = await client.post(
        "/llm/v1/messages",
        content=json.dumps({"model": "claude-haiku-5-5", "messages": []}),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    await flush_usage_writes()
    async with db.session() as s:
        usage = await s.scalar(select(LlmUsage))
    assert usage is not None
    assert (usage.model, usage.input_tokens, usage.output_tokens) == ("claude-haiku-5-5", 7, 3)


async def test_models_outside_the_allow_list_are_refused(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, upstream: Upstream
) -> None:
    token, _ = await _token(client, services, sandboxes)

    response = await client.post(
        "/llm/v1/messages",
        content=json.dumps({"model": "some-other-model", "messages": []}),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert upstream.requests == []


async def test_spent_budget_blocks_the_call_with_a_clear_error(
    client: AsyncClient,
    services: RunServices,
    sandboxes: FakeSandboxProvider,
    upstream: Upstream,
    db: Database,
) -> None:
    token, run_id = await _token(client, services, sandboxes)
    async with db.session() as s:
        run = await s.get(Run, uuid.UUID(run_id))
        assert run is not None
        s.add(
            LlmUsage(
                run_id=run.id,
                bot_id=run.bot_id,
                model="claude-sonnet-5-5",
                input_tokens=2_000_000,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
                cost_usd=0,
            )
        )
        await s.commit()

    response = await client.post(
        "/llm/v1/messages", content=REQUEST_BODY, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403  # not 429: the CLI would retry a 429
    assert response.json()["error"]["type"] == "permission_error"
    assert upstream.requests == []
    async with db.session() as s:
        run = await s.get(Run, uuid.UUID(run_id))
    assert run is not None
    assert "daily token budget" in (run.error or "")


async def test_upstream_errors_pass_through_unchanged(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, upstream: Upstream
) -> None:
    token, _ = await _token(client, services, sandboxes)
    error = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
    upstream.handler = lambda _: httpx.Response(429, json=error, headers={"retry-after": "7"})

    response = await client.post(
        "/llm/v1/messages", content=REQUEST_BODY, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 429
    assert response.json() == error
    assert response.headers["retry-after"] == "7"


async def test_count_tokens_is_forwarded(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider, upstream: Upstream
) -> None:
    token, _ = await _token(client, services, sandboxes)
    upstream.handler = lambda _: httpx.Response(200, json={"input_tokens": 12})

    response = await client.post(
        "/llm/v1/messages/count_tokens",
        content=REQUEST_BODY,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.json() == {"input_tokens": 12}
    assert upstream.requests[0].url.path == "/v1/messages/count_tokens"


async def test_revoked_tokens_stop_working(
    client: AsyncClient, services: RunServices, sandboxes: FakeSandboxProvider
) -> None:
    token, run_id = await _token(client, services, sandboxes)
    await services.finalize(run_id)

    response = await client.post(
        "/llm/v1/messages", content=REQUEST_BODY, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
