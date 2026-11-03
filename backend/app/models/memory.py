import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MemoryAuthor, MemorySyncState, db_enum


class MemoryFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A file in the bot's `memory/` folder. The database copy survives losing the sandbox."""

    __tablename__ = "memory_files"
    __table_args__ = (UniqueConstraint("bot_id", "path"),)

    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    # Relative to /home/user/bot/memory/, "/"-separated.
    path: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[MemoryAuthor] = mapped_column(db_enum(MemoryAuthor))
    # SHA-256 of the UTF-8 content, compared with the sandbox to skip unchanged files.
    content_hash: Mapped[str] = mapped_column(String(64))
    sync_state: Mapped[MemorySyncState] = mapped_column(
        db_enum(MemorySyncState), default=MemorySyncState.SYNCED
    )
