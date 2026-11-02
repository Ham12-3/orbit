"""Dashboard routes for bots. Every query is scoped to the current user."""

import re
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, RunServicesDep, SessionDep, SettingsDep
from app.models import Bot
from app.schemas.bots import BotCreate, BotRead
from app.schemas.runs import RunCreate, RunRead

router = APIRouter(prefix="/api/bots", tags=["bots"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_bot(
    body: BotCreate, user: CurrentUserDep, session: SessionDep, settings: SettingsDep
) -> BotRead:
    bot = Bot(
        user_id=user.id,
        name=body.name.strip(),
        slug=await _unique_slug(session, user.id, body.name),
        avatar_emoji=body.avatar_emoji,
        job_description=body.job_description.strip(),
        instructions=body.instructions,
        model=body.model or settings.default_model,
        max_turns_per_run=body.max_turns_per_run or settings.default_max_turns,
        daily_token_budget=body.daily_token_budget or settings.default_daily_token_budget,
    )
    session.add(bot)
    await session.commit()
    await session.refresh(bot)
    return BotRead.model_validate(bot)


@router.get("")
async def list_bots(user: CurrentUserDep, session: SessionDep) -> list[BotRead]:
    bots = await session.scalars(select(Bot).where(Bot.user_id == user.id).order_by(Bot.created_at))
    return [BotRead.model_validate(bot) for bot in bots]


@router.get("/{bot_id}")
async def get_bot(bot_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> BotRead:
    return BotRead.model_validate(await get_owned_bot(session, user.id, bot_id))


@router.post("/{bot_id}/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    bot_id: uuid.UUID,
    body: RunCreate,
    user: CurrentUserDep,
    session: SessionDep,
    runs: RunServicesDep,
) -> RunRead:
    bot = await get_owned_bot(session, user.id, bot_id)
    run = await runs.enqueue(session, bot=bot, prompt=body.prompt)
    return RunRead.model_validate(run)


async def get_owned_bot(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> Bot:
    bot = await session.scalar(select(Bot).where(Bot.id == bot_id, Bot.user_id == user_id))
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot not found")
    return bot


async def _unique_slug(session: AsyncSession, user_id: uuid.UUID, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "bot"
    taken = set(
        await session.scalars(
            select(Bot.slug).where(Bot.user_id == user_id, Bot.slug.startswith(base))
        )
    )
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug
