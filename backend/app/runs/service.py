"""Run lifecycle: queue, claim the bot, start the runner in its sandbox, watch, finish.

The Inngest workflow calls these methods as durable steps, so each one opens its own DB
session, is safe to retry, and returns plain JSON values. Status changes are conditional
UPDATEs because a cancel or a runner callback can land at any moment.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, and_, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.run_tokens import issue_run_token, revoke_run_tokens
from app.chat.replies import ensure_bot_reply
from app.config import Settings
from app.db import Database
from app.events import RUN_FINISHED, RUN_REQUESTED, EventSender
from app.llm_proxy.metering import tokens_used_today
from app.models import Bot, Run, Thread
from app.models.enums import TERMINAL_RUN_STATUSES, BotStatus, RunEventType, RunStatus, RunTrigger
from app.runs.timeline import add_system_event
from app.sandboxes import layout
from app.sandboxes.provider import Sandbox, SandboxGoneError, SandboxProvider

logger = logging.getLogger(__name__)

ACTIVE = (RunStatus.QUEUED, RunStatus.STARTING, RunStatus.RUNNING)
STARTED = (RunStatus.STARTING, RunStatus.RUNNING)
STALE_GRACE = timedelta(minutes=10)
QUEUE_DISPATCH_DELAY = timedelta(seconds=30)
SANDBOX_CALL_TIMEOUT_S = 90


class ConfigurationError(Exception):
    """Settings needed to run bots are missing. Retrying will not help."""


class RunStateError(Exception):
    """The run is not in a state that allows this action."""


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class RunServices:
    db: Database
    sandboxes: SandboxProvider
    events: EventSender
    settings: Settings

    # ---- Queue ---------------------------------------------------------------------

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        bot: Bot,
        prompt: str,
        trigger: RunTrigger = RunTrigger.MANUAL,
        trigger_ref: str | None = None,
        thread_id: uuid.UUID | None = None,
    ) -> Run:
        run = Run(
            bot_id=bot.id,
            trigger_type=trigger,
            trigger_ref=trigger_ref,
            thread_id=thread_id,
            input_prompt=prompt,
            status=RunStatus.QUEUED,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        await self._send(RUN_REQUESTED, run.id)
        return run

    async def claim(self, run_id: str, workflow_run_id: str) -> bool:
        """Make this run its bot's active run. False if the bot is busy (the run stays queued)."""
        async with self.db.session() as s:
            bot_id = await s.scalar(select(Run.bot_id).where(Run.id == uuid.UUID(run_id)))
            if bot_id is None:
                return False
            # Locking the bot row serialises claims for the same bot.
            bot = await s.scalar(select(Bot).where(Bot.id == bot_id).with_for_update())
            run = await s.scalar(select(Run).where(Run.id == uuid.UUID(run_id)).with_for_update())
            if bot is None or run is None:
                return False
            if run.status != RunStatus.QUEUED:
                # A retried claim step of the same workflow must still succeed.
                return run.workflow_run_id == workflow_run_id and run.status in STARTED
            if bot.active_run_id not in (None, run.id):
                return False
            if not bot.enabled:
                await self._finish(s, run.id, RunStatus.FAILED, error="The bot is disabled.")
                await s.commit()
                return False
            bot.active_run_id = run.id
            bot.status = BotStatus.RUNNING
            run.status = RunStatus.STARTING
            run.workflow_run_id = workflow_run_id
            run.started_at = utcnow()
            add_system_event(s, run.id, RunEventType.STATUS, "Run started")
            await s.commit()
            return True

    # ---- Start ---------------------------------------------------------------------

    async def start(self, run_id: str) -> dict[str, Any]:
        rid = uuid.UUID(run_id)
        secret = self._require_run_config()
        async with self.db.session() as s:
            run, bot = await self._load(s, rid)
            if run.status.is_terminal:
                return {"skipped": run.status.value}

            used = await tokens_used_today(s, bot.id, now=utcnow())
            if used >= bot.daily_token_budget:
                await self._finish(
                    s, rid, RunStatus.FAILED, error=budget_message(used, bot.daily_token_budget)
                )
                await s.commit()
                return {"skipped": "budget"}

            sandbox = await self._open_sandbox(s, bot, rid)
            await sandbox.make_dirs(layout.WORKSPACE_DIR, layout.MEMORY_DIR, layout.run_dir(rid))
            await sandbox.write_text(layout.CLAUDE_MD_PATH, layout.render_claude_md(bot))
            await sandbox.write_text(layout.prompt_path(rid), run.input_prompt)
            await sandbox.write_text(
                layout.RUNNER_SCRIPT,
                self.settings.runner_script_path.read_text(encoding="utf-8"),
                as_root=True,
            )

            # A retried start step must not leave a second runner or a live token behind.
            await sandbox.kill_run_processes(rid)
            await revoke_run_tokens(s, rid)
            token = issue_run_token(
                s,
                secret=secret,
                run_id=rid,
                bot_id=bot.id,
                ttl=timedelta(
                    seconds=self.settings.run_timeout_s + self.settings.run_token_margin_s
                ),
            )
            run.sandbox_id = sandbox.sandbox_id
            run.deadline_at = utcnow() + timedelta(seconds=self.settings.run_timeout_s)
            await s.commit()

            pid = await sandbox.start_background(
                layout.runner_command(rid),
                envs=layout.runner_env(
                    settings=self.settings,
                    bot=bot,
                    run_id=rid,
                    run_token=token,
                    # Read now, not at enqueue: the previous turn may have just finished.
                    resume_session_id=await self._thread_session(s, run),
                ),
                cwd=layout.BOT_HOME,
            )
            started = await self._transition(
                s, rid, (RunStatus.STARTING,), status=RunStatus.RUNNING, runner_pid=pid
            )
            if not started:  # cancelled while we were starting
                await sandbox.kill_run_processes(rid)
                await s.commit()
                return {"skipped": "cancelled"}
            add_system_event(
                s, rid, RunEventType.STATUS, "Runner started", sandbox_id=sandbox.sandbox_id
            )
            await s.commit()
            return {"sandbox_id": sandbox.sandbox_id, "pid": pid}

    async def _open_sandbox(self, s: AsyncSession, bot: Bot, run_id: uuid.UUID) -> Sandbox:
        timeout_s = self.settings.run_timeout_s + self.settings.run_token_margin_s
        if bot.sandbox_id:
            try:
                return await self.sandboxes.connect(bot.sandbox_id, timeout_s=timeout_s)
            except SandboxGoneError:
                add_system_event(
                    s,
                    run_id,
                    RunEventType.STATUS,
                    "The bot's previous computer no longer exists; created a new one.",
                )
        sandbox = await self.sandboxes.create(
            metadata={"bot_id": str(bot.id), "user_id": str(bot.user_id)}, timeout_s=timeout_s
        )
        bot.sandbox_id = sandbox.sandbox_id
        await s.commit()  # keep the id even if a later step fails
        return sandbox

    # ---- Watch ---------------------------------------------------------------------

    async def check(self, run_id: str) -> str:
        """Called after each wait slice. Returns "done" or "running"."""
        rid = uuid.UUID(run_id)
        async with self.db.session() as s:
            run = await s.get(Run, rid)
            if run is None or run.status.is_terminal:
                return "done"

            if run.deadline_at is not None and utcnow() >= run.deadline_at:
                await self._kill_runner_quietly(run)
                minutes = self.settings.run_timeout_s // 60
                if await self._finish(
                    s, rid, RunStatus.TIMED_OUT, error=f"The run hit its {minutes} minute limit."
                ):
                    add_system_event(s, rid, RunEventType.ERROR, "Run timed out")
                await s.commit()
                return "done"

            if run.sandbox_id and run.runner_pid is not None:
                alive = await self._runner_alive(run.sandbox_id, run.runner_pid)
                if alive is False:
                    await s.refresh(run)
                    if run.status.is_terminal:
                        return "done"
                    error = "The runner stopped without reporting a result (see its runner.log)."
                    if await self._finish(s, rid, RunStatus.FAILED, error=error):
                        add_system_event(s, rid, RunEventType.ERROR, error)
                    await s.commit()
                    return "done"
            return "running"

    async def _runner_alive(self, sandbox_id: str, pid: int) -> bool | None:
        """True/False when known, None when the sandbox could not be reached."""
        try:
            async with asyncio.timeout(SANDBOX_CALL_TIMEOUT_S):
                sandbox = await self.sandboxes.connect(
                    sandbox_id,
                    timeout_s=self.settings.run_timeout_s + self.settings.run_token_margin_s,
                )
                return await sandbox.is_running(pid)
        except SandboxGoneError:
            return False
        except Exception:
            logger.warning(
                "Could not check runner %s in sandbox %s", pid, sandbox_id, exc_info=True
            )
            return None

    # ---- Finish --------------------------------------------------------------------

    async def complete_from_runner(
        self,
        session: AsyncSession,
        run_id: uuid.UUID,
        *,
        succeeded: bool,
        summary: str | None,
        error: str | None,
        agent_session_id: str | None,
        num_turns: int | None,
    ) -> None:
        # Keep an error the server already recorded (e.g. budget exhausted): it is clearer.
        existing_error = await session.scalar(select(Run.error).where(Run.id == run_id))
        finished = await self._finish(
            session,
            run_id,
            RunStatus.COMPLETED if succeeded else RunStatus.FAILED,
            from_statuses=STARTED,
            error=existing_error or (None if succeeded else error),
            final_summary=summary,
            agent_session_id=agent_session_id,
            num_turns=num_turns,
        )
        if finished:
            add_system_event(
                session,
                run_id,
                RunEventType.STATUS,
                "Run completed" if succeeded else "Run failed",
            )
        await session.commit()
        await self._send(RUN_FINISHED, run_id)

    async def finalize(self, run_id: str) -> str | None:
        """Close out a run: revoke its token, stop and pause the sandbox, release the bot.

        Returns the next queued run for the bot, if any, for the caller to dispatch.
        """
        rid = uuid.UUID(run_id)
        async with self.db.session() as s:
            run = await s.get(Run, rid)
            if run is None:
                return None
            if not run.status.is_terminal:
                await self._finish(
                    s, rid, RunStatus.FAILED, error="The run ended without a result."
                )
            await revoke_run_tokens(s, rid)
            await s.commit()

            if run.sandbox_id:
                await self._stop_sandbox(run.sandbox_id, rid)

            await s.refresh(run)
            await ensure_bot_reply(s, run)  # normally already written by _finish
            next_run_id = await self._release_bot(s, bot_id=run.bot_id, run_id=rid)
            await s.commit()
            return str(next_run_id) if next_run_id else None

    async def fail(self, run_id: str, message: str) -> str | None:
        """Workflow gave up (all retries failed). Record why, then finalize."""
        rid = uuid.UUID(run_id)
        async with self.db.session() as s:
            if await self._finish(s, rid, RunStatus.FAILED, error=f"Orbit error: {message}"):
                add_system_event(s, rid, RunEventType.ERROR, message)
            await s.commit()
        return await self.finalize(run_id)

    async def cancel(self, session: AsyncSession, run: Run) -> Run:
        if run.status.is_terminal:
            raise RunStateError(f"Run is already {run.status.value}")
        was_queued = run.status == RunStatus.QUEUED
        if not await self._finish(
            session, run.id, RunStatus.CANCELLED, error="Cancelled by the user."
        ):
            raise RunStateError("Run finished before it could be cancelled")
        add_system_event(session, run.id, RunEventType.STATUS, "Run cancelled")
        await revoke_run_tokens(session, run.id)
        await session.commit()
        await session.refresh(run)
        if not was_queued:
            await self._kill_runner_quietly(run)
            await self._send(RUN_FINISHED, run.id)
        return run

    # ---- Sweeper -------------------------------------------------------------------

    async def recover_stale(self) -> list[str]:
        """Finalize runs whose workflow died (e.g. the Inngest Dev Server restarted)."""
        cutoff = utcnow() - STALE_GRACE
        started_cutoff = cutoff - timedelta(seconds=self.settings.run_timeout_s)
        async with self.db.session() as s:
            past_deadline = select(Run.id).where(
                Run.status.in_(STARTED),
                or_(
                    Run.deadline_at < cutoff,
                    and_(Run.deadline_at.is_(None), Run.started_at < started_cutoff),
                ),
            )
            finished_but_held = (
                select(Run.id)
                .join(Bot, Bot.active_run_id == Run.id)
                .where(Run.status.in_(TERMINAL_RUN_STATUSES), Run.finished_at < cutoff)
            )
            stale = list(await s.scalars(past_deadline.union(finished_but_held)))
        next_runs: list[str] = []
        for rid in stale:
            logger.warning("Recovering stale run %s", rid)
            next_run = await self.finalize(str(rid))
            if next_run:
                next_runs.append(next_run)
        return next_runs

    async def dispatchable(self) -> list[str]:
        """Oldest queued run of every idle bot, for runs whose own event may have been lost."""
        cutoff = utcnow() - QUEUE_DISPATCH_DELAY
        async with self.db.session() as s:
            rows = await s.scalars(
                select(Run.id)
                .ext(distinct_on(Run.bot_id))
                .join(Bot, Bot.id == Run.bot_id)
                .where(
                    Run.status == RunStatus.QUEUED,
                    Run.created_at < cutoff,
                    Bot.active_run_id.is_(None),
                    Bot.enabled.is_(True),
                )
                .order_by(Run.bot_id, Run.created_at)
            )
            return [str(rid) for rid in rows]

    # ---- Helpers -------------------------------------------------------------------

    def _require_run_config(self) -> str:
        if self.settings.run_token_secret is None:
            raise ConfigurationError("RUN_TOKEN_SECRET is not set")
        if not self.settings.public_base_url:
            raise ConfigurationError(
                "PUBLIC_BASE_URL is not set: sandboxes need a public URL to reach the backend"
            )
        return self.settings.run_token_secret.get_secret_value()

    async def _load(self, s: AsyncSession, run_id: uuid.UUID) -> tuple[Run, Bot]:
        run = await s.get(Run, run_id)
        bot = await s.get(Bot, run.bot_id) if run else None
        if run is None or bot is None:
            raise RunStateError(f"Run {run_id} not found")
        return run, bot

    async def _thread_session(self, s: AsyncSession, run: Run) -> str | None:
        if run.thread_id is None:
            return None
        return await s.scalar(select(Thread.agent_session_id).where(Thread.id == run.thread_id))

    async def _transition(
        self,
        s: AsyncSession,
        run_id: uuid.UUID,
        from_statuses: tuple[RunStatus, ...],
        **values: Any,
    ) -> bool:
        result = await s.execute(
            update(Run).where(Run.id == run_id, Run.status.in_(from_statuses)).values(**values)
        )
        return cast(CursorResult[Any], result).rowcount > 0

    async def _finish(
        self,
        s: AsyncSession,
        run_id: uuid.UUID,
        status: RunStatus,
        *,
        from_statuses: tuple[RunStatus, ...] = ACTIVE,
        **values: Any,
    ) -> bool:
        finished = await self._transition(
            s, run_id, from_statuses, status=status, finished_at=utcnow(), **values
        )
        if finished:
            # Same transaction as the status change: whoever sees the run finished (the live
            # stream, a page refetch) also sees the bot's reply in its chat thread.
            run = await s.get(Run, run_id, populate_existing=True)
            if run is not None:
                await ensure_bot_reply(s, run)
        return finished

    async def _release_bot(
        self, s: AsyncSession, *, bot_id: uuid.UUID, run_id: uuid.UUID
    ) -> uuid.UUID | None:
        bot = await s.scalar(select(Bot).where(Bot.id == bot_id).with_for_update())
        if bot is None:
            return None
        if bot.active_run_id == run_id:
            bot.active_run_id = None
            bot.status = BotStatus.IDLE
        if bot.active_run_id is not None:
            return None
        return await s.scalar(
            select(Run.id)
            .where(Run.bot_id == bot_id, Run.status == RunStatus.QUEUED)
            .order_by(Run.created_at)
            .limit(1)
        )

    async def _stop_sandbox(self, sandbox_id: str, run_id: uuid.UUID) -> None:
        """Best effort. If this fails, the sandbox still auto-pauses at its timeout."""
        try:
            async with asyncio.timeout(SANDBOX_CALL_TIMEOUT_S):
                sandbox = await self.sandboxes.connect(sandbox_id, timeout_s=300)
                await sandbox.kill_run_processes(run_id)
                await self.sandboxes.pause(sandbox_id)
        except SandboxGoneError:
            pass
        except Exception:
            logger.warning(
                "Could not pause sandbox %s after run %s", sandbox_id, run_id, exc_info=True
            )

    async def _kill_runner_quietly(self, run: Run) -> None:
        if not run.sandbox_id:
            return
        try:
            async with asyncio.timeout(SANDBOX_CALL_TIMEOUT_S):
                sandbox = await self.sandboxes.connect(run.sandbox_id, timeout_s=300)
                await sandbox.kill_run_processes(run.id)
        except Exception:
            logger.warning("Could not kill the runner for run %s", run.id, exc_info=True)

    async def _send(self, name: str, run_id: uuid.UUID) -> None:
        """Lost events are recovered by the sweeper, so a send failure is not fatal."""
        try:
            await self.events.send(name, {"run_id": str(run_id)})
        except Exception:
            logger.warning("Could not send %s for run %s", name, run_id, exc_info=True)


def budget_message(used: int, budget: int) -> str:
    return (
        f"This bot has used its daily token budget ({used:,} of {budget:,} tokens). "
        "Raise the budget or wait until tomorrow (UTC)."
    )
