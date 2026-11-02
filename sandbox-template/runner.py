"""Orbit bot runner: runs one Claude Agent SDK query inside the bot's sandbox.

The backend starts it as a background command with ORBIT_* variables. It streams every SDK
message to POST {api}/internal/runs/{id}/events, then reports the result to .../complete.

The run token is the only credential here. It is removed from this process's environment
at startup and handed only to the SDK subprocess, whose own child processes (the agent's
shell) get credentials scrubbed by CLAUDE_CODE_SUBPROCESS_ENV_SCRUB.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

logger = logging.getLogger("orbit.runner")

MAX_TEXT_CHARS = 20_000
HTTP_TIMEOUT = httpx.Timeout(15.0)
EVENT_ATTEMPTS = 4
COMPLETE_ATTEMPTS = 10
NOT_RETRYABLE = {400, 401, 403, 404, 409, 422}

Event = tuple[str, dict[str, Any]]


@dataclass(frozen=True)
class RunnerConfig:
    run_id: str
    api_url: str
    token: str
    model: str
    background_model: str
    max_turns: int
    prompt: str
    bot_home: str
    resume_session_id: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RunnerConfig:
        return cls(
            run_id=env["ORBIT_RUN_ID"],
            api_url=env["ORBIT_API_URL"].rstrip("/"),
            token=env["ORBIT_RUN_TOKEN"],
            model=env["ORBIT_MODEL"],
            background_model=env["ORBIT_BACKGROUND_MODEL"],
            max_turns=int(env["ORBIT_MAX_TURNS"]),
            prompt=Path(env["ORBIT_PROMPT_FILE"]).read_text(encoding="utf-8"),
            bot_home=env["ORBIT_BOT_HOME"],
            resume_session_id=env.get("ORBIT_RESUME_SESSION_ID") or None,
        )


def sdk_env(config: RunnerConfig) -> dict[str, str]:
    return {
        "ANTHROPIC_BASE_URL": f"{config.api_url}/llm",
        "ANTHROPIC_AUTH_TOKEN": config.token,
        "ANTHROPIC_MODEL": config.model,
        # The CLI's "haiku" slot is what it uses for background calls.
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": config.background_model,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",  # Orbit's memory/ folder replaces it
        "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",
        "DISABLE_AUTOUPDATER": "1",
    }


def build_options(config: RunnerConfig) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=config.model,
        max_turns=config.max_turns,
        cwd=config.bot_home,
        system_prompt={"type": "preset", "preset": "claude_code"},
        setting_sources=["project"],  # loads bot/CLAUDE.md
        strict_mcp_config=True,
        permission_mode="bypassPermissions",  # the sandbox is the security boundary
        env=sdk_env(config),
        resume=config.resume_session_id,
        stderr=lambda line: logger.debug("cli: %s", line),
    )


def remove_project_settings(bot_home: str) -> None:
    """A .claude/settings*.json written by the bot could override ANTHROPIC_BASE_URL."""
    for name in ("settings.json", "settings.local.json"):
        path = Path(bot_home, ".claude", name)
        if path.exists():
            logger.warning("Removing %s before the run", path)
            path.unlink()


# ---- SDK messages -> run events --------------------------------------------------------


def _clip(text: str) -> str:
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return f"{text[:MAX_TEXT_CHARS]}\n... [{len(text) - MAX_TEXT_CHARS} more characters]"


def _clip_json(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, default=str)
    if len(encoded) <= MAX_TEXT_CHARS:
        return value
    return {"truncated": True, "preview": encoded[:MAX_TEXT_CHARS]}


def _tool_result_text(content: str | list[dict[str, Any]] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        else:
            parts.append(f"[{block.get('type', 'content')}]")
    return "\n".join(parts)


def message_to_events(message: object) -> list[Event]:
    events: list[Event] = []
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock) and block.text.strip():
                events.append(("text", {"text": _clip(block.text)}))
            elif isinstance(block, ThinkingBlock) and block.thinking.strip():
                events.append(("thinking", {"thinking": _clip(block.thinking)}))
            elif isinstance(block, ToolUseBlock):
                events.append(
                    (
                        "tool_use",
                        {"id": block.id, "name": block.name, "input": _clip_json(block.input)},
                    )
                )
        if message.error:
            events.append(("error", {"message": f"Model API error: {message.error}"}))
    elif isinstance(message, UserMessage) and isinstance(message.content, list):
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                events.append(
                    (
                        "tool_result",
                        {
                            "tool_use_id": block.tool_use_id,
                            "content": _clip(_tool_result_text(block.content)),
                            "is_error": bool(block.is_error),
                        },
                    )
                )
    elif isinstance(message, SystemMessage) and message.subtype == "init":
        events.append(
            (
                "status",
                {
                    "message": "Agent session started",
                    "session_id": message.data.get("session_id"),
                    "model": message.data.get("model"),
                },
            )
        )
    elif isinstance(message, ResultMessage):
        events.append(
            (
                "status",
                {
                    "message": "Agent finished",
                    "subtype": message.subtype,
                    "num_turns": message.num_turns,
                    "duration_ms": message.duration_ms,
                    "is_error": message.is_error,
                },
            )
        )
    return events


def build_completion(
    result: ResultMessage | None, error: str | None, *, max_turns: int
) -> dict[str, Any]:
    if result is None:
        return {"status": "failed", "error": error or "The agent produced no result."}
    failure: str | None = None
    if result.subtype == "error_max_turns":
        failure = f"Stopped after reaching the limit of {max_turns} turns."
    elif result.is_error:
        failure = (
            "; ".join(result.errors or []) or result.result or f"Agent ended: {result.subtype}"
        )
        if result.api_error_status:
            failure = f"{failure} (API status {result.api_error_status})"
    return {
        "status": "failed" if failure else "completed",
        "summary": result.result,
        "error": failure,
        "session_id": result.session_id,
        "num_turns": result.num_turns,
    }


# ---- Reporting to the backend ----------------------------------------------------------


class Reporter:
    """Posts events in order from a background task, so slow HTTP never stalls the agent."""

    def __init__(
        self,
        config: RunnerConfig,
        client: httpx.AsyncClient,
        *,
        retry_delay_s: Callable[[int], float] = lambda attempt: min(2**attempt, 30),
    ) -> None:
        self._retry_delay_s = retry_delay_s
        self._base = f"{config.api_url}/internal/runs/{config.run_id}"
        self._headers = {"Authorization": f"Bearer {config.token}"}
        self._client = client
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._seq = 0
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._drain())

    def event(self, type_: str, payload: dict[str, Any]) -> None:
        self._seq += 1
        self._queue.put_nowait({"seq": self._seq, "type": type_, "payload": payload})

    async def close(self) -> None:
        self._queue.put_nowait(None)
        if self._task is not None:
            await self._task

    async def complete(self, completion: dict[str, Any]) -> bool:
        return await self._post("/complete", completion, attempts=COMPLETE_ATTEMPTS)

    async def _drain(self) -> None:
        while (item := await self._queue.get()) is not None:
            await self._post("/events", {"events": [item]}, attempts=EVENT_ATTEMPTS)

    async def _post(self, path: str, body: dict[str, Any], *, attempts: int) -> bool:
        for attempt in range(attempts):
            try:
                response = await self._client.post(
                    f"{self._base}{path}", json=body, headers=self._headers
                )
                if response.status_code < 300:
                    return True
                logger.warning("POST %s returned %s", path, response.status_code)
                if response.status_code in NOT_RETRYABLE:
                    return False
            except httpx.HTTPError as exc:
                logger.warning("POST %s failed: %s", path, type(exc).__name__)
            await asyncio.sleep(self._retry_delay_s(attempt))
        return False


async def run(config: RunnerConfig) -> int:
    remove_project_settings(config.bot_home)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        reporter = Reporter(config, client)
        reporter.start()
        result: ResultMessage | None = None
        error: str | None = None
        try:
            async for message in query(prompt=config.prompt, options=build_options(config)):
                for type_, payload in message_to_events(message):
                    reporter.event(type_, payload)
                if isinstance(message, ResultMessage):
                    result = message
        except Exception as exc:  # the SDK raises after an error result; keep the result
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("Agent query failed")
            if result is None:
                reporter.event("error", {"message": _clip(error)})
        await reporter.close()
        completion = build_completion(result, error, max_turns=config.max_turns)
        if not await reporter.complete(completion):
            logger.error("Could not report the run result to the backend")
        return 0 if completion["status"] == "completed" else 1


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="Orbit bot runner")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    config = RunnerConfig.from_env(os.environ)
    if config.run_id != args.run_id:
        logger.error("--run-id does not match ORBIT_RUN_ID")
        return 2
    for key in [k for k in os.environ if k.startswith("ORBIT_")]:
        del os.environ[key]  # keep the token out of anything this process spawns directly
    return asyncio.run(run(config))


if __name__ == "__main__":
    sys.exit(main())
