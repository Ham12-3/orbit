"""The sandbox operations the run lifecycle needs. E2B implements them; tests use a fake."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel


class SandboxGoneError(Exception):
    """The sandbox no longer exists (killed or expired)."""


class SandboxUnavailableError(Exception):
    """Sandboxes cannot be used right now (not configured, or the provider failed)."""


class SandboxFileNotFoundError(Exception):
    """The path does not exist in the sandbox."""


class SandboxCommandError(Exception):
    """A helper command inside the sandbox failed."""


class FileEntry(BaseModel):
    path: str  # relative to the scanned folder, "/"-separated (absolute for stat())
    kind: Literal["file", "dir", "symlink"]
    size: int
    modified_at: datetime  # scan_tree.py sends Unix seconds; Pydantic converts them
    sha256: str | None = None


class TreeScan(BaseModel):
    """A folder listing from inside the sandbox (sandbox-template/scan_tree.py)."""

    exists: bool
    truncated: bool
    entries: list[FileEntry]


@dataclass(frozen=True)
class CommandOutput:
    exit_code: int
    stdout: str
    stderr: str


class Sandbox(Protocol):
    @property
    def sandbox_id(self) -> str: ...

    async def write_text(self, path: str, content: str, *, as_root: bool = False) -> None: ...

    async def make_dirs(self, *paths: str) -> None: ...

    async def start_background(self, command: str, *, envs: dict[str, str], cwd: str) -> int:
        """Start a long-running command with no time limit. Returns its pid."""
        ...

    async def is_running(self, pid: int) -> bool: ...

    async def kill_run_processes(self, run_id: uuid.UUID) -> None:
        """Kill the runner for this run and everything it started."""
        ...

    async def exec(self, command: str, *, timeout_s: float = 60) -> CommandOutput: ...

    async def scan_tree(self, root: str, *, max_entries: int, hash_max_bytes: int = 0) -> TreeScan:
        """List everything under `root`, skipping symlinks. Raises SandboxCommandError."""
        ...

    async def stat(self, path: str) -> FileEntry:
        """Does not follow a final symlink. Raises SandboxFileNotFoundError."""
        ...

    async def read_bytes(self, path: str) -> bytes:
        """Raises SandboxFileNotFoundError."""
        ...

    async def remove(self, path: str) -> None:
        """Delete a file. A missing file is not an error."""
        ...


class SandboxProvider(Protocol):
    async def create(self, *, metadata: dict[str, str], timeout_s: int) -> Sandbox: ...

    async def connect(self, sandbox_id: str, *, timeout_s: int) -> Sandbox:
        """Connect to a running sandbox, resuming it if paused. Raises SandboxGoneError."""
        ...

    async def pause(self, sandbox_id: str) -> None: ...
