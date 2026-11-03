import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MessageRole, db_enum


class Thread(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "threads"
    __table_args__ = (Index("ix_threads_bot_id_updated_at", "bot_id", "updated_at"),)

    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))
    # Agent SDK session to resume, so the bot remembers the conversation.
    agent_session_id: Mapped[str | None] = mapped_column(String(64))


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_thread_id_created_at", "thread_id", "created_at"),)

    thread_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"))
    role: Mapped[MessageRole] = mapped_column(db_enum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True
    )
