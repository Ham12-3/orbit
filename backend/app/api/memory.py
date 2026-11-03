"""Dashboard routes for a bot's memory files. Changes reach the sandbox at the next run start."""

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bots import get_owned_bot
from app.api.deps import CurrentUserDep, SessionDep
from app.memory.paths import (
    MEMORY_FILE_MAX_BYTES,
    MEMORY_MAX_FILES,
    InvalidMemoryPathError,
    check_memory_path,
)
from app.memory.sync import content_hash
from app.models import MemoryFile
from app.models.enums import MemoryAuthor, MemorySyncState
from app.schemas.memory import MemoryFileDetail, MemoryFileRead, MemoryFileWrite

router = APIRouter(prefix="/api/bots/{bot_id}/memory", tags=["memory"])

LIVE = MemoryFile.sync_state != MemorySyncState.DELETE


@router.get("")
async def list_memory(
    bot_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> list[MemoryFileRead]:
    bot = await get_owned_bot(session, user.id, bot_id)
    files = await session.scalars(
        select(MemoryFile).where(MemoryFile.bot_id == bot.id, LIVE).order_by(MemoryFile.path)
    )
    return [MemoryFileRead.of(file) for file in files]


@router.get("/{path:path}")
async def get_memory_file(
    bot_id: uuid.UUID, path: str, user: CurrentUserDep, session: SessionDep
) -> MemoryFileDetail:
    bot = await get_owned_bot(session, user.id, bot_id)
    return MemoryFileDetail.of(await _get_live(session, bot.id, path))


@router.put("/{path:path}")
async def put_memory_file(
    bot_id: uuid.UUID,
    path: str,
    body: MemoryFileWrite,
    user: CurrentUserDep,
    session: SessionDep,
) -> MemoryFileDetail:
    """Create or replace a file. The bot sees it from its next run."""
    bot = await get_owned_bot(session, user.id, bot_id)
    try:
        path = check_memory_path(path)
    except InvalidMemoryPathError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    data = body.content.encode("utf-8")
    if len(data) > MEMORY_FILE_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Memory files can be at most {MEMORY_FILE_MAX_BYTES // 1024} KB.",
        )
    exists = await session.scalar(
        select(MemoryFile.id).where(MemoryFile.bot_id == bot.id, MemoryFile.path == path)
    )
    if exists is None:
        count = await session.scalar(
            select(func.count()).select_from(MemoryFile).where(MemoryFile.bot_id == bot.id, LIVE)
        )
        if (count or 0) >= MEMORY_MAX_FILES:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"A bot can have at most {MEMORY_MAX_FILES} files."
            )
    values = {
        "content": body.content,
        "content_hash": content_hash(data),
        "updated_by": MemoryAuthor.USER,
        "sync_state": MemorySyncState.PUSH,
    }
    await session.execute(
        insert(MemoryFile)
        .values(id=uuid.uuid4(), bot_id=bot.id, path=path, **values)
        .on_conflict_do_update(
            index_elements=["bot_id", "path"], set_={**values, "updated_at": func.now()}
        )
    )
    await session.commit()
    return MemoryFileDetail.of(await _get_live(session, bot.id, path))


@router.delete("/{path:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory_file(
    bot_id: uuid.UUID, path: str, user: CurrentUserDep, session: SessionDep
) -> Response:
    """The bot's copy is removed at the start of its next run."""
    bot = await get_owned_bot(session, user.id, bot_id)
    file = await _get_live(session, bot.id, path)
    await session.execute(
        update(MemoryFile)
        .where(MemoryFile.id == file.id)
        .values(sync_state=MemorySyncState.DELETE, updated_by=MemoryAuthor.USER)
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _get_live(session: AsyncSession, bot_id: uuid.UUID, path: str) -> MemoryFile:
    file = await session.scalar(
        select(MemoryFile)
        .where(MemoryFile.bot_id == bot_id, MemoryFile.path == path, LIVE)
        .execution_options(populate_existing=True)
    )
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memory file not found")
    return file
