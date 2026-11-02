"""Anthropic-compatible proxy that sandboxes reach via ANTHROPIC_BASE_URL={public}/llm.

It authenticates the run token, enforces the model allow-list and the bot's daily budget,
then forwards the request unchanged with the real API key. Bodies and anthropic-* headers
are passed through byte for byte and streams are relayed unbuffered, as Claude Code's LLM
gateway protocol requires. Usage is read from the response on the way through.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from typing import cast

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DatabaseDep, SettingsDep, authenticate_run
from app.auth.run_tokens import RunPrincipal
from app.db import Database
from app.llm_proxy.metering import record_usage, tokens_used_today
from app.llm_proxy.pricing import SUPPORTED_MODELS, Usage
from app.llm_proxy.usage import SseUsageTracker, usage_from_message
from app.models import Bot, Run
from app.models.enums import RunEventType
from app.runs.service import budget_message
from app.runs.timeline import add_system_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["llm-proxy"])

_FORWARD_REQUEST_HEADERS = {"content-type", "accept", "user-agent"}
_FORWARD_REQUEST_PREFIXES = ("anthropic-", "x-claude-code-", "x-stainless-")
_RETURN_RESPONSE_HEADERS = {"content-type", "request-id", "retry-after", "x-should-retry"}
_RETURN_RESPONSE_PREFIXES = ("anthropic-",)

UsageCallback = Callable[[Usage], None]

# Background usage writes outlive the response; keep references so they are not GC'd.
_background_tasks: set[asyncio.Task[None]] = set()


def anthropic_error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"type": "error", "error": {"type": error_type, "message": message}}, status_code=status
    )


def upstream_headers(incoming: Mapping[str, str], api_key: str) -> dict[str, str]:
    headers = {
        name: value
        for name, value in incoming.items()
        if name.lower() in _FORWARD_REQUEST_HEADERS
        or name.lower().startswith(_FORWARD_REQUEST_PREFIXES)
    }
    headers["x-api-key"] = api_key
    headers["accept-encoding"] = "identity"  # relay plain bytes, so usage can be parsed
    return headers


def downstream_headers(upstream: httpx.Headers) -> dict[str, str]:
    return {
        name: value
        for name, value in upstream.items()
        if name.lower() in _RETURN_RESPONSE_HEADERS
        or name.lower().startswith(_RETURN_RESPONSE_PREFIXES)
    }


@router.api_route("/api/hello", methods=["GET", "HEAD"], include_in_schema=False)
async def hello() -> Response:
    """Claude Code's startup reachability probe."""
    return Response(status_code=200)


@router.post("/v1/messages")
async def create_message(request: Request, db: DatabaseDep, settings: SettingsDep) -> Response:
    async with db.session() as session:
        principal = await authenticate_run(request, session, settings)
        if principal is None:
            return anthropic_error(401, "authentication_error", "Invalid or revoked run token.")
        body = await request.body()
        model = _requested_model(body)
        if model is None:
            return anthropic_error(400, "invalid_request_error", "Body must be JSON with a model.")
        if model not in SUPPORTED_MODELS:
            return anthropic_error(
                400, "invalid_request_error", f"Model {model!r} is not enabled in Orbit."
            )
        bot = await session.get(Bot, principal.bot_id)
        if bot is None:
            return anthropic_error(401, "authentication_error", "Unknown bot.")
        used = await tokens_used_today(session, bot.id, now=datetime.now(UTC))
        if used >= bot.daily_token_budget:
            message = budget_message(used, bot.daily_token_budget)
            await _record_budget_stop(session, principal, message)
            # 403, not 429: the CLI retries 429s, and waiting will not help.
            return anthropic_error(403, "permission_error", message)

    if settings.anthropic_api_key is None:
        return anthropic_error(500, "api_error", "Orbit has no Anthropic API key configured.")
    return await _forward(
        request,
        body,
        path="/v1/messages",
        api_key=settings.anthropic_api_key.get_secret_value(),
        on_usage=lambda usage: _spawn_record(db, principal, model, usage),
    )


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request, db: DatabaseDep, settings: SettingsDep) -> Response:
    async with db.session() as session:
        if await authenticate_run(request, session, settings) is None:
            return anthropic_error(401, "authentication_error", "Invalid or revoked run token.")
    if settings.anthropic_api_key is None:
        return anthropic_error(500, "api_error", "Orbit has no Anthropic API key configured.")
    return await _forward(
        request,
        await request.body(),
        path="/v1/messages/count_tokens",
        api_key=settings.anthropic_api_key.get_secret_value(),
        on_usage=None,
    )


def _requested_model(body: bytes) -> str | None:
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    model = parsed.get("model") if isinstance(parsed, dict) else None
    return model if isinstance(model, str) else None


async def _forward(
    request: Request,
    body: bytes,
    *,
    path: str,
    api_key: str,
    on_usage: UsageCallback | None,
) -> Response:
    client = cast(httpx.AsyncClient, request.app.state.llm_http)
    upstream_request = client.build_request(
        "POST",
        f"{request.app.state.settings.anthropic_upstream_url}{path}",
        params=str(request.query_params),
        headers=upstream_headers(request.headers, api_key),
        content=body,
    )
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        logger.warning("Upstream request failed: %s", type(exc).__name__)
        return anthropic_error(502, "api_error", "Could not reach the Anthropic API.")

    is_stream = upstream.headers.get("content-type", "").startswith("text/event-stream")
    if upstream.status_code != 200 or not is_stream:
        content = await upstream.aread()
        await upstream.aclose()
        if upstream.status_code == 200 and on_usage is not None:
            with contextlib.suppress(ValueError):
                on_usage(usage_from_message(json.loads(content)))
        return Response(
            content, status_code=upstream.status_code, headers=downstream_headers(upstream.headers)
        )

    tracker = SseUsageTracker()

    async def relay() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                tracker.feed(chunk)
                yield chunk
        finally:
            if on_usage is not None:
                on_usage(tracker.usage)
            with contextlib.suppress(Exception):
                await upstream.aclose()

    return StreamingResponse(relay(), status_code=200, headers=downstream_headers(upstream.headers))


def _spawn_record(db: Database, principal: RunPrincipal, model: str, usage: Usage) -> None:
    task = asyncio.create_task(_record(db, principal, model, usage))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _record(db: Database, principal: RunPrincipal, model: str, usage: Usage) -> None:
    try:
        async with db.session() as session:
            await record_usage(
                session, run_id=principal.run_id, bot_id=principal.bot_id, model=model, usage=usage
            )
            await session.commit()
    except Exception:
        logger.exception("Failed to record LLM usage for run %s", principal.run_id)


async def _record_budget_stop(session: AsyncSession, principal: RunPrincipal, message: str) -> None:
    run = await session.get(Run, principal.run_id)
    if run is not None and run.error is None:
        run.error = message
        add_system_event(session, run.id, RunEventType.ERROR, message)
        await session.commit()
