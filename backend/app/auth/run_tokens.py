"""Short-lived bearer tokens that let a run's sandbox call /llm, /internal and /mcp.

Tokens are HS256 JWTs. Only their SHA-256 hash is stored, so they can be revoked when a
run ends; a valid signature alone is not enough.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RunToken

ALGORITHM = "HS256"
AUDIENCE = "orbit-run"


class RunTokenError(Exception):
    """The token is malformed, expired, revoked or unknown."""


@dataclass(frozen=True)
class RunPrincipal:
    run_id: uuid.UUID
    bot_id: uuid.UUID


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_run_token(
    session: AsyncSession,
    *,
    secret: str,
    run_id: uuid.UUID,
    bot_id: uuid.UUID,
    ttl: timedelta,
    now: datetime | None = None,
) -> str:
    """Create a token and stage its hash in `session`. The caller commits."""
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + ttl
    token = jwt.encode(
        {
            "sub": str(run_id),
            "bot": str(bot_id),
            "aud": AUDIENCE,
            "iat": issued_at,
            "exp": expires_at,
            "jti": secrets.token_hex(16),
        },
        secret,
        algorithm=ALGORITHM,
    )
    session.add(RunToken(run_id=run_id, token_hash=hash_token(token), expires_at=expires_at))
    return token


async def verify_run_token(session: AsyncSession, *, secret: str, token: str) -> RunPrincipal:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            options={"require": ["exp", "sub", "bot", "aud"]},
        )
        principal = RunPrincipal(run_id=uuid.UUID(claims["sub"]), bot_id=uuid.UUID(claims["bot"]))
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise RunTokenError("invalid run token") from exc

    row = await session.scalar(select(RunToken).where(RunToken.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None or row.run_id != principal.run_id:
        raise RunTokenError("run token revoked or unknown")
    return principal


async def revoke_run_tokens(
    session: AsyncSession, run_id: uuid.UUID, *, now: datetime | None = None
) -> None:
    await session.execute(
        update(RunToken)
        .where(RunToken.run_id == run_id, RunToken.revoked_at.is_(None))
        .values(revoked_at=now or datetime.now(UTC))
    )
