"""The sandbox operations the run lifecycle needs. E2B implements them; tests use a fake."""

import uuid
from dataclasses import dataclass
from typing import Protocol


class SandboxGoneError(Exception):
    """The sandbox no longer exists (killed or expired)."""


class SandboxUnavailableError(Exception):
    """Sandboxes cannot be used right now (not configured, or the provider failed)."""


@dataclass(frozen=True)
class CommandOutput:
    exit_code: int
    stdout: str
    stderr: str


class Sandbox(Protocol):
    @property
    def sandbox_id(self) -> str: ...

    async def write_text(self, path: str, content: str) -> None: ...

    async def make_dirs(self, *paths: str) -> None: ...

    async def start_background(self, command: str, *, envs: dict[str, str], cwd: str) -> int:
        """Start a long-running command with no time limit. Returns its pid."""
        ...

    async def is_running(self, pid: int) -> bool: ...

    async def kill_run_processes(self, run_id: uuid.UUID) -> None:
        """Kill the runner for this run and everything it started."""
        ...

    async def exec(self, command: str, *, timeout_s: float = 60) -> CommandOutput: ...


class SandboxProvider(Protocol):
    async def create(self, *, metadata: dict[str, str], timeout_s: int) -> Sandbox: ...

    async def connect(self, sandbox_id: str, *, timeout_s: int) -> Sandbox:
        """Connect to a running sandbox, resuming it if paused. Raises SandboxGoneError."""
        ...

    async def pause(self, sandbox_id: str) -> None: ...
