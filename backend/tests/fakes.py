"""In-memory stand-ins for E2B and Inngest."""

import itertools
import uuid
from typing import Any

from app.sandboxes.provider import CommandOutput, SandboxGoneError


class FakeSandbox:
    def __init__(self, sandbox_id: str) -> None:
        self._sandbox_id = sandbox_id
        self.files: dict[str, str] = {}
        self.root_files: set[str] = set()
        self.dirs: set[str] = set()
        self.started: list[dict[str, Any]] = []
        self.running: dict[int, str] = {}  # pid -> command
        self.killed_runs: list[uuid.UUID] = []
        self._pids = itertools.count(100)

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    async def write_text(self, path: str, content: str, *, as_root: bool = False) -> None:
        self.files[path] = content
        if as_root:
            self.root_files.add(path)

    async def make_dirs(self, *paths: str) -> None:
        self.dirs.update(paths)

    async def start_background(self, command: str, *, envs: dict[str, str], cwd: str) -> int:
        pid = next(self._pids)
        self.started.append({"command": command, "envs": envs, "cwd": cwd, "pid": pid})
        self.running[pid] = command
        return pid

    async def is_running(self, pid: int) -> bool:
        return pid in self.running

    async def kill_run_processes(self, run_id: uuid.UUID) -> None:
        self.killed_runs.append(run_id)
        for pid, command in list(self.running.items()):
            if f"--run-id {run_id}" in command:
                del self.running[pid]

    async def exec(self, command: str, *, timeout_s: float = 60) -> CommandOutput:
        return CommandOutput(exit_code=0, stdout="", stderr="")


class FakeSandboxProvider:
    def __init__(self) -> None:
        self.sandboxes: dict[str, FakeSandbox] = {}
        self.created_metadata: list[dict[str, str]] = []
        self.paused: list[str] = []
        self._ids = itertools.count(1)

    async def create(self, *, metadata: dict[str, str], timeout_s: int) -> FakeSandbox:
        sandbox = FakeSandbox(f"sbx-{next(self._ids)}")
        self.sandboxes[sandbox.sandbox_id] = sandbox
        self.created_metadata.append(metadata)
        return sandbox

    async def connect(self, sandbox_id: str, *, timeout_s: int) -> FakeSandbox:
        if sandbox_id not in self.sandboxes:
            raise SandboxGoneError(sandbox_id)
        return self.sandboxes[sandbox_id]

    async def pause(self, sandbox_id: str) -> None:
        self.paused.append(sandbox_id)


class RecordingEvents:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def send(self, name: str, data: dict[str, Any]) -> None:
        self.sent.append((name, data))

    def names(self) -> list[str]:
        return [name for name, _ in self.sent]
