"""E2B template for Orbit bots.

Python 3.12, git, curl, ripgrep, procps, and the bot runner. The Claude Agent SDK wheel ships
its own Claude Code binary, so Node is not needed. The runner and its venv live under
/opt/orbit, owned by root and read-only to the bot (which runs as E2B's default `user`).
"""

from pathlib import Path

from e2b import Template

AGENT_SDK_VERSION = "0.2.176"
HTTPX_VERSION = "0.28.1"

template = (
    Template(file_context_path=Path(__file__).parent)
    .from_python_image("3.12")
    # bubblewrap: Claude Code needs it for CLAUDE_CODE_SUBPROCESS_ENV_SCRUB (keeps the run
    # token out of the agent's shell commands) and refuses to start without it.
    .apt_install(["git", "curl", "ripgrep", "procps", "bubblewrap"])
    .run_cmd(
        [
            "python3 -m venv /opt/orbit/venv",
            "/opt/orbit/venv/bin/pip install --no-cache-dir"
            f" claude-agent-sdk=={AGENT_SDK_VERSION} httpx=={HTTPX_VERSION}",
        ],
        user="root",
    )
    .copy("runner.py", "/opt/orbit/runner.py", user="root", mode=0o755)
)
