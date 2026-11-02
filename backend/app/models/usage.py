import uuid
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LlmUsage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per LLM call proxied for a run. Source of truth for budgets and cost."""

    __tablename__ = "llm_usage"
    __table_args__ = (Index("ix_llm_usage_bot_id_created_at", "bot_id", "created_at"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(BigInteger)
    output_tokens: Mapped[int] = mapped_column(BigInteger)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger)
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
