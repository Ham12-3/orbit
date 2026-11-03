"""Dashboard routes for bots. Every query is scoped to the current user."""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserDep, RunServicesDep, SessionDep, SettingsDep
from app.llm_proxy.metering import utc_day_start
from app.models import Bot, LlmUsage, Run
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
    return (await _with_stats(session, [bot]))[0]


@router.get("")
async def list_bots(user: CurrentUserDep, session: SessionDep) -> list[BotRead]:
    bots = list(
        await session.scalars(select(Bot).where(Bot.user_id == user.id).order_by(Bot.created_at))
    )
    return await _with_stats(session, bots)


@router.get("/by-slug/{slug}")
async def get_bot_by_slug(slug: str, user: CurrentUserDep, session: SessionDep) -> BotRead:
    bot = await session.scalar(select(Bot).where(Bot.slug == slug, Bot.user_id == user.id))
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bot not found")
    return (await _with_stats(session, [bot]))[0]


@router.get("/{bot_id}")
async def get_bot(bot_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> BotRead:
    bot = await get_owned_bot(session, user.id, bot_id)
    return (await _with_stats(session, [bot]))[0]


@router.get("/{bot_id}/runs")
async def list_runs(
    bot_id: uuid.UUID,
    user: CurrentUserDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[RunRead]:
    bot = await get_owned_bot(session, user.id, bot_id)
    runs = await session.scalars(
        select(Run).where(Run.bot_id == bot.id).order_by(Run.created_at.desc()).limit(limit)
    )
    return [RunRead.model_validate(run) for run in runs]


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


async def _with_stats(session: AsyncSession, bots: list[Bot]) -> list[BotRead]:
    """BotRead plus last run and today's spend, in two queries for the whole list."""
    ids = [bot.id for bot in bots]
    if not ids:
        return []
    last_runs = await session.execute(
        select(Run.bot_id, Run.status, Run.created_at)
        .ext(distinct_on(Run.bot_id))
        .where(Run.bot_id.in_(ids))
        .order_by(Run.bot_id, Run.created_at.desc())
    )
    last: dict[uuid.UUID, dict[str, Any]] = {
        bot_id: {"last_run_status": run_status, "last_run_at": created_at}
        for bot_id, run_status, created_at in last_runs
    }
    spend = await session.execute(
        select(LlmUsage.bot_id, func.sum(LlmUsage.cost_usd))
        .where(LlmUsage.bot_id.in_(ids), LlmUsage.created_at >= utc_day_start(datetime.now(UTC)))
        .group_by(LlmUsage.bot_id)
    )
    cost_today = {bot_id: float(total or 0) for bot_id, total in spend}
    return [
        BotRead.model_validate(bot).model_copy(
            update={**last.get(bot.id, {}), "cost_today_usd": cost_today.get(bot.id, 0.0)}
        )
        for bot in bots
    ]


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
