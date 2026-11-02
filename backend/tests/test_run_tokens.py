import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.run_tokens import (
    RunTokenError,
    issue_run_token,
    revoke_run_tokens,
    verify_run_token,
)
from app.db import Database
from app.models import Bot, Run
from app.models.enums import RunTrigger

SECRET = "secret-for-token-tests-0123456789abcdef"


async def _run(db: Database) -> tuple[uuid.UUID, uuid.UUID]:
    async with db.session() as s:
        bot = Bot(
            user_id=uuid.uuid4(),
            name="B",
            slug="b",
            avatar_emoji="🤖",
            job_description="j",
            model="claude-sonnet-5-5",
            daily_token_budget=1000,
            max_turns_per_run=5,
        )
        s.add(bot)
        await s.flush()
        run = Run(bot_id=bot.id, trigger_type=RunTrigger.MANUAL, input_prompt="p")
        s.add(run)
        await s.commit()
        return run.id, bot.id


async def _issue(
    db: Database, run_id: uuid.UUID, bot_id: uuid.UUID, *, now: datetime | None = None
) -> str:
    async with db.session() as s:
        token = issue_run_token(
            s, secret=SECRET, run_id=run_id, bot_id=bot_id, ttl=timedelta(minutes=5), now=now
        )
        await s.commit()
        return token


async def test_valid_token_identifies_its_run(db: Database) -> None:
    run_id, bot_id = await _run(db)
    token = await _issue(db, run_id, bot_id)

    async with db.session() as s:
        principal = await verify_run_token(s, secret=SECRET, token=token)

    assert (principal.run_id, principal.bot_id) == (run_id, bot_id)


async def test_expired_token_is_rejected(db: Database) -> None:
    run_id, bot_id = await _run(db)
    token = await _issue(db, run_id, bot_id, now=datetime.now(UTC) - timedelta(hours=1))

    async with db.session() as s:
        with pytest.raises(RunTokenError):
            await verify_run_token(s, secret=SECRET, token=token)


async def test_revoked_token_is_rejected(db: Database) -> None:
    run_id, bot_id = await _run(db)
    token = await _issue(db, run_id, bot_id)
    async with db.session() as s:
        await revoke_run_tokens(s, run_id)
        await s.commit()

    async with db.session() as s:
        with pytest.raises(RunTokenError):
            await verify_run_token(s, secret=SECRET, token=token)


async def test_token_signed_with_another_secret_is_rejected(db: Database) -> None:
    run_id, bot_id = await _run(db)
    token = await _issue(db, run_id, bot_id)

    async with db.session() as s:
        with pytest.raises(RunTokenError):
            await verify_run_token(s, secret="some-other-secret-0123456789abcdef-xyz", token=token)


async def test_unknown_but_well_signed_token_is_rejected(db: Database) -> None:
    run_id, bot_id = await _run(db)
    token = await _issue(db, run_id, bot_id)
    async with db.session() as s:  # a token whose hash was never stored
        forged = issue_run_token(
            s, secret=SECRET, run_id=run_id, bot_id=bot_id, ttl=timedelta(minutes=5)
        )
        await s.rollback()
        assert forged != token
        with pytest.raises(RunTokenError):
            await verify_run_token(s, secret=SECRET, token=forged)
