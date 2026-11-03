"""In-memory stand-ins for E2B and Inngest."""

import hashlib
import itertools
import uuid
from datetime import UTC, datetime
from typing import Any

from app.sandboxes.provider import (
    CommandOutput,
    FileEntry,
    SandboxFileNotFoundError,
    SandboxGoneError,
    TreeScan,
)

FIXED_TIME = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


class FakeSandbox:
    def __init__(self, sandbox_id: str) -> None:
        self._sandbox_id = sandbox_id
        self.files: dict[str, str] = {}
        self.blobs: dict[str, bytes] = {}  # binary files
        self.symlinks: set[str] = set()
        self.removed: list[str] = []
        self.reads: list[str] = []
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

    def _data(self) -> dict[str, bytes]:
        return {**{p: c.encode("utf-8") for p, c in self.files.items()}, **self.blobs}

    async def scan_tree(self, root: str, *, max_entries: int, hash_max_bytes: int = 0) -> TreeScan:
        prefix = f"{root}/"
        files = {
            path[len(prefix) :]: data
            for path, data in self._data().items()
            if path.startswith(prefix) and path not in self.symlinks
        }
        exists = root in self.dirs or bool(files)
        dirs = {
            "/".join(path.split("/")[:depth])
            for path in files
            for depth in range(1, path.count("/") + 1)
        }
        entries = [
            FileEntry(path=d, kind="dir", size=0, modified_at=FIXED_TIME) for d in sorted(dirs)
        ] + [
            FileEntry(
                path=path,
                kind="file",
                size=len(data),
                modified_at=FIXED_TIME,
                sha256=hashlib.sha256(data).hexdigest() if len(data) <= hash_max_bytes else None,
            )
            for path, data in sorted(files.items())
        ]
        return TreeScan(
            exists=exists, truncated=len(entries) > max_entries, entries=entries[:max_entries]
        )

    async def stat(self, path: str) -> FileEntry:
        data = self._data()
        if path in self.symlinks:
            return FileEntry(path=path, kind="symlink", size=0, modified_at=FIXED_TIME)
        if path in data:
            return FileEntry(path=path, kind="file", size=len(data[path]), modified_at=FIXED_TIME)
        if path in self.dirs or any(p.startswith(f"{path}/") for p in data):
            return FileEntry(path=path, kind="dir", size=0, modified_at=FIXED_TIME)
        raise SandboxFileNotFoundError(path)

    async def read_bytes(self, path: str) -> bytes:
        self.reads.append(path)
        data = self._data()
        if path not in data:
            raise SandboxFileNotFoundError(path)
        return data[path]

    async def remove(self, path: str) -> None:
        self.removed.append(path)
        self.files.pop(path, None)
        self.blobs.pop(path, None)


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


class FakeTitler:
    def __init__(self, title: str | None = "A Better Title") -> None:
        self.next_title = title
        self.calls: list[str] = []

    async def title(self, message: str) -> str | None:
        self.calls.append(message)
        return self.next_title
