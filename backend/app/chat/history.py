"""A plain-text copy of a thread's recent messages, for when its agent session is lost."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message
from app.models.enums import MessageRole

HISTORY_MAX_MESSAGES = 20
HISTORY_MESSAGE_MAX_CHARS = 2_000
HISTORY_MAX_CHARS = 12_000


def _clip(text: str) -> str:
    text = text.strip()
    if len(text) <= HISTORY_MESSAGE_MAX_CHARS:
        return text
    return f"{text[:HISTORY_MESSAGE_MAX_CHARS]} [...]"


async def recent_history(
    session: AsyncSession, thread_id: uuid.UUID, *, current_run_id: uuid.UUID
) -> str:
    """The messages before this run's, oldest first, within HISTORY_MAX_CHARS."""
    rows = list(
        await session.scalars(
            select(Message)
            .where(
                Message.thread_id == thread_id,
                or_(Message.run_id.is_(None), Message.run_id != current_run_id),
            )
            .order_by(Message.created_at.desc())
            .limit(HISTORY_MAX_MESSAGES)
        )
    )
    lines: list[str] = []
    used = 0
    for message in rows:  # newest first, so the oldest are the ones dropped
        speaker = "Owner" if message.role == MessageRole.USER else "You"
        line = f"{speaker}: {_clip(message.content)}"
        if used + len(line) > HISTORY_MAX_CHARS:
            break
        used += len(line)
        lines.append(line)
    return "\n\n".join(reversed(lines))
