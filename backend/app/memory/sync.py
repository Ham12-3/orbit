"""Keep the bot's memory/ folder and the memory_files table in step.

`push_memory` runs at run start, before the runner launches. `pull_memory` runs when a run
ends, after the runner is stopped. User edits and deletes (sync_state push/delete) win over
the sandbox; everything else the bot writes wins over the table. Every write is conditional,
so a user edit that lands mid-sync is never overwritten.
"""

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.paths import (
    MEMORY_FILE_MAX_BYTES,
    MEMORY_MAX_FILES,
    InvalidMemoryPathError,
    check_memory_path,
)
from app.models import MemoryFile
from app.models.enums import MemoryAuthor, MemorySyncState
from app.sandboxes import layout
from app.sandboxes.provider import Sandbox, SandboxFileNotFoundError

SCAN_MAX_ENTRIES = 1000


def content_hash(content: str | bytes) -> str:
    data = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(data).hexdigest()


def _summary(groups: list[tuple[str, list[str]]]) -> str | None:
    parts = [f"{label} {', '.join(paths)}" for label, paths in groups if paths]
    return f"Memory: {'; '.join(parts)}." if parts else None


@dataclass
class PushResult:
    written: list[str] = field(default_factory=list)  # edited by the user
    restored: list[str] = field(default_factory=list)  # missing from the sandbox
    removed: list[str] = field(default_factory=list)  # deleted by the user

    def summary(self) -> str | None:
        return _summary(
            [
                ("wrote your edits to", self.written),
                ("restored", self.restored),
                ("removed", self.removed),
            ]
        )


@dataclass
class PullResult:
    saved: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # each with the reason

    def summary(self) -> str | None:
        return _summary(
            [("saved", self.saved), ("forgot", self.deleted), ("skipped", self.skipped)]
        )


async def push_memory(s: AsyncSession, sandbox: Sandbox, bot_id: uuid.UUID) -> PushResult:
    """Apply the user's edits and deletes, and restore files the sandbox lost.

    Database changes are added to `s`; the caller commits.
    """
    result = PushResult()
    rows = list(
        await s.scalars(
            select(MemoryFile).where(MemoryFile.bot_id == bot_id).order_by(MemoryFile.path)
        )
    )
    if not rows:
        return result
    scan = await sandbox.scan_tree(layout.MEMORY_DIR, max_entries=SCAN_MAX_ENTRIES)
    present = {entry.path for entry in scan.entries if entry.kind == "file"}
    for row in rows:
        target = layout.memory_file_path(row.path)
        if row.sync_state == MemorySyncState.DELETE:
            await sandbox.remove(target)
            await s.execute(
                delete(MemoryFile).where(
                    MemoryFile.id == row.id, MemoryFile.sync_state == MemorySyncState.DELETE
                )
            )
            result.removed.append(row.path)
        elif row.sync_state == MemorySyncState.PUSH or row.path not in present:
            edited = row.sync_state == MemorySyncState.PUSH
            await sandbox.write_text(target, row.content)
            # Only if the user has not edited it again since we read it.
            await s.execute(
                update(MemoryFile)
                .where(MemoryFile.id == row.id, MemoryFile.content_hash == row.content_hash)
                .values(sync_state=MemorySyncState.SYNCED)
            )
            (result.written if edited else result.restored).append(row.path)
    return result


async def pull_memory(s: AsyncSession, sandbox: Sandbox, bot_id: uuid.UUID) -> PullResult:
    """Save what the bot changed in memory/. Commits."""
    result = PullResult()
    scan = await sandbox.scan_tree(
        layout.MEMORY_DIR, max_entries=SCAN_MAX_ENTRIES, hash_max_bytes=MEMORY_FILE_MAX_BYTES
    )
    if not scan.exists:
        # Never read a missing folder as "the bot forgot everything".
        return result
    rows = {
        row.path: row
        for row in await s.scalars(select(MemoryFile).where(MemoryFile.bot_id == bot_id))
    }
    count = len(rows)
    seen: set[str] = set()
    for entry in sorted(scan.entries, key=lambda e: e.path):
        if entry.kind != "file":
            continue
        try:
            path = check_memory_path(entry.path)
        except InvalidMemoryPathError:
            result.skipped.append(f"{entry.path} (name not allowed)")
            continue
        seen.add(path)
        row = rows.get(path)
        if entry.sha256 is None:
            result.skipped.append(f"{path} (over {MEMORY_FILE_MAX_BYTES // 1024} KB)")
            continue
        if row is not None and (
            row.content_hash == entry.sha256 or row.sync_state != MemorySyncState.SYNCED
        ):
            continue  # unchanged, or the user changed it and their version wins
        if row is None and count >= MEMORY_MAX_FILES:
            result.skipped.append(f"{path} (over {MEMORY_MAX_FILES} files)")
            continue
        try:
            raw = await sandbox.read_bytes(layout.memory_file_path(path))
            content = raw.decode("utf-8")
        except SandboxFileNotFoundError:
            continue
        except UnicodeDecodeError:
            result.skipped.append(f"{path} (not text)")
            continue
        if len(raw) > MEMORY_FILE_MAX_BYTES:  # it grew after the listing
            result.skipped.append(f"{path} (over {MEMORY_FILE_MAX_BYTES // 1024} KB)")
            continue
        values = {
            "content": content,
            "content_hash": content_hash(raw),
            "updated_by": MemoryAuthor.BOT,
        }
        if row is None:
            await s.execute(
                insert(MemoryFile)
                .values(id=uuid.uuid4(), bot_id=bot_id, path=path, **values)
                .on_conflict_do_nothing(index_elements=["bot_id", "path"])
            )
            count += 1
        else:
            await s.execute(
                update(MemoryFile)
                .where(
                    MemoryFile.id == row.id,
                    MemoryFile.sync_state == MemorySyncState.SYNCED,
                    MemoryFile.content_hash == row.content_hash,
                )
                .values(**values)
            )
        result.saved.append(path)
    if not scan.truncated:
        for path, row in sorted(rows.items()):
            if path in seen or row.sync_state != MemorySyncState.SYNCED:
                continue
            await s.execute(
                delete(MemoryFile).where(
                    MemoryFile.id == row.id,
                    MemoryFile.sync_state == MemorySyncState.SYNCED,
                    MemoryFile.content_hash == row.content_hash,
                )
            )
            result.deleted.append(path)
    await s.commit()
    return result
