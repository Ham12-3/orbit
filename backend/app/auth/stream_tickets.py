"""Short-lived, read-only tickets for live run streams.

A browser EventSource cannot send an Authorization header, so the page first asks for a
ticket (with its normal bearer token) and puts it in the stream URL. A ticket names one user
and one run, and uses its own audience so it can never pass as a run token.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"
AUDIENCE = "orbit-stream"


class StreamTicketError(Exception):
    pass


@dataclass(frozen=True)
class StreamTicket:
    token: str
    expires_at: datetime


def issue_stream_ticket(
    *, secret: str, user_id: uuid.UUID, run_id: uuid.UUID, ttl: timedelta
) -> StreamTicket:
    now = datetime.now(UTC)
    expires_at = now + ttl
    token = jwt.encode(
        {"sub": str(user_id), "run": str(run_id), "aud": AUDIENCE, "iat": now, "exp": expires_at},
        secret,
        algorithm=ALGORITHM,
    )
    return StreamTicket(token=token, expires_at=expires_at)


def verify_stream_ticket(*, secret: str, token: str, run_id: uuid.UUID) -> uuid.UUID:
    """Returns the user id the ticket was issued to."""
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            options={"require": ["exp", "sub", "run", "aud"]},
        )
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise StreamTicketError("invalid stream ticket") from exc
    if claims["run"] != str(run_id):
        raise StreamTicketError("ticket is for another run")
    return user_id
