"""Unit tests for sandbox-template/runner.py (on the pytest path via pyproject)."""

from pathlib import Path

import httpx
import runner
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)


def _config(tmp_path: Path) -> runner.RunnerConfig:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Write hello.txt", encoding="utf-8")
    return runner.RunnerConfig.from_env(
        {
            "ORBIT_RUN_ID": "run-1",
            "ORBIT_API_URL": "https://orbit.example.test/",
            "ORBIT_RUN_TOKEN": "tok",
            "ORBIT_MODEL": "claude-sonnet-5-5",
            "ORBIT_BACKGROUND_MODEL": "claude-haiku-5-5",
            "ORBIT_MAX_TURNS": "7",
            "ORBIT_PROMPT_FILE": str(prompt),
            "ORBIT_BOT_HOME": str(tmp_path),
        }
    )


def _result(**overrides: object) -> ResultMessage:
    fields: dict[str, object] = {
        "subtype": "success",
        "duration_ms": 10,
        "duration_api_ms": 5,
        "is_error": False,
        "num_turns": 2,
        "session_id": "sess-1",
        "result": "I wrote hello.txt.",
    }
    fields.update(overrides)
    return ResultMessage(**fields)  # type: ignore[arg-type]


def test_config_reads_the_prompt_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert config.prompt == "Write hello.txt"
    assert config.api_url == "https://orbit.example.test"
    assert config.max_turns == 7


def test_sdk_talks_only_to_the_orbit_proxy(tmp_path: Path) -> None:
    env = runner.sdk_env(_config(tmp_path))
    assert env["ANTHROPIC_BASE_URL"] == "https://orbit.example.test/llm"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "tok"
    assert "ANTHROPIC_API_KEY" not in env
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "claude-haiku-5-5"
    assert env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"


def test_options_load_the_bot_claude_md(tmp_path: Path) -> None:
    options = runner.build_options(_config(tmp_path))
    assert options.setting_sources == ["project"]
    assert options.cwd == str(tmp_path)
    assert options.max_turns == 7
    assert options.permission_mode == "bypassPermissions"


def test_project_settings_files_are_removed(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"env": {"ANTHROPIC_BASE_URL": "https://evil.example"}}')

    runner.remove_project_settings(str(tmp_path))

    assert not settings.exists()


def test_messages_map_to_timeline_events() -> None:
    assistant = AssistantMessage(
        content=[
            TextBlock(text="Creating the file."),
            ThinkingBlock(thinking="", signature="s"),  # empty (display omitted) is skipped
            ToolUseBlock(id="tu_1", name="Write", input={"file_path": "workspace/hello.txt"}),
        ],
        model="claude-sonnet-5-5",
    )
    tool_result = UserMessage(
        content=[ToolResultBlock(tool_use_id="tu_1", content=[{"type": "text", "text": "ok"}])]
    )
    init = SystemMessage(subtype="init", data={"session_id": "sess-1", "model": "m"})

    events = [
        e for m in (init, assistant, tool_result, _result()) for e in runner.message_to_events(m)
    ]

    assert [type_ for type_, _ in events] == ["status", "text", "tool_use", "tool_result", "status"]
    assert events[2][1] == {
        "id": "tu_1",
        "name": "Write",
        "input": {"file_path": "workspace/hello.txt"},
    }
    assert events[3][1] == {"tool_use_id": "tu_1", "content": "ok", "is_error": False}


def test_long_text_is_clipped() -> None:
    message = AssistantMessage(content=[TextBlock(text="x" * 50_000)], model="m")
    [(_, payload)] = runner.message_to_events(message)
    assert len(payload["text"]) < 21_000


def test_completion_for_success_and_failures() -> None:
    ok = runner.build_completion(_result(), None, max_turns=7)
    assert ok == {
        "status": "completed",
        "summary": "I wrote hello.txt.",
        "error": None,
        "session_id": "sess-1",
        "num_turns": 2,
    }

    turns = runner.build_completion(
        _result(subtype="error_max_turns", is_error=True), None, max_turns=7
    )
    assert turns["status"] == "failed"
    assert "7 turns" in turns["error"]

    api = runner.build_completion(
        _result(is_error=True, errors=["budget spent"], api_error_status=403), None, max_turns=7
    )
    assert api["error"] == "budget spent (API status 403)"

    crashed = runner.build_completion(None, "CLIConnectionError: boom", max_turns=7)
    assert crashed == {"status": "failed", "error": "CLIConnectionError: boom"}


async def test_reporter_posts_events_in_order_and_retries(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    failures = iter([500])  # the first POST fails once, then everything succeeds

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(next(failures, 204))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reporter = runner.Reporter(_config(tmp_path), client, retry_delay_s=lambda _: 0)
        reporter.start()
        reporter.event("text", {"text": "a"})
        reporter.event("text", {"text": "b"})
        await reporter.close()
        assert await reporter.complete({"status": "completed"})

    paths = [r.url.path for r in seen]
    assert paths == ["/internal/runs/run-1/events"] * 3 + ["/internal/runs/run-1/complete"]
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert [b'"seq":1' in r.content for r in seen[:3]] == [True, True, False]


async def test_reporter_gives_up_on_a_revoked_token(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reporter = runner.Reporter(_config(tmp_path), client)
        assert not await reporter.complete({"status": "completed"})
    assert calls == 1
