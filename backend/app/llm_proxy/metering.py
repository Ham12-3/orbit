"""Recording proxied LLM usage and checking daily budgets."""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm_proxy.pricing import Usage, cost_usd
from app.models import LlmUsage, Run


def utc_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def tokens_used_today(session: AsyncSession, bot_id: uuid.UUID, *, now: datetime) -> int:
    """Budget tokens (see Usage.budget_tokens) spent since 00:00 UTC."""
    total = await session.scalar(
        select(
            func.coalesce(
                func.sum(
                    LlmUsage.input_tokens + LlmUsage.cache_write_tokens + LlmUsage.output_tokens
                ),
                0,
            )
        ).where(LlmUsage.bot_id == bot_id, LlmUsage.created_at >= utc_day_start(now))
    )
    return int(total or 0)


async def record_usage(
    session: AsyncSession, *, run_id: uuid.UUID, bot_id: uuid.UUID, model: str, usage: Usage
) -> None:
    cost = cost_usd(model, usage)
    session.add(
        LlmUsage(
            run_id=run_id,
            bot_id=bot_id,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=cost,
        )
    )
    await session.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(
            input_tokens=Run.input_tokens + usage.input_tokens,
            output_tokens=Run.output_tokens + usage.output_tokens,
            cache_read_tokens=Run.cache_read_tokens + usage.cache_read_tokens,
            cache_write_tokens=Run.cache_write_tokens + usage.cache_write_tokens,
            cost_usd=Run.cost_usd + cost,
        )
    )
