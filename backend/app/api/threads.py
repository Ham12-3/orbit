"""Chat: threads and messages. Every query is scoped to the current user through the bot."""

import uuid
from typing import cast

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.bots import get_owned_bot
from app.api.deps import CurrentUserDep, DatabaseDep, RunServicesDep, SessionDep
from app.background import spawn
from app.chat.titles import TitleGenerator, fallback_title
from app.db import Database
from app.models import Bot, Message, Run, Thread
from app.models.enums import MessageRole, RunTrigger
from app.schemas.chat import MessageCreate, MessageRead, ThreadCreate, ThreadDetail, ThreadRead

router = APIRouter(tags=["chat"])


@router.get("/api/bots/{bot_id}/threads")
async def list_threads(
    bot_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> list[ThreadRead]:
    bot = await get_owned_bot(session, user.id, bot_id)
    threads = await session.scalars(
        select(Thread).where(Thread.bot_id == bot.id).order_by(Thread.updated_at.desc()).limit(100)
    )
    return [ThreadRead.model_validate(thread) for thread in threads]


@router.post("/api/bots/{bot_id}/threads", status_code=status.HTTP_201_CREATED)
async def create_thread(
    bot_id: uuid.UUID,
    body: ThreadCreate,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
    db: DatabaseDep,
    runs: RunServicesDep,
) -> ThreadDetail:
    bot = await get_owned_bot(session, user.id, bot_id)
    thread = Thread(bot_id=bot.id, title=fallback_title(body.message))
    session.add(thread)
    await session.flush()
    await _post(session, runs, bot=bot, thread=thread, content=body.message)

    titler = cast(TitleGenerator | None, request.app.state.titler)
    if titler is not None:
        spawn(_retitle(db, titler, thread.id, body.message), name=f"title-{thread.id}")
    return await _detail(session, thread)


@router.get("/api/threads/{thread_id}")
async def get_thread(
    thread_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> ThreadDetail:
    thread = await get_owned_thread(session, user.id, thread_id)
    return await _detail(session, thread)


@router.post("/api/threads/{thread_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def post_message(
    thread_id: uuid.UUID,
    body: MessageCreate,
    user: CurrentUserDep,
    session: SessionDep,
    runs: RunServicesDep,
) -> ThreadDetail:
    thread = await get_owned_thread(session, user.id, thread_id)
    bot = await get_owned_bot(session, user.id, thread.bot_id)
    await _post(session, runs, bot=bot, thread=thread, content=body.content)
    return await _detail(session, thread)


async def get_owned_thread(
    session: AsyncSession, user_id: uuid.UUID, thread_id: uuid.UUID
) -> Thread:
    thread = await session.scalar(
        select(Thread)
        .join(Bot, Bot.id == Thread.bot_id)
        .where(Thread.id == thread_id, Bot.user_id == user_id)
    )
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    return thread


async def _post(
    session: AsyncSession, runs: RunServicesDep, *, bot: Bot, thread: Thread, content: str
) -> None:
    """Store the user's message and queue the chat run that answers it."""
    message = Message(thread_id=thread.id, role=MessageRole.USER, content=content)
    session.add(message)
    await session.flush()
    run = await runs.enqueue(
        session, bot=bot, prompt=content, trigger=RunTrigger.CHAT, thread_id=thread.id
    )
    message.run_id = run.id
    await session.commit()


async def _detail(session: AsyncSession, thread: Thread) -> ThreadDetail:
    await session.refresh(thread)
    rows = await session.execute(
        select(Message, Run.status)
        .outerjoin(Run, Run.id == Message.run_id)
        .where(Message.thread_id == thread.id)
        .order_by(Message.created_at, Message.role.desc())  # user before bot on ties
    )
    messages = [
        MessageRead(
            id=message.id,
            role=message.role,
            content=message.content,
            run_id=message.run_id,
            run_status=run_status,
            created_at=message.created_at,
        )
        for message, run_status in rows
    ]
    pending = [
        m.run_id
        for m in messages
        if m.role == MessageRole.USER and m.run_status is not None and not m.run_status.is_terminal
    ]
    return ThreadDetail(
        **ThreadRead.model_validate(thread).model_dump(),
        messages=messages,
        active_run_id=pending[-1] if pending else None,
    )


async def _retitle(
    db: Database, titler: TitleGenerator, thread_id: uuid.UUID, message: str
) -> None:
    title = await titler.title(message)
    if not title:
        return
    async with db.session() as session:
        thread = await session.get(Thread, thread_id)
        if thread is not None:
            thread.title = title
            await session.commit()
