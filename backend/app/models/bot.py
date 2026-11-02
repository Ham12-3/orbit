import uuid

from sqlalchemy import BigInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import BotStatus, db_enum


class Bot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bots"
    __table_args__ = (UniqueConstraint("user_id", "slug"),)

    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(80))
    avatar_emoji: Mapped[str] = mapped_column(String(16))
    job_description: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64))
    sandbox_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[BotStatus] = mapped_column(db_enum(BotStatus), default=BotStatus.IDLE)
    daily_token_budget: Mapped[int] = mapped_column(BigInteger)
    max_turns_per_run: Mapped[int]
    enabled: Mapped[bool] = mapped_column(default=True)
    # The run currently holding this bot's sandbox (one at a time). Not a FK: it is a
    # lock pointer, and a FK here would make bots <-> runs a cycle.
    active_run_id: Mapped[uuid.UUID | None]
