import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import RunEventType, RunStatus, RunTrigger, db_enum


class Run(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_bot_id_status_created_at", "bot_id", "status", "created_at"),)

    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("threads.id", ondelete="SET NULL"), index=True
    )
    trigger_type: Mapped[RunTrigger] = mapped_column(db_enum(RunTrigger))
    trigger_ref: Mapped[str | None] = mapped_column(String(255))
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL")
    )
    handoff_depth: Mapped[int] = mapped_column(default=0)
    status: Mapped[RunStatus] = mapped_column(db_enum(RunStatus), default=RunStatus.QUEUED)
    input_prompt: Mapped[str] = mapped_column(Text)
    final_summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    # Metered by the LLM proxy (authoritative), not the SDK's client-side estimate.
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))

    agent_session_id: Mapped[str | None] = mapped_column(String(64))
    num_turns: Mapped[int | None]
    sandbox_id: Mapped[str | None] = mapped_column(String(128))
    runner_pid: Mapped[int | None]
    workflow_run_id: Mapped[str | None] = mapped_column(String(64))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(TimestampMixin, Base):
    """Append-only run timeline. A bigint id gives a total order (and SSE cursors later)."""

    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    # Runner-assigned sequence number, for idempotent retries. NULL for server events.
    seq: Mapped[int | None]
    type: Mapped[RunEventType] = mapped_column(db_enum(RunEventType))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class RunToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "run_tokens"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
