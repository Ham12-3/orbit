"""Turning a finished chat run into the bot's message in its thread."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, Run, Thread
from app.models.enums import MessageRole, RunStatus

_FALLBACKS = {
    RunStatus.CANCELLED: "Cancelled before I finished.",
    RunStatus.TIMED_OUT: "I ran out of time on this one and stopped.",
}


def reply_text(run: Run) -> str:
    if run.status == RunStatus.COMPLETED and run.final_summary:
        return run.final_summary
    if run.status in _FALLBACKS:
        return _FALLBACKS[run.status]
    return f"I couldn't finish this. {run.error or 'Something went wrong.'}"


async def ensure_bot_reply(session: AsyncSession, run: Run) -> None:
    """Add the bot's reply for a finished chat run, once. Also records the session to resume.

    Called from every place a run can end (finalize, cancelling a queued run), so a thread
    never waits forever for an answer. The caller commits.
    """
    if run.thread_id is None or not run.status.is_terminal:
        return
    already = await session.scalar(
        select(Message.id).where(Message.run_id == run.id, Message.role == MessageRole.BOT)
    )
    if already is not None:
        return
    session.add(
        Message(
            thread_id=run.thread_id, role=MessageRole.BOT, content=reply_text(run), run_id=run.id
        )
    )
    thread = await session.get(Thread, run.thread_id)
    if thread is not None:
        if run.agent_session_id:
            thread.agent_session_id = run.agent_session_id
        thread.updated_at = run.finished_at or thread.updated_at
