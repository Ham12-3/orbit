"""E2B implementation of the sandbox provider (one persistent sandbox per bot)."""

import contextlib
import shlex
import uuid
from functools import cache
from pathlib import Path
from typing import Any, Literal

from e2b import (
    AsyncSandbox,
    CommandExitException,
    FileNotFoundException,
    FileType,
    NotFoundException,
)
from pydantic import ValidationError

from app.config import Settings
from app.sandboxes.layout import RUNNER_PYTHON, RUNNER_SCRIPT
from app.sandboxes.provider import (
    CommandOutput,
    FileEntry,
    SandboxCommandError,
    SandboxFileNotFoundError,
    SandboxGoneError,
    SandboxUnavailableError,
    TreeScan,
)


@cache
def _read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class E2BSandbox:
    def __init__(
        self, sandbox: AsyncSandbox, *, request_timeout_s: float, scan_script: Path
    ) -> None:
        self._sandbox = sandbox
        self._request_timeout_s = request_timeout_s
        self._scan_script = scan_script

    @property
    def sandbox_id(self) -> str:
        return str(self._sandbox.sandbox_id)

    async def write_text(self, path: str, content: str, *, as_root: bool = False) -> None:
        await self._sandbox.files.write(
            path,
            content,
            user="root" if as_root else None,
            request_timeout=self._request_timeout_s,
        )

    async def make_dirs(self, *paths: str) -> None:
        for path in paths:
            await self._sandbox.files.make_dir(path, request_timeout=self._request_timeout_s)

    async def start_background(self, command: str, *, envs: dict[str, str], cwd: str) -> int:
        # timeout=0: without it E2B kills even background commands after 60s.
        handle = await self._sandbox.commands.run(
            command,
            background=True,
            envs=envs,
            cwd=cwd,
            timeout=0,
            request_timeout=self._request_timeout_s,
        )
        pid = int(handle.pid)
        await handle.disconnect()
        return pid

    async def is_running(self, pid: int) -> bool:
        processes = await self._sandbox.commands.list(request_timeout=self._request_timeout_s)
        return any(process.pid == pid for process in processes)

    async def kill_run_processes(self, run_id: uuid.UUID) -> None:
        # "[r]unner" keeps this command's own shell from matching the pattern.
        pattern = shlex.quote(f"[{RUNNER_SCRIPT[0]}]{RUNNER_SCRIPT[1:]} --run-id {run_id}")
        script = (
            'kt() { for c in $(pgrep -P "$1"); do kt "$c"; done; kill -KILL "$1" 2>/dev/null; }; '
            f'for p in $(pgrep -f {pattern}); do kt "$p"; done; true'
        )
        await self.exec(f"bash -c {shlex.quote(script)}", timeout_s=30)

    async def exec(self, command: str, *, timeout_s: float = 60) -> CommandOutput:
        try:
            result = await self._sandbox.commands.run(
                command, timeout=timeout_s, request_timeout=self._request_timeout_s
            )
        except CommandExitException as exc:
            return CommandOutput(exit_code=exc.exit_code, stdout=exc.stdout, stderr=exc.stderr)
        return CommandOutput(exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr)

    async def scan_tree(self, root: str, *, max_entries: int, hash_max_bytes: int = 0) -> TreeScan:
        # Runs as the sandbox's normal user, so it sees only what the bot itself can read.
        source = _read_source(self._scan_script)
        command = (
            f"{RUNNER_PYTHON} -c {shlex.quote(source)} {shlex.quote(root)} "
            f"--max-entries {max_entries} --hash-max-bytes {hash_max_bytes}"
        )
        output = await self.exec(command, timeout_s=60)
        if output.exit_code != 0:
            raise SandboxCommandError(f"Listing {root} failed: {output.stderr[-500:]}")
        try:
            return TreeScan.model_validate_json(output.stdout)
        except ValidationError as exc:
            raise SandboxCommandError(f"Listing {root} returned bad output") from exc

    async def stat(self, path: str) -> FileEntry:
        try:
            info = await self._sandbox.files.get_info(path, request_timeout=self._request_timeout_s)
        except FileNotFoundException as exc:
            raise SandboxFileNotFoundError(path) from exc
        kind: Literal["file", "dir", "symlink"]
        if info.type == FileType.SYMLINK or info.symlink_target:
            kind = "symlink"
        elif info.type == FileType.DIR:
            kind = "dir"
        else:
            kind = "file"
        return FileEntry(path=path, kind=kind, size=info.size, modified_at=info.modified_time)

    async def read_bytes(self, path: str) -> bytes:
        try:
            data = await self._sandbox.files.read(
                path, format="bytes", request_timeout=self._request_timeout_s
            )
        except FileNotFoundException as exc:
            raise SandboxFileNotFoundError(path) from exc
        return bytes(data)

    async def remove(self, path: str) -> None:
        with contextlib.suppress(FileNotFoundException):
            await self._sandbox.files.remove(path, request_timeout=self._request_timeout_s)


class E2BSandboxProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _api_opts(self) -> dict[str, Any]:
        if self._settings.e2b_api_key is None:
            raise SandboxUnavailableError("E2B_API_KEY is not set")
        return {
            "api_key": self._settings.e2b_api_key.get_secret_value(),
            "request_timeout": self._settings.e2b_request_timeout_s,
        }

    def _wrap(self, sandbox: AsyncSandbox) -> E2BSandbox:
        return E2BSandbox(
            sandbox,
            request_timeout_s=self._settings.e2b_request_timeout_s,
            scan_script=self._settings.scan_script_path,
        )

    async def create(self, *, metadata: dict[str, str], timeout_s: int) -> E2BSandbox:
        sandbox = await AsyncSandbox.create(
            template=self._settings.e2b_template,
            timeout=timeout_s,
            metadata=metadata,
            # Safety net: if a workflow dies mid-run, pause at timeout instead of the
            # API default (kill), which would delete the bot's computer.
            lifecycle={
                "on_timeout": {"action": "pause", "mode": self._settings.sandbox_pause_mode}
            },
            **self._api_opts(),
        )
        return self._wrap(sandbox)

    async def connect(self, sandbox_id: str, *, timeout_s: int) -> E2BSandbox:
        try:
            sandbox = await AsyncSandbox.connect(sandbox_id, timeout=timeout_s, **self._api_opts())
        except NotFoundException as exc:
            raise SandboxGoneError(sandbox_id) from exc
        return self._wrap(sandbox)

    async def pause(self, sandbox_id: str) -> None:
        try:
            await AsyncSandbox.pause(
                sandbox_id, mode=self._settings.sandbox_pause_mode, **self._api_opts()
            )
        except NotFoundException as exc:
            raise SandboxGoneError(sandbox_id) from exc
