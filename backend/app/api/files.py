"""Read-only view of a bot's workspace/ folder.

The listing comes from the snapshot taken when the last run ended (nothing else changes the
workspace), so browsing never wakes the sandbox. Opening a file, or asking for a live
listing, does: E2B resumes it and it pauses again on its own after FILE_BROWSE_TIMEOUT_S.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import update

from app.api.bots import get_owned_bot
from app.api.deps import CurrentUserDep, RunServicesDep, SessionDep
from app.models import Bot
from app.sandboxes import layout
from app.sandboxes.provider import (
    Sandbox,
    SandboxFileNotFoundError,
    SandboxGoneError,
    SandboxUnavailableError,
)
from app.schemas.files import WorkspaceListing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bots/{bot_id}/files", tags=["files"])

FILE_BROWSE_TIMEOUT_S = 300  # how long a sandbox woken just to read a file stays up
FILE_MAX_BYTES = 10 * 1024 * 1024
SANDBOX_WAIT_S = 60
LIVE_SCAN_MAX_ENTRIES = 2000


@router.get("")
async def list_files(
    bot_id: uuid.UUID,
    user: CurrentUserDep,
    session: SessionDep,
    runs: RunServicesDep,
    live: Annotated[bool, Query(description="List the sandbox now (wakes it)")] = False,
) -> WorkspaceListing:
    bot = await get_owned_bot(session, user.id, bot_id)
    if not live:
        if bot.workspace_snapshot is None:
            return WorkspaceListing(scanned_at=None, truncated=False, entries=[])
        return WorkspaceListing.model_validate(bot.workspace_snapshot)
    sandbox = await _open(runs, bot)
    try:
        async with asyncio.timeout(SANDBOX_WAIT_S):
            scan = await sandbox.scan_tree(layout.WORKSPACE_DIR, max_entries=LIVE_SCAN_MAX_ENTRIES)
    except Exception as exc:
        logger.warning("Live workspace listing failed for bot %s", bot.id, exc_info=True)
        raise _unavailable() from exc
    listing = WorkspaceListing(
        scanned_at=datetime.now(UTC), truncated=scan.truncated, entries=scan.entries
    )
    if bot.active_run_id is None:  # a running bot's listing is saved when its run ends
        await session.execute(
            update(Bot)
            .where(Bot.id == bot.id)
            .values(workspace_snapshot=listing.model_dump(mode="json"))
        )
        await session.commit()
    return listing


@router.get("/content/{path:path}")
async def read_file(
    bot_id: uuid.UUID,
    path: str,
    user: CurrentUserDep,
    session: SessionDep,
    runs: RunServicesDep,
) -> Response:
    """The file's bytes, always as a download (never rendered by the browser)."""
    bot = await get_owned_bot(session, user.id, bot_id)
    try:
        target = layout.workspace_file_path(path)
    except layout.InvalidWorkspacePathError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid file path") from exc
    sandbox = await _open(runs, bot)
    try:
        async with asyncio.timeout(SANDBOX_WAIT_S):
            info = await sandbox.stat(target)
            if info.kind != "file":  # symlinks are never followed
                raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
            if info.size > FILE_MAX_BYTES:
                raise HTTPException(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    f"Files over {FILE_MAX_BYTES // (1024 * 1024)} MB can't be opened here.",
                )
            data = await sandbox.read_bytes(target)
    except SandboxFileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Reading %s failed for bot %s", path, bot.id, exc_info=True)
        raise _unavailable() from exc
    name = path.rsplit("/", 1)[-1]
    return Response(
        content=data,
        # The bytes are untrusted (anything the bot wrote, e.g. HTML from a web page), so the
        # browser must never render them on Orbit's origin: download only, no sniffing.
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "no-store",
        },
    )


async def _open(runs: RunServicesDep, bot: Bot) -> Sandbox:
    if bot.sandbox_id is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This bot has no computer yet. Run it once first."
        )
    try:
        async with asyncio.timeout(SANDBOX_WAIT_S):
            # Never shortens a running sandbox's timeout (E2B only extends it).
            return await runs.sandboxes.connect(bot.sandbox_id, timeout_s=FILE_BROWSE_TIMEOUT_S)
    except SandboxGoneError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "The bot's computer no longer exists. Its next run creates a new one.",
        ) from exc
    except SandboxUnavailableError as exc:
        raise _unavailable() from exc
    except Exception as exc:
        logger.warning("Could not open the sandbox of bot %s", bot.id, exc_info=True)
        raise _unavailable() from exc


def _unavailable() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Couldn't reach the bot's computer. Try again in a moment.",
    )
